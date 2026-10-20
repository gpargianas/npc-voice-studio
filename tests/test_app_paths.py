import unittest
from pathlib import Path

from src.app_paths import APP_NAME, resolve_app_paths


class AppPathTests(unittest.TestCase):
    def test_windows_uses_local_app_data(self) -> None:
        paths = resolve_app_paths(
            environ={"LOCALAPPDATA": r"C:\Users\Example\AppData\Local"},
            home=Path(r"C:\Users\Example"),
            platform_name="nt",
        )

        self.assertEqual(paths.root.name, APP_NAME)
        self.assertEqual(paths.voice_profiles.parent, paths.root)
        self.assertEqual(paths.generated_audio.parent, paths.root)
        self.assertEqual(paths.logs.parent, paths.root)

    def test_explicit_data_directory_override_wins(self) -> None:
        paths = resolve_app_paths(
            environ={"NPC_VOICE_STUDIO_DATA_DIR": "custom-data"},
            home=Path("home"),
            platform_name="posix",
        )

        self.assertEqual(paths.root.name, "custom-data")

    def test_non_windows_uses_xdg_data_home(self) -> None:
        paths = resolve_app_paths(
            environ={"XDG_DATA_HOME": "/var/example/data"},
            home=Path("/home/example"),
            platform_name="posix",
        )

        self.assertEqual(
            paths.root,
            Path("/var/example/data/npc-voice-studio").resolve(),
        )


if __name__ == "__main__":
    unittest.main()
