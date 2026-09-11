"""The real CI generator must remain compatible with Odoo's password argument."""
import argparse
import contextlib
import io
import re
import unittest
from pathlib import Path
from unittest.mock import patch


class OdooCiPasswordArgumentTest(unittest.TestCase):
    def test_option_like_random_value_cannot_break_odoo_entrypoint(self):
        source = (Path(__file__).resolve().parents[2] / 'scripts/run_odoo_module_tests.sh').read_text()
        code = re.search(r'DB_PASSWORD="\$\(\n  python3 -I - <<\x27PY\x27\n(.*?)\nPY\n\)"', source, re.S).group(1)
        output = io.StringIO()
        with patch('secrets.token_urlsafe', return_value='-synthetic-option-like-random-value') as random, contextlib.redirect_stdout(output):
            exec(compile(code, '<ci-password-generator>', 'exec'), {})
        generated = output.getvalue().strip()
        parser = argparse.ArgumentParser()
        parser.add_argument('--db_password')
        self.assertEqual(parser.parse_args(['--db_password', generated]).db_password, generated)
        random.assert_called_once_with(36)
        self.assertIn('-synthetic-option-like-random-value', generated)
