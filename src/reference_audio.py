from dataclasses import dataclass
from pathlib import Path

import soundfile as sf


RECOMMENDED_MAX_SECONDS = 10.0
MAX_REFERENCE_SECONDS = 15.0


class ReferenceAudioError(ValueError):
    """Raised when reference audio cannot be measured or exceeds the limit."""


@dataclass(frozen=True)
class ReferenceAudioAssessment:
    duration_seconds: float
    level: str
    message: str

    @property
    def blocked(self) -> bool:
        return self.level == "error"


def assess_reference_audio(audio_path: str | Path) -> ReferenceAudioAssessment:
    """Measure one cloning reference and classify its OmniVoice guidance."""
    if not audio_path:
        raise ReferenceAudioError("Reference audio is required.")

    path = Path(audio_path)
    if not path.is_file():
        raise ReferenceAudioError("Reference audio could not be found.")

    try:
        duration = float(sf.info(path).duration)
    except (RuntimeError, OSError, TypeError, ValueError) as exc:
        raise ReferenceAudioError(
            "Could not determine the reference audio duration."
        ) from exc

    if duration > MAX_REFERENCE_SECONDS:
        return ReferenceAudioAssessment(
            duration,
            "error",
            f"Reference too long ({duration:.1f} s). Please use a reference of "
            "15 seconds or less. For best results, OmniVoice recommends "
            "3-10 seconds.",
        )
    if duration > RECOMMENDED_MAX_SECONDS:
        return ReferenceAudioAssessment(
            duration,
            "warning",
            f"Long reference ({duration:.1f} s). OmniVoice recommends 3-10 "
            "seconds. Longer samples may reduce voice-cloning quality. For "
            "best results, use a clear 3-10 second sample with an accurate "
            "matching transcript.",
        )
    return ReferenceAudioAssessment(
        duration,
        "ok",
        f"Reference duration: {duration:.1f} s.",
    )
