import os
from pathlib import Path

# Keep numba/librosa import-time caches in the project instead of site-packages.
os.environ.setdefault("NUMBA_CACHE_DIR", str(Path(".numba_cache").resolve()))

import torch
from f5_tts.api import F5TTS


class F5VoiceService:
    """Small wrapper around the installed F5-TTS Python API."""

    def __init__(self) -> None:
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Loading is intentionally done once here because model startup is expensive.
        self._model = F5TTS(device=self.device)

    def generate(
        self,
        ref_audio_path: str | Path,
        ref_text: str,
        generation_text: str,
        output_path: str | Path,
    ) -> str:
        """Generate cloned speech and save it to output_path."""
        ref_audio = self._validate_ref_audio(ref_audio_path)
        ref_text = self._validate_text(ref_text, "ref_text")
        generation_text = self._validate_text(generation_text, "generation_text")
        output_file = self._validate_output_path(output_path)

        # F5-TTS writes the WAV when file_wave is provided.
        self._model.infer(
            ref_file=str(ref_audio),
            ref_text=ref_text,
            gen_text=generation_text,
            file_wave=str(output_file),
            show_info=lambda *_args, **_kwargs: None,
            progress=None,
        )

        return str(output_file)

    @staticmethod
    def _validate_ref_audio(ref_audio_path: str | Path) -> Path:
        if not ref_audio_path:
            raise ValueError("ref_audio_path is required.")

        ref_audio = Path(ref_audio_path).expanduser()
        if not ref_audio.exists():
            raise FileNotFoundError(f"Reference audio not found: {ref_audio}")
        if not ref_audio.is_file():
            raise ValueError(f"Reference audio must be a file: {ref_audio}")

        return ref_audio

    @staticmethod
    def _validate_text(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")

        return value.strip()

    @staticmethod
    def _validate_output_path(output_path: str | Path) -> Path:
        if not output_path:
            raise ValueError("output_path is required.")

        output_file = Path(output_path).expanduser()
        if output_file.exists() and output_file.is_dir():
            raise ValueError(f"output_path must be a file path, not a directory: {output_file}")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        return output_file
