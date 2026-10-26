import json
from pathlib import Path
import tempfile
import unittest

from scripts.bootstrap_runtime import (
    UV_VERSION,
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


if __name__ == "__main__":
    unittest.main()
