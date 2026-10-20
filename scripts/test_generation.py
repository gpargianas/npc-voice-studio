import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.app_paths import APP_PATHS
from src.omnivoice_service import OmniVoiceService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one OmniVoice cloning test.")
    parser.add_argument("reference_audio", type=Path)
    parser.add_argument(
        "--reference-text",
        required=True,
        help="Exact transcript of the reference audio.",
    )
    parser.add_argument(
        "--text",
        default="This is a short local OmniVoice cloning test.",
        help="Dialogue to generate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=APP_PATHS.generated_audio / "test_output.wav",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = OmniVoiceService()

    generated_path = service.generate(
        ref_audio_path=args.reference_audio,
        ref_text=args.reference_text,
        generation_text=args.text,
        output_path=args.output,
    )

    print(f"Device: {service.device}")
    print(f"Model revision: {service.model_revision}")
    print(f"Output: {generated_path}")


if __name__ == "__main__":
    main()
