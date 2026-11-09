from __future__ import annotations

import errno


def _error_text(error: BaseException) -> str:
    messages: list[str] = []
    current: BaseException | None = error
    while current is not None:
        messages.append(str(current).lower())
        current = current.__cause__ or current.__context__
    return " ".join(messages)


def model_load_error_message(error: BaseException) -> str:
    """Return a concise startup message while logs retain the traceback."""
    message = _error_text(error)
    if "model installation is incomplete" in message:
        return (
            "The OmniVoice model installation is incomplete. Restart NPC Voice "
            "Studio to repair/download the model."
        )
    if "out of memory" in message or "cuda error: out of memory" in message:
        return "OmniVoice could not load because GPU memory is insufficient."
    if "cuda" in message or "cudnn" in message:
        return "OmniVoice could not load because CUDA or the GPU is unavailable."
    if any(
        marker in message
        for marker in ("connection", "offline", "timeout", "download", "huggingface")
    ):
        return (
            "OmniVoice could not load. Check the internet connection and model "
            "cache, then restart the application."
        )
    return "OmniVoice could not be initialized. See the application log for details."


def generation_error_message(error: BaseException) -> str:
    """Translate common inference and filesystem failures for the local UI."""
    message = _error_text(error)
    error_number = getattr(error, "errno", None)

    if "out of memory" in message or "cuda error: out of memory" in message:
        return (
            "The GPU ran out of memory while generating audio. Close other GPU "
            "applications and try a shorter dialogue."
        )
    if isinstance(error, PermissionError) or error_number in {errno.EACCES, errno.EPERM}:
        return (
            "NPC Voice Studio cannot write to its data directory. Check folder "
            "permissions and available disk space."
        )
    if "could not write generated audio" in message:
        return (
            "NPC Voice Studio cannot write to its data directory. Check folder "
            "permissions and available disk space."
        )
    if error_number == errno.ENOSPC or "no space left" in message or "disk full" in message:
        return "There is not enough free disk space to save the generated audio."
    if isinstance(error, FileNotFoundError):
        return (
            "A required reference audio file is missing. Reselect the audio or "
            "recreate the saved voice."
        )
    if any(
        marker in message
        for marker in (
            "libsndfile",
            "format not recognised",
            "unknown format",
            "error opening",
            "failed to load audio",
            "audioread",
        )
    ):
        return (
            "The reference audio could not be read. It may be corrupted or use "
            "an unsupported format."
        )
    return "Voice generation failed. See the application log for technical details."
