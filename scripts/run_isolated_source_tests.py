#!/usr/bin/env python3
"""Run preserved source tests without placing the candidate root before stdlib."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Append rather than prepend: trusted standard-library and installed modules
# must win over any same-named file imported from the synchronized candidate.
sys.path.append(str(ROOT))

TEST_ROOT = ROOT / "tests" / "security"
suite = unittest.defaultTestLoader.discover(
    str(TEST_ROOT),
    pattern="test_*.py",
    top_level_dir=str(TEST_ROOT),
)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
