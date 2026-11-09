"""Small, dependency-free setup progress protocol shared by bootstrap tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time


FIRST_RUN_DETAIL = (
    "This can take several minutes. NPC Voice Studio only needs to perform "
    "this full setup once."
)
MODEL_DOWNLOAD_DETAIL = (
    "This can take several minutes. This model only needs to be downloaded once."
)
_PROGRESS_WRITE_LOCK = threading.Lock()


def write_setup_progress(
    path: str | Path | None,
    operation: str,
    percent: int,
    detail: str = "",
) -> None:
    """Atomically publish one milestone for the Windows setup window."""
    if path is None:
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "operation": operation,
        "percent": max(0, min(100, int(percent))),
        "detail": detail,
    }
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    # Hugging Face may report transfers from several worker threads. Progress
    # is best effort and must never cause a model download to fail.
    with _PROGRESS_WRITE_LOCK:
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            for attempt in range(5):
                try:
                    os.replace(temporary, destination)
                    return
                except PermissionError:
                    if attempt == 4:
                        return
                    time.sleep(0.02)
        finally:
            temporary.unlink(missing_ok=True)
