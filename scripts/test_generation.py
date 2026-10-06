from importlib.resources import files
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.f5_service import F5VoiceService


def main() -> None:
    service = F5VoiceService()

    ref_audio_path = files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav")
    ref_text = "Some call me nature, others call me mother nature."
    generation_text = "This is a short local zero shot voice cloning test."
    output_path = PROJECT_ROOT / "generated_audio" / "test_output.wav"

    generated_path = service.generate(
        ref_audio_path=ref_audio_path,
        ref_text=ref_text,
        generation_text=generation_text,
        output_path=output_path,
    )

    print(f"Device: {service.device}")
    print(f"Output: {generated_path}")


if __name__ == "__main__":
    main()
