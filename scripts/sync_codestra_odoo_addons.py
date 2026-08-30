#!/usr/bin/env python3
"""Synchronize the private Codestra Odoo addon authority into this repository.

The source repository is copied in two forms:

1. a complete, provenance-marked snapshot under ``upstream/``; and
2. a source-wins overlay at the repository root, with every discovered Odoo
   addon also promoted into ``custom-addons`` so the destination can use one
   stable runtime addons path.

Destination governance files are preserved by policy. Deletion is limited to
paths recorded as managed by an earlier successful sync. The script never
activates a workflow, deploys Odoo, changes a database, or enables live writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "upstream-sync-policy.json"
MODULE_MANIFESTS = ("__manifest__.py", "__openerp__.py")
MODULE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


class SyncError(RuntimeError):
    """The upstream tree or sync policy is unsafe or internally inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SyncError(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"cannot load JSON document: {path}") from exc
    require(isinstance(value, dict), f"JSON document must be an object: {path}")
    return value


def normalize_relative(value: str, *, field: str) -> Path:
    require(isinstance(value, str) and value.strip(), f"{field} must be a path")
    path = Path(value)
    require(not path.is_absolute(), f"{field} must be relative")
    require(".." not in path.parts, f"{field} must not traverse upward")
    normalized = Path(*[part for part in path.parts if part not in {"", "."}])
    require(bool(normalized.parts), f"{field} must not resolve to repository root")
    return normalized


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    policy = load_json(path)
    require(policy.get("schema_version") == "1.0", "unsupported sync policy")
    require(
        policy.get("source_repository") == "Codestra-SRL/codestra-odoo-addons",
        "source repository authority drift",
    )
    require(
        policy.get("destination_repository") == "appolon1908-hue/Odoo",
        "destination repository authority drift",
    )
    require(
        policy.get("sync_strategy")
        == "full_source_overlay_with_runtime_addon_promotion",
        "unsupported sync strategy",
    )
    for flag in (
        "activate_source_workflows",
        "runtime_activation",
        "deployment_authorized",
        "live_write_authorized",
    ):
        require(policy.get(flag) is False, f"{flag} must remain false")
    require(
        policy.get("source_wins_on_non_governance_collisions") is True,
        "source collision policy must remain source-wins",
    )
    require(
        policy.get("delete_only_previously_managed_paths") is True,
        "sync must not delete unmanaged destination paths",
    )
    for field in ("snapshot_path", "runtime_addons_path", "state_path"):
        normalize_relative(policy.get(field, ""), field=field)
    for field in ("preserve_destination_paths", "excluded_source_paths"):
        values = policy.get(field)
        require(isinstance(values, list) and values, f"{field} must be a list")
        for index, value in enumerate(values):
            normalize_relative(value, field=f"{field}[{index}]")
    return policy


def path_is_within(relative: Path, configured: Path) -> bool:
    return relative == configured or relative.parts[: len(configured.parts)] == configured.parts


def matches_any(relative: Path, configured: Iterable[Path]) -> bool:
    return any(path_is_within(relative, item) for item in configured)


