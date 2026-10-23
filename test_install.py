"""Configuration, installer synchronization, and helper integration tests."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import install
from dsh_config import config_dir, load_runtime, normalize, read_json, targets


def configuration(home):
    return normalize({'npx': '/usr/bin/true', 'local': {'port': 4080, 'workdir': str(home / 'Projects')},
        'remotes': {'development': {'label': 'Development', 'ssh_host': 'dev-server', 'local_port': 4081},
                    'research': {'label': 'GPU Research', 'ssh_host': 'research-server', 'local_port': 4082, 'remote_port': 5080}}}, home)


class Manager:
    def __init__(self, running=(), enabled=()):
        self.running = set(running)
        self.enabled = set(enabled)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        action = command[2]
        units = [arg for arg in command[3:] if not arg.startswith('-')]
        status = 0
        if action == 'is-active':
            status = 0 if units[0] in self.running else 3
        elif action == 'is-enabled':
            status = 0 if units[0] in self.enabled else 1
        elif action == 'stop':
            self.running.difference_update(units)
        elif action == 'start':
            self.running.update(units)
        elif action == 'disable':
            self.enabled.difference_update(units)
        output = ('enabled' if units[0] in self.enabled else 'static') if action == 'is-enabled' else ''
        return subprocess.CompletedProcess(command, status, stdout=output)

    def mutations(self):
        return [command for command in self.calls if command[2] not in ('is-active', 'is-enabled')]


def helper(name):
    loader = importlib.machinery.SourceFileLoader('test_' + name.replace('-', '_'), str(install.SOURCE / name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


class ConfigTests(unittest.TestCase):
    def test_multiple_targets_and_zero_remotes(self):
        settings = configuration(Path('/home/example'))
        self.assertEqual(list(targets(settings)), ['local', 'development', 'research'])
        self.assertEqual(targets(settings)['research']['label'], 'GPU Research')
        self.assertEqual(list(targets(normalize({'remotes': {}}))), ['local'])

    def test_legacy_flat_configuration_migrates_without_losing_connection(self):
        settings = normalize({'ssh_host': 'existing-server', 'local_port': 4080, 'tunnel_port': 4181,
                              'remote_port': 5080, 'workdir': '/home/example/Work', 'npx': '/usr/bin/true'})
        self.assertEqual(settings['local']['port'], 4080)
        self.assertEqual(settings['local']['workdir'], '/home/example/Work')
        self.assertEqual(settings['remotes']['remote']['ssh_host'], 'existing-server')
        self.assertEqual(settings['remotes']['remote']['local_port'], 4181)
        self.assertEqual(settings['remotes']['remote']['remote_port'], 5080)

    def test_invalid_ids_ports_fields_and_colors_are_rejected(self):
        for remote in ({'local': {'ssh_host': 'server', 'local_port': 4181}},
                       {'../escape': {'ssh_host': 'server', 'local_port': 4181}},
                       {'a': {'ssh_host': 'server', 'local_port': 3080}},
                       {'a': {'ssh_host': 'server', 'local_port': True}},
                       {'a': {'ssh_host': '-oProxyCommand=bad', 'local_port': 4181}},
                       {'a': {'ssh_host': 'server', 'local_port': 4181, 'color': 'red;display:none'}},
                       {'a': {'ssh_host': 'server', 'local_port': 4181, 'typo': 1}},
                       {'a': {'ssh_host': 'server', 'local_port': 4181}, 'b': {'ssh_host': 'other', 'local_port': 4181}}):
            with self.subTest(remote=remote), self.assertRaises(ValueError):
                normalize({'remotes': remote})
        with self.assertRaises(ValueError):
            normalize({'local': {'workdir': 'relative/path'}})
        with self.assertRaises(ValueError):
            normalize({'version': 99})
        with self.assertRaises(ValueError):
            normalize({'version': 2.0})
        with self.assertRaises(ValueError):
            normalize({'npx': False})

    def test_duplicate_config_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text('{"remotes": {}, "remotes": {}}')
            with self.assertRaises(ValueError):
                read_json(path)

    def test_desired_edits_do_not_change_runtime_until_reinstall(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            settings = configuration(home)
            install.apply_plan(install.build_plan(home, settings))
            (config_dir(home) / 'config.json').write_text('{"remotes":{}}')
            self.assertIn('research', load_runtime(home)['remotes'])
            settings = normalize(read_json(config_dir(home) / 'config.json'), home)
            install.apply_plan(install.build_plan(home, settings))
            self.assertEqual(load_runtime(home)['remotes'], {})


class InstallTests(unittest.TestCase):
    def test_startup_menu_and_units_for_each_target(self):
        home = Path('/home/example')
        settings = configuration(home)
        entries = install.menu_entries(home, settings)
        plan = install.build_plan(home, settings)
        for target_id, target in targets(settings).items():
            with self.subTest(target=target_id):
                unit = target['unit']
                self.assertEqual(entries[f'dsh.{target_id}.enable']['when'],
                                 f'! systemctl --user is-enabled --quiet {unit}')
                self.assertEqual(entries[f'dsh.{target_id}.disable']['when'],
                                 f'systemctl --user is-enabled --quiet {unit}')
                self.assertIn('[Install]\nWantedBy=default.target', plan[home / '.config/systemd/user' / unit])

    def test_jsonc_merge_preserves_unrelated_strings_and_comments(self):
        original = '''{
 // Keep personal shortcuts.
 "personal": {"label": "Notes // really", "action": "open https://example.org/a,b"},
 "dsh": {"label": "Old"},
 "dsh.old.open": {"action": "old command"},
 "other": {"nested": [1, 2,],},
}'''
        home = Path('/home/another user')
        entries = install.menu_entries(home, configuration(home))
        merged = install.update_menu(original, entries)
        parsed = json.loads(install.clean_jsonc(merged))
        self.assertIn('// Keep personal shortcuts.', merged)
        self.assertEqual(parsed['personal']['action'], 'open https://example.org/a,b')
        self.assertEqual(parsed['personal']['label'], 'Notes // really')
        self.assertEqual(parsed['other'], {'nested': [1, 2]})
        self.assertNotIn('dsh.old.open', parsed)
        self.assertEqual(install.update_menu(merged, entries), merged)
        self.assertEqual(shlex.split(entries['dsh.research.open']['action']),
                         ['/home/another user/.local/bin/dsh-control', 'research', 'open'])

    def test_merge_empty_and_last_members(self):
        entries = install.menu_entries(Path('/home/example'), normalize({}))
        for original in ('{}', '{"personal": 1}', '{"dsh": {}}', '{"dsh":{},"personal":1}', '{"personal":1,"dsh":{}}'):
            with self.subTest(original=original):
                result = json.loads(install.clean_jsonc(install.update_menu(original, entries)))
                self.assertEqual(result['dsh'], entries['dsh'])
                if 'personal' in original:
                    self.assertEqual(result['personal'], 1)

    def test_generation_is_portable_and_reinstallation_is_noop(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'another user'
            settings = configuration(home)
            manager = Manager()
            plan = install.build_plan(home, settings)
            updated, _, _ = install.sync_install(home, plan, runner=manager)
            self.assertTrue(all(path.is_relative_to(home) for path in updated))
            self.assertEqual(manager.running, set())
            self.assertTrue((home / '.local/bin/dsh-control').stat().st_mode & 0o111)
            self.assertTrue((home / '.local/bin/dsh_config.py').exists())
            units = home / '.config/systemd/user'
            self.assertIn('WorkingDirectory=' + settings['local']['workdir'] + '\n', (units / 'dsh-local.service').read_text())
            self.assertIn('127.0.0.1:4082:localhost:5080', (units / 'dsh-tunnel-research.service').read_text())
            mapping = (home / '.config/dsh-webapps/labels/targets.js').read_text()
            self.assertIn('GPU Research', mapping)
            self.assertIn('"4082"', mapping)
            manager.calls.clear()
            updated, removed, restarted = install.sync_install(home, install.build_plan(home, settings), runner=manager)
            self.assertEqual((updated, removed, restarted), ([], set(), set()))
            self.assertEqual(manager.mutations(), [])

    def test_remove_one_remote_stops_only_its_service_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            settings = configuration(home)
            install.apply_plan(install.build_plan(home, settings))
            manager = Manager({'dsh-local.service', 'dsh-tunnel-development.service', 'dsh-tunnel-research.service'}, {'dsh-tunnel-research.service'})
            del settings['remotes']['research']
            units = home / '.config/systemd/user'
            unrelated = units / 'dsh-tunnel-unrelated.service'
            unrelated.write_text('Not managed by the app')
            _, removed, _ = install.sync_install(home, install.build_plan(home, settings), runner=manager)
            self.assertEqual(removed, {'dsh-tunnel-research.service'})
            self.assertEqual(manager.running, {'dsh-local.service', 'dsh-tunnel-development.service'})
            self.assertFalse((units / 'dsh-tunnel-research.service').exists())
            self.assertNotIn('dsh-tunnel-research.service', manager.enabled)
            self.assertTrue(list(units.glob('dsh-tunnel-research.service.bak.*')))
            self.assertTrue(unrelated.exists())
            self.assertNotIn('dsh.research', json.loads(install.clean_jsonc((home / '.config/omarchy/extensions/omarchy-menu.jsonc').read_text())))

    def test_changed_running_remote_restarts_but_stopped_remote_stays_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            settings = configuration(home)
            install.apply_plan(install.build_plan(home, settings))
            settings['remotes']['development']['remote_port'] = 5081
            settings['remotes']['research']['remote_port'] = 5082
            manager = Manager({'dsh-tunnel-development.service'})
            _, _, restarted = install.sync_install(home, install.build_plan(home, settings), runner=manager)
            self.assertEqual(restarted, {'dsh-tunnel-development.service'})
            self.assertEqual(manager.running, {'dsh-tunnel-development.service'})

    def test_port_swap_stops_both_before_starting_either(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            settings = configuration(home)
            install.apply_plan(install.build_plan(home, settings))
            a, b = settings['remotes'].values()
            a['local_port'], b['local_port'] = b['local_port'], a['local_port']
            manager = Manager({'dsh-tunnel-development.service', 'dsh-tunnel-research.service'})
            install.sync_install(home, install.build_plan(home, settings), runner=manager)
            operations = manager.mutations()
            self.assertEqual(operations[0][2], 'stop')
            self.assertEqual(set(operations[0][3:]), manager.running)
            self.assertEqual(operations[-1][2], 'start')

    def test_label_only_change_does_not_restart_service(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            settings = configuration(home)
            install.apply_plan(install.build_plan(home, settings))
            settings['remotes']['research']['label'] = 'New label'
            manager = Manager({'dsh-tunnel-research.service'})
            _, _, restarted = install.sync_install(home, install.build_plan(home, settings), runner=manager)
            self.assertEqual(restarted, set())
            self.assertFalse(any(call[2] in ('stop', 'start') for call in manager.calls))

    def test_legacy_unit_migration_transfers_running_state(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            units = home / '.config/systemd/user'
            units.mkdir(parents=True)
            old = units / 'dsh-tunnel-retired.service'
            old.write_text('[Unit]\nDescription=DeepSeek Harness SSH tunnel\n')
            extension = home / '.config/omarchy/extensions/omarchy-menu.jsonc'
            extension.parent.mkdir(parents=True)
            extension.write_text(json.dumps({'dsh.remote': {'checked': 'systemctl --user is-active --quiet dsh-tunnel-retired.service'}}))
            settings = normalize({'npx': '/usr/bin/true', 'ssh_host': 'existing-server'}, home)
            manager = Manager({'dsh-tunnel-retired.service'})
            install.sync_install(home, install.build_plan(home, settings), migrate=True, runner=manager)
            self.assertEqual(manager.running, {'dsh-tunnel-remote.service'})
            self.assertFalse(old.exists())

    def test_unmanaged_collision_is_rejected_without_stopping_services(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            units = home / '.config/systemd/user'
            units.mkdir(parents=True)
            (units / 'dsh-local.service').write_text('[Unit]\nDescription=Unrelated user service\n')
            manager = Manager({'dsh-local.service'})
            with self.assertRaises(ValueError):
                install.sync_install(home, install.build_plan(home, configuration(home)), runner=manager)
            self.assertEqual(manager.calls, [])

    def test_invalid_menu_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            path = home / '.config/omarchy/extensions/omarchy-menu.jsonc'
            path.parent.mkdir(parents=True)
            path.write_text('{ invalid')
            with self.assertRaises(ValueError):
                install.build_plan(home, configuration(home))
            self.assertFalse((config_dir(home) / 'runtime.json').exists())


class HelperTests(unittest.TestCase):
    def test_enable_disable_only_change_named_target_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            install.apply_plan(install.build_plan(home, configuration(home)))
            control = helper('dsh-control')
            with patch.dict('os.environ', {'HOME': str(home)}), patch.object(control, 'run') as run, patch.object(control, 'notify'):
                for action in ('enable', 'disable'):
                    with patch('sys.argv', ['dsh-control', 'research', action]):
                        control.main()
                    run.assert_called_with('systemctl', '--user', action, 'dsh-tunnel-research.service')
            self.assertEqual(run.call_count, 2)

    def test_webapp_token_uses_target_port_and_encodes_query_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            install.apply_plan(install.build_plan(home, configuration(home)))
            webapp = helper('dsh-webapp')
            with patch.dict('os.environ', {'HOME': str(home)}), patch.object(webapp, 'seed_login'), patch.object(webapp.os, 'execvp') as execute:
                for target, port in (('local', 4080), ('research', 4082)):
                    with self.subTest(target=target), patch('sys.argv', ['dsh-webapp', target, 'abc+def/ghi==&other=#%']):
                        webapp.main()
                        self.assertIn(f'--app=http://localhost:{port}/?token=abc%2Bdef%2Fghi%3D%3D%26other%3D%23%25', execute.call_args.args[1])

    def test_webapp_rejects_invalid_inputs_without_launching(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            install.apply_plan(install.build_plan(home, configuration(home)))
            webapp = helper('dsh-webapp')
            with patch.dict('os.environ', {'HOME': str(home)}), patch.object(webapp, 'seed_login'), patch.object(webapp.os, 'execvp') as execute:
                for value in ('', ' ', 'token\n', 'https://localhost:4082/?token=test',
                              'http://example.com:4082/?token=test', 'http://127.0.0.1:3080/?token=test',
                              'http://user:pass@localhost:4082/', '//localhost:4082/', 'javascript:alert(1)'):
                    with self.subTest(value=value), patch('sys.argv', ['dsh-webapp', 'research', value]):
                        with self.assertRaises(SystemExit):
                            webapp.main()
                execute.assert_not_called()

    def test_stop_targets_only_the_named_remote(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            install.apply_plan(install.build_plan(home, configuration(home)))
            control = helper('dsh-control')
            with patch.dict('os.environ', {'HOME': str(home)}), patch.object(control, 'run') as run, patch.object(control, 'notify'):
                with patch('sys.argv', ['dsh-control', 'research', 'stop']):
                    control.main()
                run.assert_called_once_with('systemctl', '--user', 'stop', 'dsh-tunnel-research.service')

    def test_webapp_rejects_other_targets_url_and_accepts_its_own(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            install.apply_plan(install.build_plan(home, configuration(home)))
            webapp = helper('dsh-webapp')
            with patch.dict('os.environ', {'HOME': str(home)}), patch.object(webapp, 'seed_login'), patch.object(webapp.os, 'execvp') as execute:
                with patch('sys.argv', ['dsh-webapp', 'research', 'http://localhost:4081/']):
                    with self.assertRaises(SystemExit):
                        webapp.main()
                execute.assert_not_called()
                with patch('sys.argv', ['dsh-webapp', 'research', 'http://localhost:4082/']):
                    webapp.main()
                self.assertIn('--app=http://localhost:4082/', execute.call_args.args[1])
                with patch('sys.argv', ['dsh-webapp', 'research', 'http://127.0.0.1:4082/?token=test']):
                    webapp.main()
                self.assertIn('--app=http://127.0.0.1:4082/?token=test', execute.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
