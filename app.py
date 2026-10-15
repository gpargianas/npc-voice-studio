import logging
from pathlib import Path
from uuid import uuid4

import gradio as gr
import soundfile as sf

from src.batch_generation import (
    BatchCsvError,
    batch_output_path,
    create_batch_zip,
    parse_dialogue_csv,
    validate_batch_table,
)
from src.omnivoice_service import (
    BatchGenerationRequest,
    BatchVoiceContext,
    OmniVoiceService,
)
from src.voice_profiles import VoiceProfileError, VoiceProfileManager


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "generated_audio"
PROFILES_DIR = PROJECT_ROOT / "voice_profiles"
CREATE_FROM_SAMPLE = "Create from Sample"
DESIGN_VOICE = "Design Voice"
RANDOM_VOICE = "Random Voice"
VOICE_LIBRARY = "Voice Library"
BATCH_GENERATION = "Batch Generation"
UNSPECIFIED = "Any / unspecified"
NORMAL_UNSPECIFIED = "Normal / unspecified"

BATCH_TABLE_CSS = """
#batch-preview-table .add-row-button,
#batch-preview-table button[aria-label="Add row above"],
#batch-preview-table button[aria-label="Add row below"],
#batch-preview-table button[aria-label="Delete row"],
#batch-preview-table button[aria-label="Add column to the left"],
#batch-preview-table button[aria-label="Add column to the right"],
#batch-preview-table button[aria-label="Delete column"] {
    display: none !important;
}
"""

logger = logging.getLogger(__name__)

DIALOGUE_HELP = """
**Expression and non-verbal cues**

Insert a supported tag directly into the dialogue:

```text
[laughter] You really thought that would work?
[sigh] Fine. I'll help you.
[question-en] Where have you been?
```

**All supported tags**

`[laughter]`, `[sigh]`, `[confirmation-en]`, `[question-en]`,
`[question-ah]`, `[question-oh]`, `[question-ei]`, `[question-yi]`,
`[surprise-ah]`, `[surprise-oh]`, `[surprise-wa]`, `[surprise-yo]`,
`[dissatisfaction-hnn]`

**Pronunciation**

Override an English pronunciation by placing its **CMU/ARPAbet phonemes** in
square brackets. The contents must use CMU/ARPAbet notation, not an arbitrary
phonetic spelling.

```text
He plays the [B EY1 S] guitar while catching a [B AE1 S] fish.
```

This is useful for fantasy names, character names, place names, and unusual
terminology.

**Pacing**

Use normal punctuation naturally to shape sentence structure and pacing.
"""

# Values mirror OmniVoice's supported English voice-design attributes exactly.
VOICE_DESIGN_VALUES = {
    "gender": {
        UNSPECIFIED: "",
        "Male": "male",
        "Female": "female",
    },
    "age": {
        UNSPECIFIED: "",
        "Child": "child",
        "Teenager": "teenager",
        "Young adult": "young adult",
        "Middle-aged": "middle-aged",
        "Elderly": "elderly",
    },
    "pitch": {
        UNSPECIFIED: "",
        "Very low": "very low pitch",
        "Low": "low pitch",
        "Moderate": "moderate pitch",
        "High": "high pitch",
        "Very high": "very high pitch",
    },
    "style": {
        NORMAL_UNSPECIFIED: "",
        "Whisper": "whisper",
    },
    "accent": {
        UNSPECIFIED: "",
        "American": "american accent",
        "British": "british accent",
        "Australian": "australian accent",
        "Canadian": "canadian accent",
        "Indian": "indian accent",
        "Chinese": "chinese accent",
        "Korean": "korean accent",
        "Japanese": "japanese accent",
        "Portuguese": "portuguese accent",
        "Russian": "russian accent",
    },
}

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


def render_dialogue_help() -> None:
    """Render the shared, secondary help for OmniVoice inline controls."""
    with gr.Accordion("Dialogue controls & pronunciation", open=False):
        gr.Markdown(DIALOGUE_HELP)


