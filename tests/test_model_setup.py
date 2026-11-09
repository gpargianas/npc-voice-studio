from pathlib import Path
import tempfile
import unittest

from src.model_setup import (
    ModelDownloadError,
    ModelSpec,
    install_model,
    model_cache_environment,
    resolve_installed_model,
    validate_model_cache,
    write_model_ready_marker,
)


SPEC = ModelSpec(
    repository="k2-fsa/OmniVoice",
    revision="c5fdb5ccb189668d56333f77ba2629f4cd7535f4",
    approximate_download_bytes=3_511_135_764,
    license_identifier="CC-BY-NC (version unspecified by upstream model card)",
    source_url="https://huggingface.co/k2-fsa/OmniVoice",
    model_card_url="https://huggingface.co/k2-fsa/OmniVoice/model-card",
)


def create_snapshot(root: Path) -> Path:
    snapshot = (
        root
        / "hub"
        / "models--k2-fsa--OmniVoice"
        / "snapshots"
        / SPEC.revision
    )
    snapshot.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.safetensors", "tokenizer.json"):
        (snapshot / name).write_bytes(b"fixture")
    return snapshot


class ModelSetupTests(unittest.TestCase):
    def test_valid_ready_marker_avoids_hugging_face_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot = create_snapshot(root)
            write_model_ready_marker(root, SPEC, snapshot)

            def fail_if_called(**_kwargs):
                raise AssertionError("Hugging Face lookup must not run")

            self.assertEqual(
                resolve_installed_model(root, SPEC, fail_if_called), snapshot
            )

    def test_missing_local_model_has_repair_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            calls = []

            def missing(**kwargs):
                calls.append(kwargs)
                raise FileNotFoundError("not cached")

            with self.assertRaisesRegex(
                RuntimeError,
                "model installation is incomplete",
            ):
                resolve_installed_model(root, SPEC, missing)

            self.assertEqual(calls[0]["revision"], SPEC.revision)
            self.assertTrue(calls[0]["local_files_only"])

    def test_local_validation_uses_exact_revision_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot = create_snapshot(root)
            calls = []

            def fake_download(**kwargs):
                calls.append(kwargs)
                return str(snapshot)

            self.assertEqual(validate_model_cache(root, SPEC, fake_download), snapshot)
            self.assertEqual(calls[0]["repo_id"], SPEC.repository)
            self.assertEqual(calls[0]["revision"], SPEC.revision)
            self.assertTrue(calls[0]["local_files_only"])
            self.assertEqual(calls[0]["cache_dir"], str(root / "hub"))

    def test_install_downloads_exact_pinned_revision_without_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot = create_snapshot(root)
            calls = []

            def fake_download(**kwargs):
                calls.append(kwargs)
                return str(snapshot)

            result = install_model(root, SPEC, snapshot_download=fake_download)
            self.assertEqual(result, snapshot)
            self.assertEqual(calls[0]["repo_id"], SPEC.repository)
            self.assertEqual(calls[0]["revision"], SPEC.revision)

    def test_failed_download_preserves_cache_and_retry_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            partial = root / "hub" / "partial-download"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b"keep me")
            snapshot = create_snapshot(root)
            network_attempts = 0

            def fake_download(**kwargs):
                nonlocal network_attempts
                if not kwargs["local_files_only"]:
                    network_attempts += 1
                    if network_attempts == 1:
                        raise OSError("simulated network failure")
                return str(snapshot)

            with self.assertRaises(ModelDownloadError):
                install_model(root, SPEC, snapshot_download=fake_download)
            self.assertEqual(partial.read_bytes(), b"keep me")

            result = install_model(root, SPEC, snapshot_download=fake_download)
            self.assertEqual(result, snapshot)
            self.assertTrue(partial.is_file())
            self.assertEqual(network_attempts, 2)

    def test_model_environment_is_dedicated_and_disables_telemetry(self) -> None:
        root = Path("models").resolve()
        environment = model_cache_environment(root)
        self.assertEqual(environment["HF_HOME"], str(root))
        self.assertEqual(environment["HF_HUB_CACHE"], str(root / "hub"))
        self.assertEqual(environment["HF_XET_CACHE"], str(root / "xet"))
        self.assertEqual(environment["HF_HUB_DISABLE_TELEMETRY"], "1")

    def test_model_progress_uses_hugging_face_hook_without_disabling_cache_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot = create_snapshot(root)
            calls = []
            progress = []
            verified = []

            def fake_download(**kwargs):
                calls.append(kwargs)
                if not kwargs["local_files_only"]:
                    progress_bar = kwargs["tqdm_class"](total=4, disable=True)
                    progress_bar.update(2)
                    progress_bar.update(2)
                    progress_bar.close()
                return str(snapshot)

            result = install_model(
                root,
                SPEC,
                snapshot_download=fake_download,
                progress_callback=lambda current, total: progress.append(
                    (current, total)
                ),
                verification_callback=lambda: verified.append(True),
            )

            self.assertEqual(result, snapshot)
            network_call = calls[0]
            self.assertEqual(network_call["cache_dir"], str(root / "hub"))
            self.assertEqual(network_call["revision"], SPEC.revision)
            self.assertFalse(network_call["local_files_only"])
            self.assertFalse(network_call["force_download"])
            self.assertNotIn("local_dir", network_call)
            self.assertEqual(progress, [(2, 4), (4, 4)])
            self.assertEqual(verified, [True])


if __name__ == "__main__":
    unittest.main()
