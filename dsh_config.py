"""Shared configuration and target model for DSH Menu (standard library only)."""
import hashlib
import json
from pathlib import Path
import re
import shutil

VERSION = 2
PALETTE = ('#99baff', '#dfb0ff', '#ffbf87', '#f59fbb', '#9ddbd5')


def config_dir(home=None):
    return (home or Path.home()) / '.config/dsh-menu'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate configuration key: {key}')
        result[key] = value
    return result


def read_json(path):
    try:
        return json.loads(path.read_text(), object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise ValueError(f'{path}: invalid JSON at line {exc.lineno}, column {exc.colno}') from None


def _fields(value, allowed, context):
    if not isinstance(value, dict):
        raise ValueError(f'{context} must be an object')
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f'{context}: unknown fields: {", ".join(sorted(unknown))}')


def _text(value, context):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f'{context} must be nonempty text without control characters')
    return value


def _port(value, context, minimum=1024):
    if type(value) is not int or not minimum <= value <= 65535:
        raise ValueError(f'{context} must be an integer from {minimum} to 65535')
    return value


def _label(value, context):
    value = _text(value, context)
    if len(value) > 80 or '[' in value or ']' in value:
        raise ValueError(f'{context} must be at most 80 characters, without square brackets')
    return value


def legacy_config(raw):
    return isinstance(raw, dict) and any(k in raw for k in ('ssh_host', 'local_port', 'tunnel_port', 'remote_port', 'workdir')) and 'remotes' not in raw and 'local' not in raw


def normalize(raw, home=None):
    home = home or Path.home()
    if legacy_config(raw):
        _fields(raw, ('ssh_host', 'local_port', 'tunnel_port', 'remote_port', 'workdir', 'npx'), 'legacy config')
        raw = {'version': VERSION, 'npx': raw.get('npx'),
               'local': {'port': raw.get('local_port', 3080), 'workdir': raw.get('workdir', str(home / 'Projects'))},
               'remotes': {'remote': {'label': 'Remote', 'ssh_host': raw.get('ssh_host', 'remote'),
                                      'local_port': raw.get('tunnel_port', 3081), 'remote_port': raw.get('remote_port', 3080)}}}
    _fields(raw, ('version', 'npx', 'local', 'remotes'), 'config')
    if type(raw.get('version', VERSION)) is not int or raw.get('version', VERSION) != VERSION:
        raise ValueError(f'Unsupported configuration version; expected {VERSION}')
    local = raw.get('local', {})
    _fields(local, ('label', 'port', 'workdir'), 'local')
    workdir = _text(local.get('workdir', str(home / 'Projects')), 'local.workdir')
    workdir = str(home) + workdir[1:] if workdir == '~' or workdir.startswith('~/') else workdir
    if not Path(workdir).is_absolute():
        raise ValueError('local.workdir must be absolute or start with ~/')
    shim = home / '.local/share/mise/shims/npx'
    if raw.get('npx') is not None and not isinstance(raw['npx'], str):
        raise ValueError('npx must be a path string')
    npx = raw.get('npx') or (str(shim) if shim.exists() else shutil.which('npx') or '')
    if npx:
        npx = _text(npx, 'npx')
        npx = str(home) + npx[1:] if npx.startswith('~/') else npx
        if not Path(npx).is_absolute():
            raise ValueError('npx must be an absolute path or start with ~/')
    settings = {'version': VERSION, 'npx': npx,
                'local': {'label': _label(local.get('label', 'Local'), 'local.label'),
                          'port': _port(local.get('port', 3080), 'local.port'), 'workdir': str(Path(workdir))}, 'remotes': {}}
    remotes = raw.get('remotes', {})
    if not isinstance(remotes, dict):
        raise ValueError('remotes must be an object keyed by target ID')
    ports = {settings['local']['port']: 'local'}
    for target_id, remote in remotes.items():
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', target_id) or target_id == 'local':
            raise ValueError(f'Invalid remote ID: {target_id}; use lowercase letters, numbers, hyphens, and reserve local')
        context = f'remotes.{target_id}'
        _fields(remote, ('label', 'ssh_host', 'local_port', 'remote_port', 'color'), context)
        host = remote.get('ssh_host')
        if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]*', host):
            raise ValueError(f'{context}.ssh_host must be an SSH alias or user@hostname')
        port = _port(remote.get('local_port'), f'{context}.local_port')
        if port in ports:
            raise ValueError(f'Local port {port} is assigned to both {ports[port]} and {target_id}')
        ports[port] = target_id
        color = remote.get('color', PALETTE[int(hashlib.sha256(target_id.encode()).hexdigest(), 16) % len(PALETTE)])
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError(f'{context}.color must be a six-digit hex color such as #99baff')
        settings['remotes'][target_id] = {'label': _label(remote.get('label', target_id.replace('-', ' ').title()), f'{context}.label'),
            'ssh_host': host, 'local_port': port, 'remote_port': _port(remote.get('remote_port', 3080), f'{context}.remote_port', 1), 'color': color}
    return settings


def targets(settings):
    local = settings['local']
    result = {'local': {'unit': 'dsh-local.service', 'port': local['port'], 'label': local['label'],
                         'detail': 'This computer', 'color': '#71d6af', 'background': '#102820', 'kind': 'local'}}
    for target_id, remote in settings['remotes'].items():
        result[target_id] = {'unit': f'dsh-tunnel-{target_id}.service', 'port': remote['local_port'], 'label': remote['label'],
                             'detail': 'SSH · ' + remote['ssh_host'], 'color': remote['color'], 'background': '#17243b', 'kind': 'remote'}
    return result


def load_runtime(home=None):
    path = config_dir(home) / 'runtime.json'
    if not path.exists():
        raise ValueError('DSH Menu has no applied configuration. Run python3 install.py first.')
    return normalize(read_json(path), home)
