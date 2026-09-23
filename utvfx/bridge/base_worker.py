from PySide6.QtCore import QThread, Signal
import traceback

class BaseWorker(QThread):
    """
    Base class for all plugin workers.
    Standardizes the QThread lifecycle, signal emission, and error handling.

    Every run ends with exactly one of finished_success, error_occurred or
    cancelled, so the engine can always clean up.
    """
    progress_update = Signal(str, int, int) # node_id, current, total
    log_message = Signal(str, str)          # node_id, message
    error_occurred = Signal(str, str)       # node_id, error_msg
    finished_success = Signal(str)          # node_id
    cancelled = Signal(str)                 # node_id

    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.params = params
        self.inputs = inputs
        self.cache_dir = cache_dir
        self.output_dir = output_dir
        # (first, last) timeline positions to render, inclusive, or None for the whole plate.
        self.frame_range = None

        self.is_cancelled = False

    def positions(self, total):
        """Timeline positions this run should process, honouring the In/Out range."""
        if not self.frame_range:
            return range(total)
        first, last = self.frame_range
        first = max(0, first if first is not None else 0)
        last = min(total - 1, last if last is not None else total - 1)
        return range(first, last + 1)

    def run(self):
        """
        The QThread execution wrapper. Do not override this method directly.
        Override `run_task()` instead.
        """
        try:
            self.run_task()
            if self.is_cancelled:
                self.cancelled.emit(self.node_id)
            else:
                self.finished_success.emit(self.node_id)
        except Exception as e:
            if self.is_cancelled:
                self.cancelled.emit(self.node_id)
                return
            error_msg = f"Worker failed: {str(e)}\n{traceback.format_exc()}"
            self.log_message.emit(self.node_id, error_msg)
            self.error_occurred.emit(self.node_id, str(e))

    def run_task(self):
        """
        Subclasses must implement this method to perform their actual work.
        Periodically check `self.is_cancelled` and return early if True.
        Iterate `self.positions(total)` so the In/Out range is honoured.
        Use `self.log_message.emit(self.node_id, msg)` for logging.
        Use `self.progress_update.emit(self.node_id, current, total)` for progress.
        """
        raise NotImplementedError("Subclasses must implement run_task()")

    def cancel(self):
        """
        Requests the worker to stop processing.
        Subclasses should respect self.is_cancelled.
        """
        self.is_cancelled = True
