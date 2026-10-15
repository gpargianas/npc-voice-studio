import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from src.reference_audio import ReferenceAudioError, assess_reference_audio


class ReferenceAudioTests(unittest.TestCase):
    sample_rate = 1000

    def write_audio(self, directory: Path, duration: float) -> Path:
        path = directory / f"reference_{duration}.wav"
        frames = int(duration * self.sample_rate)
        sf.write(path, np.zeros(frames, dtype=np.float32), self.sample_rate)
        return path

    def test_recommended_length_references_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for duration in (5.0, 9.9, 10.0):
                with self.subTest(duration=duration):
                    result = assess_reference_audio(
                        self.write_audio(root, duration)
                    )
                    self.assertEqual(result.level, "ok")
                    self.assertFalse(result.blocked)
                    self.assertIn(f"{duration:.1f} s", result.message)

    def test_long_references_warn_but_remain_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for duration in (12.0, 15.0):
                with self.subTest(duration=duration):
                    result = assess_reference_audio(
                        self.write_audio(root, duration)
                    )
                    self.assertEqual(result.level, "warning")
                    self.assertFalse(result.blocked)
                    self.assertIn(f"Long reference ({duration:.1f} s)", result.message)
                    self.assertIn("accurate matching transcript", result.message)

    def test_reference_over_fifteen_seconds_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = assess_reference_audio(
                self.write_audio(Path(temporary_directory), 15.1)
            )

            self.assertEqual(result.level, "error")
            self.assertTrue(result.blocked)
            self.assertIn("Reference too long (15.1 s)", result.message)
            self.assertIn("15 seconds or less", result.message)

    def test_unreadable_reference_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "broken.wav"
            path.write_bytes(b"not audio")

            with self.assertRaises(ReferenceAudioError) as raised:
                assess_reference_audio(path)

            self.assertIn("determine", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
