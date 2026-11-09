import json
from pathlib import Path
import tempfile
import threading
import unittest

from src.setup_progress import write_setup_progress


class SetupProgressTests(unittest.TestCase):
    def test_concurrent_download_updates_never_break_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            status_file = Path(temporary_directory) / "setup_status.json"
            failures = []

            def write_updates(worker: int) -> None:
                try:
                    for update in range(40):
                        write_setup_progress(
                            status_file,
                            "Downloading OmniVoice model (~3.3 GB)...",
                            75 + (update % 15),
                            f"worker={worker} update={update}",
                        )
                except Exception as exc:  # pragma: no cover - assertion evidence
                    failures.append(exc)

            workers = [
                threading.Thread(target=write_updates, args=(index,))
                for index in range(8)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()

            self.assertEqual(failures, [])
            payload = json.loads(status_file.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["operation"],
                "Downloading OmniVoice model (~3.3 GB)...",
            )
            self.assertGreaterEqual(payload["percent"], 75)
            self.assertLessEqual(payload["percent"], 89)


if __name__ == "__main__":
    unittest.main()
