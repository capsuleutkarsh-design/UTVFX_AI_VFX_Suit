import sys
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
app = QApplication(sys.argv)
window = QMainWindow()
window.setCentralWidget(QLabel("Hello World!"))
window.show()
sys.exit(app.exec())
