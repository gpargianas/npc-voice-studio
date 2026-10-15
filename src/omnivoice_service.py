from pathlib import Path

import soundfile as sf
import torch
from omnivoice import OmniVoice


class OmniVoiceService:
    """Load OmniVoice once for cloning, voice design, and Auto Voice."""

    MODEL_ID = "k2-fsa/OmniVoice"

    def __init__(self) -> None:
        use_cuda = torch.cuda.is_available()
        self.device = "cuda:0" if use_cuda else "cpu"
        dtype = torch.float16 if use_cuda else torch.float32

        # Keep the model resident so repeated UI generations do not reload it.
        self._model = OmniVoice.from_pretrained(
            self.MODEL_ID,
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

        sf.write(str(output_file), audio[0], self.sample_rate)
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

        sf.write(str(output_file), audio[0], self.sample_rate)
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

        sf.write(str(output_file), audio[0], self.sample_rate)
        return str(output_file)
