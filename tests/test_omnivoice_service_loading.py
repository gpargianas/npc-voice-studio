import sys
import types
import unittest
from unittest.mock import patch

from src.omnivoice_service import OmniVoiceService


class OmniVoiceServiceLoadingTests(unittest.TestCase):
    def test_exact_model_revision_is_resolved_before_loading(self) -> None:
        snapshot_calls: list[dict[str, str]] = []
        model_calls: list[tuple[str, dict]] = []

        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)
        fake_torch.float16 = "float16"
        fake_torch.float32 = "float32"

        fake_hub = types.ModuleType("huggingface_hub")

        def snapshot_download(**kwargs):
            snapshot_calls.append(kwargs)
            return "cached-model-snapshot"

        fake_hub.snapshot_download = snapshot_download

        fake_omnivoice = types.ModuleType("omnivoice")

        class FakeModel:
            sampling_rate = 24000

        class FakeOmniVoice:
            @classmethod
            def from_pretrained(cls, model_path, **kwargs):
                model_calls.append((model_path, kwargs))
                return FakeModel()

        fake_omnivoice.OmniVoice = FakeOmniVoice

        with patch.dict(
            sys.modules,
            {
                "torch": fake_torch,
                "huggingface_hub": fake_hub,
                "omnivoice": fake_omnivoice,
            },
        ):
            service = OmniVoiceService()

        self.assertEqual(
            snapshot_calls,
            [
                {
                    "repo_id": OmniVoiceService.MODEL_ID,
                    "revision": OmniVoiceService.MODEL_REVISION,
                }
            ],
        )
        self.assertEqual(model_calls[0][0], "cached-model-snapshot")
        self.assertEqual(model_calls[0][1]["device_map"], "cuda:0")
        self.assertEqual(service.model_revision, OmniVoiceService.MODEL_REVISION)


if __name__ == "__main__":
    unittest.main()