def build_voice_design_instruct(
    gender: str | None,
    age: str | None,
    pitch: str | None,
    style: str | None,
    accent: str | None,
) -> str:
    """Convert constrained UI selections to OmniVoice's instruct format."""
    selections = {
        "gender": gender,
        "age": age,
        "pitch": pitch,
        "style": style,
        "accent": accent,
    }
    parts: list[str] = []
    for category, selection in selections.items():
        if selection is None:
            continue
        values = VOICE_DESIGN_VALUES[category]
        if selection not in values:
            raise gr.Error(f"Invalid voice design {category} selection.")
        if values[selection]:
            parts.append(values[selection])
    return ", ".join(parts)


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
) -> tuple:
    """Switch top-level workflows and close transient panels."""
    if voice_source not in {
        CREATE_FROM_SAMPLE,
        DESIGN_VOICE,
        RANDOM_VOICE,
        VOICE_LIBRARY,
        BATCH_GENERATION,
    }:
        raise gr.Error("Invalid voice source.")

    sample_mode = voice_source == CREATE_FROM_SAMPLE
    design_mode = voice_source == DESIGN_VOICE
    random_mode = voice_source == RANDOM_VOICE
    library_mode = voice_source == VOICE_LIBRARY
    batch_mode = voice_source == BATCH_GENERATION
    return (
        gr.update(visible=sample_mode),
        gr.update(visible=design_mode),
        gr.update(visible=random_mode),
        gr.update(visible=library_mode),
        gr.update(visible=batch_mode),
        gr.update(visible=not batch_mode),
        gr.update(label="3. Dialogue" if sample_mode else "Dialogue"),
        gr.update(label="Output Audio" if library_mode else "Generated Audio"),
        gr.update(value="Generate Random Voice" if random_mode else "Generate"),
        gr.update(visible=False),
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
) -> tuple[dict, dict, dict, str, dict, None, str, str, dict, dict]:
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


def load_batch_csv(
    csv_path: str | None,
) -> tuple:
    """Parse one upload and keep only validated rows in server-side state."""
    if not csv_path:
        return (
            gr.update(value=[], interactive=False),
            [],
            "",
            gr.update(interactive=False),
            gr.update(value=None, visible=False),
            gr.update(choices=[], value=None, visible=False),
            gr.update(visible=False),
            None,
            None,
        )

    try:
        rows = parse_dialogue_csv(csv_path)
    except BatchCsvError as exc:
        gr.Warning(str(exc))
        error_message = str(exc).replace("\n", "\n\n")
        return (
            gr.update(value=[], interactive=False),
            [],
            f"**CSV error**\n\n{error_message}",
            gr.update(interactive=False),
            gr.update(value=None, visible=False),
            gr.update(choices=[], value=None, visible=False),
            gr.update(visible=False),
            None,
            None,
        )

    row_state = [
        {
            "filename": row.filename,
            "text": row.text,
            "status": "Ready",
            "error": "",
        }
        for row in rows
    ]
    preview = _batch_preview(row_state)
    return (
        gr.update(value=preview, interactive=True),
        [],
        f"{len(rows)} dialogue lines ready.",
        gr.update(interactive=True),
        gr.update(value=None, visible=False),
        gr.update(choices=[], value=None, visible=False),
        gr.update(visible=False),
        None,
        None,
    )


def _batch_preview(row_state: list[dict[str, str]]) -> list[list[str]]:
    preview: list[list[str]] = []
    for row in row_state:
        status = row.get("status", "Ready")
        if status == "Failed" and row.get("error"):
            status = f"Failed: {row['error']}"
        preview.append([row["filename"], row["text"], status])
    return preview


def _batch_review_choices(
    row_state: list[dict[str, str]],
) -> list[tuple[str, str]]:
    return [
        (f"{row['filename']} - {row.get('status', 'Ready')}", row["filename"])
        for row in row_state
    ]


def _find_batch_row(
    filename: str | None,
    row_state: list[dict[str, str]] | None,
) -> dict[str, str]:
    if not filename or not row_state:
        raise gr.Error("Select a batch line first.")
    for row in row_state:
        if row.get("filename") == filename:
            return row
    raise gr.Error("The selected batch line was not found.")


