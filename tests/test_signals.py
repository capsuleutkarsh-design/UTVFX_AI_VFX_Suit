import sys
import os
import unittest
from PySide6.QtWidgets import QApplication

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utvfx.ui.panels.properties_panel import PropertiesPanel
from utvfx.core.execution_engine import ExecutionEngine

class MockNode:
    def __init__(self):
        self.node_id = '123'
        self.plugin_type = 'media_plate'
        self.name = 'Media Plate'

class MockScene:
    def __init__(self):
        self.nodes = [MockNode()]
        self.connections = []

class TestSignals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from utvfx.core.plugin_manager import PluginManager
        PluginManager() # Initialize registry
        
        self.scene = MockScene()
        self.engine = ExecutionEngine(self.scene)
        self.panel = PropertiesPanel()
        self.panel.set_node(self.scene.nodes[0])
        
        self.engine.log_message.connect(self.panel.append_console_log)
        self.panel.execute_node_requested.connect(self.engine.execute_node)

    def test_execute_node_logs_to_console(self):
        initial_text = self.panel.console_widget.toPlainText()
        self.assertEqual(initial_text, "")
        
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        
        # Connect to finished or error signal to exit loop
        self.engine.node_execution_finished.connect(loop.quit)
        
        # Add a timeout just in case
        QTimer.singleShot(2000, loop.quit)
        
        self.panel._on_execute_clicked()
        loop.exec()
        
        after_text = self.panel.console_widget.toPlainText()
        self.assertNotEqual(initial_text, after_text)
        self.assertIn("Media Plate has no valid file selected.", after_text)

if __name__ == "__main__":
    unittest.main()
