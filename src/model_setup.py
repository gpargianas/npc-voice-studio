from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, Callable


MODEL_READY_FILENAME = "omnivoice_ready.json"
MODEL_INCOMPLETE_MESSAGE = (
    "The OmniVoice model installation is incomplete. Restart NPC Voice Studio "
    "to repair/download the model."
)
REQUIRED_MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json")


@dataclass(frozen=True)
class ModelSpec:
    repository: str
    revision: str
    approximate_download_bytes: int
    license_identifier: str
    source_url: str
    model_card_url: str


class ModelDownloadError(RuntimeError):
    """The explicit online model download did not complete."""


class ModelValidationError(RuntimeError):
    """Downloaded model content did not pass pinned local validation."""


def load_model_spec(source_root: str | Path | None = None) -> ModelSpec:
    root = (
        Path(source_root)
        if source_root is not None
        else Path(__file__).resolve().parents[1]
    )
    manifest = json.loads(
        (root / "runtime_manifest.json").read_text(encoding="utf-8")
    )
    return ModelSpec(**manifest["model"])


def model_cache_environment(models_root: str | Path) -> dict[str, str]:
    root = Path(models_root)
    return {
        "HF_HOME": str(root),
        "HF_HUB_CACHE": str(root / "hub"),
        "HF_XET_CACHE": str(root / "xet"),
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }


def model_ready_path(models_root: str | Path) -> Path:
    return Path(models_root) / MODEL_READY_FILENAME


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _default_snapshot_download() -> Callable[..., str]:
    from huggingface_hub import snapshot_download

    return snapshot_download


def _model_download_tqdm(
    progress_callback: Callable[[int, int], None],
) -> type:
    """Adapt Hugging Face's supported snapshot progress hook for setup UI."""
    from tqdm.auto import tqdm

    class ModelDownloadProgress(tqdm):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._setup_completed = 0
            super().__init__(*args, **kwargs)

        def update(self, n: int | float = 1) -> bool | None:
            displayed = super().update(n)
            self._setup_completed += int(n)
            if self.total:
                progress_callback(
                    min(self._setup_completed, int(self.total)), int(self.total)
                )
            return displayed

    return ModelDownloadProgress


def _validate_snapshot_path(
    models_root: Path,
    snapshot: str | Path,
) -> Path:
    resolved_root = models_root.resolve()
    resolved_cache = (resolved_root / "hub").resolve()
    resolved_snapshot = Path(snapshot).resolve()
    if (
        resolved_snapshot == resolved_cache
        or resolved_cache not in resolved_snapshot.parents
    ):
        raise RuntimeError(MODEL_INCOMPLETE_MESSAGE)

    missing = [
        name
        for name in REQUIRED_MODEL_FILES
        if not (resolved_snapshot / name).is_file()
        or (resolved_snapshot / name).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError(MODEL_INCOMPLETE_MESSAGE)
    return resolved_snapshot


def resolve_installed_model(
    models_root: str | Path,
    spec: ModelSpec | None = None,
    snapshot_download: Callable[..., str] | None = None,
) -> Path:
    """Resolve only the exact model already installed in the app-owned cache."""
    root = Path(models_root)
    pinned = spec or load_model_spec()

    marker = _read_json(model_ready_path(root))
    if (
        marker
        and marker.get("model_repository") == pinned.repository
        and marker.get("model_revision") == pinned.revision
        and marker.get("snapshot_path")
    ):
        try:
            return _validate_snapshot_path(root, str(marker["snapshot_path"]))
        except (OSError, RuntimeError):
            # A stale marker may be repaired by an exact local cache lookup.
            pass

    downloader = snapshot_download or _default_snapshot_download()
    try:
        snapshot = downloader(
            repo_id=pinned.repository,
            revision=pinned.revision,
            cache_dir=str(root / "hub"),
            local_files_only=True,
        )
        return _validate_snapshot_path(root, snapshot)
    except Exception as exc:
        raise RuntimeError(MODEL_INCOMPLETE_MESSAGE) from exc


def validate_model_cache(
    models_root: str | Path,
    spec: ModelSpec,
    snapshot_download: Callable[..., str] | None = None,
) -> Path:
    """Validate the exact cached snapshot without contacting Hugging Face."""
    return resolve_installed_model(models_root, spec, snapshot_download)


def write_model_ready_marker(
    models_root: str | Path,
    spec: ModelSpec,
    snapshot: Path,
) -> Path:
    path = model_ready_path(models_root)
    _write_json_atomic(
        path,
        {
            "model_repository": spec.repository,
            "model_revision": spec.revision,
            "snapshot_path": str(snapshot),
            "verified_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    return path


def install_model(
    models_root: str | Path,
    spec: ModelSpec,
    snapshot_download: Callable[..., str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    verification_callback: Callable[[], None] | None = None,
) -> Path:
    """Download or resume the manifest-pinned model into the app cache."""
    root = Path(models_root)
    downloader = snapshot_download or _default_snapshot_download()
    # Hugging Face's content-addressed cache resumes partial downloads and reuses
    # valid blobs. Ordinary retries must not remove this directory.
    download_arguments: dict[str, Any] = {
        "repo_id": spec.repository,
        "revision": spec.revision,
        "cache_dir": str(root / "hub"),
        "local_files_only": False,
        "force_download": False,
    }
    if progress_callback is not None:
        # snapshot_download officially supports tqdm_class. This preserves its
        # content-addressed cache, retry, and resume behavior.
        download_arguments["tqdm_class"] = _model_download_tqdm(progress_callback)
    try:
        downloader(**download_arguments)
    except Exception as exc:
        raise ModelDownloadError(
            "The pinned OmniVoice model download did not complete."
        ) from exc
    if verification_callback is not None:
        verification_callback()
    try:
        snapshot = validate_model_cache(root, spec, downloader)
    except Exception as exc:
        raise ModelValidationError(
            "The downloaded OmniVoice model did not pass local validation."
        ) from exc
    write_model_ready_marker(root, spec, snapshot)
    return snapshot
