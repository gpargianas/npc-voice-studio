from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import soundfile as sf

from src.error_messages import generation_error_message


logger = logging.getLogger(__name__)


def _write_generated_audio(output_file: Path, audio: Any, sample_rate: int) -> None:
    try:
        sf.write(str(output_file), audio, sample_rate)
    except Exception as exc:
        raise OSError("Could not write generated audio file.") from exc


@dataclass(frozen=True)
class BatchGenerationRequest:
    generation_text: str
    output_path: Path


@dataclass(frozen=True)
class BatchGenerationResult:
    output_path: Path
    error: str | None = None


@dataclass(frozen=True)
class BatchVoiceContext:
    """Keep one encoded OmniVoice cloning prompt in the Gradio session."""

    voice_clone_prompt: Any


@dataclass(frozen=True)
class BatchGenerationRun:
    results: list[BatchGenerationResult]
    voice_context: BatchVoiceContext


class OmniVoiceService:
    """Load OmniVoice once for cloning, voice design, and Auto Voice."""

    MODEL_ID = "k2-fsa/OmniVoice"
    # This is the exact model snapshot validated during the OmniVoice migration.
    MODEL_REVISION = "c5fdb5ccb189668d56333f77ba2629f4cd7535f4"

    def __init__(self, model_revision: str = MODEL_REVISION) -> None:
        # Heavy ML imports stay inside guarded startup so the UI can always open.
        import torch
        from huggingface_hub import snapshot_download
        from omnivoice import OmniVoice

        use_cuda = torch.cuda.is_available()
        self.device = "cuda:0" if use_cuda else "cpu"
        dtype = torch.float16 if use_cuda else torch.float32
        self.model_revision = model_revision

        # Resolve the exact tested snapshot before OmniVoice loads its local files.
        model_path = snapshot_download(
            repo_id=self.MODEL_ID,
            revision=self.model_revision,
        )
        logger.info(
            "Loading OmniVoice model %s at revision %s on %s",
            self.MODEL_ID,
            self.model_revision,
            self.device,
        )
        # Keep the model resident so repeated UI generations do not reload it.
        self._model = OmniVoice.from_pretrained(
            model_path,
            device_map=self.device,
            dtype=dtype,
        )
        self.sample_rate = int(self._model.sampling_rate)

    def generate(
        self,
        ref_audio_path: str | Path,
        ref_text: str,
        generation_text: str,
        output_path: str | Path,
    ) -> str:
        if not ref_audio_path:
            raise ValueError("Reference audio is required.")
        reference_path = Path(ref_audio_path)
        if not reference_path.is_file():
            raise FileNotFoundError(f"Reference audio not found: {reference_path}")
        if not ref_text or not ref_text.strip():
            raise ValueError("Reference transcript is required.")
        if not generation_text or not generation_text.strip():
            raise ValueError("Generation text is required.")
        if not output_path:
            raise ValueError("Output path is required.")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # OmniVoice returns one NumPy waveform per requested text item.
        audio = self._model.generate(
            text=generation_text.strip(),
            ref_audio=str(reference_path),
            ref_text=ref_text.strip(),
        )
        if not audio:
            raise RuntimeError("OmniVoice did not return generated audio.")

        _write_generated_audio(output_file, audio[0], self.sample_rate)
        return str(output_file)

    def generate_designed_voice(
        self,
        generation_text: str,
        instruct: str,
        output_path: str | Path,
    ) -> str:
        """Generate a voice from supported OmniVoice speaker attributes."""
        if not generation_text or not generation_text.strip():
            raise ValueError("Generation text is required.")
        if not instruct or not instruct.strip():
            raise ValueError("At least one voice design attribute is required.")
        if not output_path:
            raise ValueError("Output path is required.")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        audio = self._model.generate(
            text=generation_text.strip(),
            instruct=instruct.strip(),
        )
        if not audio:
            raise RuntimeError("OmniVoice did not return generated audio.")

        _write_generated_audio(output_file, audio[0], self.sample_rate)
        return str(output_file)

    def generate_random_voice(
        self,
        generation_text: str,
        output_path: str | Path,
    ) -> str:
        """Generate an Auto Voice candidate without a reference or instruct."""
        if not generation_text or not generation_text.strip():
            raise ValueError("Generation text is required.")
        if not output_path:
            raise ValueError("Output path is required.")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Omitting reference and instruct arguments activates OmniVoice Auto Voice.
        audio = self._model.generate(text=generation_text.strip())
        if not audio:
            raise RuntimeError("OmniVoice did not return generated audio.")

        _write_generated_audio(output_file, audio[0], self.sample_rate)
        return str(output_file)

    def generate_batch(
        self,
        ref_audio_path: str | Path,
        ref_text: str,
        requests: Sequence[BatchGenerationRequest],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> BatchGenerationRun:
        """Generate sequentially while reusing one encoded cloning prompt."""
        if not ref_audio_path:
            raise ValueError("Reference audio is required.")
        reference_path = Path(ref_audio_path)
        if not reference_path.is_file():
            raise FileNotFoundError(f"Reference audio not found: {reference_path}")
        if not ref_text or not ref_text.strip():
            raise ValueError("Reference transcript is required.")
        if not requests:
            raise ValueError("At least one batch item is required.")

        # Encoding the saved voice is expensive, so do it once for the batch.
        voice_context = self._create_batch_voice_context(
            reference_path,
            ref_text,
        )

        results: list[BatchGenerationResult] = []
        total = len(requests)
        for index, request in enumerate(requests, start=1):
            output_file = Path(request.output_path)
            existed_before = output_file.exists()
            try:
                if not request.generation_text or not request.generation_text.strip():
                    raise ValueError("Generation text is required.")
                if output_file.exists():
                    raise FileExistsError(
                        f"Output file already exists: {output_file.name}"
                    )

                output_file.parent.mkdir(parents=True, exist_ok=True)
                audio = self._model.generate(
                    text=request.generation_text,
                    voice_clone_prompt=voice_context.voice_clone_prompt,
                )
                if not audio:
                    raise RuntimeError("OmniVoice did not return generated audio.")

                _write_generated_audio(output_file, audio[0], self.sample_rate)
                results.append(BatchGenerationResult(output_file))
            except Exception as exc:  # Keep later dialogue lines running.
                if not existed_before:
                    output_file.unlink(missing_ok=True)
                logger.exception(
                    "Batch generation failed for %s", output_file.name
                )
                results.append(
                    BatchGenerationResult(
                        output_file,
                        generation_error_message(exc),
                    )
                )
            finally:
                if progress_callback is not None:
                    try:
                        progress_callback(index, total)
                    except Exception:
                        logger.warning(
                            "Batch progress update failed after item %s", index
                        )

        return BatchGenerationRun(results, voice_context)

    def regenerate_batch_line(
        self,
        generation_text: str,
        output_path: str | Path,
        voice_context: BatchVoiceContext | None = None,
        ref_audio_path: str | Path | None = None,
        ref_text: str | None = None,
    ) -> tuple[BatchGenerationResult, BatchVoiceContext]:
        """Safely replace one batch WAV while preserving a working prior file."""
        if not generation_text or not generation_text.strip():
            raise ValueError("Generation text is required.")
        if not output_path:
            raise ValueError("Output path is required.")

        if voice_context is None:
            if not ref_audio_path or not ref_text:
                raise ValueError("Reference audio and transcript are required.")
            reference_path = Path(ref_audio_path)
            if not reference_path.is_file():
                raise FileNotFoundError(
                    f"Reference audio not found: {reference_path}"
                )
            voice_context = self._create_batch_voice_context(
                reference_path,
                ref_text,
            )

        output_file = Path(output_path)
        if not output_file.parent.is_dir():
            raise FileNotFoundError("The batch output directory no longer exists.")
        temporary_file = output_file.with_name(
            f".{output_file.stem}.{uuid4().hex}.tmp.wav"
        )

        try:
            audio = self._model.generate(
                text=generation_text,
                voice_clone_prompt=voice_context.voice_clone_prompt,
            )
            if not audio:
                raise RuntimeError("OmniVoice did not return generated audio.")

            _write_generated_audio(temporary_file, audio[0], self.sample_rate)
            os.replace(temporary_file, output_file)
            return BatchGenerationResult(output_file), voice_context
        except Exception as exc:
            temporary_file.unlink(missing_ok=True)
            logger.exception("Batch line regeneration failed for %s", output_file.name)
            return (
                BatchGenerationResult(
                    output_file,
                    generation_error_message(exc),
                ),
                voice_context,
            )

    def _create_batch_voice_context(
        self,
        reference_path: Path,
        ref_text: str,
    ) -> BatchVoiceContext:
        """Encode one saved reference for reuse across a batch session."""
        prompt = self._model.create_voice_clone_prompt(
            ref_audio=str(reference_path),
            ref_text=ref_text.strip(),
        )
        return BatchVoiceContext(prompt)
