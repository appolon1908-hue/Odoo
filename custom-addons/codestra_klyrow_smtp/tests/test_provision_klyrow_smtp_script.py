import os
import runpy
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "provision_klyrow_smtp.py"


class UserError(Exception):
    pass


class Record:
    def __init__(self):
        self.values = {}

    def write(self, values):
        self.values.update(values)


class Parameters:
    def sudo(self):
        return self

    def set_param(self, key, value):
        self.key_value = (key, value)


class Cursor:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


class Environment:
    def __init__(self):
        self.shared = Record()
        self.beyvra = Record()
        self.parameters = Parameters()
        self.cr = Cursor()

    def ref(self, name):
        return self.shared if name.endswith("klyrow_production") else self.beyvra

    def __getitem__(self, name):
        if name != "ir.config_parameter":
            raise KeyError(name)
        return self.parameters


class ProvisionScriptTest(unittest.TestCase):
    def run_script(self, records):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential.env"
            path.write_text("".join(f"{key}={value}\n" for key, value in records), encoding="utf-8")
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            env = Environment()
            odoo = types.ModuleType("odoo")
            odoo.fields = types.SimpleNamespace(Datetime=types.SimpleNamespace(now=lambda: "now"))
            exceptions = types.ModuleType("odoo.exceptions")
            exceptions.UserError = UserError
            old_modules = {name: sys.modules.get(name) for name in ("odoo", "odoo.exceptions")}
            old_path = os.environ.get("KLYROW_ODOO_SMTP_ENV_FILE")
            try:
                sys.modules["odoo"] = odoo
                sys.modules["odoo.exceptions"] = exceptions
                os.environ["KLYROW_ODOO_SMTP_ENV_FILE"] = str(path)
                runpy.run_path(str(SCRIPT), init_globals={"env": env})
                return env
            finally:
                for name, module in old_modules.items():
                    if module is None:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = module
                if old_path is None:
                    os.environ.pop("KLYROW_ODOO_SMTP_ENV_FILE", None)
                else:
                    os.environ["KLYROW_ODOO_SMTP_ENV_FILE"] = old_path

    def credential(self):
        return [
            ("SMTP_HOST", "mail.klyrow.com"),
            ("SMTP_PORT", "25"),
            ("SMTP_SECURITY", "STARTTLS"),
            ("SMTP_USERNAME", "klyrow/klyrow-production"),
            ("SMTP_PASSWORD", "disposable-not-a-real-secret"),
        ]

    def test_imports_exact_export_and_keeps_delivery_disabled(self):
        env = self.run_script(self.credential())
        self.assertEqual(env.shared.values["smtp_pass"], "disposable-not-a-real-secret")
        self.assertFalse(env.shared.values["active"])
        self.assertFalse(env.beyvra.values["active"])
        self.assertEqual(env.parameters.key_value, ("codestra.mail.live_delivery_enabled", "false"))
        self.assertTrue(env.cr.committed)

    def test_rejects_wrong_transport_binding(self):
        records = [(key, "465" if key == "SMTP_PORT" else value) for key, value in self.credential()]
        with self.assertRaisesRegex(UserError, "unexpected SMTP_PORT"):
            self.run_script(records)

    def test_rejects_unrelated_key(self):
        with self.assertRaisesRegex(UserError, "unexpected key"):
            self.run_script(self.credential() + [("EXTRA", "value")])

    def test_rejects_incomplete_export(self):
        with self.assertRaisesRegex(UserError, "incomplete"):
            self.run_script(self.credential()[:-1])


if __name__ == "__main__":
    unittest.main()
