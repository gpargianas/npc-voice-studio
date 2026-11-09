import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scripts.bootstrap_runtime as bootstrap_runtime

from scripts.bootstrap_runtime import (
    APPLICATION_VERSION,
    UV_VERSION,
    _runtime_environment,
    _stage_project,
    expected_marker,
    model_cache_environment,
    repair_runtime,
    resolve_runtime_layout,
    runtime_is_ready,
)


class RuntimeBootstrapTests(unittest.TestCase):
    def make_layout(self, root: Path):
        source = root / "source"
        source.mkdir()
        return resolve_runtime_layout(
            source,
            environ={"NPC_VOICE_STUDIO_DATA_DIR": str(root / "app-data")},
            home=root / "home",
            platform_name="nt",
        )

    def test_runtime_paths_are_separate_and_app_owned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            layout = self.make_layout(root)

            self.assertEqual(layout.runtime_root, layout.app_root / "runtime")
            self.assertEqual(layout.project_root, layout.runtime_root / "project")
            self.assertEqual(layout.venv_root, layout.project_root / ".venv")
            self.assertEqual(layout.models_root, layout.app_root / "models")
            self.assertEqual(layout.voice_profiles, layout.app_root / "voice_profiles")

    def test_valid_marker_requires_matching_lock_and_managed_python(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            layout = self.make_layout(root)
            lockfile = root / "uv.lock"
            lockfile.write_text("version = 1\n", encoding="utf-8")
            layout.venv_python.parent.mkdir(parents=True)
            layout.venv_python.write_bytes(b"python fixture")
            layout.marker_path.parent.mkdir(parents=True, exist_ok=True)
            layout.marker_path.write_text(
                json.dumps(expected_marker(lockfile)),
                encoding="utf-8",
            )

            self.assertTrue(runtime_is_ready(layout, lockfile))
            lockfile.write_text("version = 2\n", encoding="utf-8")
            self.assertFalse(runtime_is_ready(layout, lockfile))

    def test_invalid_marker_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            layout = self.make_layout(root)
            lockfile = root / "uv.lock"
            lockfile.write_text("lock", encoding="utf-8")
            layout.venv_python.parent.mkdir(parents=True)
            layout.venv_python.write_bytes(b"python fixture")
            layout.marker_path.parent.mkdir(parents=True, exist_ok=True)
            layout.marker_path.write_text("not json", encoding="utf-8")

            self.assertFalse(runtime_is_ready(layout, lockfile))

    def test_marker_never_allows_an_external_python_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            layout = self.make_layout(root)
            lockfile = root / "uv.lock"
            lockfile.write_text("lock", encoding="utf-8")
            layout.marker_path.parent.mkdir(parents=True, exist_ok=True)
            layout.marker_path.write_text(
                json.dumps(expected_marker(lockfile)),
                encoding="utf-8",
            )
            (root / "developer-python.exe").write_bytes(b"external python")

            self.assertFalse(runtime_is_ready(layout, lockfile))

    def test_model_cache_is_separate_from_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            layout = self.make_layout(Path(temporary_directory))
            environment = model_cache_environment(layout)

            self.assertEqual(environment["HF_HOME"], str(layout.models_root))
            self.assertEqual(
                environment["HF_HUB_CACHE"], str(layout.models_root / "hub")
            )
            self.assertNotEqual(layout.models_root, layout.voice_profiles)
            self.assertNotEqual(layout.models_root, layout.generated_audio)

    def test_managed_python_uses_utf8_for_windows_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            layout = self.make_layout(Path(temporary_directory))
            environment = _runtime_environment(layout)
            self.assertEqual(environment["PYTHONUTF8"], "1")
            self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")
            self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(
                environment["UV_DATA_DIR"], str(layout.runtime_root / "uv-data")
            )
            self.assertEqual(
                environment["UV_PYTHON_BIN_DIR"],
                str(layout.runtime_root / "python-bin"),
            )

    def test_repair_preserves_models_and_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            layout = self.make_layout(Path(temporary_directory))
            layout.venv_root.mkdir(parents=True)
            layout.marker_path.write_text("{}", encoding="utf-8")
            preserved = [
                layout.models_root / "model.bin",
                layout.voice_profiles / "voice" / "reference.wav",
                layout.generated_audio / "generation.wav",
                layout.logs / "npc_voice_studio.log",
            ]
            for path in preserved:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")

            repair_runtime(layout)

            self.assertFalse(layout.venv_root.exists())
            self.assertFalse(layout.marker_path.exists())
            self.assertTrue(all(path.is_file() for path in preserved))

    def test_expected_marker_pins_uv_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lockfile = Path(temporary_directory) / "uv.lock"
            lockfile.write_text("lock", encoding="utf-8")
            self.assertEqual(expected_marker(lockfile)["uv_version"], UV_VERSION)

    def test_staged_source_is_versioned_and_replaces_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            layout = self.make_layout(root)
            stale = layout.project_root / "src" / "removed_module.py"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale", encoding="utf-8")

            source_root = Path(__file__).resolve().parents[1]
            _stage_project(source_root, layout)

            marker = json.loads(
                (layout.project_root / "app_source.json").read_text(encoding="utf-8")
            )
            self.assertEqual(marker["application_version"], APPLICATION_VERSION)
            self.assertEqual(len(marker["source_sha256"]), 64)
            self.assertFalse(stale.exists())
            self.assertTrue((layout.project_root / "scripts" / "setup_model.py").is_file())
            self.assertTrue((layout.project_root / "assets" / "app_icon.png").is_file())

    def test_first_run_progress_follows_runtime_stage_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            layout = self.make_layout(root)
            statuses: list[tuple[str, int]] = []

            def create_venv(*_args, **_kwargs):
                layout.venv_python.parent.mkdir(parents=True, exist_ok=True)
                layout.venv_python.write_bytes(b"fixture")

            with (
                patch.object(bootstrap_runtime, "_verify_writable"),
                patch.object(bootstrap_runtime, "_stage_project"),
                patch.object(bootstrap_runtime, "runtime_is_ready", return_value=False),
                patch.object(bootstrap_runtime, "_run_checked", side_effect=create_venv),
                patch.object(bootstrap_runtime, "_verify_managed_python"),
                patch.object(bootstrap_runtime, "_write_ready_marker"),
                patch.object(
                    bootstrap_runtime,
                    "_write_status",
                    side_effect=lambda _path, message, percent, _detail="": statuses.append(
                        (message, percent)
                    ),
                ),
            ):
                bootstrap_runtime.install_or_verify_runtime(
                    root / "source", root / "uv.exe", layout
                )

            self.assertEqual(
                [message for message, _ in statuses],
                [
                    "Checking managed AI runtime...",
                    "Downloading and installing AI runtime (~3.2 GB)...",
                    "Verifying NVIDIA GPU...",
                    "Managed AI runtime is ready.",
                ],
            )
            self.assertEqual([percent for _, percent in statuses], sorted(p for _, p in statuses))

    def test_ready_runtime_fast_path_has_no_download_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            layout = self.make_layout(root)
            statuses: list[str] = []

            with (
                patch.object(bootstrap_runtime, "_verify_writable"),
                patch.object(bootstrap_runtime, "_stage_project"),
                patch.object(bootstrap_runtime, "runtime_is_ready", return_value=True),
                patch.object(bootstrap_runtime, "_verify_managed_python"),
                patch.object(bootstrap_runtime, "_run_checked") as sync,
                patch.object(
                    bootstrap_runtime,
                    "_write_status",
                    side_effect=lambda _path, message, _percent, _detail="": statuses.append(message),
                ),
            ):
                bootstrap_runtime.install_or_verify_runtime(
                    root / "source", root / "uv.exe", layout
                )

            sync.assert_not_called()
            self.assertFalse(any("Downloading" in message for message in statuses))


if __name__ == "__main__":
    unittest.main()
