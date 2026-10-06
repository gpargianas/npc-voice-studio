from pathlib import Path
from uuid import uuid4

import gradio as gr
import soundfile as sf

from src.f5_service import F5VoiceService


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "generated_audio"

# Keep one model instance alive for every generation request.
voice_service = F5VoiceService()


def load_text_file(file_path: str | None) -> str:
    """Load a UTF-8 .txt file, accepting and removing an optional BOM."""
    if not file_path:
        raise gr.Error("Please select a .txt file.")

    text_path = Path(file_path)
    if text_path.suffix.lower() != ".txt":
        raise gr.Error("Only .txt files are supported.")

    try:
        # utf-8-sig handles both plain UTF-8 and UTF-8 files with a BOM.
        return text_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise gr.Error("The text file must be encoded as UTF-8.") from exc
    except OSError as exc:
        raise gr.Error("Could not read the text file.") from exc


def generate_voice(
    ref_audio_path: str | None,
    ref_transcript: str,
    dialogue: str,
) -> str:
    """Validate the UI inputs and generate one WAV file."""
    if not ref_audio_path:
        raise gr.Error("Reference audio is required.")
    if not ref_transcript or not ref_transcript.strip():
        raise gr.Error("Reference transcript is required.")
    if not dialogue or not dialogue.strip():
        raise gr.Error("Dialogue is required.")

    try:
        # Read duration metadata only; F5-TTS handles all audio preprocessing.
        duration_seconds = sf.info(ref_audio_path).duration
    except (RuntimeError, TypeError, ValueError) as exc:
        raise gr.Error("Could not read the reference audio file.") from exc

    # Reject long clips because F5-TTS may shorten the audio but leave a manual
    # transcript untouched, creating a mismatch that can corrupt generation.
    if duration_seconds > 12:
        raise gr.Error(
            "Reference audio is longer than 12 seconds. F5-TTS may shorten "
            "long reference audio without shortening a manually supplied "
            "transcript, causing the audio and transcript to become mismatched. "
            "Please provide a reference clip of 12 seconds or less with a "
            "matching transcript."
        )

    output_path = OUTPUT_DIR / f"generation_{uuid4().hex}.wav"
    return voice_service.generate(
        ref_audio_path=ref_audio_path,
        ref_text=ref_transcript,
        generation_text=dialogue,
        output_path=output_path,
    )


with gr.Blocks(title="NPC Voice Studio") as demo:
    gr.Markdown("# NPC Voice Studio")

    reference_audio = gr.Audio(
        label="Reference Audio",
        sources=["upload"],
        type="filepath",
    )
    reference_transcript = gr.Textbox(
        label="Reference Transcript",
        placeholder="Exact words spoken in the reference audio OR upload text file below",
    )
    reference_transcript_file = gr.File(
        label="Import Reference Transcript (.txt)",
        file_types=[".txt"],
        type="filepath",
    )
    dialogue = gr.Textbox(
        label="Dialogue to generate",
        placeholder="Text to generate OR upload text file below",
        lines=5,
    )
    dialogue_file = gr.File(
        label="Import Dialogue (.txt)",
        file_types=[".txt"],
        type="filepath",
    )
    generate_button = gr.Button("Generate", variant="primary")
    output_audio = gr.Audio(label="Output Audio", type="filepath")

    # Uploading text only fills the editable textbox; Generate remains explicit.
    reference_transcript_file.upload(
        fn=load_text_file,
        inputs=reference_transcript_file,
        outputs=reference_transcript,
    )
    dialogue_file.upload(
        fn=load_text_file,
        inputs=dialogue_file,
        outputs=dialogue,
    )

    generate_button.click(
        fn=generate_voice,
        inputs=[reference_audio, reference_transcript, dialogue],
        outputs=output_audio,
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch()
