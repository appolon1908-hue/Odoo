#!/usr/bin/env python3
"""Run preserved source tests without placing the candidate root before stdlib."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Bind the preserved scripts directory as an explicit namespace. Adding the
# candidate root to sys.path would let a synchronized root-level scripts.py
# shadow this trusted namespace and execute during source validation.
trusted_scripts = types.ModuleType("scripts")
trusted_scripts.__path__ = [str(ROOT / "scripts")]
trusted_scripts.__package__ = "scripts"
sys.modules["scripts"] = trusted_scripts

TEST_ROOT = ROOT / "tests" / "security"
suite = unittest.defaultTestLoader.discover(
    str(TEST_ROOT),
    pattern="test_*.py",
    top_level_dir=str(TEST_ROOT),
)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
