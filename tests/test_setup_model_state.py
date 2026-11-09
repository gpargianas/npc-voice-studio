import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import scripts.setup_model as setup_model
from src.model_setup import (
    ModelDownloadError,
    ModelValidationError,
    load_model_spec,
    model_ready_path,
    write_model_ready_marker,
)


class SetupModelStateTests(unittest.TestCase):
    def arguments(self, result_file: Path, **overrides):
        values = {
            "check": False,
            "install": False,
            "status_file": None,
            "result_file": result_file,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def read_state(self, result_file: Path) -> str:
        return json.loads(result_file.read_text(encoding="utf-8"))["state"]

    def test_missing_check_has_setup_required_state_and_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result_file = root / "result.json"
            marker = model_ready_path(root)
            marker.write_text("{}", encoding="utf-8")

            with (
                patch.object(setup_model, "APP_PATHS", SimpleNamespace(models=root)),
                patch.object(
                    setup_model,
                    "parse_args",
                    return_value=self.arguments(result_file, check=True),
                ),
                patch.object(
                    setup_model,
                    "validate_model_cache",
                    side_effect=RuntimeError("missing"),
                ),
            ):
                exit_code = setup_model.main()

            self.assertEqual(exit_code, setup_model.MODEL_MISSING_EXIT)
            self.assertEqual(self.read_state(result_file), "setup_required")
            self.assertFalse(marker.exists())

    def test_complete_cached_model_reports_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result_file = root / "result.json"
            snapshot = root / "hub" / "snapshot"
            snapshot.mkdir(parents=True)

            with (
                patch.object(setup_model, "APP_PATHS", SimpleNamespace(models=root)),
                patch.object(
                    setup_model,
                    "parse_args",
                    return_value=self.arguments(result_file, check=True),
                ),
                patch.object(
                    setup_model,
                    "validate_model_cache",
                    return_value=snapshot,
                ),
            ):
                exit_code = setup_model.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(self.read_state(result_file), "ready")
            self.assertTrue(model_ready_path(root).is_file())

    def test_download_failure_has_explicit_state_and_no_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result_file = root / "result.json"

            with (
                patch.object(setup_model, "APP_PATHS", SimpleNamespace(models=root)),
                patch.object(
                    setup_model,
                    "parse_args",
                    return_value=self.arguments(
                        result_file,
                        install=True,
                    ),
                ),
                patch.object(
                    setup_model,
                    "install_model",
                    side_effect=ModelDownloadError("network failed"),
                ),
            ):
                exit_code = setup_model.main()

            self.assertEqual(exit_code, setup_model.DOWNLOAD_FAILED_EXIT)
            self.assertEqual(self.read_state(result_file), "download_failed")
            self.assertFalse(model_ready_path(root).exists())

    def test_validation_failure_has_explicit_state_and_no_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result_file = root / "result.json"

            with (
                patch.object(setup_model, "APP_PATHS", SimpleNamespace(models=root)),
                patch.object(
                    setup_model,
                    "parse_args",
                    return_value=self.arguments(result_file, install=True),
                ),
                patch.object(
                    setup_model,
                    "install_model",
                    side_effect=ModelValidationError("invalid snapshot"),
                ),
            ):
                exit_code = setup_model.main()

            self.assertEqual(exit_code, setup_model.VALIDATION_FAILED_EXIT)
            self.assertEqual(self.read_state(result_file), "validation_failed")
            self.assertFalse(model_ready_path(root).exists())

    def test_obsolete_acknowledgement_is_removed_without_blocking_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            root.mkdir(parents=True, exist_ok=True)
            obsolete = root / setup_model.OBSOLETE_ACKNOWLEDGEMENT_FILENAME
            obsolete.write_text("{}", encoding="utf-8")
            result_file = root / "result.json"
            snapshot = root / "hub" / "snapshot"
            snapshot.mkdir(parents=True)

            with (
                patch.object(setup_model, "APP_PATHS", SimpleNamespace(models=root)),
                patch.object(
                    setup_model,
                    "parse_args",
                    return_value=self.arguments(result_file, install=True),
                ),
                patch.object(setup_model, "install_model", return_value=snapshot),
            ):
                exit_code = setup_model.main()

            self.assertEqual(exit_code, 0)
            self.assertFalse(obsolete.exists())

    def test_successful_install_reports_ready_only_with_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result_file = root / "result.json"
            spec = load_model_spec()
            snapshot = root / "hub" / "snapshot"
            snapshot.mkdir(parents=True)

            install_arguments = []

            def install(*_args, **kwargs):
                install_arguments.append(kwargs)
                write_model_ready_marker(root, spec, snapshot)
                return snapshot

            with (
                patch.object(setup_model, "APP_PATHS", SimpleNamespace(models=root)),
                patch.object(
                    setup_model,
                    "parse_args",
                    return_value=self.arguments(
                        result_file,
                        install=True,
                    ),
                ),
                patch.object(setup_model, "install_model", side_effect=install),
            ):
                exit_code = setup_model.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(self.read_state(result_file), "ready")
            self.assertTrue(model_ready_path(root).is_file())
            self.assertNotIn("acknowledge_license", install_arguments[0])

    def test_real_check_process_does_not_return_success_for_missing_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result_file = root / "result.json"
            environment = dict(os.environ)
            environment["NPC_VOICE_STUDIO_DATA_DIR"] = str(root)
            environment["HF_HUB_OFFLINE"] = "1"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-u",
                    str(Path(setup_model.__file__).resolve()),
                    "--check",
                    "--result-file",
                    str(result_file),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, setup_model.MODEL_MISSING_EXIT)
            self.assertEqual(self.read_state(result_file), "setup_required")


if __name__ == "__main__":
    unittest.main()
