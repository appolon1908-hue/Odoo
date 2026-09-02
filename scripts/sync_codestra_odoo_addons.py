#!/usr/bin/env python3
"""Synchronize the private Codestra Odoo addon authority into this repository.

The source is copied as a complete provenance snapshot and as a controlled
source overlay. Every discovered Odoo addon is also promoted into the stable
``custom-addons`` runtime path. Destination governance code is immutable during
the operation and every mutation remains subject to a normal protected PR.
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
MODULE_MANIFESTS = ("__manifest__.py",)
MODULE_NAME = re.compile(r"^[A-Za-z0-9_]+$")
REQUIRED_PRESERVED_ROOTS = (
    Path(".github"),
    Path("config"),
    Path("scripts"),
    Path("tests/security"),
    Path("README.md"),
    Path(".gitleaks.toml"),
)


class SyncError(RuntimeError):
    """The upstream tree or synchronization policy is unsafe."""


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


def path_is_within(relative: Path, configured: Path) -> bool:
    return (
        relative == configured
        or relative.parts[: len(configured.parts)] == configured.parts
    )


def matches_any(relative: Path, configured: Iterable[Path]) -> bool:
    return any(path_is_within(relative, item) for item in configured)


def intersects_any(relative: Path, configured: Iterable[Path]) -> bool:
    return any(
        path_is_within(relative, item) or path_is_within(item, relative)
        for item in configured
    )


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
    for flag in (
        "source_wins_on_non_governance_collisions",
        "delete_only_previously_managed_paths",
        "require_private_destination",
        "pre_import_full_history_secret_scan",
    ):
        require(policy.get(flag) is True, f"{flag} must remain true")

    for field in ("snapshot_path", "runtime_addons_path", "state_path"):
        normalize_relative(policy.get(field, ""), field=field)
    for field in ("preserve_destination_paths", "excluded_source_paths"):
        values = policy.get(field)
        require(isinstance(values, list) and values, f"{field} must be a list")
        for index, value in enumerate(values):
            normalize_relative(value, field=f"{field}[{index}]")

    preserved = [
        normalize_relative(value, field="preserve_destination_paths")
        for value in policy["preserve_destination_paths"]
    ]
    for required in REQUIRED_PRESERVED_ROOTS:
        require(
            matches_any(required, preserved),
            f"destination governance path is not preserved: {required}",
        )
    return policy


def git_value(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        joined = " ".join(arguments)
        raise SyncError(f"cannot read upstream Git identity: {joined}") from exc
    value = result.stdout.strip()
    require(bool(value), f"upstream Git identity is empty: {' '.join(arguments)}")
    return value


def source_identity(upstream: Path) -> dict[str, str]:
    return {
        "source_sha": git_value(upstream, "rev-parse", "HEAD"),
        "source_tree": git_value(upstream, "rev-parse", "HEAD^{tree}"),
        "source_committed_at": git_value(
            upstream, "show", "-s", "--format=%cI", "HEAD"
        ),
    }


def validate_symlinks(
    upstream: Path,
    excluded: Sequence[Path],
    preserved: Sequence[Path],
) -> None:
    root = upstream.resolve()
    for path in sorted(upstream.rglob("*")):
        relative = path.relative_to(upstream)
        if matches_any(relative, excluded) or not path.is_symlink():
            continue
        try:
            target = (path.parent / os.readlink(path)).resolve(strict=True)
            target_relative = target.relative_to(root)
        except (OSError, ValueError) as exc:
            raise SyncError(f"unsafe or broken upstream symlink: {relative}") from exc
        require(
            not matches_any(target_relative, excluded),
            f"upstream symlink targets an excluded path: {relative}",
        )
        if not intersects_any(relative, preserved):
            require(
                not intersects_any(target_relative, preserved),
                f"upstream symlink targets a destination-preserved path: {relative}",
            )


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def ensure_parent_directory(path: Path) -> None:
    parents: list[Path] = []
    current = path.parent
    while current != current.parent and not current.exists():
        parents.append(current)
        current = current.parent
    if current.exists() and not current.is_dir():
        remove_path(current)
    for parent in reversed(parents):
        parent.mkdir(exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)


def copy_node(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        remove_path(destination)
    ensure_parent_directory(destination)
    if source.is_symlink():
        destination.symlink_to(
            os.readlink(source),
            target_is_directory=source.resolve().is_dir(),
        )
    else:
        shutil.copy2(source, destination)


def copy_directory(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        remove_path(destination)
    ensure_parent_directory(destination)
    shutil.copytree(source, destination, symlinks=False, copy_function=shutil.copy2)


def iter_source_nodes(
    upstream: Path,
    excluded: Sequence[Path],
) -> Iterable[tuple[Path, Path]]:
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


def tree_digest(root: Path, excluded: frozenset[str] = frozenset()) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative_text = path.relative_to(root).as_posix()
        if relative_text in excluded:
            continue
        relative = relative_text.encode("utf-8")
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


def module_symlinks(module: Path) -> list[Path]:
    links: list[Path] = []
    if module.is_symlink():
        links.append(module)
    links.extend(path for path in module.rglob("*") if path.is_symlink())
    return links


def discover_modules(
    upstream: Path,
    excluded: Sequence[Path],
) -> dict[str, Path]:
    found: dict[str, Path] = {}
    duplicates: dict[str, list[Path]] = {}
    for manifest_name in MODULE_MANIFESTS:
        for manifest in sorted(upstream.rglob(manifest_name)):
            relative = manifest.relative_to(upstream)
            if matches_any(relative, excluded):
                continue
            module = manifest.parent
            name = module.name
            require(
                MODULE_NAME.fullmatch(name) is not None,
                f"invalid addon name: {name}",
            )
            if name in found and found[name] != module:
                duplicates.setdefault(name, [found[name]]).append(module)
            else:
                found[name] = module
    if duplicates:
        details = "; ".join(
            f"{name}="
            + ",".join(
                path.relative_to(upstream).as_posix() for path in paths
            )
            for name, paths in sorted(duplicates.items())
        )
        raise SyncError(
            f"duplicate addon names require an explicit disposition: {details}"
        )

    for name, module in sorted(found.items()):
        links = module_symlinks(module)
        if links:
            rendered = ",".join(
                path.relative_to(upstream).as_posix() for path in links
            )
            raise SyncError(
                "symlinked addon content requires an explicit disposition: "
                f"{name}={rendered}"
            )
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
) -> str:
    reserved_marker = upstream / ".source.json"
    require(
        not reserved_marker.exists() and not reserved_marker.is_symlink(),
        "upstream source reserves .source.json for generated provenance",
    )
    snapshot = destination / snapshot_relative
    remove_path(snapshot)

    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory).resolve()
        try:
            relative = current.relative_to(upstream.resolve())
        except ValueError:
            return set()
        return {
            name
            for name in names
            if matches_any(relative / name, excluded)
        }

    shutil.copytree(
        upstream,
        snapshot,
        symlinks=True,
        copy_function=shutil.copy2,
        ignore=ignore,
    )
    snapshot_sha256 = tree_digest(snapshot)
    complete_marker = {**marker, "snapshot_tree_sha256": snapshot_sha256}
    (snapshot / ".source.json").write_text(
        json.dumps(complete_marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot_sha256


def overlay_source(
    upstream: Path,
    destination: Path,
    *,
    excluded: Sequence[Path],
    preserved: Sequence[Path],
    previous_managed: set[str],
) -> set[str]:
    entries = [
        (relative, source)
        for relative, source in iter_source_nodes(upstream, excluded)
        if not intersects_any(relative, preserved)
    ]
    managed = {relative.as_posix() for relative, _source in entries}

    stale = previous_managed - managed
    for raw in sorted(
        stale,
        key=lambda value: (len(Path(value).parts), value),
        reverse=True,
    ):
        relative = normalize_relative(raw, field="previous managed path")
        if not matches_any(relative, preserved):
            remove_path(destination / relative)

    for relative, source in entries:
        copy_node(source, destination / relative)
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
        require(
            MODULE_NAME.fullmatch(name) is not None,
            f"invalid prior addon name: {name}",
        )
        remove_path(runtime_root / name)

    result: dict[str, dict[str, str]] = {}
    for name, source in sorted(modules.items()):
        require(
            not module_symlinks(source),
            f"symlinked addon content is prohibited during promotion: {name}",
        )
        target = runtime_root / name
        copy_directory(source, target)
        result[name] = {
            "source_path": source.relative_to(upstream).as_posix(),
            "tree_sha256": tree_digest(target),
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
    path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
    require(
        (upstream / ".git").exists(),
        "upstream checkout is not a Git repository",
    )

    excluded = [
        normalize_relative(value, field="excluded_source_paths")
        for value in policy["excluded_source_paths"]
    ]
    preserved = [
        normalize_relative(value, field="preserve_destination_paths")
        for value in policy["preserve_destination_paths"]
    ]
    snapshot_relative = normalize_relative(
        policy["snapshot_path"], field="snapshot_path"
    )
    runtime_relative = normalize_relative(
        policy["runtime_addons_path"], field="runtime_addons_path"
    )
    state_relative = normalize_relative(
        policy["state_path"], field="state_path"
    )
    preserved.append(snapshot_relative)
    require(
        matches_any(policy_path.resolve().relative_to(destination), preserved),
        "sync policy must preserve itself",
    )
    require(
        matches_any(state_relative, preserved),
        "sync state path must be destination-preserved",
    )

    validate_symlinks(upstream, excluded, preserved)
    upstream_runtime_root = upstream / runtime_relative
    require(
        not upstream_runtime_root.is_symlink(),
        "upstream runtime addon root must not be a symlink",
    )
    identity = source_identity(upstream)
    old = previous_state(destination, state_relative)
    previous_managed = {
        value
        for value in old.get("managed_overlay_files", [])
        if isinstance(value, str) and value
    }
    old_modules = old.get("modules", {})
    previous_modules = {
        name
        for name in old_modules
        if isinstance(name, str) and MODULE_NAME.fullmatch(name)
    } if isinstance(old_modules, dict) else set()
    modules = discover_modules(upstream, excluded)

    marker = {
        "schema_version": "1.0",
        "source_repository": policy["source_repository"],
        "source_ref": source_ref,
        **identity,
    }
    snapshot_sha256 = mirror_snapshot(
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
        "snapshot_tree_sha256": snapshot_sha256,
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
    snapshot_relative = normalize_relative(
        policy["snapshot_path"], field="snapshot_path"
    )
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
        isinstance(source_sha, str)
        and re.fullmatch(r"[0-9a-f]{40}", source_sha) is not None,
        "sync state source SHA is invalid",
    )
    marker = load_json(destination / snapshot_relative / ".source.json")
    require(marker.get("schema_version") == state.get("schema_version"), "snapshot marker schema drift")
    for field in (
        "source_repository",
        "source_ref",
        "source_sha",
        "source_tree",
        "source_committed_at",
    ):
        require(marker.get(field) == state.get(field), f"snapshot {field} drift")
    expected_snapshot_sha256 = state.get("snapshot_tree_sha256")
    require(
        isinstance(expected_snapshot_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_snapshot_sha256) is not None,
        "snapshot tree digest is invalid",
    )
    require(
        marker.get("snapshot_tree_sha256") == expected_snapshot_sha256,
        "snapshot marker digest drift",
    )
    snapshot = destination / snapshot_relative
    actual_snapshot_sha256 = tree_digest(
        snapshot, frozenset({".source.json"})
    )
    require(
        actual_snapshot_sha256 == expected_snapshot_sha256,
        "snapshot content drift",
    )
    safety = state.get("safety")
    require(isinstance(safety, dict), "sync safety evidence is missing")
    require(not any(safety.values()), "sync state claims a live effect")

    modules = state.get("modules")
    require(isinstance(modules, dict) and modules, "sync imported no Odoo addons")
    for name, details in modules.items():
        require(
            isinstance(name, str) and MODULE_NAME.fullmatch(name) is not None,
            f"invalid synced addon: {name}",
        )
        require(isinstance(details, dict), f"invalid addon state: {name}")
        module = destination / runtime_relative / name
        require(module.is_dir(), f"promoted addon is missing: {name}")
        require(
            not module_symlinks(module),
            f"promoted addon contains a symlink: {name}",
        )
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
            state = verify_state(
                destination=args.destination,
                policy_path=args.policy,
            )
        else:
            require(
                args.upstream is not None,
                "--upstream is required for synchronization",
            )
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
