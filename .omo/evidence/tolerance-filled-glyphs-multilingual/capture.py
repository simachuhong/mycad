import os
from dataclasses import replace
from pathlib import Path
from PySide6.QtWidgets import QApplication
from mycad import app
from mycad.core.geometric_tolerance import DatumReference, FeatureControlFrame, ToleranceRow
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
tools = editor.canvas.geometric_tolerance_tools
assert tools is not None
frame = FeatureControlFrame('c' * 32, (ToleranceRow('position', 0.1, 2, True, 'M', (DatumReference('A基准'),)),), (10, 10), leader_target_mm=(80, 7))
width = tools._layout(frame).bounds.width()
frame = replace(frame, leader_anchor_offset=(width, -3))
loaded.bus.execute('drawing.tolerance.batch', {'add_frames': [frame.to_mapping()]}, 'local')
window._sync_drawing_layers()
qt.processEvents()
folder = Path(__file__).parent
assert editor.canvas.grab().save(str(folder / 'canvas.png'))
preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True, graphic_frame_widths=tools.graphic_frame_export_widths((frame,)), graphic_frame_glyphs=tools.graphic_frame_export_glyphs((frame,)))
preview.write(folder / 'graphic.dxf')
print('frame_width', width, 'warnings', preview.report.warnings, flush=True)
os._exit(0)
