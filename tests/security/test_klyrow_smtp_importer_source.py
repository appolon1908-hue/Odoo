"""Run the fake-Odoo importer suite in mandatory isolated source validation.

Load only the standalone test file, not the addon package or a real Odoo
registry. Its disposable fixtures never access production credentials or SMTP.
"""

import importlib.util
from pathlib import Path


TEST_FILE = (
    Path(__file__).resolve().parents[2]
    / "custom-addons"
    / "codestra_klyrow_smtp"
    / "tests"
    / "test_provision_klyrow_smtp_script.py"
)


def load_tests(loader, standard_tests, pattern):
    """Include the existing behavioral tests in unittest source discovery."""
    del standard_tests, pattern
    spec = importlib.util.spec_from_file_location(
        "_codestra_klyrow_smtp_provision_source_tests", TEST_FILE
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load the Klyrow SMTP importer source tests")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = loader.loadTestsFromModule(module)
    if not suite.countTestCases():
        raise RuntimeError("Klyrow SMTP importer source tests were not discovered")
    return suite
