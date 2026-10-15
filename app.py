from pathlib import Path
from uuid import uuid4

import gradio as gr
import soundfile as sf

from src.omnivoice_service import OmniVoiceService
from src.voice_profiles import VoiceProfileError, VoiceProfileManager


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "generated_audio"
PROFILES_DIR = PROJECT_ROOT / "voice_profiles"
CREATE_FROM_SAMPLE = "Create from Sample"
VOICE_LIBRARY = "Voice Library"

# Keep one model instance alive for every generation request.
voice_service = OmniVoiceService()
profile_manager = VoiceProfileManager(PROFILES_DIR)


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


def _voice_error_message(error: VoiceProfileError) -> str:
    """Translate backend terminology into the simpler product language."""
    return (
        str(error)
        .replace("Voice profile", "Voice")
        .replace("voice profile", "voice")
        .replace("Profile name", "Voice name")
        .replace("profile name", "voice name")
    )


def get_user_voice_choices() -> list[tuple[str, str]]:
    """Return radio choices with duration while keeping stored names as values."""
    choices: list[tuple[str, str]] = []
    for name in profile_manager.list_profiles():
        try:
            profile = profile_manager.get_profile(name)
            duration = sf.info(profile.reference_audio_path).duration
            label = f"{name} ({duration:.1f}s)"
        except (VoiceProfileError, RuntimeError, OSError, TypeError, ValueError):
            label = name
        choices.append((label, name))
    return choices


def switch_voice_source(
    voice_source: str,
) -> tuple[
    dict,
    dict,
    dict,
    dict,
    dict,
    dict,
    dict,
    None,
    dict,
    dict,
]:
    """Switch top-level workflows and close transient panels."""
    if voice_source not in {CREATE_FROM_SAMPLE, VOICE_LIBRARY}:
        raise gr.Error("Invalid voice source.")

    sample_mode = voice_source == CREATE_FROM_SAMPLE
    return (
        gr.update(visible=sample_mode),
        gr.update(visible=not sample_mode),
        gr.update(label="3. Dialogue" if sample_mode else "Dialogue"),
        gr.update(label="Generated Audio" if sample_mode else "Output Audio"),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value="", visible=False),
        None,
        gr.update(visible=False),
        gr.update(value="", visible=False),
    )


def clear_sample_save_state() -> tuple[dict, dict, dict, None]:
    """Invalidate post-generation saving when the sample source changes."""
    return (
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value="", visible=False),
        None,
    )


def select_user_voice(
    voice_name: str | None,
) -> tuple[str, dict, str | None, str, dict, str, dict]:
    """Load one selected user voice into the shared library display."""
    if not voice_name:
        return (
            "",
            gr.update(visible=False),
            None,
            "",
            gr.update(visible=False),
            "",
            gr.update(value="", visible=False),
        )

    try:
        profile = profile_manager.get_profile(voice_name)
    except VoiceProfileError as exc:
        raise gr.Error(_voice_error_message(exc)) from exc

    return (
        f"### Selected Voice: {voice_name}",
        gr.update(visible=True),
        str(profile.reference_audio_path),
        profile.transcript,
        gr.update(visible=False),
        "",
        gr.update(value="", visible=False),
    )


def show_delete_voice_confirmation(
    voice_name: str | None,
) -> tuple[str, dict, dict]:
    """Require an explicit second action before deleting a user voice."""
    if not voice_name:
        raise gr.Error("Select a voice from My Voices first.")

    try:
        profile_manager.get_profile(voice_name)
    except VoiceProfileError as exc:
        raise gr.Error(_voice_error_message(exc)) from exc

    message = (
        f'### Delete "{voice_name}"?\n\n'
        "This will remove the saved reference audio and transcript "
        "from your Voice Library."
    )
    return message, gr.update(visible=True), gr.update(value="", visible=False)


def cancel_delete_voice() -> tuple[str, dict]:
    return "", gr.update(visible=False)


def delete_user_voice(
    voice_name: str | None,
) -> tuple[dict, dict, str, dict, None, str, str, dict, dict]:
    """Delete a confirmed user voice and reset all related library state."""
    if not voice_name:
        raise gr.Error("Select a voice from My Voices first.")

    try:
        profile_manager.delete_profile(voice_name)
    except VoiceProfileError as exc:
        raise gr.Error(_voice_error_message(exc)) from exc

    choices = get_user_voice_choices()
    gr.Info(f'Voice "{voice_name}" deleted.')
    return (
        gr.update(choices=choices, value=None),
        gr.update(visible=not choices),
        "",
        gr.update(visible=False),
        None,
        "",
        "",
        gr.update(visible=False),
        gr.update(value=f'Voice "{voice_name}" deleted.', visible=True),
    )


