from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import sync_codestra_odoo_addons as sync
from scripts import review_modules
from scripts import validate_legacy_addon_baseline as baseline


class UpstreamSyncTests(unittest.TestCase):
    def test_isolated_validation_rejects_candidate_module_shadowing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = Path(__file__).resolve().parents[2] / "scripts/run_isolated_source_tests.py"
            self.write(root, "scripts/run_isolated_source_tests.py", runner.read_text())
            self.write(root, "scripts/trusted_marker.py", "VALUE = 'trusted'\n")
            for name in ("scripts.py", "json.py"):
                self.write(root, name, "raise RuntimeError('candidate code executed')\n")
            self.write(
                root, "tests/security/test_import.py",
                "import json\nimport unittest\nfrom scripts import trusted_marker\n"
                "class ImportTest(unittest.TestCase):\n"
                "    def test_trusted(self):\n"
                "        self.assertEqual(trusted_marker.VALUE, 'trusted')\n"
                "        self.assertEqual(json.dumps({}), '{}')\n",
            )
            subprocess.run(
                ["python3", "-I", "scripts/run_isolated_source_tests.py"],
                cwd=root, check=True, capture_output=True, text=True,
            )

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
                ".codestra/calling-contract.lock.json",
                "contracts/vendor/calling-contract-authority",
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
        self.write(destination, ".codestra/calling-contract.lock.json", '{"role": "agent_workspace"}\n')
        self.write(destination, "contracts/vendor/calling-contract-authority/component.yaml", "destination authority\n")
        self.add_module(destination, "custom-addons", "target_only", "target")
        return self.policy(destination)

    def test_module_tree_validators_read_the_staged_candidate_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self.initialize_source(repository)
            module = repository / "custom-addons/example"
            self.write(repository, "custom-addons/example/__manifest__.py", "{'name': 'before'}\n")
            self.commit(repository, "baseline")
            head_tree = self.git(repository, "rev-parse", "HEAD:custom-addons/example")

            self.write(repository, "custom-addons/example/__manifest__.py", "{'name': 'candidate'}\n")
            self.git(repository, "add", "-A")
            candidate_tree = self.git(repository, "write-tree")
            candidate_module_tree = self.git(
                repository, "rev-parse", f"{candidate_tree}:custom-addons/example"
            )
            self.assertNotEqual(head_tree, candidate_module_tree)

            with (
                mock.patch.dict(os.environ, {"ODOO_VALIDATION_TREEISH": candidate_tree}),
                mock.patch.object(baseline, "ROOT", repository),
                mock.patch.object(review_modules, "ROOT", repository),
            ):
                self.assertEqual(
                    candidate_module_tree,
                    baseline.git_tree_sha(Path("custom-addons/example")),
                )
                self.assertEqual(
                    candidate_module_tree,
                    review_modules.git_tree_sha(module),
                )

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
            self.write(source, ".codestra/calling-contract.lock.json", '{"role": "untrusted"}\n')
            self.write(source, "contracts/vendor/calling-contract-authority/component.yaml", "upstream authority\n")
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
            for relative, expected, upstream_expected in (
                (".codestra/calling-contract.lock.json", '{"role": "agent_workspace"}\n', '{"role": "untrusted"}\n'),
                ("contracts/vendor/calling-contract-authority/component.yaml", "destination authority\n", "upstream authority\n"),
            ):
                self.assertEqual(expected, (destination / relative).read_text())
                self.assertEqual(upstream_expected, (snapshot / relative).read_text())
                self.assertNotIn(relative, state["managed_overlay_files"])
            self.assertTrue(
                (destination / "custom-addons/module_a/__manifest__.py").is_file()
            )
            self.assertTrue(
                (destination / "custom-addons/target_only/__manifest__.py").is_file()
            )
            self.assertEqual(["target_only"], state["target_only_modules"])
            sync.verify_state(destination=destination, policy_path=policy)

            (destination / "docs/source.md").write_text("overlay tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(sync.SyncError, "managed overlay content drift"):
                sync.verify_state(destination=destination, policy_path=policy)
            (destination / "docs/source.md").write_text("upstream document\n", encoding="utf-8")

            state_path = destination / "config/upstream-sync-state.json"
            recorded = json.loads(state_path.read_text(encoding="utf-8"))
            recorded["managed_overlay_files"].remove("docs/source.md")
            state_path.write_text(json.dumps(recorded), encoding="utf-8")
            with self.assertRaisesRegex(sync.SyncError, "managed overlay file inventory drift"):
                sync.verify_state(destination=destination, policy_path=policy)
            recorded["managed_overlay_files"].append("docs/source.md")
            state_path.write_text(json.dumps(recorded), encoding="utf-8")

            (snapshot / "docs/source.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(sync.SyncError, "snapshot content drift"):
                sync.verify_state(destination=destination, policy_path=policy)

    def test_symlink_to_destination_preserved_source_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.write(source, "scripts/tool.py", "# upstream\n")
            os.symlink("scripts", source / "alias")
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "symlink to preserved path")
            policy = self.prepare_destination(destination)

            with self.assertRaisesRegex(
                sync.SyncError, "destination-preserved path"
            ):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    def test_symlink_to_ancestor_of_destination_preserved_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.write(source, "tests/security/test_guard.py", "# upstream\n")
            os.symlink("tests", source / "alias")
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "symlink to preserved ancestor")
            policy = self.prepare_destination(destination)

            with self.assertRaisesRegex(sync.SyncError, "destination-preserved path"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    def test_snapshot_only_symlink_inside_preserved_path_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.write(source, "scripts/helper.py", "# upstream helper\n")
            os.symlink("helper.py", source / "scripts/tool.py")
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "snapshot-only preserved symlink")
            policy = self.prepare_destination(destination)

            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            snapshot_link = destination / "upstream/codestra-odoo-addons/scripts/tool.py"
            self.assertTrue(snapshot_link.is_symlink())
            self.assertEqual(
                "#!/bin/sh\necho destination-ci\n",
                (destination / "scripts/run_ci.sh").read_text(encoding="utf-8"),
            )

    def test_verify_state_rejects_marker_provenance_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "canonical source")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            marker_path = destination / "upstream/codestra-odoo-addons/.source.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["source_ref"] = "unreviewed"
            marker_path.write_text(json.dumps(marker), encoding="utf-8")

            with self.assertRaisesRegex(sync.SyncError, "snapshot source_ref drift"):
                sync.verify_state(destination=destination, policy_path=policy)

    def test_legacy_openerp_manifest_is_not_a_promotable_addon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "legacy"
            self.write(root, "legacy/__openerp__.py", "{'name': 'legacy'}\n")
            self.assertEqual({}, sync.discover_modules(root, []))

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

    def test_unmanaged_file_ancestor_is_rejected_before_overlay(self) -> None:
        for prior_sync in (False, True):
            for child in ("docs/item/child.txt", "docs/item/sub/child.txt"):
                with self.subTest(prior_sync=prior_sync, child=child):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        source = root / "source"
                        destination = root / "destination"
                        source.mkdir()
                        destination.mkdir()
                        self.initialize_source(source)
                        self.add_module(source, "addons", "module_a", "first")
                        self.commit(source, "initial source")
                        policy = self.prepare_destination(destination)
                        if prior_sync:
                            sync.synchronize(
                                upstream=source, destination=destination,
                                policy_path=policy, source_ref="main",
                            )
                        self.write(destination, "docs/item", "destination-only\n")
                        self.initialize_source(destination)
                        self.commit(destination, "tracked destination-only file")
                        self.write(source, "aaa.txt", "must not overlay\n")
                        self.write(source, child, "upstream directory content\n")
                        self.commit(source, "directory collides with local file")

                        with self.assertRaisesRegex(
                            sync.SyncError, "would delete unmanaged ancestor"
                        ):
                            sync.synchronize(
                                upstream=source, destination=destination,
                                policy_path=policy, source_ref="main",
                            )
                        self.assertEqual(
                            "destination-only\n",
                            (destination / "docs/item").read_text(),
                        )
                        self.assertFalse((destination / "aaa.txt").exists())

    def test_nested_directory_replacement_recreates_removed_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(source, "docs/item", "file collision\n")
            self.commit(source, "file form")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            (source / "docs/item").unlink()
            self.write(source, "docs/item/sub/child.txt", "nested form\n")
            self.commit(source, "nested directory form")
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            self.assertEqual(
                "nested form\n",
                (destination / "docs/item/sub/child.txt").read_text(
                    encoding="utf-8"
                ),
            )

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
            (source / "escape").symlink_to(Path("../outside.txt"))
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
    def test_absolute_in_checkout_symlink_is_not_relocation_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            shared = self.write(source, "shared/value.txt", "value\n")
            (source / "absolute-link").symlink_to(shared)
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "absolute symlink")
            policy = self.prepare_destination(destination)

            with self.assertRaisesRegex(sync.SyncError, "absolute upstream symlink"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )

    def test_verify_state_recomputes_target_only_module_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.add_module(source, "addons", "module_b", "second")
            self.commit(source, "source module")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            state_path = destination / "config/upstream-sync-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["target_only_modules"] = []
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(sync.SyncError, "target-only addon inventory drift"):
                sync.verify_state(destination=destination, policy_path=policy)

    def test_verify_state_derives_imported_modules_and_bytes_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.add_module(source, "addons", "module_b", "second")
            self.commit(source, "source module")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            state_path = destination / "config/upstream-sync-state.json"
            original = json.loads(state_path.read_text(encoding="utf-8"))

            reclassified = json.loads(json.dumps(original))
            reclassified["modules"].pop("module_a")
            reclassified["target_only_modules"].append("module_a")
            reclassified["target_only_modules"].sort()
            state_path.write_text(json.dumps(reclassified), encoding="utf-8")
            with self.assertRaisesRegex(sync.SyncError, "imported addon inventory drift"):
                sync.verify_state(destination=destination, policy_path=policy)

            state_path.write_text(json.dumps(original), encoding="utf-8")
            promoted = destination / "custom-addons/module_a/models.py"
            promoted.write_text("MARKER = 'tampered'\n", encoding="utf-8")
            altered = json.loads(json.dumps(original))
            altered["modules"]["module_a"]["tree_sha256"] = sync.tree_digest(
                destination / "custom-addons/module_a"
            )
            state_path.write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(
                sync.SyncError, "imported addon source digest drift|promoted addon content drift"
            ):
                sync.verify_state(destination=destination, policy_path=policy)

    def test_verify_state_requires_complete_false_safety_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "source module")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )
            state_path = destination / "config/upstream-sync-state.json"
            original = json.loads(state_path.read_text(encoding="utf-8"))
            for unsafe in ({}, {"runtime_activated": False}, {**original["safety"], "extra": False}, {**original["safety"], "runtime_activated": 0}):
                changed = json.loads(json.dumps(original))
                changed["safety"] = unsafe
                state_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(sync.SyncError, "safety evidence"):
                    sync.verify_state(destination=destination, policy_path=policy)

    def test_verify_state_binds_snapshot_and_runtime_paths_to_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "source module")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source, destination=destination, policy_path=policy, source_ref="main"
            )
            state_path = destination / "config/upstream-sync-state.json"
            original = json.loads(state_path.read_text(encoding="utf-8"))
            for field, value, message in (
                ("snapshot_path", "docs/fake-snapshot", "snapshot path drift"),
                ("runtime_addons_path", "addons/fake-runtime", "runtime addon path drift"),
            ):
                changed = json.loads(json.dumps(original))
                changed[field] = value
                state_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(sync.SyncError, message):
                    sync.verify_state(destination=destination, policy_path=policy)

    def test_verify_state_binds_snapshot_bytes_to_recorded_git_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(source, "docs/source.md", "original\n")
            self.commit(source, "source tree")
            policy = self.prepare_destination(destination)
            state = sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            snapshot = destination / state["snapshot_path"]
            self.write(snapshot, "docs/source.md", "tampered\n")
            changed_digest = sync.tree_digest(snapshot, frozenset({".source.json"}))
            state["snapshot_tree_sha256"] = changed_digest
            state_path = destination / self.policy_document()["state_path"]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            marker_path = snapshot / ".source.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["snapshot_tree_sha256"] = changed_digest
            marker_path.write_text(json.dumps(marker), encoding="utf-8")

            with self.assertRaisesRegex(sync.SyncError, "snapshot Git tree drift"):
                sync.verify_state(destination=destination, policy_path=policy)

    def test_verify_state_binds_recorded_commit_sha_to_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.commit(source, "source identity")
            policy = self.prepare_destination(destination)
            state = sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            forged_sha = "a" * 40 if state["source_sha"] != "a" * 40 else "b" * 40
            state["source_sha"] = forged_sha
            state_path = destination / self.policy_document()["state_path"]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            marker_path = destination / state["snapshot_path"] / ".source.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["source_sha"] = forged_sha
            marker_path.write_text(json.dumps(marker), encoding="utf-8")

            with self.assertRaisesRegex(sync.SyncError, "source commit object SHA drift"):
                sync.verify_state(destination=destination, policy_path=policy)

    def test_directory_replacement_rejects_unmanaged_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(source, "docs/item/a", "managed\n")
            self.commit(source, "managed directory")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source, destination=destination, policy_path=policy, source_ref="main"
            )
            self.write(destination, "docs/item/local", "destination-only\n")
            (source / "docs/item/a").unlink()
            (source / "docs/item").rmdir()
            self.write(source, "docs/item", "replacement\n")
            self.commit(source, "replace directory with file")
            with self.assertRaisesRegex(sync.SyncError, "unmanaged descendants"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )
            self.assertEqual(
                "destination-only\n",
                (destination / "docs/item/local").read_text(encoding="utf-8"),
            )

    def test_snapshot_namespace_is_preserved_from_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(
                source,
                "upstream/codestra-odoo-addons/nested.txt",
                "source namespace content\n",
            )
            self.commit(source, "snapshot namespace source")
            policy = self.prepare_destination(destination)

            state = sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            self.assertNotIn(
                "upstream/codestra-odoo-addons/nested.txt",
                state["managed_overlay_files"],
            )
            sync.verify_state(destination=destination, policy_path=policy)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_destination_symlink_ancestor_is_rejected_before_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(source, "alias/validate_manifests.py", "untrusted\n")
            self.commit(source, "overlay through destination symlink")
            policy = self.prepare_destination(destination)
            (destination / "alias").symlink_to("scripts", target_is_directory=True)

            with self.assertRaisesRegex(sync.SyncError, "destination symlink ancestor"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )
            self.assertEqual(
                "#!/bin/sh\necho destination-ci\n",
                (destination / "scripts/run_ci.sh").read_text(encoding="utf-8"),
            )
            self.assertFalse((destination / "scripts/validate_manifests.py").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_verify_state_rejects_managed_destination_symlink_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(source, "alias/CODEOWNERS", "managed bytes\n")
            self.commit(source, "managed nested path")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            shutil.rmtree(destination / "alias")
            self.write(destination, ".github/CODEOWNERS", "managed bytes\n")
            (destination / "alias").symlink_to(
                ".github", target_is_directory=True
            )

            with self.assertRaisesRegex(
                sync.SyncError, "managed overlay symlink ancestor"
            ):
                sync.verify_state(destination=destination, policy_path=policy)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_stale_path_with_destination_symlink_ancestor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            self.initialize_source(source)
            self.add_module(source, "addons", "module_a", "first")
            self.write(source, "alias/CODEOWNERS", "managed\n")
            self.commit(source, "managed alias")
            policy = self.prepare_destination(destination)
            sync.synchronize(
                upstream=source,
                destination=destination,
                policy_path=policy,
                source_ref="main",
            )

            (source / "alias/CODEOWNERS").unlink()
            (source / "alias").rmdir()
            self.commit(source, "remove managed alias")
            shutil.rmtree(destination / "alias")
            self.write(destination, ".github/CODEOWNERS", "preserved\n")
            (destination / "alias").symlink_to(".github", target_is_directory=True)

            with self.assertRaisesRegex(sync.SyncError, "destination symlink ancestor"):
                sync.synchronize(
                    upstream=source,
                    destination=destination,
                    policy_path=policy,
                    source_ref="main",
                )
            self.assertEqual(
                "preserved\n",
                (destination / ".github/CODEOWNERS").read_text(encoding="utf-8"),
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

    def test_policy_requires_preserved_calling_contract_authority(self) -> None:
        for required in (
            ".codestra/calling-contract.lock.json",
            "contracts/vendor/calling-contract-authority",
        ):
            with self.subTest(path=required), tempfile.TemporaryDirectory() as directory:
                document = self.policy_document()
                document["preserve_destination_paths"].remove(required)
                path = self.write(
                    Path(directory), "config/upstream-sync-policy.json", json.dumps(document)
                )
                with self.assertRaisesRegex(sync.SyncError, "governance path is not preserved"):
                    sync.load_policy(path)

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
