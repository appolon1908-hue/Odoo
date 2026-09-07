from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import validate_upstream_git_tree as validator


class UpstreamGitTreeTests(unittest.TestCase):
    def git(self, repository: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def initialize(self, repository: Path) -> None:
        self.git(repository, "init", "-q")
        self.git(repository, "config", "user.name", "Upstream Test")
        self.git(repository, "config", "user.email", "upstream@example.invalid")

    def commit_file(self, repository: Path, relative: str, content: str) -> str:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git(repository, "add", relative)
        self.git(repository, "commit", "-q", "-m", f"add {relative}")
        return self.git(repository, "rev-parse", "HEAD")

    def test_clean_repository_without_gitlinks_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self.initialize(repository)
            head = self.commit_file(repository, "addon/__manifest__.py", "{}\n")

            evidence = validator.validate(repository)

            self.assertEqual(head, evidence["head"])
            self.assertEqual([], evidence["gitlinks"])
            self.assertTrue(evidence["worktree_clean"])
            self.assertEqual(1, evidence["tracked_entries"])

    def test_gitlink_is_rejected_before_source_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "source"
            nested = root / "nested"
            repository.mkdir()
            nested.mkdir()
            self.initialize(repository)
            self.initialize(nested)
            nested_sha = self.commit_file(nested, "README.md", "nested\n")
            self.commit_file(repository, "README.md", "source\n")
            self.git(
                repository,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{nested_sha},vendor/private-addon",
            )
            self.git(repository, "commit", "-q", "-m", "add gitlink")

            with self.assertRaisesRegex(
                validator.UpstreamTreeError,
                "submodules require explicit disposition",
            ):
                validator.validate(repository)

    def test_untracked_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self.initialize(repository)
            self.commit_file(repository, "README.md", "source\n")
            (repository / "untracked-secret.txt").write_text(
                "not part of provenance\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(
                validator.UpstreamTreeError,
                "uncommitted or untracked content",
            ):
                validator.validate(repository)

    def test_modified_tracked_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self.initialize(repository)
            self.commit_file(repository, "README.md", "source\n")
            (repository / "README.md").write_text("modified\n", encoding="utf-8")

            with self.assertRaisesRegex(
                validator.UpstreamTreeError,
                "uncommitted or untracked content",
            ):
                validator.validate(repository)


if __name__ == "__main__":
    unittest.main()
