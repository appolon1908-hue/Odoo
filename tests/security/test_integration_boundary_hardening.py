from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import validate_integration_boundary_hardening as hardening
from scripts import validate_integration_boundary as boundary
from scripts import validate_platform_control_plane as platform_control_plane


class IntegrationBoundaryHardeningTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_platform_policy_hmac_field_order_must_match_contract(self) -> None:
        expected = ["timestamp", "event_id", "raw_body"]
        platform_control_plane.validate_hmac_field_order(expected, expected, expected)
        with self.assertRaisesRegex(
            SystemExit, "machine integration policy HMAC canonical field order drifted"
        ):
            platform_control_plane.validate_hmac_field_order(
                expected, list(reversed(expected)), expected
            )

    def test_platform_compatibility_routes_require_exact_methods_and_replay(self) -> None:
        expected = {"/compatibility": {"GET", "PATCH"}}
        platform_control_plane.validate_route_contract(
            {"/compatibility": ({"GET", "PATCH"}, True)}, expected
        )
        with self.assertRaisesRegex(SystemExit, "route methods drifted"):
            platform_control_plane.validate_route_contract(
                {"/compatibility": ({"GET"}, True)}, expected
            )
        with self.assertRaisesRegex(SystemExit, "replay-protected"):
            platform_control_plane.validate_route_contract(
                {"/compatibility": ({"GET", "PATCH"}, False)}, expected
            )

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

    def test_database_credentials_are_rejected_in_ordinary_addon_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(
                root,
                "custom-addons/example/data/provider.xml",
                "<odoo><field name='value'>postgresql://odoo:example-secret@db/odoo</field></odoo>",
            )
            findings = hardening.scan_repository(root)
            self.assertTrue(
                any("addon text contains database credentials" in finding for finding in findings)
            )

    def test_chained_assignments_propagate_guarded_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/chained.py",
                "def apply(request):\n    cursor = saved = request.env.cr\n    cursor.execute('DELETE FROM x')\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(path, allow_cursor_sql=False)
                )
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

    def test_python_literal_database_credentials_are_rejected_without_process_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/job.py",
                "DSN = 'postgresql://odoo:example-secret@db/odoo'\n",
            )
            self.assertIn(
                "Python source contains database credentials or PostgreSQL DSN",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_composed_python_database_credentials_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/composed.py",
                "DSN = 'postgres' + 'ql://odoo:example-secret@db/odoo'\n",
            )
            self.assertIn(
                "Python source contains database credentials or PostgreSQL DSN",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_direct_os_exec_and_spawn_psql_launchers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exec_path = self.write(
                root,
                "custom-addons/example/models/exec_job.py",
                "import os\nos.execvp('psql', ['psql', 'db'])\n",
            )
            spawn_path = self.write(
                root,
                "custom-addons/example/models/spawn_job.py",
                "import os\nos.spawnvp(os.P_NOWAIT, 'psql', ['psql', 'db'])\n",
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(exec_path, allow_cursor_sql=False),
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(spawn_path, allow_cursor_sql=False),
            )

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

    def test_attribute_bound_process_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/attribute_alias.py",
                "import subprocess\nclass Job:\n    launch = subprocess.run\n    def apply(self):\n        self.launch('psql db', shell=True)\n",
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_loop_bound_process_command_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/loop_shadow.py",
                "import subprocess\ncommand = 'echo safe'\ndef apply(values):\n    for command in values:\n        subprocess.run(command, shell=True)\n",
            )
            self.assertIn(
                "unanalyzable process invocation is prohibited in Odoo addons",
                hardening.python_findings(path, allow_cursor_sql=False),
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

    def test_environment_identity_propagates_through_helper_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/controllers/helper_env.py",
                "def dispatch(env, model):\n    return env[model].sudo().create({})\ndef route(request, payload):\n    return dispatch(request.env, payload['model'])\n",
            )
            self.assertIn(
                "controller uses a caller-selected Odoo model; only static model names are allowed",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_acl_guarded_dynamic_browse_is_read_only_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = self.write(
                root,
                "custom-addons/example/models/safe_browse.py",
                "def resolve(env, model_name, record_id):\n    model = env[model_name]\n    record = model.browse(record_id).exists()\n    record.check_access('read')\n    return record\ndef caller(request, payload):\n    return resolve(request.env, payload['model'], payload['id'])\n",
            )
            unsafe = self.write(
                root,
                "custom-addons/example/models/unsafe_browse.py",
                "def resolve(env, model_name, record_id):\n    model = env[model_name]\n    record = model.browse(record_id).exists()\n    record.check_access('read')\n    record.action_confirm()\n    return record\ndef caller(request, payload):\n    return resolve(request.env, payload['model'], payload['id'])\n",
            )
            marker = "controller uses a caller-selected Odoo model; only static model names are allowed"
            self.assertNotIn(marker, hardening.python_findings(safe, allow_cursor_sql=False))
            self.assertIn(marker, hardening.python_findings(unsafe, allow_cursor_sql=False))

    def test_acl_guarded_dynamic_browse_rejects_aliases_mutations_and_weak_guards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = {
                "alias.py": "other = record\n    other.write({'name': 'x'})",
                "subscript.py": "record['name'] = 'x'",
                "conditional.py": "if False:\n        record.check_access('read')",
            }
            marker = "controller uses a caller-selected Odoo model; only static model names are allowed"
            for name, use in cases.items():
                path = self.write(
                    root,
                    f"custom-addons/example/models/{name}",
                    "def resolve(env, model_name, record_id):\n"
                    "    model = env[model_name]\n"
                    "    record = model.browse(record_id).exists()\n"
                    f"    {use}\n"
                    "    return record\n"
                    "def caller(request, payload):\n"
                    "    return resolve(request.env, payload['model'], payload['id'])\n",
                )
                self.assertIn(marker, hardening.python_findings(path, allow_cursor_sql=False), name)

            nested = self.write(
                root,
                "custom-addons/example/models/nested_alias.py",
                "def resolve(env, model_name, record_id, values):\n"
                "    model = env[model_name]\n"
                "    record = model.browse(record_id).exists()\n"
                "    record.check_access('read')\n"
                "    holder = [record]\n"
                "    holder[0].write(values)\n"
                "    return record\n"
                "def caller(request, payload):\n"
                "    return resolve(request.env, payload['model'], payload['id'], payload['values'])\n",
            )
            self.assertIn(marker, hardening.python_findings(nested, allow_cursor_sql=False))

            for name, use in {
                "setattr_escape.py": "setattr(record, 'name', value)",
                "helper_escape.py": "mutate(record, value)",
            }.items():
                escaped = self.write(
                    root,
                    f"custom-addons/example/models/{name}",
                    "def resolve(env, model_name, record_id, value):\n"
                    "    model = env[model_name]\n"
                    "    record = model.browse(record_id).exists()\n"
                    "    record.check_access('read')\n"
                    f"    {use}\n"
                    "    return record\n"
                    "def caller(request, payload):\n"
                    "    return resolve(request.env, payload['model'], payload['id'], payload['value'])\n",
                )
                self.assertIn(marker, hardening.python_findings(escaped, allow_cursor_sql=False), name)

    def test_process_module_aliases_are_lexically_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/scoped_process.py",
                "import subprocess\ndef unsafe():\n    launcher = subprocess\n    launcher.run('psql db')\ndef unrelated(value):\n    launcher = value\n    return launcher\n",
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

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

    def test_reflective_environment_indexing_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/controllers/reflective.py",
                "def route(request, payload, values):\n    return getattr(request.env, '__getitem__')(payload['model']).sudo().create(values)\n",
            )
            self.assertIn(
                "controller uses a caller-selected Odoo model; only static model names are allowed",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_reflective_cursor_execution_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/reflective_cursor.py",
                "def apply(request):\n    getattr(request.env.cr, 'execute')('DELETE FROM x')\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(path, allow_cursor_sql=False)
                )
            )

    def test_reflectively_acquired_cursor_method_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/reflective_cursor_alias.py",
                "def apply(request):\n    run_sql = getattr(request.env.cr, 'execute')\n    run_sql('DELETE FROM x')\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(path, allow_cursor_sql=False)
                )
            )

    def test_reflectively_acquired_process_launcher_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/reflective_process.py",
                "import subprocess\nlaunch = getattr(subprocess, 'run')\nlaunch(['psql', 'database'])\n",
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_immediately_invoked_reflective_process_launcher_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/direct_reflective_process.py",
                "import subprocess\ngetattr(subprocess, 'run')(['psql', 'database'])\n",
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_asyncio_subprocess_launchers_and_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            direct = self.write(
                root,
                "custom-addons/example/models/async_process.py",
                "import asyncio\nasync def run():\n    await asyncio.create_subprocess_exec('psql', 'database')\n",
            )
            alias = self.write(
                root,
                "custom-addons/example/models/async_process_alias.py",
                "from asyncio import create_subprocess_shell as launch\nasync def run():\n    await launch('psql database')\n",
            )
            for path in (direct, alias):
                self.assertIn(
                    "Python process invocation of psql is prohibited",
                    hardening.python_findings(path, allow_cursor_sql=False),
                )

    def test_unpacked_process_callable_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/unpacked_process.py",
                "import subprocess\nlaunch, unused = subprocess.run, None\nlaunch(['psql', 'database'])\n",
            )
            self.assertIn(
                "Python process invocation of psql is prohibited",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_chained_bound_cursor_method_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/chained_cursor_methods.py",
                "def apply(request):\n    run_sql = saved = request.env.cr.execute\n    run_sql('DELETE FROM res_users')\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(path, allow_cursor_sql=False)
                )
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

    def test_private_model_wrapper_callable_escape_revokes_exemption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, invocation in {
                "assigned.py": "invoke = helper._dispatch\n    return invoke(payload['model'])",
                "reflective.py": "invoke = getattr(helper, '_dispatch')\n    return invoke(payload['model'])",
            }.items():
                path = self.write(
                    root,
                    f"custom-addons/example/controllers/{name}",
                    "class Helper:\n"
                    "    def _dispatch(self, model):\n"
                    "        return request.env[model].search([])\n"
                    "    def safe(self):\n"
                    "        return self._dispatch('crm.lead')\n"
                    "def route(helper, payload):\n"
                    f"    {invocation}\n",
                )
                self.assertIn(
                    "controller uses a caller-selected Odoo model; only static model names are allowed",
                    hardening.python_findings(path, allow_cursor_sql=False),
                    name,
                )

    def test_same_named_safe_helper_does_not_exempt_routed_lexical_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/controllers/owners.py",
                """
class Helper:
    def _dispatch(self, model):
        return request.env[model].search([])
    def safe(self):
        return self._dispatch('crm.lead')

class Controller:
    @http.route('/proxy/<model>')
    def _dispatch(self, model):
        return request.env[model].sudo().create({})
""",
            )
            self.assertIn(
                "controller uses a caller-selected Odoo model; only static model names are allowed",
                hardening.python_findings(path, allow_cursor_sql=False),
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

    def test_module_constant_shadowed_by_parameter_is_dynamic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/shadowed_model.py",
                "MODEL = 'crm.lead'\ndef dispatch(self, MODEL, values):\n    return self.env[MODEL].create(values)\n",
            )
            self.assertIn(
                "controller uses a caller-selected Odoo model; only static model names are allowed",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_cursor_executemany_and_bound_alias_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/bulk_sql.py",
                "def bulk(self, rows):\n    run = self.env.cr.executemany\n    run('INSERT INTO x VALUES (%s)', rows)\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(path, allow_cursor_sql=False)
                )
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

    def test_assigned_operator_getitem_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/operator_assigned.py",
                "import operator\nget = operator.getitem\ndef dispatch(request, payload):\n    return get(request.env, payload['model']).sudo().create({})\n",
            )
            self.assertTrue(
                any(
                    "caller-selected Odoo model" in finding
                    for finding in hardening.python_findings(path, allow_cursor_sql=False)
                )
            )

    def test_cursor_attribute_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(
                Path(directory),
                "custom-addons/example/models/attribute_cursor.py",
                "def remove(self):\n    self.cursor = self.env.cr\n    self.cursor.execute('DELETE FROM x')\n",
            )
            self.assertTrue(
                any(
                    "cursor execution" in finding
                    for finding in hardening.python_findings(path, allow_cursor_sql=False)
                )
            )

    def test_subprocess_shell_output_helpers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for helper in ("getoutput", "getstatusoutput"):
                path = self.write(
                    root,
                    f"custom-addons/example/models/{helper}.py",
                    f"import subprocess\ndef probe():\n    return subprocess.{helper}('psql database')\n",
                )
                self.assertTrue(
                    any(
                        "psql" in finding
                        for finding in hardening.python_findings(path, allow_cursor_sql=False)
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