def git_value(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SyncError(f"cannot read upstream Git identity: {' '.join(arguments)}") from exc
    value = result.stdout.strip()
    require(bool(value), f"upstream Git identity is empty: {' '.join(arguments)}")
    return value


def source_identity(upstream: Path) -> dict[str, str]:
    return {
        "source_sha": git_value(upstream, "rev-parse", "HEAD"),
        "source_tree": git_value(upstream, "rev-parse", "HEAD^{tree}"),
        "source_committed_at": git_value(upstream, "show", "-s", "--format=%cI", "HEAD"),
    }


def validate_symlinks(upstream: Path, excluded: Sequence[Path]) -> None:
    root = upstream.resolve()
    for path in sorted(upstream.rglob("*")):
        relative = path.relative_to(upstream)
        if matches_any(relative, excluded) or not path.is_symlink():
            continue
        try:
            target = (path.parent / os.readlink(path)).resolve(strict=True)
            target.relative_to(root)
        except (OSError, ValueError) as exc:
            raise SyncError(f"unsafe or broken upstream symlink: {relative}") from exc


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def copy_node(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        remove_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
    else:
        shutil.copy2(source, destination)


def copy_directory(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        remove_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True, copy_function=shutil.copy2)


def iter_source_nodes(upstream: Path, excluded: Sequence[Path]) -> Iterable[tuple[Path, Path]]:
    for source in sorted(upstream.rglob("*")):
        relative = source.relative_to(upstream)
        if matches_any(relative, excluded):
            continue
        if source.is_file() or source.is_symlink():
            yield relative, source


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_dir() and not path.is_symlink():
            continue
        digest.update(relative)
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode("utf-8"))
        else:
            digest.update(b"F")
            digest.update(sha256_file(path).encode("ascii"))
            digest.update(oct(stat.S_IMODE(path.stat().st_mode)).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def discover_modules(upstream: Path, excluded: Sequence[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    duplicates: dict[str, list[Path]] = {}
    for manifest_name in MODULE_MANIFESTS:
        for manifest in sorted(upstream.rglob(manifest_name)):
            relative = manifest.relative_to(upstream)
            if matches_any(relative, excluded):
                continue
            module = manifest.parent
            name = module.name
            require(MODULE_NAME.fullmatch(name) is not None, f"invalid addon name: {name}")
            if name in found and found[name] != module:
                duplicates.setdefault(name, [found[name]]).append(module)
            else:
                found[name] = module
    if duplicates:
        details = "; ".join(
            f"{name}=" + ",".join(path.relative_to(upstream).as_posix() for path in paths)
            for name, paths in sorted(duplicates.items())
        )
        raise SyncError(f"duplicate addon names require an explicit disposition: {details}")
    return found


def previous_state(destination: Path, state_relative: Path) -> dict[str, Any]:
    path = destination / state_relative
    return load_json(path) if path.is_file() else {}


def mirror_snapshot(
    upstream: Path,
    destination: Path,
    snapshot_relative: Path,
    excluded: Sequence[Path],
    marker: Mapping[str, Any],
) -> None:
    snapshot = destination / snapshot_relative
    remove_path(snapshot)

    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory).resolve()
        try:
            relative = current.relative_to(upstream.resolve())
        except ValueError:
            return set()
        ignored: set[str] = set()
        for name in names:
            candidate = relative / name
            if matches_any(candidate, excluded):
                ignored.add(name)
        return ignored

    shutil.copytree(
        upstream,
        snapshot,
        symlinks=True,
        copy_function=shutil.copy2,
        ignore=ignore,
    )
    (snapshot / ".source.json").write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def overlay_source(
    upstream: Path,
    destination: Path,
    *,
    excluded: Sequence[Path],
    preserved: Sequence[Path],
    previous_managed: set[str],
) -> set[str]:
    managed: set[str] = set()
    for relative, source in iter_source_nodes(upstream, excluded):
        if matches_any(relative, preserved):
            continue
        copy_node(source, destination / relative)
        managed.add(relative.as_posix())

    for raw in sorted(previous_managed - managed, reverse=True):
        relative = normalize_relative(raw, field="previous managed path")
        if matches_any(relative, preserved):
            continue
        remove_path(destination / relative)
    return managed


def promote_modules(
    modules: Mapping[str, Path],
    upstream: Path,
    destination: Path,
    runtime_relative: Path,
    previous_modules: set[str],
) -> dict[str, dict[str, str]]:
    runtime_root = destination / runtime_relative
    runtime_root.mkdir(parents=True, exist_ok=True)
    current = set(modules)
    for name in sorted(previous_modules - current):
        require(MODULE_NAME.fullmatch(name) is not None, f"invalid prior addon name: {name}")
        remove_path(runtime_root / name)

    result: dict[str, dict[str, str]] = {}
    for name, source in sorted(modules.items()):
        target = runtime_root / name
        copy_directory(source, target)
        result[name] = {
            "source_path": source.relative_to(upstream).as_posix(),
            "tree_sha256": tree_digest(source),
        }
    return result


def destination_modules(runtime_root: Path) -> set[str]:
    if not runtime_root.is_dir():
        return set()
    names: set[str] = set()
    for manifest_name in MODULE_MANIFESTS:
        for manifest in runtime_root.glob(f"*/{manifest_name}"):
            names.add(manifest.parent.name)
    return names


def write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def synchronize(
    *,
    upstream: Path,
    destination: Path,
    policy_path: Path,
    source_ref: str,
) -> dict[str, Any]:
    policy = load_policy(policy_path)
    upstream = upstream.resolve()
    destination = destination.resolve()
    require(upstream.is_dir(), f"upstream checkout is missing: {upstream}")
    require(destination.is_dir(), f"destination checkout is missing: {destination}")
    require((upstream / ".git").exists(), "upstream checkout is not a Git repository")

    excluded = [
        normalize_relative(value, field="excluded_source_paths")
        for value in policy["excluded_source_paths"]
    ]
    preserved = [
        normalize_relative(value, field="preserve_destination_paths")
        for value in policy["preserve_destination_paths"]
    ]
    snapshot_relative = normalize_relative(policy["snapshot_path"], field="snapshot_path")
    runtime_relative = normalize_relative(
        policy["runtime_addons_path"], field="runtime_addons_path"
    )
    state_relative = normalize_relative(policy["state_path"], field="state_path")
    require(
        matches_any(policy_path.resolve().relative_to(destination), preserved),
        "sync policy must preserve itself",
    )
    require(
        matches_any(state_relative, preserved),
        "sync state path must be destination-preserved",
    )

    validate_symlinks(upstream, excluded)
    identity = source_identity(upstream)
    old = previous_state(destination, state_relative)
    previous_managed = {
        value
        for value in old.get("managed_overlay_files", [])
        if isinstance(value, str) and value
    }
    previous_modules = {
        name
        for name in old.get("modules", {})
        if isinstance(name, str) and MODULE_NAME.fullmatch(name)
    }
    modules = discover_modules(upstream, excluded)

    marker = {
        "schema_version": "1.0",
        "source_repository": policy["source_repository"],
        "source_ref": source_ref,
        **identity,
    }
    mirror_snapshot(
        upstream,
        destination,
        snapshot_relative,
        excluded,
        marker,
    )
    managed = overlay_source(
        upstream,
        destination,
        excluded=excluded,
        preserved=preserved,
        previous_managed=previous_managed,
    )
    promoted = promote_modules(
        modules,
        upstream,
        destination,
        runtime_relative,
        previous_modules,
    )
    runtime_names = destination_modules(destination / runtime_relative)

    state: dict[str, Any] = {
        "schema_version": "1.0",
        "source_repository": policy["source_repository"],
        "source_ref": source_ref,
        "destination_repository": policy["destination_repository"],
        **identity,
        "snapshot_path": snapshot_relative.as_posix(),
        "runtime_addons_path": runtime_relative.as_posix(),
        "managed_overlay_files": sorted(managed),
        "modules": promoted,
        "target_only_modules": sorted(runtime_names - set(promoted)),
        "safety": {
            "source_workflows_activated": False,
            "runtime_activated": False,
            "deployment_authorized": False,
            "live_write_authorized": False,
        },
    }
    write_state(destination / state_relative, state)
    verify_state(destination=destination, policy_path=policy_path)
    return state


def verify_state(*, destination: Path, policy_path: Path) -> dict[str, Any]:
    policy = load_policy(policy_path)
    destination = destination.resolve()
    state_relative = normalize_relative(policy["state_path"], field="state_path")
    snapshot_relative = normalize_relative(policy["snapshot_path"], field="snapshot_path")
    runtime_relative = normalize_relative(
        policy["runtime_addons_path"], field="runtime_addons_path"
    )
    state = load_json(destination / state_relative)
    require(state.get("schema_version") == "1.0", "sync state schema drift")
    require(
        state.get("source_repository") == policy["source_repository"],
        "sync state source drift",
    )
    require(
        state.get("destination_repository") == policy["destination_repository"],
        "sync state destination drift",
    )
    source_sha = state.get("source_sha")
    require(
        isinstance(source_sha, str) and re.fullmatch(r"[0-9a-f]{40}", source_sha),
        "sync state source SHA is invalid",
    )
    marker = load_json(destination / snapshot_relative / ".source.json")
    require(marker.get("source_sha") == source_sha, "snapshot source SHA drift")
    safety = state.get("safety")
    require(isinstance(safety, dict), "sync safety evidence is missing")
    require(not any(safety.values()), "sync state claims a live effect")

    modules = state.get("modules")
    require(isinstance(modules, dict) and modules, "sync imported no Odoo addons")
    for name, details in modules.items():
        require(MODULE_NAME.fullmatch(name) is not None, f"invalid synced addon: {name}")
        require(isinstance(details, dict), f"invalid addon state: {name}")
        module = destination / runtime_relative / name
        require(module.is_dir(), f"promoted addon is missing: {name}")
        require(
            any((module / manifest).is_file() for manifest in MODULE_MANIFESTS),
            f"promoted addon manifest is missing: {name}",
        )
        require(
            tree_digest(module) == details.get("tree_sha256"),
            f"promoted addon content drift: {name}",
        )
    return state


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--destination", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--source-ref", default="main")
    parser.add_argument("--verify-state", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.verify_state:
            state = verify_state(destination=args.destination, policy_path=args.policy)
        else:
            require(args.upstream is not None, "--upstream is required for synchronization")
            state = synchronize(
                upstream=args.upstream,
                destination=args.destination,
                policy_path=args.policy,
                source_ref=args.source_ref,
            )
    except SyncError as exc:
        print(f"ODOO_UPSTREAM_SYNC=FAIL reason={exc}", file=sys.stderr)
        return 1

    print(
        "ODOO_UPSTREAM_SYNC=PASS "
        f"source_sha={state['source_sha']} "
        f"modules={len(state['modules'])} "
        f"managed_files={len(state['managed_overlay_files'])} "
        "runtime_activation=NO deployment=NO live_write=NO"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
