"""Session logging and crash capture.

Logs go to <workspace>/logs, one file per session (the newest 20 are kept), so a
crash is recorded even before a project is named and switching projects does not
start a new log. Native crashes (Qt, CUDA) are written by faulthandler to the same
session's faults file. Unhandled Python errors, on any thread, are logged and shown
to the user with the path of the log.
"""
import faulthandler
import glob
import logging
import os
import sys
import threading
from datetime import datetime

from utvfx.core.settings_manager import SettingsManager

KEEP_SESSIONS = 20
_state = {"log_file": None, "fault_file": None, "installed": False}


class InterceptStream:
    """Tees print()/stderr into the log. Thread-safe: workers print from their own threads."""

    def __init__(self, original_stream, logger, level):
        self.original_stream = original_stream
        self.logger = logger
        self.level = level
        self.buffer = ""
        self._lock = threading.Lock()

    def write(self, message):
        if self.original_stream is not None:
            try:
                self.original_stream.write(message)
            except (OSError, ValueError):
                pass  # no console (pythonw / frozen exe)
        with self._lock:
            self.buffer += message
            if "\n" not in self.buffer:
                return
            *lines, self.buffer = self.buffer.split("\n")
        for line in lines:
            if line.strip():
                self.logger.log(self.level, line)

    def flush(self):
        if self.original_stream is not None:
            try:
                self.original_stream.flush()
            except (OSError, ValueError):
                pass
        with self._lock:
            rest, self.buffer = self.buffer, ""
        if rest.strip():
            self.logger.log(self.level, rest)

    def isatty(self):
        return False

    def fileno(self):
        return self.original_stream.fileno() if self.original_stream is not None else -1


def log_dir():
    return os.path.join(SettingsManager().workspace_dir, "logs")


def current_log_file():
    return _state["log_file"]


def _prune(folder):
    for pattern in ("session_*.log", "faults_*.log"):
        files = sorted(glob.glob(os.path.join(folder, pattern)))
        for old in files[:-KEEP_SESSIONS]:
            try:
                os.remove(old)
            except OSError:
                pass


def _show_crash_dialog(summary):
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None or threading.current_thread() is not threading.main_thread():
            return
        QMessageBox.critical(
            None, "Something went wrong",
            f"{summary}\n\nThe details are in the log:\n{_state['log_file']}\n\n"
            "Save your work: the app may be unstable until it is restarted.")
    except Exception:
        pass  # never let the crash handler crash


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("crash").critical("Unhandled error", exc_info=(exc_type, exc, tb))
    _show_crash_dialog(f"{exc_type.__name__}: {exc}")


def _thread_excepthook(args):
    logging.getLogger("crash").critical(
        "Unhandled error in thread %s", getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def setup_global_logger():
    """Start this session's log and install the crash handlers (safe to call again)."""
    if _state["installed"]:
        return
    folder = log_dir()
    os.makedirs(folder, exist_ok=True)
    _prune(folder)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _state["log_file"] = os.path.join(folder, f"session_{stamp}.log")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)
    file_handler = logging.FileHandler(_state["log_file"], encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"))
    root.addHandler(file_handler)
    for noisy in ("PIL", "matplotlib", "urllib3", "httpx", "filelock", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Native crashes (access violations in Qt or CUDA) bypass Python; faulthandler records them.
    _state["fault_file"] = open(os.path.join(folder, f"faults_{stamp}.log"), "w", encoding="utf-8")
    faulthandler.enable(file=_state["fault_file"], all_threads=True)

    if not isinstance(sys.stdout, InterceptStream):
        sys.stdout = InterceptStream(sys.stdout, root, logging.INFO)
    if not isinstance(sys.stderr, InterceptStream):
        sys.stderr = InterceptStream(sys.stderr, root, logging.ERROR)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    _state["installed"] = True

    from utvfx.version import APP_NAME, VERSION
    logging.info("%s %s started. Log: %s", APP_NAME, VERSION, _state["log_file"])


def update_logger_directory():
    """Project changes no longer move the session log; just note the switch."""
    if _state["installed"]:
        logging.info("Project: %s", SettingsManager().current_project_name)


def shutdown_logger():
    """Close the log files (e.g. before moving folders that might contain them)."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)
    if _state["fault_file"] is not None:
        faulthandler.disable()
        _state["fault_file"].close()
        _state["fault_file"] = None
    _state["installed"] = False
