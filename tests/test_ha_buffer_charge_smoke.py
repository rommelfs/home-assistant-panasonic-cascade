"""Run a real HA lifecycle in isolation from the protocol-test import fixtures."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(importlib.util.find_spec('homeassistant'), 'Home Assistant required')
class HALifecycleTest(unittest.TestCase):
    def test_charge_services_entities_storage_and_reload_restore(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / 'tests/ha_buffer_charge_smoke.py')],
                                cwd=root, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SERVICE_START_RELOAD_RESTORE_AND_UNLOAD_OK', result.stdout)
