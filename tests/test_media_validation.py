from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filmora_wfp.analysis import validate_project

from helpers import write_project


class ExternalMediaValidationTest(unittest.TestCase):
    def test_explicit_media_check_fails_when_a_source_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = write_project(Path(directory) / "missing-media.wfp")

            result = validate_project(project, check_media=True)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any(message.startswith("Missing external media:") for message in result["errors"])
        )
        self.assertFalse(result["details"]["external_media_valid"])
        self.assertEqual(result["details"]["missing_external_media_count"], 1)
