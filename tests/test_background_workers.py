from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from app.gui.workers import BackgroundRunnable, WorkerSignals, submit_background_task


class TestWorkerSignals:

    @classmethod
    def setup_class(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def test_signals_emit_on_success(self) -> None:
        results: list = []
        errors: list = []
        finished: list = []

        def work() -> object:
            return 42

        runnable = BackgroundRunnable("t1", "test", 1, work)
        runnable.signals.result.connect(lambda tid, tn, bid, r: results.append(r))
        runnable.signals.error.connect(lambda tid, tn, bid, e: errors.append(e))
        runnable.signals.finished.connect(lambda tid, tn, bid: finished.append(True))
        runnable.run()

        assert results == [42]
        assert errors == []
        assert finished == [True]

    def test_signals_emit_on_exception(self) -> None:
        results: list = []
        errors: list = []
        finished: list = []

        def work() -> object:
            raise ValueError("test error")

        runnable = BackgroundRunnable("t2", "test", 1, work)
        runnable.signals.result.connect(lambda tid, tn, bid, r: results.append(r))
        runnable.signals.error.connect(lambda tid, tn, bid, e: errors.append(e))
        runnable.signals.finished.connect(lambda tid, tn, bid: finished.append(True))
        runnable.run()

        assert results == []
        assert len(errors) == 1
        assert "test error" in errors[0]
        assert finished == [True]

    def test_finished_always_emits(self) -> None:
        finished_good: list = []
        finished_bad: list = []

        r1 = BackgroundRunnable("g", "good", None, lambda: "ok")
        r1.signals.finished.connect(lambda tid, tn, bid: finished_good.append(True))
        r1.run()
        assert finished_good == [True]

        r2 = BackgroundRunnable("b", "bad", None, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        r2.signals.finished.connect(lambda tid, tn, bid: finished_bad.append(True))
        r2.run()
        assert finished_bad == [True]

    def test_task_id_unique(self) -> None:
        h1 = submit_background_task(task_name="test", book_id=1, fn=lambda: None)
        h2 = submit_background_task(task_name="test", book_id=1, fn=lambda: None)
        assert h1.task_id != h2.task_id

    def test_no_parent_on_signals(self) -> None:
        signals = WorkerSignals()
        assert signals.parent() is None

    def test_runnable_is_qrunnable(self) -> None:
        r = BackgroundRunnable("x", "y", None, lambda: None)
        from PySide6.QtCore import QRunnable
        assert isinstance(r, QRunnable)