def _batch_directory(batch_session: dict[str, str] | None) -> Path:
    if not batch_session or not isinstance(batch_session, dict):
        raise gr.Error("Generate a batch before reviewing its lines.")
    directory_value = batch_session.get("batch_directory")
    if not directory_value:
        raise gr.Error("The batch output directory is unavailable.")

    batches_root = (OUTPUT_DIR / "batches").resolve()
    directory = Path(directory_value).resolve()
    if directory.parent != batches_root or not directory.is_dir():
        raise gr.Error("The batch output directory is invalid or missing.")
    return directory


def select_batch_line(
    filename: str | None,
    row_state: list[dict[str, str]] | None,
    batch_session: dict[str, str] | None,
) -> tuple[dict, str, str, str | None, str, str]:
    """Show one generated line without creating duplicate audio players."""
    row = _find_batch_row(filename, row_state)
    directory = _batch_directory(batch_session)
    output_path = batch_output_path(directory, row["filename"])
    audio_path = str(output_path) if row.get("status") == "Success" else None
    status = f"**Status:** {row.get('status', 'Ready')}"
    if row.get("status") == "Failed" and row.get("error"):
        status += f"\n\n{row['error']}"
    return (
        gr.update(visible=True),
        row["filename"],
        row["text"],
        audio_path,
        status,
        "",
    )


def generate_batch(
    voice_name: str | None,
    preview_table: list[list[str]] | None,
    progress: gr.Progress = gr.Progress(),
) -> tuple:
    """Generate the current edited preview with one saved voice."""
    if not voice_name:
        raise gr.Error("Select a saved voice before generating the batch.")

    try:
        rows = validate_batch_table(preview_table)
    except BatchCsvError as exc:
        raise gr.Error(str(exc)) from exc

    try:
        profile = profile_manager.get_profile(voice_name)
    except VoiceProfileError as exc:
        raise gr.Error(_voice_error_message(exc)) from exc

    batch_directory = OUTPUT_DIR / "batches" / uuid4().hex
    batch_directory.mkdir(parents=True, exist_ok=False)
    requests = [
        BatchGenerationRequest(
            generation_text=row.text,
            output_path=batch_output_path(batch_directory, row.filename),
        )
        for row in rows
    ]

    progress(0, desc=f"Preparing {len(rows)} lines")

    def update_progress(completed: int, total: int) -> None:
        progress((completed, total), desc=f"Generating {completed} / {total}")

    try:
        run = voice_service.generate_batch(
            ref_audio_path=profile.reference_audio_path,
            ref_text=profile.transcript,
            requests=requests,
            progress_callback=update_progress,
        )
    except Exception as exc:
        logger.exception("Batch generation could not start")
        error = str(exc).replace("\n", " ")[:180]
        raise gr.Error(f"Batch generation could not start: {error}") from exc

    generated_rows: list[dict[str, str]] = []
    successful_files: list[Path] = []
    failed = 0
    for row, result in zip(rows, run.results, strict=True):
        if result.error is None and result.output_path.is_file():
            status = "Success"
            error = ""
            successful_files.append(result.output_path)
        else:
            failed += 1
            error = (result.error or "Output file was not created.").replace("\n", " ")
            error = error[:180]
            status = "Failed"
        generated_rows.append(
            {
                "filename": row.filename,
                "text": row.text,
                "status": status,
                "error": error,
            }
        )

    successful = len(successful_files)
    summary = (
        f"Batch complete: {successful} generated, {failed} failed "
        f"({len(rows)} total)."
    )
    download_update = gr.update(value=None, visible=False)
    if successful_files:
        try:
            zip_path = create_batch_zip(batch_directory, successful_files)
            download_update = gr.update(value=str(zip_path), visible=True)
        except (BatchCsvError, OSError) as exc:
            logger.exception("Could not create batch ZIP")
            gr.Warning(f"Audio was generated, but the ZIP could not be created: {exc}")

    first_row = generated_rows[0]
    first_output = batch_output_path(batch_directory, first_row["filename"])
    first_audio = (
        str(first_output) if first_row["status"] == "Success" else None
    )
    first_status = f"**Status:** {first_row['status']}"
    if first_row["error"]:
        first_status += f"\n\n{first_row['error']}"
    batch_session = {
        "batch_directory": str(batch_directory),
        "voice_name": voice_name,
    }
    return (
        gr.update(value=_batch_preview(generated_rows), interactive=False),
        summary,
        download_update,
        generated_rows,
        gr.update(
            choices=_batch_review_choices(generated_rows),
            value=first_row["filename"],
            visible=True,
        ),
        gr.update(visible=True),
        first_row["filename"],
        first_row["text"],
        first_audio,
        first_status,
        "",
        batch_session,
        run.voice_context,
    )


