from collections.abc import Callable
import logging
from threading import Lock
from typing import Any

from src.error_messages import model_load_error_message


logger = logging.getLogger(__name__)


class ModelUnavailableError(RuntimeError):
    """Raised when generation is requested without a loaded model."""


def _create_service() -> Any:
    # Import lazily so constructing the Gradio UI never initializes the model.
    from src.omnivoice_service import OmniVoiceService

    return OmniVoiceService()


class OmniVoiceRuntime:
    """Initialize one shared OmniVoice service and preserve load failures."""

    def __init__(self, factory: Callable[[], Any] | None = None) -> None:
        self._factory = factory or _create_service
        self._service: Any | None = None
        self._error_message: str | None = None
        self._attempted = False
        self._lock = Lock()

    @property
    def error_message(self) -> str | None:
        return self._error_message

    @property
    def attempted(self) -> bool:
        return self._attempted

    def initialize(self) -> Any | None:
        with self._lock:
            if self._attempted:
                return self._service
            self._attempted = True
            logger.info("Initializing OmniVoice")
            try:
                self._service = self._factory()
            except Exception as exc:
                self._error_message = model_load_error_message(exc)
                logger.exception("OmniVoice initialization failed")
                return None

            logger.info(
                "OmniVoice initialized successfully on %s",
                getattr(self._service, "device", "unknown device"),
            )
            return self._service

    def require(self) -> Any:
        service = self.initialize()
        if service is None:
            raise ModelUnavailableError(
                self._error_message
                or "OmniVoice is unavailable. See the application log for details."
            )
        return service
