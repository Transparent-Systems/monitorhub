"""
Base worker abstraction for stoppable background threads in monitorhub.
"""

import logging
import threading
from abc import ABC, abstractmethod


class StoppableWorker(ABC):
    """
    A standardized base class for stoppable background worker threads.

    Provides a unified lifecycle:
    - Thread creation and startup with idempotent start()
    - Clean shutdown via threading.Event and join() with configurable timeout
    - Extension hook _on_stop() for waking custom wait primitives (e.g. Conditions, queues)
    """

    def __init__(
        self,
        name: str | None = None,
        logger: logging.Logger | None = None,
    ):
        self.name = name or self.__class__.__name__
        self.logger = logger or logging.getLogger(__name__)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Returns True if the worker thread is started and alive."""
        return self.thread is not None and self.thread.is_alive()

    @property
    def is_stopped(self) -> bool:
        """Returns True if a stop has been requested."""
        return self.stop_event.is_set()

    def start(self) -> None:
        """Starts the worker thread if not already running."""
        if self.is_running:
            self.logger.debug(f"{self.name} is already running.")
            return

        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run_wrapper,
            name=self.name,
            daemon=True,
        )
        self.thread.start()
        self.logger.info(f"{self.name} started.")

    def stop(self, timeout: float = 2.0) -> None:
        """
        Signals the worker thread to stop, notifies any waiting primitives,
        and joins the thread.
        """
        self.stop_event.set()
        self._on_stop()

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)
            if self.thread.is_alive():
                self.logger.warning(
                    f"{self.name} thread did not terminate within {timeout}s timeout."
                )

        self.logger.info(f"{self.name} stopped.")

    def _on_stop(self) -> None:
        """
        Hook called immediately after stop_event.set().
        Subclasses can override to wake custom blocking mechanisms
        (such as threading.Condition, queue sentinels, or OS pipes).
        """

    def wait_stop(self, timeout: float | None = None) -> bool:
        """
        Waits for stop_event to be set or until timeout expires.

        :param timeout: Timeout in seconds, or None to wait indefinitely.
        :return: True if stop_event is set, False if timeout expired.
        """
        return self.stop_event.wait(timeout=timeout)

    def _run_wrapper(self) -> None:
        """Internal wrapper around run() to guarantee clean exit handling."""
        try:
            self.run()
        except Exception:
            self.logger.exception(f"Unhandled exception in {self.name} worker thread")

    @abstractmethod
    def run(self) -> None:
        """Main worker loop to be implemented by subclasses."""
