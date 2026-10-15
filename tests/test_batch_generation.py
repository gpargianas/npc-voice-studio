import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from src.batch_generation import (
    BatchCsvError,
    batch_output_path,
    create_batch_zip,
    parse_dialogue_csv,
    sanitize_wav_filename,
    validate_batch_table,
)
from src.omnivoice_service import BatchGenerationRequest, OmniVoiceService


class BatchCsvTests(unittest.TestCase):
    def write_csv(self, directory: Path, content: str) -> Path:
        path = directory / "dialogue.csv"
        path.write_text(content, encoding="utf-8-sig")
        return path

    def test_valid_csv_preserves_unicode_and_inline_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            csv_path = self.write_csv(
                root,
                "filename,text\n"
                'merchant_001,"Welcome, traveler."\n'
                'merchant_002.wav,"[laughter] Привет, путник."\n'
                'merchant_003,"He plays the [B EY1 S] guitar."\n'
                ",\n",
            )

            rows = parse_dialogue_csv(csv_path)

            self.assertEqual(
                [row.filename for row in rows],
                ["merchant_001.wav", "merchant_002.wav", "merchant_003.wav"],
            )
            self.assertEqual(rows[1].text, "[laughter] Привет, путник.")
            self.assertEqual(rows[2].text, "He plays the [B EY1 S] guitar.")

    def test_invalid_rows_and_duplicates_are_rejected_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            csv_path = self.write_csv(
                root,
                "filename,text\n"
                "missing_text,\n"
                ',"Missing filename"\n'
                'same,"First"\n'
                'SAME.wav,"Second"\n',
            )

            with self.assertRaises(BatchCsvError) as raised:
                parse_dialogue_csv(csv_path)

            message = str(raised.exception)
            self.assertIn("Row 2: text is required", message)
            self.assertIn("Row 3: filename is required", message)
            self.assertIn("duplicate output filename", message)

    def test_edited_preview_is_validated_as_generation_source(self) -> None:
        table = [
            ["merchant_001.wav", "Welcome, traveler.", "Ready"],
            ["merchant_002.wav", "[sigh] I haven't seen him for days.", "Ready"],
            ["merchant_003.wav", "[laughter] Привет!", "Ready"],
            ["merchant_004.wav", "He plays the [B EY1 S] guitar?", "Ready"],
        ]

        rows = validate_batch_table(table)

        self.assertEqual([row.filename for row in rows], [row[0] for row in table])
        self.assertEqual([row.text for row in rows], [row[1] for row in table])

    def test_edited_preview_rejects_empty_dialogue(self) -> None:
        table = [
            ["merchant_001.wav", "Good line.", "Ready"],
            ["merchant_002.wav", "   ", "Ready"],
        ]

        with self.assertRaises(BatchCsvError) as raised:
            validate_batch_table(table)

        self.assertIn("Row 2: dialogue is required", str(raised.exception))

    def test_edited_preview_rejects_filename_tampering_and_duplicates(self) -> None:
        table = [
            ["merchant_001.wav", "First.", "Ready"],
            ["../outside.wav", "Unsafe.", "Ready"],
            ["MERCHANT_001.wav", "Duplicate.", "Ready"],
        ]

        with self.assertRaises(BatchCsvError) as raised:
            validate_batch_table(table)

        message = str(raised.exception)
        self.assertIn("Row 2: invalid output filename", message)
        self.assertIn("duplicate output filename", message)

    def test_filename_sanitization_prevents_paths_and_double_extensions(self) -> None:
        self.assertEqual(
            sanitize_wav_filename(r"../characters\merchant.wav"),
            "characters_merchant.wav",
        )
        self.assertEqual(sanitize_wav_filename("line.WAV"), "line.wav")
        self.assertEqual(sanitize_wav_filename("CON"), "_CON.wav")

    def test_output_path_cannot_escape_batch_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.assertEqual(
                batch_output_path(root, "line.wav").parent,
                root.resolve(),
            )
            with self.assertRaises(BatchCsvError):
                batch_output_path(root, "../outside.wav")

    def test_zip_contains_only_valid_successful_wavs_at_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            batch_directory = root / "batch"
            batch_directory.mkdir()
            first = batch_directory / "first.wav"
            second = batch_directory / "second.wav"
            ignored = root / "outside.wav"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            ignored.write_bytes(b"outside")

            zip_path = create_batch_zip(
                batch_directory,
                [first, ignored, second],
            )

            with ZipFile(zip_path) as archive:
                self.assertEqual(archive.namelist(), ["first.wav", "second.wav"])


class FakeOmniVoiceModel:
    def __init__(self) -> None:
        self.prompt_calls = 0
        self.generate_calls: list[dict] = []
        self.prompt = object()

    def create_voice_clone_prompt(self, **kwargs):
        self.prompt_calls += 1
        return self.prompt

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        if kwargs["text"] == "FAIL":
            raise RuntimeError("deliberate test failure")
        value = (sum(kwargs["text"].encode("utf-8")) % 100) / 1000
        return [np.full(240, value, dtype=np.float32)]


