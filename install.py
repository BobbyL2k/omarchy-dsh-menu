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
import tempfile

from dsh_config import config_dir, legacy_config, normalize, read_json, targets

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


def menu_entries(home, settings):
    control = shlex.quote(str(home / '.local/bin/dsh-control'))
    entries = {'dsh': {'icon': '', 'label': 'DeepSeek Harness'}}
    for target_id, target in targets(settings).items():
        entries[f'dsh.{target_id}'] = {'label': target['label'], 'checked': f"systemctl --user is-active --quiet {target['unit']}"}
        for action, title in (('open', 'Open webapp'), ('start', 'Start service' if target_id == 'local' else 'Start tunnel'),
                              ('stop', 'Stop service' if target_id == 'local' else 'Stop tunnel'), ('logs', 'Logs')):
            entries[f'dsh.{target_id}.{action}'] = {'label': title, 'action': f'{control} {target_id} {action}'}
        enabled = f"systemctl --user is-enabled --quiet {target['unit']}"
        entries[f'dsh.{target_id}.enable'] = {'label': 'Enable at login', 'when': f'! {enabled}',
                                                'action': f'{control} {target_id} enable'}
        entries[f'dsh.{target_id}.disable'] = {'label': 'Disable at login', 'when': enabled,
                                                 'action': f'{control} {target_id} disable'}
    return entries