def regenerate_batch_line(
    selected_filename: str | None,
    edited_text: str,
    row_state: list[dict[str, str]] | None,
    batch_session: dict[str, str] | None,
    voice_context: BatchVoiceContext | None,
) -> tuple:
    """Regenerate one selected row and refresh its batch ZIP on success."""
    if not edited_text or not edited_text.strip():
        raise gr.Error("Dialogue is required before regenerating a line.")

    selected_row = _find_batch_row(selected_filename, row_state)
    directory = _batch_directory(batch_session)
    output_path = batch_output_path(directory, selected_row["filename"])
    voice_name = batch_session.get("voice_name") if batch_session else None
    if not voice_name:
        raise gr.Error("The saved voice used for this batch is unavailable.")
    try:
        profile = profile_manager.get_profile(voice_name)
    except VoiceProfileError as exc:
        raise gr.Error(_voice_error_message(exc)) from exc

    result, refreshed_context = voice_service.regenerate_batch_line(
        generation_text=edited_text,
        output_path=output_path,
        voice_context=voice_context,
        ref_audio_path=profile.reference_audio_path,
        ref_text=profile.transcript,
    )
    current_rows = [dict(row) for row in row_state or []]
    row_index = next(
        index
        for index, row in enumerate(current_rows)
        if row.get("filename") == selected_row["filename"]
    )

    if result.error is not None:
        error = result.error.replace("\n", " ")[:180]
        previous_status = current_rows[row_index].get("status", "Failed")
        current_audio = (
            str(output_path)
            if previous_status == "Success" and output_path.is_file()
            else None
        )
        message = (
            f'Regeneration failed for "{selected_row["filename"]}": {error}. '
            "The previous audio was preserved."
        )
        gr.Warning(message)
        zip_path = directory / "batch.zip"
        return (
            _batch_preview(current_rows),
            current_rows,
            gr.update(
                choices=_batch_review_choices(current_rows),
                value=selected_row["filename"],
            ),
            edited_text,
            current_audio,
            f"**Status:** {previous_status}",
            message,
            _batch_summary(current_rows),
            gr.update(
                value=str(zip_path) if zip_path.is_file() else None,
                visible=zip_path.is_file(),
            ),
            refreshed_context,
        )

    current_rows[row_index].update(
        text=edited_text,
        status="Success",
        error="",
    )
    successful_files = [
        batch_output_path(directory, row["filename"])
        for row in current_rows
        if row.get("status") == "Success"
    ]
    try:
        zip_path = create_batch_zip(directory, successful_files)
        download_update = gr.update(value=str(zip_path), visible=True)
    except (BatchCsvError, OSError) as exc:
        logger.exception("Could not refresh batch ZIP after regeneration")
        gr.Warning(f"The line was regenerated, but the ZIP refresh failed: {exc}")
        download_update = gr.update(value=None, visible=False)

    message = f'{selected_row["filename"]} regenerated successfully.'
    gr.Info(message)
    return (
        _batch_preview(current_rows),
        current_rows,
        gr.update(
            choices=_batch_review_choices(current_rows),
            value=selected_row["filename"],
        ),
        edited_text,
        str(output_path),
        "**Status:** Success",
        message,
        _batch_summary(current_rows),
        download_update,
        refreshed_context,
    )


