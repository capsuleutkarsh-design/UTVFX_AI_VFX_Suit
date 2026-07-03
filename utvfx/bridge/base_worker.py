from PySide6.QtCore import QThread, Signal
import traceback

class BaseWorker(QThread):
    """
    Abstract base class for all plugin workers in the UTVFX AI & VFX Suit.
    Standardizes the QThread lifecycle, signal emission, and error handling.
    """
    # Standardized signals for all workers
    progress_update = Signal(str, int, int) # node_id, current, total
    log_message = Signal(str, str)          # node_id, message
    error_occurred = Signal(str, str)       # node_id, error_msg
    finished_success = Signal(str)          # node_id

    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.params = params
        self.inputs = inputs
        self.cache_dir = cache_dir
        self.output_dir = output_dir
        
        self.is_cancelled = False

    def run(self):
        """
        The QThread execution wrapper. Do not override this method directly.
        Override `run_task()` instead.
        """
        try:
            self.run_task()
            if not self.is_cancelled:
                self.finished_success.emit(self.node_id)
        except Exception as e:
            error_msg = f"Worker failed: {str(e)}\n{traceback.format_exc()}"
            self.log_message.emit(self.node_id, error_msg)
            self.error_occurred.emit(self.node_id, str(e))

    def run_task(self):
        """
        Subclasses must implement this method to perform their actual work.
        Periodically check `self.is_cancelled` and return early if True.
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
