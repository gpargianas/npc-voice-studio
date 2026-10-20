import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FILENAME = "npc_voice_studio.log"


def configure_logging(log_directory: str | Path) -> Path | None:
    """Add one small rotating application log, falling back to the console."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    log_path = Path(log_directory) / LOG_FILENAME
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not any(
            getattr(handler, "_npc_voice_studio_file", False)
            for handler in root_logger.handlers
        ):
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=2 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler._npc_voice_studio_file = True  # type: ignore[attr-defined]
            root_logger.addHandler(file_handler)
        return log_path
    except OSError:
        root_logger.exception("Application log file could not be created")
        return None
