import sys
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
import unittest

class TestPySide(unittest.TestCase):
    def test_pyside_import(self):
        self.assertTrue(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setCentralWidget(QLabel("Hello World!"))
    window.show()
    sys.exit(app.exec())
