from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts import validate_integration_boundary_hardening as hardening


class IntegrationBoundaryHardeningTerminationTests(unittest.TestCase):
    def test_conflicting_literal_assignments_remain_unresolved(self) -> None:
        tree = ast.parse("command = 'safe'\ncommand = 'different'\n")
        self.assertEqual({}, hardening.static_assignments(tree))

    def test_conflicting_process_command_assignments_fail_closed(self) -> None:
        source = """
import subprocess
command = 'echo safe'
command = 'echo different'
subprocess.run(command)
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom-addons" / "example" / "models" / "job.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
            self.assertIn(
                "unanalyzable process invocation is prohibited in Odoo addons",
                hardening.python_findings(path, allow_cursor_sql=False),
            )

    def test_static_dependency_chain_resolves_once(self) -> None:
        tree = ast.parse(
            "prefix = 'psql '\n"
            "target = 'postgresql://db/write'\n"
            "command = prefix + target\n"
        )
        self.assertEqual(
            {
                "prefix": "psql ",
                "target": "postgresql://db/write",
                "command": "psql postgresql://db/write",
            },
            hardening.static_assignments(tree),
        )


if __name__ == "__main__":
    unittest.main()
