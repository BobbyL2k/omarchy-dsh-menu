"""Installer portability and update checks. Run: python3 -m unittest -v"""
import json
from pathlib import Path
import runpy
import shlex
import tempfile
import unittest
from unittest.mock import patch

import install


class InstallTests(unittest.TestCase):
    def test_jsonc_merge_retains_strings_comments_and_unrelated_entries(self):
        original = '''{
  // Keep my personal menu.
  "personal": {"label": "Notes // really", "action": "open https://example.org/a,b"},
  "dsh": {"label": "Old"},
  "dsh.local.open": {"action": "old command"},
  "other": {"nested": [1, 2,],},
}'''
        entries = install.menu_entries(Path('/home/another user'))
        merged = install.update_menu(original, entries)
        parsed = json.loads(install.clean_jsonc(merged))
        self.assertIn('// Keep my personal menu.', merged)
        self.assertEqual(parsed['personal']['action'], 'open https://example.org/a,b')
        self.assertEqual(parsed['personal']['label'], 'Notes // really')
        self.assertEqual(parsed['other'], {'nested': [1, 2]})
        self.assertEqual(parsed['dsh.local.open'], entries['dsh.local.open'])
        self.assertEqual(install.update_menu(merged, entries), merged)
        self.assertEqual(shlex.split(entries['dsh.local.open']['action']),
                         ['/home/another user/.local/bin/dsh-control', 'local', 'open'])

    def test_merge_handles_empty_and_unterminated_last_members(self):
        entries = install.menu_entries(Path('/home/new'))
        for original in ('{}', '{"personal": 1}', '{"dsh": {}}',
                         '{"dsh":{},"personal":1}', '{"personal":1,"dsh":{}}'):
            with self.subTest(original=original):
                result = json.loads(install.clean_jsonc(install.update_menu(original, entries)))
                self.assertEqual(result['dsh'], entries['dsh'])
                if 'personal' in original:
                    self.assertEqual(result['personal'], 1)

    def test_fresh_install_update_and_custom_ports_in_another_home(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'another user'
            settings = {'ssh_host': 'workstation', 'local_port': 4080, 'tunnel_port': 4081,
                        'remote_port': 5080, 'workdir': str(home / 'Projects'), 'npx': '/usr/bin/true'}
            plan = install.build_plan(home, settings)
            changed = install.apply_plan(plan)
            self.assertEqual(len(changed), len(plan))
            self.assertTrue(all(p.is_relative_to(home) for p in changed))
            self.assertEqual(install.apply_plan(install.build_plan(home, settings)), [])
            self.assertTrue((home / '.local/bin/dsh-control').stat().st_mode & 0o111)
            local_unit = (home / '.config/systemd/user/dsh-local.service').read_text()
            self.assertIn('WorkingDirectory=' + settings['workdir'] + '\n', local_unit)
            self.assertIn('127.0.0.1:4081:localhost:5080', (home / '.config/systemd/user/dsh-tunnel-remote.service').read_text())
            labels = (home / '.config/dsh-webapps/labels/targets.js').read_text()
            self.assertIn('"4080"', labels)
            self.assertIn('SSH · workstation', labels)
            with patch.dict('os.environ', {'HOME': str(home)}):
                control = runpy.run_path(str(home / '.local/bin/dsh-control'))
                self.assertEqual(control['TARGETS']['local'][1], 4080)
                self.assertEqual(control['TARGETS']['remote'][1], 4081)
            settings['tunnel_port'] = 4181
            install.apply_plan(install.build_plan(home, settings))
            installed = json.loads((home / '.config/dsh-menu/config.json').read_text())
            self.assertEqual(installed['tunnel_port'], 4181)
            self.assertTrue(list((home / '.config/dsh-menu').glob('config.json.bak.*')))

    def test_invalid_menu_is_rejected_before_installation(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            install.update_menu('{ invalid', install.menu_entries(Path('/home/test')))


if __name__ == '__main__':
    unittest.main()
