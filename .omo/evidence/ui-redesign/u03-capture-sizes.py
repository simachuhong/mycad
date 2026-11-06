from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from mycad.app import build_app
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow

app = QApplication([])
window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
window.resize(1024, 768)
window.show()
entry = window.new_session_document('part')
values = [(1024, 768), (1366, 768), (1920, 1080)]
out = Path('/tmp/mycad-u03-captures')
out.mkdir(exist_ok=True)
def capture(index):
    width, height = values[index]
    window.resize(width, height)
    def save():
        print(width, height, window.width(), window.height(), window.grab().save(str(out / f'{width}x{height}.png')), flush=True)
        if index + 1 == len(values):
            entry.placeholder = True
            window.close()
            app.quit()
        else:
            capture(index + 1)
    QTimer.singleShot(600, save)
QTimer.singleShot(600, lambda: capture(0))
app.exec()