class BatchServiceTests(unittest.TestCase):
    def test_one_prompt_is_reused_and_failure_does_not_stop_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            reference = root / "reference.wav"
            reference.write_bytes(b"fixture")
            model = FakeOmniVoiceModel()
            service = object.__new__(OmniVoiceService)
            service._model = model
            service.sample_rate = 24000
            progress: list[tuple[int, int]] = []
            requests = [
                BatchGenerationRequest("[laughter] First.", root / "first.wav"),
                BatchGenerationRequest("FAIL", root / "failed.wav"),
                BatchGenerationRequest(
                    "Play the [B EY1 S] guitar.", root / "third.wav"
                ),
            ]

            with self.assertLogs("src.omnivoice_service", level="ERROR"):
                run = service.generate_batch(
                    reference,
                    "Matching reference transcript.",
                    requests,
                    progress_callback=lambda current, total: progress.append(
                        (current, total)
                    ),
                )
            results = run.results

            self.assertEqual(model.prompt_calls, 1)
            self.assertEqual(len(model.generate_calls), 3)
            self.assertEqual(
                [call["text"] for call in model.generate_calls],
                [request.generation_text for request in requests],
            )
            self.assertTrue(
                all(
                    call["voice_clone_prompt"] is model.prompt
                    for call in model.generate_calls
                )
            )
            self.assertIsNone(results[0].error)
            self.assertIn("deliberate test failure", results[1].error or "")
            self.assertIsNone(results[2].error)
            self.assertTrue((root / "first.wav").is_file())
            self.assertFalse((root / "failed.wav").exists())
            self.assertTrue((root / "third.wav").is_file())
            self.assertEqual(progress, [(1, 3), (2, 3), (3, 3)])

    def test_regeneration_replaces_only_selected_audio_and_refreshes_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            reference = root / "reference.wav"
            reference.write_bytes(b"fixture")
            model = FakeOmniVoiceModel()
            service = object.__new__(OmniVoiceService)
            service._model = model
            service.sample_rate = 24000
            requests = [
                BatchGenerationRequest("First line.", root / "first.wav"),
                BatchGenerationRequest("Second line.", root / "second.wav"),
                BatchGenerationRequest("Third line.", root / "third.wav"),
            ]
            run = service.generate_batch(
                reference,
                "Matching reference transcript.",
                requests,
            )
            before = {
                request.output_path.name: request.output_path.read_bytes()
                for request in requests
            }
            create_batch_zip(root, [request.output_path for request in requests])

            result, context = service.regenerate_batch_line(
                "[sigh] Updated second line.",
                root / "second.wav",
                voice_context=run.voice_context,
            )

            self.assertIsNone(result.error)
            self.assertIs(context, run.voice_context)
            self.assertEqual(model.prompt_calls, 1)
            self.assertEqual((root / "first.wav").read_bytes(), before["first.wav"])
            self.assertNotEqual(
                (root / "second.wav").read_bytes(), before["second.wav"]
            )
            self.assertEqual((root / "third.wav").read_bytes(), before["third.wav"])

            successful_files = [request.output_path for request in requests]
            zip_path = create_batch_zip(root, successful_files)
            with ZipFile(zip_path) as archive:
                self.assertEqual(
                    archive.read("second.wav"),
                    (root / "second.wav").read_bytes(),
                )

            working_audio = (root / "second.wav").read_bytes()
            with self.assertLogs("src.omnivoice_service", level="ERROR"):
                failed_result, _ = service.regenerate_batch_line(
                    "FAIL",
                    root / "second.wav",
                    voice_context=run.voice_context,
                )
            self.assertIn("deliberate test failure", failed_result.error or "")
            self.assertEqual((root / "second.wav").read_bytes(), working_audio)

    def test_failed_line_can_be_retried_with_the_same_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            reference = root / "reference.wav"
            reference.write_bytes(b"fixture")
            model = FakeOmniVoiceModel()
            service = object.__new__(OmniVoiceService)
            service._model = model
            service.sample_rate = 24000
            failed_output = root / "retry.wav"
            with self.assertLogs("src.omnivoice_service", level="ERROR"):
                run = service.generate_batch(
                    reference,
                    "Matching reference transcript.",
                    [BatchGenerationRequest("FAIL", failed_output)],
                )
            self.assertIsNotNone(run.results[0].error)
            self.assertFalse(failed_output.exists())

            result, context = service.regenerate_batch_line(
                "Recovered dialogue.",
                failed_output,
                voice_context=run.voice_context,
            )

            self.assertIsNone(result.error)
            self.assertTrue(failed_output.is_file())
            self.assertIs(context, run.voice_context)
            self.assertEqual(model.prompt_calls, 1)
            zip_path = create_batch_zip(root, [failed_output])
            with ZipFile(zip_path) as archive:
                self.assertEqual(archive.namelist(), ["retry.wav"])


if __name__ == "__main__":
    unittest.main()
