"""Execute the same event/session cases shipped to the Odoo browser."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / 'custom-addons/codestra_vicidial_crm'


class CallingBrowserSourceTest(unittest.TestCase):
    def test_readside_event_and_session_cases(self):
        self.assertIsNotNone(shutil.which('node'), 'Node is required for the calling browser source gate')
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            (target/'schema.mjs').write_text((ADDON/'static/src/js/calling_schema.js').read_text())
            (target/'client.mjs').write_text((ADDON/'static/src/js/calling_realtime.js').read_text().replace("'./calling_schema'", "'./schema.mjs'"))
            (target/'cases.mjs').write_text((ADDON/'static/tests/calling_realtime_cases.js').read_text())
            (target/'run.mjs').write_text("import * as client from './client.mjs';\nimport { callingSchema } from './schema.mjs';\nimport { runCallingRealtimeCases } from './cases.mjs';\nconsole.log('CALLING_BROWSER_CASES=' + await runCallingRealtimeCases(client, callingSchema));\n")
            result = subprocess.run(['node', str(target/'run.mjs')], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('CALLING_BROWSER_CASES=', result.stdout)
