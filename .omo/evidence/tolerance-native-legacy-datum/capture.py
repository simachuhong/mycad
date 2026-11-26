import os
from pathlib import Path
from PySide6.QtWidgets import QApplication
from mycad import app
from mycad.core.drawing_text import TextStyle, TextStyleTable
from mycad.core.geometric_tolerance import DatumIdentifier
from mycad.formats.dxf_datum import datum_box_dimensions
from mycad.formats.dxf_preview import prepare_dxf_output_preview
from mycad.ui.main_window import MainWindow

qt = QApplication([])
services = app.build_app(discoverers=())
window = MainWindow(services=services)
window.resize(1400, 900)
window.show()
window.act_new_drawing.trigger()
qt.processEvents()
editor, loaded = window.active_sketch_dialog(), window.loaded_document()
assert editor is not None and loaded is not None
style = TextStyle('wide', '宽字', font_family='DejaVu Sans', height_mm=5.5, width_factor=1.8)
loaded.bus.execute('drawing.text_styles.set', TextStyleTable((TextStyle(), style)).to_mapping(), 'local')
datum = DatumIdentifier('d' * 32, 'B8', (10, 10), (55, 0), text_style_id='wide')
loaded.bus.execute('drawing.tolerance.batch', {'add_datums': [datum.to_mapping()]}, 'local')
window._sync_drawing_layers()
editor.canvas.fit_view()
qt.processEvents()
folder = Path(__file__).parent
assert editor.canvas.grab().save(str(folder / 'canvas.png'))
tools = editor.canvas.geometric_tolerance_tools
assert tools is not None
preview = prepare_dxf_output_preview(services.kernel, legacy_datum_snapshots=tools.legacy_datum_export_snapshots((datum,)))
preview.write(folder / 'after.dxf')
print(preview.report.warnings, flush=True)
os._exit(0)