def build_plan(home, settings, source_text=None):
    extension = home / '.config/omarchy/extensions/omarchy-menu.jsonc'
    original = extension.read_text() if extension.exists() else '{}'
    paths = [str(Path(settings['npx']).parent)]
    if shutil.which('node'):
        paths.append(str(Path(shutil.which('node')).parent))
    paths += [str(home / '.local/share/mise/shims'), '/usr/share/omarchy/bin', '/usr/local/bin', '/usr/bin']
    command = [settings['npx'], '--offline', '--yes', '@deepseek-ai/dsh', 'web', '--host', '127.0.0.1',
               '--port', str(settings['local']['port']), '--no-open']
    local_unit = '[Unit]\nDescription=DeepSeek Harness local web service\n\n[Service]\nType=exec\n'
    local_unit += 'WorkingDirectory=' + settings['local']['workdir'].replace('%', '%%') + '\n'
    local_unit += 'Environment=' + unit_quote('PATH=' + ':'.join(dict.fromkeys(paths)), environment=True) + '\n'
    local_unit += 'ExecStart=' + ' '.join(map(unit_quote, command)) + '\nKillMode=control-group\nTimeoutStopSec=20\n\n[Install]\nWantedBy=default.target\n'
    units = home / '.config/systemd/user'
    plan = {config_dir(home) / 'config.json': source_text if source_text is not None else json.dumps(settings, indent=2) + '\n',
            config_dir(home) / 'runtime.json': json.dumps(settings, indent=2) + '\n',
            extension: update_menu(original, menu_entries(home, settings)), units / 'dsh-local.service': local_unit}
    for target_id, remote in settings['remotes'].items():
        command = ['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=10',
                   '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                   '-L', f"127.0.0.1:{remote['local_port']}:localhost:{remote['remote_port']}", remote['ssh_host']]
        text = '[Unit]\nDescription=DeepSeek Harness SSH tunnel\n\n[Service]\nType=exec\n'
        text += 'ExecStart=' + ' '.join(map(unit_quote, command)) + '\nKillMode=control-group\nTimeoutStopSec=10\n\n[Install]\nWantedBy=default.target\n'
        plan[units / f'dsh-tunnel-{target_id}.service'] = text
    mapping = {str(t['port']): {key: t[key] for key in ('label', 'detail', 'color', 'background')} for t in targets(settings).values()}
    plan[home / '.config/dsh-webapps/labels/targets.js'] = 'globalThis.DSH_MENU_TARGETS = ' + json.dumps(mapping, ensure_ascii=False) + ';\n'
    for name in ('dsh_config.py', 'dsh-control', 'dsh-webapp'):
        plan[home / '.local/bin' / name] = (SOURCE / name).read_text()
    for name in ('manifest.json', 'labels.js'):
        plan[home / '.config/dsh-webapps/labels' / name] = (SOURCE / 'labels' / name).read_text()
    # Ownership is explicit: removing a remote must not delete unrelated units.
    plan[config_dir(home) / 'installed.json'] = json.dumps({'units': sorted(t['unit'] for t in targets(settings).values())}, indent=2) + '\n'
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
        temporary = path.with_name(path.name + '.tmp.' + stamp)
        try:
            temporary.write_text(text)
            temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        changed.append(path)
    for path in plan:
        if path.name in ('dsh-control', 'dsh-webapp'):
            path.chmod(0o755)
    return changed


def owned_units(home):
    state = config_dir(home) / 'installed.json'
    names = set()
    if state.exists():
        data = read_json(state)
        if not isinstance(data, dict) or not isinstance(data.get('units'), list) or not all(isinstance(name, str) for name in data['units']):
            raise ValueError('Invalid DSH Menu ownership state')
        names.update(data['units'])
    else:
        # Adopt an earlier install using only its owned menu entries and units.
        extension = home / '.config/omarchy/extensions/omarchy-menu.jsonc'
        if extension.exists():
            for key, row in json.loads(clean_jsonc(extension.read_text())).items():
                if key.startswith('dsh.') and isinstance(row, dict):
                    match = re.fullmatch(r'systemctl --user is-active --quiet (dsh-[a-z0-9-]+\.service)', row.get('checked', ''))
                    if match:
                        path = home / '.config/systemd/user' / match[1]
                        if path.exists() and re.search(r'^Description=DeepSeek Harness ', path.read_text(), re.M):
                            names.add(match[1])
    if any(not re.fullmatch(r'dsh-(?:local|tunnel-[a-z][a-z0-9-]{0,47})\.service', name) for name in names):
        raise ValueError('Invalid unit name in DSH Menu ownership state')
    return names


def service_changes(home, plan, previous):
    desired = {p.name for p in plan if p.suffix == '.service'}
    # [Install] only controls future enablement and needs a reload, not a restart.
    runtime = lambda text: text.split('\n[Install]\n', 1)[0]
    changed = {p.name for p, text in plan.items() if p.suffix == '.service' and
               (not p.exists() or runtime(p.read_text()) != runtime(text))}
    return desired, changed, previous - desired


def sync_install(home, plan, migrate=False, runner=None):
    runner = runner or subprocess.run
    previous = owned_units(home)
    desired, changed, obsolete = service_changes(home, plan, previous)
    for path in plan:
        if path.suffix == '.service' and path.exists() and path.name not in previous:
            if not re.search(r'^Description=DeepSeek Harness ', path.read_text(), re.M):
                raise ValueError(f'Refusing to replace an unmanaged service: {path.name}')
    def active(unit):
        return runner(['systemctl', '--user', 'is-active', '--quiet', unit], check=False).returncode == 0
    running = {unit for unit in previous | desired if active(unit)}
    restart = changed & running & desired
    # Single-remote legacy migration preserves its running/stopped state even
    # when the old installation used a different generated unit name.
    old_remote = previous - {'dsh-local.service'}
    new_remote = desired - {'dsh-local.service'}
    if migrate and len(old_remote) == len(new_remote) == 1 and old_remote & running:
        restart.update(new_remote)
    stopped = sorted((obsolete | changed) & running)
    if stopped:
        runner(['systemctl', '--user', 'stop', *stopped], check=True)
    for unit in sorted(obsolete):
        enabled = runner(['systemctl', '--user', 'is-enabled', unit], check=False,
                         capture_output=True, text=True)
        if (enabled.stdout or '').strip() in ('enabled', 'enabled-runtime'):
            runner(['systemctl', '--user', 'disable', unit], check=True)
    updated = apply_plan(plan)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for unit in sorted(obsolete):
        path = home / '.config/systemd/user' / unit
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + '.bak.' + stamp))
            path.unlink()
    if updated or obsolete:
        runner(['systemctl', '--user', 'daemon-reload'], check=True)
    if restart:
        runner(['systemctl', '--user', 'start', *sorted(restart)], check=True)
    return updated, obsolete, restart


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Import settings from a JSON file; later installs use the saved config')
    parser.add_argument('--prepare-dsh', action='store_true', help='Download/prepare DSH via npx (requires network)')
    parser.add_argument('--dry-run', action='store_true', help='Validate and preview without writing, downloading, or stopping services')
    args = parser.parse_args()
    home = Path.home()
    source = args.config.expanduser() if args.config else config_dir(home) / 'config.json'
    try:
        raw = read_json(source) if source.exists() else {}
        if args.config and not source.exists():
            raise ValueError(f'Configuration file does not exist: {source}')
        migrate = legacy_config(raw)
        settings = normalize(raw, home)
        text = source.read_text() if source.exists() and not migrate else None
        plan = build_plan(home, settings, text)
        previous = owned_units(home)
        desired, changed, obsolete = service_changes(home, plan, previous)
        missing = [name for name in ('node', 'chromium', 'ssh', 'systemctl', 'systemd-analyze', 'journalctl',
                                     'notify-send', 'uwsm-app', 'omarchy-menu', 'omarchy-launch-terminal') if not shutil.which(name)]
        if not settings['npx'] or not os.access(settings['npx'], os.X_OK):
            missing.append('npx')
        if missing:
            raise ValueError('Missing dependencies: ' + ', '.join(missing) + '. See README.md.')
        if args.dry_run:
            print('Targets: ' + ', '.join(f"{key} ({target['label']}, port {target['port']})" for key, target in targets(settings).items()))
            print('Would update:')
            print('\n'.join(str(path) for path, text in plan.items() if not path.exists() or path.read_text() != text) or '(no files)')
            print('Would remove obsolete units: ' + (', '.join(sorted(obsolete)) or '(none)'))
            print('Changed service definitions (restarted only if already running): ' + (', '.join(sorted(changed)) or '(none)'))
            return
        subprocess.run(['systemctl', '--user', 'show-environment'], check=True, stdout=subprocess.DEVNULL)
        # Check every generated service before touching installed files or services.
        with tempfile.TemporaryDirectory(prefix='dsh-menu-verify-') as folder:
            files = []
            for path, body in plan.items():
                if path.suffix == '.service':
                    staged = Path(folder) / path.name
                    staged.write_text(body)
                    files.append(str(staged))
            subprocess.run(['systemd-analyze', '--user', 'verify', *files], check=True)
        if args.prepare_dsh:
            subprocess.run([settings['npx'], '--yes', '@deepseek-ai/dsh', 'web', '--help'], check=True)
        Path(settings['local']['workdir']).mkdir(parents=True, exist_ok=True)
        updated, obsolete, restarted = sync_install(home, plan, migrate)
        print(f'DSH Menu synced: {len(updated)} files updated, {len(obsolete)} obsolete units removed, {len(restarted)} active services refreshed.')
        print('New targets remain stopped. Open them from Win + Space → DeepSeek Harness.')
        print('After label/port changes, close all dedicated DSH browser windows and reopen them.')
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Installation failed: {exc}\n')


if __name__ == '__main__':
    main()
