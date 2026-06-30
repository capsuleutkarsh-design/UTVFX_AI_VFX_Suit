import sys
import os
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import VFXCoreWindow

class TestScreenshot(unittest.TestCase):
    def test_take_screenshot(self):
        app = QApplication.instance() or QApplication(sys.argv)
        window = VFXCoreWindow()
        window.show()
        
        def take_screenshot():
            pixmap = window.grab()
            pixmap.save(os.path.join(os.path.dirname(__file__), "screenshot.png"))
            app.quit()
            
        QTimer.singleShot(1000, take_screenshot)
        app.exec()
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(__file__), "screenshot.png")))

if __name__ == "__main__":
    unittest.main()
