#!/usr/bin/env python3
"""Validate an upstream Git checkout before Odoo source synchronization.

The importer copies one exact working tree. Gitlinks are rejected because an
uninitialized submodule appears as an empty directory and would make the
recorded parent tree claim more source than the destination actually imported.
The checkout must also be clean so provenance always describes the bytes that
are copied.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence


class UpstreamTreeError(RuntimeError):
    """The checked-out upstream tree cannot be imported completely."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise UpstreamTreeError(message)


def git(repository: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UpstreamTreeError(
            f"cannot inspect upstream Git tree: {' '.join(arguments)}"
        ) from exc
    return result.stdout


def staged_entries(repository: Path) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    for raw in git(repository, "ls-files", "--stage", "-z").split(b"\0"):
        if not raw:
            continue
        try:
            metadata, path_raw = raw.split(b"\t", 1)
            mode_raw, object_raw, stage_raw = metadata.split(b" ", 2)
            mode = mode_raw.decode("ascii")
            object_id = object_raw.decode("ascii")
            stage = stage_raw.decode("ascii")
            path = path_raw.decode("utf-8", errors="surrogateescape")
        except (ValueError, UnicodeError) as exc:
            raise UpstreamTreeError("cannot parse upstream index entry") from exc
        entries.append((mode, stage, path))
        require(
            re.fullmatch(r"[0-9a-f]{40,64}", object_id) is not None,
            f"invalid upstream object identity: {path}",
        )
    return entries


def validate(repository: Path) -> dict[str, object]:
    repository = repository.resolve()
    require(repository.is_dir(), f"upstream checkout is missing: {repository}")
    require((repository / ".git").exists(), "upstream checkout is not a Git repository")

    head = git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    tree = git(repository, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    require(re.fullmatch(r"[0-9a-f]{40,64}", head) is not None, "invalid upstream HEAD")
    require(re.fullmatch(r"[0-9a-f]{40,64}", tree) is not None, "invalid upstream tree")

    entries = staged_entries(repository)
    unmerged = sorted(path for _mode, stage, path in entries if stage != "0")
    require(not unmerged, "upstream index contains unmerged entries: " + ", ".join(unmerged))

    gitlinks = sorted(path for mode, _stage, path in entries if mode == "160000")
    require(
        not gitlinks,
        "upstream Git submodules require explicit disposition: " + ", ".join(gitlinks),
    )

    dirty = git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    require(not dirty, "upstream checkout contains uncommitted or untracked content")

    return {
        "head": head,
        "tree": tree,
        "tracked_entries": len(entries),
        "gitlinks": [],
        "worktree_clean": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        evidence = validate(args.repository)
    except UpstreamTreeError as exc:
        print(f"UPSTREAM_GIT_TREE=FAIL reason={exc}", file=sys.stderr)
        return 1
    print(
        "UPSTREAM_GIT_TREE=PASS "
        f"head={evidence['head']} "
        f"tree={evidence['tree']} "
        f"tracked_entries={evidence['tracked_entries']} "
        "gitlinks=0 worktree_clean=YES"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
