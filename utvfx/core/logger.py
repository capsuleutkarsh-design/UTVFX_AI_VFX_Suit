import os
import sys
import logging
from datetime import datetime
from utvfx.core.settings_manager import SettingsManager

class InterceptStream:
    def __init__(self, original_stream, logger, level):
        self.original_stream = original_stream
        self.logger = logger
        self.level = level
        self.buffer = ""

    def write(self, message):
        self.original_stream.write(message)
        self.buffer += message
        if "\n" in self.buffer:
            lines = self.buffer.split("\n")
            for line in lines[:-1]:
                if line.strip():
                    self.logger.log(self.level, line)
            self.buffer = lines[-1]

    def flush(self):
        self.original_stream.flush()
        if self.buffer.strip():
            self.logger.log(self.level, self.buffer)
            self.buffer = ""

def setup_global_logger():
    """Initializes the global logging system routed to the current project workspace."""
    log_dir = SettingsManager().get("log_dir")
    if not log_dir:
        return
        
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"session_{timestamp}.log")
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
        
    # File Handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Intercept stdout and stderr
    sys.stdout = InterceptStream(sys.stdout, root_logger, logging.INFO)
    sys.stderr = InterceptStream(sys.stderr, root_logger, logging.ERROR)
    
    logging.info(f"Global Logger Initialized. Project: {getattr(SettingsManager(), 'current_project_name', 'Untitled')}")
    
def update_logger_directory():
    """Called when the project changes to roll logs to the new directory."""
    setup_global_logger()

def shutdown_logger():
    """Closes all logger handlers."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