def _batch_summary(row_state: list[dict[str, str]]) -> str:
    successful = sum(row.get("status") == "Success" for row in row_state)
    failed = sum(row.get("status") == "Failed" for row in row_state)
    return (
        f"Batch complete: {successful} generated, {failed} failed "
        f"({len(row_state)} total)."
    )


def generate_voice(
    voice_source: str,
    selected_voice: str | None,
    ref_audio_path: str | None,
    ref_transcript: str,
    dialogue: str,
    design_gender: str | None = None,
    design_age: str | None = None,
    design_pitch: str | None = None,
    design_style: str | None = None,
    design_accent: str | None = None,
) -> tuple[str, dict, dict[str, str] | None, dict, dict, dict, dict]:
    """Resolve the selected source and generate one WAV file."""
    reusable_voice_source: dict[str, str] | None = None
    output_path = OUTPUT_DIR / f"generation_{uuid4().hex}.wav"

    if voice_source == RANDOM_VOICE:
        if not dialogue or not dialogue.strip():
            raise gr.Error("Dialogue is required.")

        dialogue = dialogue.strip()
        generated_path = voice_service.generate_random_voice(
            generation_text=dialogue,
            output_path=output_path,
        )
        # Auto Voice does not recreate a prior speaker, so preserve this exact
        # candidate as the cloning reference if the user chooses to save it.
        reusable_voice_source = {
            "voice_source": RANDOM_VOICE,
            "ref_audio_path": generated_path,
            "ref_transcript": dialogue,
        }
    elif voice_source == DESIGN_VOICE:
        if not dialogue or not dialogue.strip():
            raise gr.Error("Dialogue is required.")

        instruct = build_voice_design_instruct(
            design_gender,
            design_age,
            design_pitch,
            design_style,
            design_accent,
        )
        if not instruct:
            raise gr.Error(
                "Select at least one Voice Design attribute before generating."
            )

        dialogue = dialogue.strip()
        generated_path = voice_service.generate_designed_voice(
            generation_text=dialogue,
            instruct=instruct,
            output_path=output_path,
        )
        # A design instruction does not guarantee the same speaker on a later
        # run, so reuse the successful output as a normal cloning reference.
        reusable_voice_source = {
            "voice_source": DESIGN_VOICE,
            "ref_audio_path": generated_path,
            "ref_transcript": dialogue,
        }
    else:
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
        generated_path = voice_service.generate(
            ref_audio_path=ref_audio_path,
            ref_text=ref_transcript,
            generation_text=dialogue,
            output_path=output_path,
        )

        if voice_source == CREATE_FROM_SAMPLE:
            # Keep the original sample source; never save cloned output here.
            reusable_voice_source = {
                "voice_source": CREATE_FROM_SAMPLE,
                "ref_audio_path": str(ref_audio_path),
                "ref_transcript": ref_transcript,
            }

    return (
        generated_path,
        gr.update(value=generated_path, visible=True),
        reusable_voice_source,
        gr.update(visible=reusable_voice_source is not None),
        gr.update(visible=False),
        gr.update(value="", visible=False),
        gr.update(visible=voice_source == RANDOM_VOICE),
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
    reusable_voice_source: dict[str, str] | None,
) -> tuple:
    """Save the reusable source from the last successful creation."""
    if not voice_name or not voice_name.strip():
        raise gr.Error("Voice name is required.")
    if not reusable_voice_source or reusable_voice_source.get("voice_source") not in {
        CREATE_FROM_SAMPLE,
        DESIGN_VOICE,
        RANDOM_VOICE,
    }:
        raise gr.Error("Generate a voice before saving it for reuse.")

    ref_audio_path = reusable_voice_source.get("ref_audio_path")
    ref_transcript = reusable_voice_source.get("ref_transcript")
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

    choices = get_user_voice_choices()
    gr.Info(f'Voice "{profile.name}" saved to My Voices.')
    return (
        gr.update(choices=choices, value=None),
        gr.update(choices=choices, value=None),
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
        choices=[
            CREATE_FROM_SAMPLE,
            DESIGN_VOICE,
            RANDOM_VOICE,
            VOICE_LIBRARY,
            BATCH_GENERATION,
        ],
        value=CREATE_FROM_SAMPLE,
        label="Workflow",
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

    with gr.Column(visible=False) as design_voice_panel:
        gr.Markdown("## Design Voice")
        with gr.Row():
            design_gender = gr.Dropdown(
                choices=list(VOICE_DESIGN_VALUES["gender"]),
                value=UNSPECIFIED,
                label="Gender",
            )
            design_age = gr.Dropdown(
                choices=list(VOICE_DESIGN_VALUES["age"]),
                value=UNSPECIFIED,
                label="Age",
            )
            design_pitch = gr.Dropdown(
                choices=list(VOICE_DESIGN_VALUES["pitch"]),
                value=UNSPECIFIED,
                label="Pitch",
            )
        with gr.Row():
            design_style = gr.Dropdown(
                choices=list(VOICE_DESIGN_VALUES["style"]),
                value=NORMAL_UNSPECIFIED,
                label="Style",
            )
            design_accent = gr.Dropdown(
                choices=list(VOICE_DESIGN_VALUES["accent"]),
                value=UNSPECIFIED,
                label="English Accent",
            )

    with gr.Column(visible=False) as random_voice_panel:
        gr.Markdown("## Random Voice")
        gr.Markdown(
            "Generate an original voice without providing a sample or choosing "
            "voice characteristics."
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

    with gr.Column(visible=False) as batch_generation_panel:
        gr.Markdown("## Batch Generation")
        batch_voice_selector = gr.Dropdown(
            choices=initial_user_voice_choices,
            value=None,
            label="Voice",
        )
        batch_csv = gr.File(
            label="Dialogue CSV",
            file_types=[".csv"],
            type="filepath",
        )
        with gr.Accordion("CSV format", open=False):
            gr.Markdown(
                "Use a UTF-8 CSV with exactly these headers. Filenames do not "
                "need the `.wav` extension.\n\n"
                "```csv\n"
                "filename,text\n"
                'merchant_001,"Welcome, traveler."\n'
                'merchant_002,"Take a look at my wares."\n'
                'merchant_003,"Come back anytime."\n'
                "```"
            )
        batch_preview = gr.Dataframe(
            headers=["Filename", "Dialogue", "Status"],
            datatype=["str", "str", "str"],
            type="array",
            value=[],
            column_count=3,
            label="Dialogue Preview & Edit",
            interactive=True,
            static_columns=[0, 2],
            elem_id="batch-preview-table",
        )
        gr.Markdown(
            "Review and edit dialogue before generation. Changes here will "
            "be used for the batch."
        )
        batch_status = gr.Markdown()
        batch_generate_button = gr.Button(
            "Generate All",
            variant="primary",
            interactive=False,
        )
        batch_download = gr.DownloadButton(
            "Download Batch (.zip)",
            value=None,
            variant="secondary",
            size="lg",
            visible=False,
        )
        batch_review_selector = gr.Dropdown(
            choices=[],
            value=None,
            label="Review generated line",
            visible=False,
        )
        with gr.Column(visible=False, variant="panel") as batch_review_panel:
            batch_review_filename = gr.Textbox(
                label="Filename",
                interactive=False,
            )
            batch_review_dialogue = gr.Textbox(
                label="Dialogue",
                lines=4,
            )
            batch_review_status = gr.Markdown()
            batch_review_audio = gr.Audio(
                label="Generated Audio",
                type="filepath",
                interactive=False,
                autoplay=False,
                editable=False,
                buttons=[],
            )
            regenerate_batch_line_button = gr.Button(
                "Regenerate Line",
                variant="primary",
            )
            batch_review_message = gr.Markdown()
        batch_rows_state = gr.State(value=[])
        batch_session_state = gr.State(value=None)
        batch_voice_context_state = gr.State(value=None)

    with gr.Column(visible=True) as single_generation_panel:
        dialogue = gr.Textbox(
            label="3. Dialogue",
            placeholder="Text to generate",
            lines=5,
        )
        render_dialogue_help()
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
        try_another_button = gr.Button(
            "Try Another",
            variant="secondary",
            visible=False,
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

        # Stores the exact source created by the last successful generation.
        reusable_voice_state = gr.State(value=None)

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
    batch_csv.change(
        fn=load_batch_csv,
        inputs=batch_csv,
        outputs=[
            batch_preview,
            batch_rows_state,
            batch_status,
            batch_generate_button,
            batch_download,
            batch_review_selector,
            batch_review_panel,
            batch_session_state,
            batch_voice_context_state,
        ],
    )
    batch_generate_button.click(
        fn=generate_batch,
        # The live table value, including unsaved cell edits, is authoritative.
        inputs=[batch_voice_selector, batch_preview],
        outputs=[
            batch_preview,
            batch_status,
            batch_download,
            batch_rows_state,
            batch_review_selector,
            batch_review_panel,
            batch_review_filename,
            batch_review_dialogue,
            batch_review_audio,
            batch_review_status,
            batch_review_message,
            batch_session_state,
            batch_voice_context_state,
        ],
    )
    batch_review_selector.change(
        fn=select_batch_line,
        inputs=[
            batch_review_selector,
            batch_rows_state,
            batch_session_state,
        ],
        outputs=[
            batch_review_panel,
            batch_review_filename,
            batch_review_dialogue,
            batch_review_audio,
            batch_review_status,
            batch_review_message,
        ],
    )
    regenerate_batch_line_button.click(
        fn=regenerate_batch_line,
        inputs=[
            batch_review_selector,
            batch_review_dialogue,
            batch_rows_state,
            batch_session_state,
            batch_voice_context_state,
        ],
        outputs=[
            batch_preview,
            batch_rows_state,
            batch_review_selector,
            batch_review_dialogue,
            batch_review_audio,
            batch_review_status,
            batch_review_message,
            batch_status,
            batch_download,
            batch_voice_context_state,
        ],
    )

    voice_source.change(
        fn=switch_voice_source,
        inputs=voice_source,
        outputs=[
            create_from_sample_panel,
            design_voice_panel,
            random_voice_panel,
            voice_library_panel,
            batch_generation_panel,
            single_generation_panel,
            dialogue,
            output_audio,
            generate_button,
            try_another_button,
            save_voice_for_reuse_button,
            save_voice_panel,
            save_voice_confirmation,
            reusable_voice_state,
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
            reusable_voice_state,
        ],
    )
    reference_transcript.change(
        fn=clear_sample_save_state,
        outputs=[
            save_voice_for_reuse_button,
            save_voice_panel,
            save_voice_confirmation,
            reusable_voice_state,
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
            batch_voice_selector,
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

    generation_inputs = [
        voice_source,
        user_voice_selector,
        reference_audio,
        reference_transcript,
        dialogue,
        design_gender,
        design_age,
        design_pitch,
        design_style,
        design_accent,
    ]
    generation_outputs = [
        output_audio,
        download_generated_audio,
        reusable_voice_state,
        save_voice_for_reuse_button,
        save_voice_panel,
        save_voice_confirmation,
        try_another_button,
    ]
    generate_button.click(
        fn=generate_voice,
        inputs=generation_inputs,
        outputs=generation_outputs,
    )
    try_another_button.click(
        fn=generate_voice,
        inputs=generation_inputs,
        outputs=generation_outputs,
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
        inputs=[voice_name, reusable_voice_state],
        outputs=[
            user_voice_selector,
            batch_voice_selector,
            no_user_voices,
            voice_name,
            save_voice_panel,
            save_voice_for_reuse_button,
            save_voice_confirmation,
            reusable_voice_state,
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
    demo.queue(default_concurrency_limit=1).launch(css=BATCH_TABLE_CSS)
