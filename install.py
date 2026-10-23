#!/usr/bin/python3
"""Install/update DSH Menu for the current Omarchy user; no root required."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parent


def uncomment(text):
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                  lambda m: m[0] if m[0].startswith('"') else re.sub(r'[^\n]', ' ', m[0]), text)


def clean_jsonc(text):
    """Parse JSONC without corrupting strings or changing character offsets."""
    return re.sub(r'("(?:\\.|[^"\\])*")|,(?=\s*[}\]])',
                  lambda m: m[1] or ' ', uncomment(text))


def update_menu(original, entries):
    """Replace only dsh.* entries, retaining unrelated entries and comments."""
    clean = clean_jsonc(original)
    existing = json.loads(clean)
    if not isinstance(existing, dict):
        raise ValueError('The menu extension must be a JSONC object.')
    if {k: v for k, v in existing.items() if k == 'dsh' or k.startswith('dsh.')} == entries:
        return original
    decoder = json.JSONDecoder()
    position = clean.index('{') + 1
    commented = uncomment(original)
    spans = []
    while True:
        while clean[position].isspace() or clean[position] == ',':
            position += 1
        if clean[position] == '}':
            break
        start = position
        key, position = decoder.raw_decode(clean, position)
        while clean[position].isspace():
            position += 1
        if clean[position] != ':':
            raise ValueError('Invalid menu member.')
        position += 1
        while clean[position].isspace():
            position += 1
        _, position = decoder.raw_decode(clean, position)
        end = cursor = position
        while commented[cursor].isspace():
            cursor += 1
        if commented[cursor] == ',':
            end = cursor + 1
        if key == 'dsh' or key.startswith('dsh.'):
            spans.append((start, end))
    result = original
    for start, end in reversed(spans):
        result = result[:start] + result[end:]
    position = clean_jsonc(result).rfind('}')
    prefix = result[:position]
    separator = '' if uncomment(prefix).rstrip().endswith(('{', ',')) else ','
    body = json.dumps(entries, indent=2, ensure_ascii=False)[1:-1].strip()
    result = prefix + separator + '\n  ' + body + '\n' + result[position:]
    json.loads(clean_jsonc(result))
    return result


def unit_quote(value, environment=False):
    text = str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if not environment:
        text = text.replace('$', '$$')
    return '"' + text + '"'


def menu_entries(home):
    control = shlex.quote(str(home / '.local/bin/dsh-control'))
    entries = {'dsh': {'icon': '', 'label': 'DeepSeek Harness'}}
    for target, label, unit in (('local', 'Local', 'dsh-local'), ('remote', 'Remote', 'dsh-tunnel-remote')):
        entries[f'dsh.{target}'] = {'label': label, 'checked': f'systemctl --user is-active --quiet {unit}.service'}
        for action, title in (('open', 'Open webapp'), ('start', 'Start service' if target == 'local' else 'Start tunnel'),
                              ('stop', 'Stop service' if target == 'local' else 'Stop tunnel'), ('logs', 'Logs')):
            entries[f'dsh.{target}.{action}'] = {'label': title, 'action': f'{control} {target} {action}'}
    return entries


def build_plan(home, settings):
    extension = home / '.config/omarchy/extensions/omarchy-menu.jsonc'
    original = extension.read_text() if extension.exists() else '{}'
    paths = [str(Path(settings['npx']).parent)]
    if shutil.which('node'):
        paths.append(str(Path(shutil.which('node')).parent))
    paths += [str(home / '.local/share/mise/shims'), '/usr/share/omarchy/bin', '/usr/local/bin', '/usr/bin']
    local_command = [settings['npx'], '--offline', '--yes', '@deepseek-ai/dsh', 'web', '--host', '127.0.0.1',
                     '--port', str(settings['local_port']), '--no-open']
    tunnel_command = ['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=10',
                      '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                      '-L', f"127.0.0.1:{settings['tunnel_port']}:localhost:{settings['remote_port']}", settings['ssh_host']]
    units = home / '.config/systemd/user'
    local_unit = '[Unit]\nDescription=DeepSeek Harness local web service\n\n[Service]\nType=exec\n'
    # WorkingDirectory is one path, not an argv list; systemd treats quotes
    # here as literal filename characters. Interior spaces need no quoting.
    local_unit += 'WorkingDirectory=' + settings['workdir'].replace('%', '%%') + '\n'
    local_unit += 'Environment=' + unit_quote('PATH=' + ':'.join(dict.fromkeys(paths)), environment=True) + '\n'
    local_unit += 'ExecStart=' + ' '.join(map(unit_quote, local_command)) + '\nKillMode=control-group\nTimeoutStopSec=20\n'
    tunnel_unit = '[Unit]\nDescription=DeepSeek Harness SSH tunnel\n\n[Service]\nType=exec\n'
    tunnel_unit += 'ExecStart=' + ' '.join(map(unit_quote, tunnel_command)) + '\nKillMode=control-group\nTimeoutStopSec=10\n'
    targets = {
        str(settings['local_port']): {'label': 'Local', 'detail': 'This computer', 'color': '#71d6af', 'background': '#102820'},
        str(settings['tunnel_port']): {'label': 'Remote', 'detail': 'SSH · ' + settings['ssh_host'], 'color': '#99baff', 'background': '#17243b'},
    }
    plan = {
        home / '.config/dsh-menu/config.json': json.dumps(settings, indent=2) + '\n',
        extension: update_menu(original, menu_entries(home)),
        units / 'dsh-local.service': local_unit,
        units / 'dsh-tunnel-remote.service': tunnel_unit,
        home / '.config/dsh-webapps/labels/targets.js': 'globalThis.DSH_MENU_TARGETS = ' + json.dumps(targets, ensure_ascii=False) + ';\n',
    }
    for name in ('dsh-control', 'dsh-webapp'):
        plan[home / '.local/bin' / name] = (SOURCE / name).read_text()
    for name in ('manifest.json', 'labels.js'):
        plan[home / '.config/dsh-webapps/labels' / name] = (SOURCE / 'labels' / name).read_text()
    return plan


def apply_plan(plan):
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    changed = []
    for path, text in plan.items():
        if path.exists() and path.read_text() == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + '.bak.' + stamp))
        path.write_text(text)
        changed.append(path)
    for path in plan:
        if path.parent.name == 'bin':
            path.chmod(0o755)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-host', help='SSH alias for Remote (default: remote)')
    parser.add_argument('--local-port', type=int, help='Local DSH port (default: 3080)')
    parser.add_argument('--tunnel-port', type=int, help='Local forwarded port (default: 3081)')
    parser.add_argument('--remote-port', type=int, help='DSH port on the remote host (default: 3080)')
    parser.add_argument('--workdir', help='Local DSH working directory (default: ~/Projects)')
    parser.add_argument('--npx', help='Path to npx (default: mise shim, then PATH)')
    parser.add_argument('--prepare-dsh', action='store_true', help='Download/prepare DSH via npx before installing (requires network)')
    parser.add_argument('--dry-run', action='store_true', help='Validate and list files without writing or downloading')
    args = parser.parse_args()
    home = Path.home()
    config = home / '.config/dsh-menu/config.json'
    previous = json.loads(config.read_text()) if config.exists() else {}
    shim = home / '.local/share/mise/shims/npx'
    settings = {'ssh_host': 'remote', 'local_port': 3080, 'tunnel_port': 3081, 'remote_port': 3080,
                'workdir': str(home / 'Projects'), 'npx': str(shim) if shim.exists() else shutil.which('npx'), **previous}
    for name in ('ssh_host', 'local_port', 'tunnel_port', 'remote_port', 'workdir', 'npx'):
        if getattr(args, name) is not None:
            settings[name] = getattr(args, name)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]*', settings['ssh_host']):
        parser.error('Use an SSH alias, such as remote or user@hostname.')
    if any(not 1024 <= settings[p] <= 65535 for p in ('local_port', 'tunnel_port', 'remote_port')):
        parser.error('Ports must be between 1024 and 65535.')
    if settings['local_port'] == settings['tunnel_port']:
        parser.error('Local DSH and the tunnel need different local ports.')
    missing = [name for name in ('node', 'chromium', 'ssh', 'systemctl', 'journalctl', 'notify-send',
                                 'uwsm-app', 'omarchy-menu', 'omarchy-launch-terminal') if not shutil.which(name)]
    if not settings['npx'] or not os.access(os.path.expanduser(settings['npx']), os.X_OK):
        missing.append('npx')
    if missing:
        parser.error('Missing dependencies: ' + ', '.join(missing) + '. See README.md.')
    settings['workdir'] = os.path.abspath(os.path.expanduser(settings['workdir']))
    settings['npx'] = os.path.abspath(os.path.expanduser(settings['npx']))
    if any('\n' in str(v) or '\r' in str(v) for v in settings.values()):
        parser.error('Settings cannot contain newlines.')
    plan = build_plan(home, settings)
    if args.dry_run:
        print(json.dumps(settings, indent=2))
        print('\nWould install/update:\n' + '\n'.join(str(p) for p in plan))
        return
    subprocess.run(['systemctl', '--user', 'show-environment'], check=True, stdout=subprocess.DEVNULL)
    if args.prepare_dsh:
        subprocess.run([settings['npx'], '--yes', '@deepseek-ai/dsh', 'web', '--help'], check=True)
    Path(settings['workdir']).mkdir(parents=True, exist_ok=True)
    changed = apply_plan(plan)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print(f'Installed DSH Menu ({len(changed)} files updated). No services started or enabled at login.')
    print('Open: Win + Space → DeepSeek Harness, or: omarchy menu summon dsh')
    print('Stop/start running services to apply changed unit settings.')
    if not args.prepare_dsh:
        print('DSH must already be cached. For a fresh machine, use --prepare-dsh.')


if __name__ == '__main__':
    main()
