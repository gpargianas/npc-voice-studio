import unittest

from src.error_messages import generation_error_message, model_load_error_message


class ErrorMessageTests(unittest.TestCase):
    def test_incomplete_model_error_requests_launcher_repair(self) -> None:
        message = model_load_error_message(
            RuntimeError(
                "The OmniVoice model installation is incomplete. Restart NPC "
                "Voice Studio to repair/download the model."
            )
        )
        self.assertIn("model installation is incomplete", message)
        self.assertIn("Restart NPC Voice Studio", message)

    def test_cuda_out_of_memory_is_concise(self) -> None:
        message = generation_error_message(RuntimeError("CUDA out of memory"))
        self.assertIn("GPU ran out of memory", message)

    def test_corrupted_audio_is_identified(self) -> None:
        message = generation_error_message(RuntimeError("libsndfile error opening"))
        self.assertIn("corrupted", message)

    def test_output_write_failure_is_actionable(self) -> None:
        message = generation_error_message(
            OSError("Could not write generated audio file.")
        )
        self.assertIn("data directory", message)

    def test_model_download_failure_is_actionable(self) -> None:
        message = model_load_error_message(RuntimeError("connection timeout"))
        self.assertIn("internet connection", message)


if __name__ == "__main__":
    unittest.main()
