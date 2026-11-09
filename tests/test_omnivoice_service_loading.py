import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from src.omnivoice_service import OmniVoiceService
from src.model_setup import load_model_spec, write_model_ready_marker


class OmniVoiceServiceLoadingTests(unittest.TestCase):
    def create_snapshot(self, root: Path) -> Path:
        spec = load_model_spec()
        snapshot = (
            root
            / "hub"
            / "models--k2-fsa--OmniVoice"
            / "snapshots"
            / spec.revision
        )
        snapshot.mkdir(parents=True)
        for name in ("config.json", "model.safetensors", "tokenizer.json"):
            (snapshot / name).write_bytes(b"fixture")
        return snapshot

    def fake_runtime_modules(self, model_calls):
        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)
        fake_torch.float16 = "float16"
        fake_torch.float32 = "float32"

        fake_omnivoice = types.ModuleType("omnivoice")

        class FakeModel:
            sampling_rate = 24000

        class FakeOmniVoice:
            @classmethod
            def from_pretrained(cls, model_path, **kwargs):
                model_calls.append((model_path, kwargs))
                return FakeModel()

        fake_omnivoice.OmniVoice = FakeOmniVoice
        return {"torch": fake_torch, "omnivoice": fake_omnivoice}

    def test_offline_complete_pinned_cache_initializes_without_hub_lookup(self) -> None:
        model_calls: list[tuple[str, dict]] = []
        spec = load_model_spec()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot = self.create_snapshot(root)
            write_model_ready_marker(root, spec, snapshot)

            fake_hub = types.ModuleType("huggingface_hub")

            def forbidden_lookup(**_kwargs):
                raise AssertionError("runtime attempted a Hugging Face lookup")

            fake_hub.snapshot_download = forbidden_lookup
            modules = self.fake_runtime_modules(model_calls)
            modules["huggingface_hub"] = fake_hub

            with (
                patch.dict(sys.modules, modules),
                patch.dict(os.environ, {"HF_HUB_OFFLINE": "1"}),
            ):
                service = OmniVoiceService(models_root=root, model_spec=spec)

        self.assertEqual(Path(model_calls[0][0]), snapshot)
        self.assertEqual(model_calls[0][1]["device_map"], "cuda:0")
        self.assertEqual(service.model_id, spec.repository)
        self.assertEqual(service.model_revision, spec.revision)

    def test_offline_missing_cache_has_useful_error(self) -> None:
        model_calls = []
        spec = load_model_spec()
        fake_hub = types.ModuleType("huggingface_hub")
        calls = []

        def missing(**kwargs):
            calls.append(kwargs)
            raise FileNotFoundError("cache is empty")

        fake_hub.snapshot_download = missing
        modules = self.fake_runtime_modules(model_calls)
        modules["huggingface_hub"] = fake_hub

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.dict(sys.modules, modules),
                patch.dict(os.environ, {"HF_HUB_OFFLINE": "1"}),
                self.assertRaisesRegex(
                    RuntimeError,
                    "model installation is incomplete",
                ),
            ):
                OmniVoiceService(
                    models_root=Path(temporary_directory),
                    model_spec=spec,
                )

        self.assertEqual(model_calls, [])
        self.assertEqual(calls[0]["repo_id"], spec.repository)
        self.assertEqual(calls[0]["revision"], spec.revision)
        self.assertTrue(calls[0]["local_files_only"])


if __name__ == "__main__":
    unittest.main()
