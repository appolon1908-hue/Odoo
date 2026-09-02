from __future__ import annotations

import json
import os
import shutil
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

    def policy_document(self) -> dict[str, object]:
        return {
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
            "require_private_destination": True,
            "pre_import_full_history_secret_scan": True,
            "activate_source_workflows": False,
            "preserve_destination_paths": [
                ".github",
                ".gitignore",
                ".gitleaks.toml",
                "README.md",
                "config",
                "scripts",
                "tests/security",
                "docs/UPSTREAM-SYNC.md",
            ],
            "excluded_source_paths": [".git"],
            "runtime_activation": False,
            "deployment_authorized": False,
            "live_write_authorized": False,
        }

    def policy(self, destination: Path) -> Path:
        path = destination / "config" / "upstream-sync-policy.json"
        self.write(
            destination,
            "config/upstream-sync-policy.json",
            json.dumps(self.policy_document(), indent=2) + "\n",
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

    def prepare_destination(self, destination: Path) -> Path:
        self.write(destination, "README.md", "destination readme\n")
        self.write(destination, ".gitleaks.toml", "[allowlist]\n")
        self.write(destination, ".github/workflows/target.yml", "name: target\n")
        self.write(destination, "config/mission.json", "{}\n")
        self.write(destination, "scripts/run_ci.sh", "#!/bin/sh\necho destination-ci\n")
        self.write(destination, "scripts/sync_codestra_odoo_addons.py", "# preserved\n")
        self.write(destination, "tests/security/test_guard.py", "# preserved\n")
        self.write(destination, "docs/UPSTREAM-SYNC.md", "destination sync docs\n")
        self.add_module(destination, "custom-addons", "target_only", "target")
        return self.policy(destination)

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
            self.write(source, "config/mission.json", '{"source": true}\n')
            self.write(source, "scripts/run_ci.sh", "#!/bin/sh\necho untrusted\n")
            self.write(source, "tests/security/test_guard.py", "raise SystemExit(1)\n")
            self.write(source, "docs/source.md", "upstream document\n")
            self.add_module(source, "ci_addons", "module_a", "upstream-a")
            source_sha = self.commit(source, "initial source")
            policy = self.prepare_destination(destination)

            state = sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            self.assertEqual(source_sha, state["source_sha"])
            self.assertEqual("destination readme\n", (destination / "README.md").read_text())
            self.assertEqual("{}\n", (destination / "config/mission.json").read_text())
            self.assertEqual(
                "#!/bin/sh\necho destination-ci\n",
                (destination / "scripts/run_ci.sh").read_text(),
            )
            self.assertEqual(
                "# preserved\n",
                (destination / "tests/security/test_guard.py").read_text(),
            )
            self.assertTrue((destination / ".github/workflows/target.yml").is_file())
            self.assertFalse((destination / ".github/workflows/source.yml").exists())
            self.assertEqual(
                "upstream document\n",
                (destination / "docs/source.md").read_text(),
            )
            snapshot = destination / "upstream/codestra-odoo-addons"
            self.assertEqual("upstream readme\n", (snapshot / "README.md").read_text())
            self.assertTrue((snapshot / ".github/workflows/source.yml").is_file())
            self.assertTrue((snapshot / "scripts/run_ci.sh").is_file())
            self.assertTrue(
                (destination / "custom-addons/module_a/__manifest__.py").is_file()
            )
            self.assertTrue(
                (destination / "custom-addons/target_only/__manifest__.py").is_file()
            )
            self.assertEqual(["target_only"], state["target_only_modules"])
            sync.verify_state(destination=destination, policy_path=policy)

    def test_file_and_directory_transitions_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(source, "docs/item", "first-file\n")
            self.commit(source, "file form")
            policy = self.prepare_destination(destination)

            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            (source / "docs/item").unlink()
            self.write(source, "docs/item/child.txt", "directory form\n")
            self.commit(source, "directory form")
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            self.assertEqual(
                "directory form\n",
                (destination / "docs/item/child.txt").read_text(),
            )

            shutil.rmtree(source / "docs/item")
            self.write(source, "docs/item", "second-file\n")
            self.commit(source, "file form again")
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            self.assertTrue((destination / "docs/item").is_file())
            self.assertEqual("second-file\n", (destination / "docs/item").read_text())

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
            policy = self.prepare_destination(destination)
            self.write(destination, "unmanaged.txt", "keep me\n")

            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            shutil.rmtree(source / "addons/module_a")
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
            policy = self.prepare_destination(destination)

            with self.assertRaisesRegex(sync.SyncError, "duplicate addon names"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_symlinked_module_content_requires_explicit_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "nested/addons", "module_a", "first")
            self.write(source, "shared/common.py", "VALUE = 1\n")
            (source / "nested/addons/module_a/common.py").symlink_to(
                Path("../../../shared/common.py")
            )
            self.commit(source, "module symlink")
            policy = self.prepare_destination(destination)

            with self.assertRaisesRegex(sync.SyncError, "symlinked addon content"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_repository_escaping_or_excluded_symlink_fails_closed(self) -> None:
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
            policy = self.prepare_destination(destination)

            with self.assertRaisesRegex(sync.SyncError, "unsafe or broken upstream symlink"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_preserved_child_cannot_be_replaced_by_upstream_ancestor_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(source, "payload/security/test_guard.py", "raise SystemExit(1)\n")
            (source / "tests").symlink_to("payload", target_is_directory=True)
            self.commit(source, "ancestor symlink")
            policy = self.prepare_destination(destination)

            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            self.assertTrue((destination / "tests").is_dir())
            self.assertFalse((destination / "tests").is_symlink())
            self.assertEqual(
                "# preserved\n",
                (destination / "tests/security/test_guard.py").read_text(),
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_runtime_root_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            (source / "custom-addons").symlink_to("addons", target_is_directory=True)
            self.commit(source, "runtime root symlink")
            policy = self.prepare_destination(destination)

            with self.assertRaisesRegex(sync.SyncError, "runtime addon root"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    def test_upstream_source_marker_name_is_reserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.write(source, ".source.json", '{"untrusted": true}\n')
            self.commit(source, "reserved marker")
            policy = self.prepare_destination(destination)

            with self.assertRaisesRegex(sync.SyncError, "reserves .source.json"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    def test_policy_rejects_replaceable_destination_validation_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            document = self.policy_document()
            document["preserve_destination_paths"] = [
                ".github",
                ".gitignore",
                ".gitleaks.toml",
                "README.md",
                "config",
                "tests/security",
            ]
            path = self.write(
                destination,
                "config/upstream-sync-policy.json",
                json.dumps(document),
            )
            with self.assertRaisesRegex(sync.SyncError, "scripts"):
                sync.load_policy(path)


if __name__ == "__main__":
    unittest.main()
