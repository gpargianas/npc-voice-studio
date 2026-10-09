from dataclasses import dataclass
from pathlib import Path
import re
import shutil


class VoiceProfileError(ValueError):
    """Raised when a voice profile cannot be created or loaded."""


@dataclass(frozen=True)
class VoiceProfile:
    name: str
    reference_audio_path: Path
    transcript: str


class VoiceProfileManager:
    """Store reusable voice references as ordinary folders and files."""

    _RESERVED_WINDOWS_NAMES = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }

    def __init__(self, profiles_directory: str | Path) -> None:
        self.profiles_directory = Path(profiles_directory).resolve()
        # Profile data is runtime state, so the directory is not tracked in Git.
        self.profiles_directory.mkdir(parents=True, exist_ok=True)

    def create_profile(
        self,
        name: str,
        reference_audio_path: str | Path,
        transcript: str,
    ) -> VoiceProfile:
        safe_name = self._sanitize_name(name)
        if not reference_audio_path:
            raise VoiceProfileError("Reference audio is required.")
        source_audio = Path(reference_audio_path).expanduser()

        if not source_audio.is_file():
            raise VoiceProfileError("Reference audio file does not exist.")
        if not isinstance(transcript, str) or not transcript.strip():
            raise VoiceProfileError("Reference transcript is required.")

        suffix = source_audio.suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            raise VoiceProfileError("Reference audio must have a valid file extension.")

        profile_directory = self._profile_directory(safe_name)
        if profile_directory.exists():
            raise VoiceProfileError(f'Voice profile "{safe_name}" already exists.')

        reference_audio = profile_directory / f"reference{suffix}"
        transcript_path = profile_directory / "transcript.txt"

        try:
            profile_directory.mkdir()
            # Preserve the uploaded audio bytes; F5-TTS handles preprocessing later.
            shutil.copy2(source_audio, reference_audio)
            transcript_path.write_text(transcript, encoding="utf-8")
        except FileExistsError as exc:
            raise VoiceProfileError(
                f'Voice profile "{safe_name}" already exists.'
            ) from exc
        except OSError as exc:
            if profile_directory.exists():
                shutil.rmtree(profile_directory, ignore_errors=True)
            raise VoiceProfileError("Could not save the voice profile.") from exc

        return VoiceProfile(safe_name, reference_audio, transcript)

    def get_profile(self, name: str) -> VoiceProfile:
        safe_name = self._sanitize_name(name)
        if safe_name != name:
            raise VoiceProfileError("Invalid voice profile name.")

        profile_directory = self._profile_directory(safe_name)
        if not profile_directory.is_dir():
            raise VoiceProfileError(f'Voice profile "{safe_name}" was not found.')

        transcript_path = profile_directory / "transcript.txt"
        audio_files = sorted(
            path
            for path in profile_directory.glob("reference.*")
            if path.is_file()
        )
        if len(audio_files) != 1 or not transcript_path.is_file():
            raise VoiceProfileError(f'Voice profile "{safe_name}" is incomplete.')

        try:
            transcript = transcript_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise VoiceProfileError(
                f'Could not read voice profile "{safe_name}".'
            ) from exc

        if not transcript.strip():
            raise VoiceProfileError(f'Voice profile "{safe_name}" has no transcript.')

        return VoiceProfile(safe_name, audio_files[0], transcript)

    def list_profiles(self) -> list[str]:
        profiles: list[str] = []
        for path in self.profiles_directory.iterdir():
            if not path.is_dir():
                continue
            try:
                self.get_profile(path.name)
            except VoiceProfileError:
                continue
            profiles.append(path.name)

        return sorted(profiles, key=str.casefold)

    def delete_profile(self, name: str) -> None:
        """Delete one validated profile directory from the user storage root."""
        safe_name = self._sanitize_name(name)
        if safe_name != name:
            raise VoiceProfileError("Invalid voice profile name.")

        # Validate the complete profile and its contained path before deletion.
        self.get_profile(safe_name)
        profile_directory = self._profile_directory(safe_name)

        try:
            shutil.rmtree(profile_directory)
        except OSError as exc:
            raise VoiceProfileError(
                f'Could not delete voice profile "{safe_name}".'
            ) from exc

    @classmethod
    def _sanitize_name(cls, name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise VoiceProfileError("Profile name is required.")

        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
        safe_name = safe_name.strip("._-")
        if not safe_name:
            raise VoiceProfileError("Profile name must contain letters or numbers.")
        if len(safe_name) > 80:
            raise VoiceProfileError("Profile name must be 80 characters or fewer.")
        if safe_name.upper() in cls._RESERVED_WINDOWS_NAMES:
            raise VoiceProfileError("That profile name is reserved by Windows.")

        return safe_name

    def _profile_directory(self, safe_name: str) -> Path:
        profile_directory = (self.profiles_directory / safe_name).resolve()
        # Defense in depth: every profile must remain directly under the root.
        if profile_directory.parent != self.profiles_directory:
            raise VoiceProfileError("Invalid voice profile path.")
        return profile_directory
