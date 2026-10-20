import tempfile
import unittest
from pathlib import Path

from src.voice_profiles import VoiceProfileManager


class VoiceProfileManagerTests(unittest.TestCase):
    def test_missing_storage_is_empty_until_first_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            profiles = Path(temporary_directory) / "profiles"
            manager = VoiceProfileManager(profiles)

            self.assertEqual(manager.list_profiles(), [])
            self.assertFalse(profiles.exists())

    def test_create_load_and_delete_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "reference.wav"
            source.write_bytes(b"audio fixture")
            manager = VoiceProfileManager(root / "profiles")

            created = manager.create_profile(
                "Old Merchant",
                source,
                "Matching transcript.",
            )
            loaded = manager.get_profile(created.name)

            self.assertEqual(created.name, "Old_Merchant")
            self.assertEqual(loaded.transcript, "Matching transcript.")
            self.assertEqual(manager.list_profiles(), ["Old_Merchant"])

            manager.delete_profile(created.name)
            self.assertEqual(manager.list_profiles(), [])


if __name__ == "__main__":
    unittest.main()
