from __future__ import annotations

import logging
import traceback
import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    started = Signal(str, str, object)
    result = Signal(str, str, object, object)
    error = Signal(str, str, object, str)
    finished = Signal(str, str, object)


class BackgroundRunnable(QRunnable):
    def __init__(
        self,
        task_id: str,
        task_name: str,
        book_id: int | None,
        fn: Callable[[], Any],
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.task_name = task_name
        self.book_id = book_id
        self.fn = fn
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.started.emit(self.task_id, self.task_name, self.book_id)
        logger.info(
            "Background task started id=%s name=%s book_id=%s",
            self.task_id, self.task_name, self.book_id,
        )
        try:
            result = self.fn()
            logger.info(
                "Background task finished id=%s name=%s book_id=%s",
                self.task_id, self.task_name, self.book_id,
            )
            self.signals.result.emit(self.task_id, self.task_name, self.book_id, result)
        except Exception:
            tb = traceback.format_exc()
            logger.error(
                "Background task failed id=%s name=%s book_id=%s\n%s",
                self.task_id, self.task_name, self.book_id, tb,
            )
            self.signals.error.emit(self.task_id, self.task_name, self.book_id, tb)
        finally:
            self.signals.finished.emit(self.task_id, self.task_name, self.book_id)


def submit_background_task(
    *,
    task_name: str,
    book_id: int | None,
    fn: Callable[[], Any],
    on_started: Callable[[str, str, object], None] | None = None,
    on_result: Callable[[str, str, object, object], None] | None = None,
    on_error: Callable[[str, str, object, str], None] | None = None,
    on_finished: Callable[[str, str, object], None] | None = None,
) -> BackgroundRunnable:
    task_id = f"{task_name}:{book_id}:{uuid.uuid4().hex[:8]}"
    runnable = BackgroundRunnable(task_id, task_name, book_id, fn)

    if on_started:
        runnable.signals.started.connect(on_started)
    if on_result:
        runnable.signals.result.connect(on_result)
    if on_error:
        runnable.signals.error.connect(on_error)
    if on_finished:
        runnable.signals.finished.connect(on_finished)

    logger.info(
        "Submitting background task id=%s name=%s book_id=%s",
        task_id, task_name, book_id,
    )
    QThreadPool.globalInstance().start(runnable)
    return runnable
