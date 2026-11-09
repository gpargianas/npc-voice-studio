import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.app_paths import APP_PATHS
from src.model_setup import (
    ModelDownloadError,
    ModelValidationError,
    install_model,
    load_model_spec,
    model_cache_environment,
    model_ready_path,
    validate_model_cache,
    write_model_ready_marker,
)
from src.setup_progress import MODEL_DOWNLOAD_DETAIL, write_setup_progress


MODEL_MISSING_EXIT = 2
DOWNLOAD_FAILED_EXIT = 4
VALIDATION_FAILED_EXIT = 5

STATE_READY = "ready"
STATE_SETUP_REQUIRED = "setup_required"
STATE_DOWNLOAD_FAILED = "download_failed"
STATE_VALIDATION_FAILED = "validation_failed"
OBSOLETE_ACKNOWLEDGEMENT_FILENAME = "omnivoice_license_acknowledgement.json"


def _write_status(
    path: Path | None,
    message: str,
    percent: int,
    detail: str = "",
) -> None:
    write_setup_progress(path, message, percent, detail)


def _write_result(
    path: Path | None,
    state: str,
    message: str = "",
    snapshot: Path | None = None,
) -> None:
    """Publish explicit model state; the launcher never infers it from text."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "message": message,
        "snapshot_path": str(snapshot) if snapshot is not None else None,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the pinned OmniVoice model.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--install", action="store_true")
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--result-file", type=Path)
    return parser.parse_args()


def main() -> int:
    # uv/Hugging Face diagnostics and our own messages share one ordered stream
    # when the launcher redirects setup output to setup.log.
    sys.stderr = sys.stdout
    args = parse_args()
    spec = load_model_spec()
    APP_PATHS.models.mkdir(parents=True, exist_ok=True)
    os.environ.update(model_cache_environment(APP_PATHS.models))
    # Remove the obsolete per-revision acknowledgement left by pre-audit builds.
    (APP_PATHS.models / OBSOLETE_ACKNOWLEDGEMENT_FILENAME).unlink(missing_ok=True)

    if args.check:
        _write_status(args.status_file, "Checking OmniVoice model...", 72)
        try:
            snapshot = validate_model_cache(APP_PATHS.models, spec)
            write_model_ready_marker(APP_PATHS.models, spec, snapshot)
        except Exception as exc:
            model_ready_path(APP_PATHS.models).unlink(missing_ok=True)
            _write_result(args.result_file, STATE_SETUP_REQUIRED, str(exc))
            print(f"OmniVoice model is not ready: {exc}", file=sys.stderr)
            return MODEL_MISSING_EXIT
        _write_result(args.result_file, STATE_READY, snapshot=snapshot)
        print(f"OmniVoice model ready: {snapshot}")
        return 0

    _write_status(
        args.status_file,
        "Preparing OmniVoice model (~3.3 GB)...",
        75,
        MODEL_DOWNLOAD_DETAIL,
    )

    def report_download(current: int, total: int) -> None:
        ratio = 0.0 if total <= 0 else min(1.0, current / total)
        percent = 75 + round(ratio * 14)
        _write_status(
            args.status_file,
            "Downloading OmniVoice model (~3.3 GB)...",
            percent,
            f"Prepared {current} of {total} model files. {MODEL_DOWNLOAD_DETAIL}",
        )

    def report_verification() -> None:
        _write_status(args.status_file, "Verifying OmniVoice model...", 92)

    try:
        snapshot = install_model(
            APP_PATHS.models,
            spec,
            progress_callback=report_download,
            verification_callback=report_verification,
        )
    except ModelDownloadError as exc:
        model_ready_path(APP_PATHS.models).unlink(missing_ok=True)
        _write_result(args.result_file, STATE_DOWNLOAD_FAILED, str(exc))
        print(
            "OmniVoice model download failed. Existing valid cache files were "
            f"kept for retry. Details: {exc}",
            file=sys.stderr,
        )
        return DOWNLOAD_FAILED_EXIT
    except ModelValidationError as exc:
        model_ready_path(APP_PATHS.models).unlink(missing_ok=True)
        _write_result(args.result_file, STATE_VALIDATION_FAILED, str(exc))
        print(f"OmniVoice model validation failed: {exc}", file=sys.stderr)
        return VALIDATION_FAILED_EXIT
    except Exception as exc:
        model_ready_path(APP_PATHS.models).unlink(missing_ok=True)
        _write_result(args.result_file, STATE_DOWNLOAD_FAILED, str(exc))
        print(
            "OmniVoice model setup failed. Check the network connection and retry. "
            f"Details: {exc}",
            file=sys.stderr,
        )
        return DOWNLOAD_FAILED_EXIT

    _write_status(args.status_file, "OmniVoice model is ready.", 95)
    _write_result(args.result_file, STATE_READY, snapshot=snapshot)
    print(f"OmniVoice model ready: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
