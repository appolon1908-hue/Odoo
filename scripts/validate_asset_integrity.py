#!/usr/bin/env python3
"""Fail closed on browser-asset drift in every custom Odoo addon.

Codestra custom styles are maintained as standards-based CSS rather than SCSS,
Sass, or Less. Odoo may still compile its own core SCSS, but no repository-owned
stylesheet should require the production database to run a custom preprocessor.
"""

from __future__ import annotations

import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ADDONS_DIR = ROOT / "custom-addons"
STYLE_SUFFIXES = {".css", ".scss", ".sass", ".less"}
TEXT_ASSET_SUFFIXES = STYLE_SUFFIXES | {".js", ".xml"}
SASS_ONLY_RE = re.compile(
    r"(?mi)^\s*(?:\$[a-z_-][\w-]*\s*:|//|@(mixin|include|extend|use|forward)\b)|#\{|^\s*&(?:[:.\[#>+~]|\s)"
)
REMOTE_ASSET_RE = re.compile(
    r"(?i)(?:@import\s+(?:url\()?|url\()\s*['\"]?(?:https?:)?//"
)
BUNDLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def load_manifest(path: Path) -> dict[str, Any]:
    value = ast.literal_eval(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be a dictionary literal")
    return value


def declaration_paths(declaration: Any) -> Iterable[str]:
    """Yield filesystem-backed paths from an Odoo asset declaration."""
    if isinstance(declaration, str):
        yield declaration
        return

    if not isinstance(declaration, (tuple, list)) or not declaration:
        raise ValueError(f"unsupported asset declaration: {declaration!r}")

    directive = declaration[0]
    if not isinstance(directive, str):
        raise ValueError(f"asset directive must start with a string: {declaration!r}")

    # An include directive references another bundle rather than a file.
    if directive == "include":
        if len(declaration) != 2 or not isinstance(declaration[1], str):
            raise ValueError(f"invalid include directive: {declaration!r}")
        return

    expected_lengths = {
        "append": 2,
        "prepend": 2,
        "remove": 2,
        "before": 3,
        "after": 3,
        "replace": 3,
    }
    if directive not in expected_lengths or len(declaration) != expected_lengths[directive]:
        raise ValueError(f"unsupported asset directive: {declaration!r}")

    candidate = declaration[-1]
    if not isinstance(candidate, str):
        raise ValueError(f"asset directive path must be a string: {declaration!r}")
    yield candidate


def validate_balanced_css(text: str) -> str | None:
    """Return a compact delimiter/string error, or None when structurally valid."""
    pairs = {"}": "{", ")": "(", "]": "["}
    opening = set(pairs.values())
    stack: list[tuple[str, int]] = []
    quote: str | None = None
    escaped = False
    in_comment = False
    index = 0

    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""

        if in_comment:
            if char == "*" and following == "/":
                in_comment = False
                index += 2
                continue
            index += 1
            continue

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char == "/" and following == "*":
            in_comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char in opening:
            stack.append((char, index))
        elif char in pairs:
            if not stack or stack[-1][0] != pairs[char]:
                return f"unmatched {char!r} at byte {index}"
            stack.pop()
        index += 1

    if in_comment:
        return "unterminated CSS comment"
    if quote:
        return f"unterminated {quote} string"
    if stack:
        delimiter, position = stack[-1]
        return f"unclosed {delimiter!r} from byte {position}"
    return None


def validate_stylesheet(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read stylesheet as UTF-8: {exc}"]

    if not text.strip():
        errors.append("stylesheet is empty")
    if text.startswith("\ufeff"):
        errors.append("stylesheet contains a UTF-8 BOM")
    if "\x00" in text:
        errors.append("stylesheet contains a NUL byte")
    if "<style" in text.lower():
        errors.append("stylesheet contains an embedded <style> element")
    if re.search(r"(?i)@import\b", text):
        errors.append("CSS @import is prohibited; declare local assets in the manifest")
    if REMOTE_ASSET_RE.search(text):
        errors.append("stylesheet references a remote URL")
    if SASS_ONLY_RE.search(text):
        errors.append("stylesheet contains Sass/Less nesting or preprocessor syntax")
    if "{" not in text:
        errors.append("stylesheet has no rules")

    balance_error = validate_balanced_css(text)
    if balance_error:
        errors.append(balance_error)
    return errors


def validate_text_asset(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read asset as UTF-8: {exc}"]
    errors: list[str] = []
    if not text.strip():
        errors.append("asset is empty")
    if text.startswith("\ufeff"):
        errors.append("asset contains a UTF-8 BOM")
    if "\x00" in text:
        errors.append("asset contains a NUL byte")
    return errors


def validate_module(module_dir: Path) -> tuple[list[str], int, int]:
    errors: list[str] = []
    declared_paths: set[str] = set()
    declared_styles: set[Path] = set()
    declaration_count = 0
    stylesheet_count = 0

    try:
        manifest = load_manifest(module_dir / "__manifest__.py")
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        return ([f"cannot parse manifest for asset validation: {exc}"], 0, 0)

    assets = manifest.get("assets", {})
    if not isinstance(assets, dict):
        return (["manifest key 'assets' must be a dictionary"], 0, 0)

    for bundle, declarations in assets.items():
        if not isinstance(bundle, str) or not BUNDLE_NAME_RE.fullmatch(bundle):
            errors.append(f"invalid asset bundle name: {bundle!r}")
            continue
        if not isinstance(declarations, list):
            errors.append(f"asset bundle {bundle!r} must contain a list")
            continue

        for declaration in declarations:
            try:
                paths = list(declaration_paths(declaration))
            except ValueError as exc:
                errors.append(f"{bundle}: {exc}")
                continue

            for asset_path in paths:
                declaration_count += 1
                if asset_path in declared_paths:
                    errors.append(f"asset is declared more than once: {asset_path}")
                declared_paths.add(asset_path)

                prefix = f"{module_dir.name}/"
                if not asset_path.startswith(prefix):
                    errors.append(f"asset leaves module namespace: {asset_path}")
                    continue

                relative_pattern = asset_path[len(prefix):]
                relative = Path(relative_pattern)
                if relative.is_absolute() or ".." in relative.parts:
                    errors.append(f"unsafe asset path: {asset_path}")
                    continue

                try:
                    matches = sorted(module_dir.glob(relative_pattern))
                except ValueError as exc:
                    errors.append(f"invalid asset glob {asset_path}: {exc}")
                    continue
                if not matches:
                    errors.append(f"asset has no file match: {asset_path}")
                    continue

                for match in matches:
                    if not match.is_file():
                        errors.append(f"asset match is not a file: {match.relative_to(ROOT)}")
                        continue
                    suffix = match.suffix.lower()
                    if suffix in STYLE_SUFFIXES:
                        stylesheet_count += 1
                        declared_styles.add(match.resolve())
                        if suffix != ".css":
                            errors.append(
                                f"custom preprocessor stylesheet is prohibited: "
                                f"{match.relative_to(ROOT)}"
                            )
                            continue
                        for error in validate_stylesheet(match):
                            errors.append(f"{match.relative_to(ROOT)}: {error}")
                    elif suffix == ".xml":
                        try:
                            ET.parse(match)
                        except (ET.ParseError, OSError) as exc:
                            errors.append(f"invalid asset XML {match.relative_to(ROOT)}: {exc}")
                    elif suffix in TEXT_ASSET_SUFFIXES:
                        for error in validate_text_asset(match):
                            errors.append(f"{match.relative_to(ROOT)}: {error}")

    static_src = module_dir / "static" / "src"
    if static_src.is_dir():
        repository_styles = {
            path.resolve()
            for path in static_src.rglob("*")
            if path.is_file() and path.suffix.lower() in STYLE_SUFFIXES
        }
        for stylesheet in sorted(repository_styles):
            relative_name = Path(stylesheet).relative_to(ROOT)
            if Path(stylesheet).suffix.lower() != ".css":
                errors.append(f"legacy preprocessor stylesheet remains in repository: {relative_name}")
            if stylesheet not in declared_styles:
                errors.append(f"orphan stylesheet is not declared by a manifest: {relative_name}")

    return errors, declaration_count, stylesheet_count


def main() -> int:
    if not ADDONS_DIR.is_dir():
        print(f"ERROR: missing addon directory: {ADDONS_DIR}", file=sys.stderr)
        return 1

    module_dirs = sorted(
        path
        for path in ADDONS_DIR.iterdir()
        if path.is_dir() and (path / "__manifest__.py").is_file()
    )
    failures = 0
    total_declarations = 0
    total_stylesheets = 0

    for module_dir in module_dirs:
        module_errors, declaration_count, stylesheet_count = validate_module(module_dir)
        total_declarations += declaration_count
        total_stylesheets += stylesheet_count
        if module_errors:
            failures += 1
            print(f"ERROR: {module_dir.name}", file=sys.stderr)
            for error in module_errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(
                f"PASS: {module_dir.name} "
                f"({declaration_count} asset declaration(s), "
                f"{stylesheet_count} CSS stylesheet(s))"
            )

    if failures:
        print(
            f"Browser asset validation failed for {failures} module(s).",
            file=sys.stderr,
        )
        return 1

    print(f"CUSTOM_MODULES_ASSET_VALIDATED={len(module_dirs)}")
    print(f"CUSTOM_ASSET_DECLARATIONS_VALIDATED={total_declarations}")
    print(f"CUSTOM_CSS_STYLESHEETS_VALIDATED={total_stylesheets}")
    print("CUSTOM_PREPROCESSOR_STYLESHEETS=0")
    print("REPOSITORY_BROWSER_ASSET_INTEGRITY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
