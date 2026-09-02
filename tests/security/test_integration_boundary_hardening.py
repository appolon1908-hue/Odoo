from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import validate_integration_boundary_hardening as hardening
from scripts import validate_integration_boundary as boundary


class IntegrationBoundaryHardeningTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_only_addon_root_migration_paths_receive_migration_treatment(self) -> None:
        self.assertTrue(boundary.is_module_migration_path("migrations/19.0.1.0/pre.py"))
        self.assertTrue(boundary.is_module_migration_path("upgrades/19.0.1.0/post.py"))
        self.assertFalse(boundary.is_module_migration_path("models/upgrades/job.py"))
        self.assertFalse(boundary.is_module_migration_path("controllers/migrations/proxy.py"))
        self.assertFalse(boundary.is_module_migration_path("migrations/runtime.py"))
        self.assertFalse(boundary.is_module_migration_path("migrations/not-a-version/job.py"))
        self.assertFalse(boundary.is_module_migration_path("upgrades/models/proxy.py"))

    def test_shell_psql_and_database_credentials_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write(
                root,
                "custom-addons/example/hooks/apply.sh",
                "#!/bin/sh\nPGPASSWORD=secret psql postgresql://db/write\n",
            )
            findings = hardening.config_findings(path)
            self.assertIn("shell/config psql invocation is prohibited", findings)
            self.assertIn(
                "shell/config database credential or PostgreSQL DSN is prohibited",
                findings,
            )

    def test_python_process_psql_invocation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "import subprocess\nsubprocess.run(['psql', '-c', 'DELETE FROM x'])\n",
            )
            findings = hardening.python_findings(path, allow_cursor_sql=False)
            self.assertIn("Python process invocation of psql is prohibited", findings)

    def test_wildcard_process_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "from subprocess import *\nrun('psql database')\n",
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_python_process_command_variable_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "import subprocess\ncommand = 'psql postgresql://db/write'\nsubprocess.run(command, shell=True)\n",
            )
            findings = hardening.python_findings(path, allow_cursor_sql=False)
            self.assertIn("Python process invocation of psql is prohibited", findings)
            self.assertIn(
                "Python process invocation contains database credentials",
                findings,
            )

    def test_unanalyzable_process_invocation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "import subprocess\ndef run(command):\n    subprocess.run(command)\n",
            )
            self.assertIn(
                "unanalyzable process invocation is prohibited in Odoo addons",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_process_alias_and_lexically_shadowed_command_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alias = self.write(
                root,
                "custom-addons/example/models/alias.py",
                "import subprocess\nlaunch = subprocess.run\nlaunch('psql database')\n",
            )
            shadow = self.write(
                root,
                "custom-addons/example/models/shadow.py",
                "import subprocess\ncommand = 'echo safe'\ndef launch(command):\n    subprocess.run(command, shell=True)\n",
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(alias, allow_cursor_sql=False),
            )
            self.assertIn(
                "unanalyzable process invocation is prohibited in Odoo addons",
                hardening.python_findings(shadow, allow_cursor_sql=False),
            )

    def test_odoo_sql_db_helpers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "from odoo.sql_db import db_connect\nconnection = db_connect('postgresql://db')\n",
            )
            findings = hardening.python_findings(path, allow_cursor_sql=False)
            self.assertTrue(any("sql_db" in finding for finding in findings), findings)

    def test_odoo_package_sql_db_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "from odoo import sql_db as db\ndb.db_connect('database')\n",
            )
            self.assertTrue(
                any("sql_db connection helper" in finding for finding in hardening.python_findings(path, allow_cursor_sql=False))
            )

    def test_all_common_odoo_cursor_aliases_are_rejected(self) -> None:
        source = """
def apply(self, env, cr):
    self._cr.execute('DELETE FROM a')
    env.cr.execute('DELETE FROM b')
    cr.execute('DELETE FROM c')
    cursor = env.cr
    another_cursor = cursor
    another_cursor.execute('DELETE FROM d')
"""
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                source,
            )
            findings = hardening.python_findings(path, allow_cursor_sql=False)
            cursor_findings = [
                finding for finding in findings if "cursor execution" in finding
            ]
            self.assertEqual(4, len(cursor_findings), cursor_findings)
            self.assertFalse(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(
                        path,
                        allow_cursor_sql=True,
                    )
                )
            )

    def test_bound_cursor_execute_method_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "def apply(request):\n    execute = request.env.cr.execute\n    run = execute\n    run('DELETE FROM x')\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(
                        path, allow_cursor_sql=False
                    )
                )
            )

    def test_bound_execute_forwarded_to_helper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "def raw(execute):\n    execute('DELETE FROM x')\ndef apply(request):\n    raw(request.env.cr.execute)\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(
                        path, allow_cursor_sql=False
                    )
                )
            )

    def test_process_module_assignment_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/process.py",
                "import subprocess\nlauncher = subprocess\nlauncher.run('psql database')\n",
            )
            self.assertTrue(
                any(
                    "psql" in finding
                    for finding in hardening.python_findings(
                        path, allow_cursor_sql=False
                    )
                )
            )

    def test_sql_db_module_assignment_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/database.py",
                "from odoo import sql_db\ndatabase = sql_db\ndatabase.db_connect('database')\n",
            )
            self.assertTrue(
                any(
                    "sql_db connection helper" in finding
                    for finding in hardening.python_findings(
                        path, allow_cursor_sql=False
                    )
                )
            )

    def test_cursor_forwarded_through_helper_parameter_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/helper.py",
                "def raw(cursor):\n    cursor.execute('DELETE FROM x')\ndef route(request):\n    raw(request.env.cr)\n",
            )

    def test_same_named_helpers_in_different_classes_do_not_hide_cursor_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/helper.py",
                """
class A:
    def raw(self, cursor):
        cursor.execute('DELETE FROM x')

    def apply(self, request):
        self.raw(request.env.cr)

class B:
    def raw(self, other):
        return other
""",
            )
            self.assertTrue(any("cursor execution" in finding for finding in hardening.python_findings(path, allow_cursor_sql=False)))
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(path, allow_cursor_sql=False)
                )
            )

    def test_unrelated_function_assignment_does_not_hide_local_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cursor_path = self.write(
                root,
                "custom-addons/example/models/cursor.py",
                "def unsafe(request):\n    cursor = request.env.cr\n    cursor.execute('DELETE FROM x')\ndef unrelated(value):\n    cursor = value\n",
            )
            env_path = self.write(
                root,
                "custom-addons/example/controllers/env.py",
                "def unsafe(request, model):\n    env = request.env\n    return env[model]\ndef unrelated(value):\n    env = value\n",
            )
            self.assertTrue(any("cursor execution" in finding for finding in hardening.python_findings(cursor_path, allow_cursor_sql=False)))
            self.assertTrue(any("caller-selected Odoo model" in finding for finding in hardening.python_findings(env_path, allow_cursor_sql=False)))

    def test_dynamic_controller_model_proxy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dynamic = self.write(
                root,
                "custom-addons/example/controllers/api.py",
                "def route(request, payload):\n    return request.env[payload['model']].sudo().create(payload['values'])\n",
            )
            alias = self.write(
                root,
                "custom-addons/example/controllers/alias.py",
                "def route(request, payload):\n    env = request.env\n    return env[payload['model']].sudo().create(payload['values'])\n",
            )
            getitem = self.write(
                root,
                "custom-addons/example/controllers/getitem.py",
                "def route(request, payload):\n    return request.env.__getitem__(payload['model']).sudo().create(payload['values'])\n",
            )
            static = self.write(
                root,
                "custom-addons/example/controllers/static.py",
                "def route(request, payload):\n    return request.env['crm.lead'].create({'name': payload['name']})\n",
            )
            marker = (
                "controller uses a caller-selected Odoo model; only static model names are allowed"
            )
            self.assertIn(
                marker,
                hardening.python_findings(dynamic, allow_cursor_sql=False),
            )
            self.assertIn(
                marker,
                hardening.python_findings(alias, allow_cursor_sql=False),
            )
            self.assertIn(
                marker,
                hardening.python_findings(getitem, allow_cursor_sql=False),
            )
            self.assertNotIn(
                marker,
                hardening.python_findings(static, allow_cursor_sql=False),
            )

    def test_private_model_wrapper_is_allowed_only_for_literal_callers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = self.write(
                root,
                "custom-addons/example/controllers/safe.py",
                """
class Controller:
    def _read(self, model_name, public_id):
        return request.env[model_name].search([('public_id', '=', public_id)])

    def read_lead(self, public_id):
        return self._read('crm.lead', public_id)

    def read_partner(self, public_id):
        return self._read('res.partner', public_id)
""",
            )
            unsafe = self.write(
                root,
                "custom-addons/example/controllers/unsafe.py",
                """
class Controller:
    def _read(self, model_name, public_id):
        return request.env[model_name].search([('public_id', '=', public_id)])

    def route(self, model_name, public_id):
        return self._read(model_name, public_id)
""",
            )
            marker = (
                "controller uses a caller-selected Odoo model; only static model names are allowed"
            )
            self.assertNotIn(
                marker,
                hardening.python_findings(safe, allow_cursor_sql=False),
            )
            self.assertIn(
                marker,
                hardening.python_findings(unsafe, allow_cursor_sql=False),
            )

    def test_routed_private_wrapper_is_never_exempted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/controllers/routed.py",
                """
class Controller:
    @http.route('/proxy/<model_name>')
    def _proxy(self, model_name):
        return request.env[model_name].search([])

    def internal(self):
        return self._proxy('crm.lead')
""",
            )
            self.assertIn(
                "controller uses a caller-selected Odoo model; only static model names are allowed",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_aliased_route_decorator_never_exempts_dynamic_model_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/controllers/routed_alias.py",
                """
from odoo.http import route as endpoint

class Controller:
    @endpoint('/proxy/<model_name>')
    def _proxy(self, model_name):
        return request.env[model_name].search([])

    def internal(self):
        return self._proxy('crm.lead')
""",
            )
            self.assertIn(
                "controller uses a caller-selected Odoo model; only static model names are allowed",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_shadowed_parameter_anywhere_in_command_expression_is_dynamic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/shadow_list.py",
                "import subprocess\ncommand = 'echo safe'\ndef launch(command):\n    subprocess.run([command], shell=True)\n",
            )
            self.assertIn(
                "unanalyzable process invocation is prohibited in Odoo addons",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_process_callable_default_and_argument_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            default = self.write(
                root,
                "custom-addons/example/models/default_callable.py",
                "import subprocess\ndef invoke(command, launch=subprocess.run):\n    launch(command)\ninvoke('psql db')\n",
            )
            argument = self.write(
                root,
                "custom-addons/example/models/argument_callable.py",
                "import subprocess\ndef invoke(command, launch):\n    launch(command)\ninvoke('psql db', subprocess.run)\n",
            )
            for path in (default, argument):
                self.assertIn(
                    "unanalyzable process invocation is prohibited in Odoo addons",
                    hardening.python_findings(path, allow_cursor_sql=False),
                )

    def test_bridge_manifest_must_load_acl_and_tests_must_be_real(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(
                root,
                "custom-addons/codestra_middleware_bridge/__manifest__.py",
                "{'name': 'Bridge', 'data': []}",
            )
            self.write(
                root,
                "custom-addons/codestra_middleware_bridge/tests/__init__.py",
                "from . import test_placeholder\n",
            )
            self.write(
                root,
                "custom-addons/codestra_middleware_bridge/tests/test_placeholder.py",
                """
from odoo.tests.common import TransactionCase

class TestPlaceholder(TransactionCase):
    def test_signature_tenant_idempotency(self):
        self.assertTrue(True)
""",
            )
            findings = hardening.bridge_scaffold_findings(root)
            self.assertIn(
                "bridge manifest does not load security/security.xml",
                findings,
            )
            self.assertIn(
                "bridge manifest does not load security/ir.model.access.csv",
                findings,
            )
            self.assertIn(
                "bridge tests contain no meaningful discoverable Odoo test case methods",
                findings,
            )

    def test_valid_bridge_scaffold_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(
                root,
                "custom-addons/codestra_middleware_bridge/__manifest__.py",
                "{'name': 'Bridge', 'data': ['security/security.xml', 'security/ir.model.access.csv']}",
            )
            self.write(
                root,
                "custom-addons/codestra_middleware_bridge/tests/__init__.py",
                "from . import test_bridge\n",
            )
            self.write(
                root,
                "custom-addons/codestra_middleware_bridge/tests/test_bridge.py",
                """
from odoo.tests.common import HttpCase

class TestBridge(HttpCase):
    def test_controls(self):
        response = self.url_open('/synthetic')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get('signature'), 'signature')
        self.assertEqual(response.json().get('tenant'), 'tenant')
        self.assertEqual(response.json().get('idempotency'), 'idempotency')
""",
            )
            self.assertEqual([], hardening.bridge_scaffold_findings(root))

    def test_unreviewed_sql_is_not_exempted_by_a_directory_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(
                root,
                "config/canonical-addon-baseline.json",
                json.dumps({"modules": {}, "strict_mission_overrides": {}}),
            )
            path = self.write(
                root,
                "custom-addons/example/migrations/controllers.py",
                "def route(request):\n    request.env.cr.execute('DELETE FROM x')\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(
                        path,
                        allow_cursor_sql=False,
                    )
                )
            )

    def test_dynamic_model_selector_in_model_helper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/proxy.py",
                "def dispatch(self, model_name, values):\n    return self.env[model_name].sudo().create(values)\n",
            )
            self.assertIn(
                "controller uses a caller-selected Odoo model; only static model names are allowed",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_operator_getitem_dynamic_model_selector_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module_path = self.write(
                root,
                "custom-addons/example/models/operator_module.py",
                "import operator as op\ndef dispatch(request, payload):\n    return op.getitem(request.env, payload['model']).sudo().create({})\n",
            )
            alias_path = self.write(
                root,
                "custom-addons/example/models/operator_alias.py",
                "from operator import getitem as select\ndef dispatch(request, payload):\n    return select(request.env, payload['model']).sudo().create({})\n",
            )
            for path in (module_path, alias_path):
                self.assertTrue(
                    any(
                        "caller-selected Odoo model" in finding
                        for finding in hardening.python_findings(
                            path, allow_cursor_sql=False
                        )
                    )
                )

    def test_statically_resolved_model_selectors_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/static.py",
                "MODEL = 'crm.lead'\ndef read(self):\n    first = self.env[MODEL]\n    second = self.env['crm.' + 'lead']\n    return first, second\n",
            )
            self.assertFalse(
                any(
                    "caller-selected Odoo model" in finding
                    for finding in hardening.python_findings(
                        path, allow_cursor_sql=False
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
