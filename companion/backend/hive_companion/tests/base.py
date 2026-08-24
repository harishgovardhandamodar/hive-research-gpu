"""Shared helpers for companion backend tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
