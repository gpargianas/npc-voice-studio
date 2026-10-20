from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


APP_NAME = "NPC Voice Studio"
DATA_DIRECTORY_ENV = "NPC_VOICE_STUDIO_DATA_DIR"


@dataclass(frozen=True)
class AppPaths:
    """Central locations for mutable application data."""

    root: Path
    voice_profiles: Path
    generated_audio: Path
    logs: Path

    @property
    def gradio_allowed_paths(self) -> tuple[Path, Path]:
        """Runtime directories whose files the browser legitimately consumes."""
        return (self.generated_audio, self.voice_profiles)


def resolve_app_paths(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform_name: str | None = None,
) -> AppPaths:
    """Resolve per-user paths without tying the app to its install directory."""
    values = os.environ if environ is None else environ
    user_home = Path.home() if home is None else Path(home)
    platform = os.name if platform_name is None else platform_name

    override = values.get(DATA_DIRECTORY_ENV)
    if override:
        root = Path(override).expanduser()
    elif platform == "nt":
        local_app_data = values.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else user_home / "AppData" / "Local"
        root = base / APP_NAME
    else:
        xdg_data_home = values.get("XDG_DATA_HOME")
        base = Path(xdg_data_home) if xdg_data_home else user_home / ".local" / "share"
        root = base / "npc-voice-studio"

    root = root.resolve()
    return AppPaths(
        root=root,
        voice_profiles=root / "voice_profiles",
        generated_audio=root / "generated_audio",
        logs=root / "logs",
    )


APP_PATHS = resolve_app_paths()
