import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from PySide6.QtWidgets import QApplication
from astroview.app.main_window import MainWindow

app = QApplication(sys.argv)
w = MainWindow()
w.initialize()
print("status bar:", w.statusBar())
print("app_status_bar:", w.app_status_bar)
print("visible:", w.app_status_bar.isVisible() if w.app_status_bar else "N/A")
print("height:", w.app_status_bar.height() if w.app_status_bar else "N/A")
print("same?", w.statusBar() is w.app_status_bar)
w.show()
print("after show visible:", w.app_status_bar.isVisible())
print("statusBar visible:", w.statusBar().isVisible())
print("isSizeGripEnabled:", w.app_status_bar.isSizeGripEnabled())
print("children:", [c.objectName() for c in w.app_status_bar.children()])
app.processEvents()
print("after events visible:", w.app_status_bar.isVisible())
print("geometry:", w.app_status_bar.geometry())