def generate_voice(
    voice_source: str,
    selected_voice: str | None,
    ref_audio_path: str | None,
    ref_transcript: str,
    dialogue: str,
) -> tuple[str, dict, dict[str, str] | None, dict, dict, dict]:
    """Resolve the selected source and generate one WAV file."""
    sample_generation: dict[str, str] | None = None

    if voice_source == VOICE_LIBRARY:
        if not selected_voice:
            raise gr.Error("Select a voice from My Voices before generating.")
        try:
            profile = profile_manager.get_profile(selected_voice)
        except VoiceProfileError as exc:
            raise gr.Error(_voice_error_message(exc)) from exc
        ref_audio_path = str(profile.reference_audio_path)
        ref_transcript = profile.transcript
    elif voice_source != CREATE_FROM_SAMPLE:
        raise gr.Error("Invalid voice source.")

    if not ref_audio_path:
        raise gr.Error("Reference audio is required.")
    if not ref_transcript or not ref_transcript.strip():
        raise gr.Error("Transcript is required.")
    if not dialogue or not dialogue.strip():
        raise gr.Error("Dialogue is required.")

    ref_transcript = ref_transcript.strip()

    output_path = OUTPUT_DIR / f"generation_{uuid4().hex}.wav"
    generated_path = voice_service.generate(
        ref_audio_path=ref_audio_path,
        ref_text=ref_transcript,
        generation_text=dialogue,
        output_path=output_path,
    )

    if voice_source == CREATE_FROM_SAMPLE:
        # Keep the exact source used for inference; never save generated audio.
        sample_generation = {
            "voice_source": CREATE_FROM_SAMPLE,
            "ref_audio_path": str(ref_audio_path),
            "ref_transcript": ref_transcript,
        }

    return (
        generated_path,
        gr.update(value=generated_path, visible=True),
        sample_generation,
        gr.update(visible=sample_generation is not None),
        gr.update(visible=False),
        gr.update(value="", visible=False),
    )


def show_save_voice_panel() -> tuple[dict, str, dict]:
    return (
        gr.update(visible=True),
        "",
        gr.update(value="", visible=False),
    )


def cancel_save_voice() -> tuple[dict, str]:
    return gr.update(visible=False), ""


def save_generated_voice(
    voice_name: str,
    sample_generation: dict[str, str] | None,
) -> tuple[
    dict,
    dict,
    str,
    dict,
    dict,
    dict,
    None,
    str,
    dict,
    None,
    str,
    str,
    dict,
    dict,
]:
    """Save the source from the last successful sample-based generation."""
    if not voice_name or not voice_name.strip():
        raise gr.Error("Voice name is required.")
    if not sample_generation or sample_generation.get("voice_source") != CREATE_FROM_SAMPLE:
        raise gr.Error("Generate from a sample before saving a voice.")

    ref_audio_path = sample_generation.get("ref_audio_path")
    ref_transcript = sample_generation.get("ref_transcript")
    if not ref_audio_path or not ref_transcript:
        raise gr.Error("The generated voice source is no longer available.")

    try:
        profile = profile_manager.create_profile(
            voice_name,
            ref_audio_path,
            ref_transcript,
        )
    except VoiceProfileError as exc:
        raise gr.Error(_voice_error_message(exc)) from exc

    gr.Info(f'Voice "{profile.name}" saved to My Voices.')
    return (
        gr.update(choices=get_user_voice_choices(), value=None),
        gr.update(visible=False),
        "",
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(
            value=f'Voice "{profile.name}" saved to My Voices.',
            visible=True,
        ),
        None,
        "",
        gr.update(visible=False),
        None,
        "",
        "",
        gr.update(visible=False),
        gr.update(value="", visible=False),
    )


initial_user_voice_choices = get_user_voice_choices()

