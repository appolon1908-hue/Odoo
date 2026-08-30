from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import sync_codestra_odoo_addons as sync


class UpstreamSyncTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def git(self, repository: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def initialize_source(self, source: Path) -> None:
        self.git(source, "init", "-q")
        self.git(source, "config", "user.name", "Sync Test")
        self.git(source, "config", "user.email", "sync-test@example.invalid")

    def commit(self, source: Path, message: str) -> str:
        self.git(source, "add", "-A")
        self.git(source, "commit", "-q", "-m", message)
        return self.git(source, "rev-parse", "HEAD")

    def policy(self, destination: Path) -> Path:
        path = destination / "config" / "upstream-sync-policy.json"
        self.write(
            destination,
            "config/upstream-sync-policy.json",
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source_repository": "Codestra-SRL/codestra-odoo-addons",
                    "source_ref": "main",
                    "destination_repository": "appolon1908-hue/Odoo",
                    "sync_strategy": "full_source_overlay_with_runtime_addon_promotion",
                    "snapshot_path": "upstream/codestra-odoo-addons",
                    "runtime_addons_path": "custom-addons",
                    "state_path": "config/upstream-sync-state.json",
                    "source_wins_on_non_governance_collisions": True,
                    "delete_only_previously_managed_paths": True,
                    "activate_source_workflows": False,
                    "preserve_destination_paths": [
                        ".github",
                        ".gitignore",
                        ".gitleaks.toml",
                        "README.md",
                        "config/upstream-sync-policy.json",
                        "config/upstream-sync-state.json",
                        "docs/UPSTREAM-SYNC.md",
                        "scripts/sync_codestra_odoo_addons.py",
                        "tests/security/test_upstream_sync.py",
                    ],
                    "excluded_source_paths": [".git"],
                    "runtime_activation": False,
                    "deployment_authorized": False,
                    "live_write_authorized": False,
                },
                indent=2,
            )
            + "\n",
        )
        return path

    def add_module(self, source: Path, root: str, name: str, marker: str) -> None:
        self.write(source, f"{root}/{name}/__init__.py", "from . import models\n")
        self.write(
            source,
            f"{root}/{name}/__manifest__.py",
            "{'name': '" + name + "', 'version': '19.0.1.0.0'}\n",
        )
        self.write(source, f"{root}/{name}/models.py", f"MARKER = {marker!r}\n")

    def test_complete_snapshot_overlay_and_runtime_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)

            self.write(source, "README.md", "upstream readme\n")
            self.write(source, ".github/workflows/source.yml", "name: source\n")
            self.write(source, "docs/source.md", "upstream document\n")
            self.add_module(source, "ci_addons", "module_a", "upstream-a")
            source_sha = self.commit(source, "initial source")

            self.write(destination, "README.md", "destination readme\n")
            self.write(destination, ".github/workflows/target.yml", "name: target\n")
            self.add_module(destination, "custom-addons", "target_only", "target")
            policy = self.policy(destination)

            state = sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            self.assertEqual(source_sha, state["source_sha"])
            self.assertEqual("destination readme\n", (destination / "README.md").read_text())
            self.assertTrue((destination / ".github/workflows/target.yml").is_file())
            self.assertFalse((destination / ".github/workflows/source.yml").exists())
            self.assertEqual(
                "upstream document\n",
                (destination / "docs/source.md").read_text(),
            )
            self.assertEqual(
                "upstream readme\n",
                (
                    destination
                    / "upstream/codestra-odoo-addons/README.md"
                ).read_text(),
            )
            self.assertTrue(
                (
                    destination
                    / "upstream/codestra-odoo-addons/.github/workflows/source.yml"
                ).is_file()
            )
            self.assertTrue(
                (destination / "custom-addons/module_a/__manifest__.py").is_file()
            )
            self.assertTrue(
                (destination / "custom-addons/target_only/__manifest__.py").is_file()
            )
            self.assertEqual(["target_only"], state["target_only_modules"])
            sync.verify_state(destination=destination, policy_path=policy)

    def test_later_sync_deletes_only_previously_managed_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "module a")
            self.add_module(destination, "custom-addons", "target_only", "target")
            self.write(destination, "unmanaged.txt", "keep me\n")
            policy = self.policy(destination)

            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            shutil_target = source / "addons" / "module_a"
            for path in sorted(shutil_target.rglob("*"), reverse=True):
                if path.is_file() or path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            shutil_target.rmdir()
            self.add_module(source, "addons", "module_b", "second")
            self.commit(source, "replace module")

            state = sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            self.assertFalse((destination / "custom-addons/module_a").exists())
            self.assertTrue((destination / "custom-addons/module_b").is_dir())
            self.assertTrue((destination / "custom-addons/target_only").is_dir())
            self.assertEqual("keep me\n", (destination / "unmanaged.txt").read_text())
            self.assertEqual(["target_only"], state["target_only_modules"])

    def test_duplicate_module_names_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "duplicate", "one")
            self.add_module(source, "ci_addons", "duplicate", "two")
            self.commit(source, "duplicates")
            policy = self.policy(destination)

            with self.assertRaisesRegex(sync.SyncError, "duplicate addon names"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_repository_escaping_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            outside = root / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")
            (source / "escape").symlink_to(outside)
            self.commit(source, "unsafe symlink")
            policy = self.policy(destination)

            with self.assertRaisesRegex(sync.SyncError, "unsafe or broken upstream symlink"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )


if __name__ == "__main__":
    unittest.main()