with gr.Blocks(title="NPC Voice Studio") as demo:
    gr.Markdown("# NPC Voice Studio")

    voice_source = gr.Radio(
        choices=[CREATE_FROM_SAMPLE, VOICE_LIBRARY],
        value=CREATE_FROM_SAMPLE,
        label="Voice Source",
    )

    with gr.Column(visible=True) as create_from_sample_panel:
        reference_audio = gr.Audio(
            label="1. Reference Audio",
            sources=["upload"],
            type="filepath",
            autoplay=False,
        )
        reference_transcript = gr.Textbox(
            label="2. Transcript",
            placeholder="Exact words spoken in the reference audio",
        )
        reference_transcript_file = gr.File(
            label="Import Transcript (.txt)",
            file_types=[".txt"],
            type="filepath",
        )

    with gr.Column(visible=False) as voice_library_panel:
        gr.Markdown("## My Voices")
        no_user_voices = gr.Markdown(
            "No voices saved yet.",
            visible=not initial_user_voice_choices,
        )
        user_voice_selector = gr.Radio(
            choices=initial_user_voice_choices,
            value=None,
            label="Choose a voice",
        )

        with gr.Column(visible=False, variant="panel") as selected_voice_panel:
            selected_voice_heading = gr.Markdown()
            library_reference_audio = gr.Audio(
                label="Reference Audio",
                interactive=False,
                autoplay=False,
                editable=False,
                buttons=[],
            )
            library_reference_transcript = gr.Textbox(
                label="Reference Transcript",
                interactive=False,
            )
            delete_voice_button = gr.Button("Delete Voice", variant="stop")
            with gr.Column(visible=False, variant="panel") as delete_voice_panel:
                delete_voice_message = gr.Markdown()
                with gr.Row():
                    cancel_delete_voice_button = gr.Button("Cancel")
                    confirm_delete_voice_button = gr.Button(
                        "Delete Voice",
                        variant="stop",
                    )

        library_action_message = gr.Markdown(visible=False)

        # Built-ins intentionally have a separate future data source and UI section.
        gr.Markdown("## Built-in Voices")
        gr.Markdown("No built-in voices installed yet.")

    dialogue = gr.Textbox(
        label="3. Dialogue",
        placeholder="Text to generate",
        lines=5,
    )
    dialogue_file = gr.File(
        label="Import Dialogue (.txt)",
        file_types=[".txt"],
        type="filepath",
    )
    generate_button = gr.Button("Generate", variant="primary")
    output_audio = gr.Audio(
        label="Generated Audio",
        type="filepath",
        buttons=["download"],
    )
    download_generated_audio = gr.DownloadButton(
        "Download Generated Audio",
        value=None,
        variant="secondary",
        size="lg",
        visible=False,
    )

    save_voice_for_reuse_button = gr.Button(
        "Save Voice for Reuse",
        variant="primary",
        visible=False,
    )
    with gr.Column(visible=False, variant="panel") as save_voice_panel:
        gr.Markdown("### Save this voice")
        voice_name = gr.Textbox(label="Voice Name")
        with gr.Row():
            cancel_save_voice_button = gr.Button("Cancel")
            confirm_save_voice_button = gr.Button(
                "Save to Voice Library",
                variant="primary",
            )
    save_voice_confirmation = gr.Markdown(visible=False)

    # Stores only the sample source used by the last successful generation.
    sample_generation_state = gr.State(value=None)

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

    voice_source.change(
        fn=switch_voice_source,
        inputs=voice_source,
        outputs=[
            create_from_sample_panel,
            voice_library_panel,
            dialogue,
            output_audio,
            save_voice_for_reuse_button,
            save_voice_panel,
            save_voice_confirmation,
            sample_generation_state,
            delete_voice_panel,
            library_action_message,
        ],
    )
    reference_audio.change(
        fn=clear_sample_save_state,
        outputs=[
            save_voice_for_reuse_button,
            save_voice_panel,
            save_voice_confirmation,
            sample_generation_state,
        ],
    )
    reference_transcript.change(
        fn=clear_sample_save_state,
        outputs=[
            save_voice_for_reuse_button,
            save_voice_panel,
            save_voice_confirmation,
            sample_generation_state,
        ],
    )

    user_voice_selector.change(
        fn=select_user_voice,
        inputs=user_voice_selector,
        outputs=[
            selected_voice_heading,
            selected_voice_panel,
            library_reference_audio,
            library_reference_transcript,
            delete_voice_panel,
            delete_voice_message,
            library_action_message,
        ],
    )
    delete_voice_button.click(
        fn=show_delete_voice_confirmation,
        inputs=user_voice_selector,
        outputs=[
            delete_voice_message,
            delete_voice_panel,
            library_action_message,
        ],
    )
    cancel_delete_voice_button.click(
        fn=cancel_delete_voice,
        outputs=[delete_voice_message, delete_voice_panel],
    )
    confirm_delete_voice_button.click(
        fn=delete_user_voice,
        inputs=user_voice_selector,
        outputs=[
            user_voice_selector,
            no_user_voices,
            selected_voice_heading,
            selected_voice_panel,
            library_reference_audio,
            library_reference_transcript,
            delete_voice_message,
            delete_voice_panel,
            library_action_message,
        ],
    )

    generate_button.click(
        fn=generate_voice,
        inputs=[
            voice_source,
            user_voice_selector,
            reference_audio,
            reference_transcript,
            dialogue,
        ],
        outputs=[
            output_audio,
            download_generated_audio,
            sample_generation_state,
            save_voice_for_reuse_button,
            save_voice_panel,
            save_voice_confirmation,
        ],
    )
    save_voice_for_reuse_button.click(
        fn=show_save_voice_panel,
        outputs=[save_voice_panel, voice_name, save_voice_confirmation],
    )
    cancel_save_voice_button.click(
        fn=cancel_save_voice,
        outputs=[save_voice_panel, voice_name],
    )
    confirm_save_voice_button.click(
        fn=save_generated_voice,
        inputs=[voice_name, sample_generation_state],
        outputs=[
            user_voice_selector,
            no_user_voices,
            voice_name,
            save_voice_panel,
            save_voice_for_reuse_button,
            save_voice_confirmation,
            sample_generation_state,
            selected_voice_heading,
            selected_voice_panel,
            library_reference_audio,
            library_reference_transcript,
            delete_voice_message,
            delete_voice_panel,
            library_action_message,
        ],
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch()
