import os
from dataclasses import replace
import math
from pathlib import Path
from PySide6.QtWidgets import QApplication
from mycad import app
from mycad.core.geometric_tolerance import DatumReference, FeatureControlFrame, ToleranceRow
from mycad.core.drawing_text import TextStyle, TextStyleTable
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
style = TextStyle('wide', '宽字', height_mm=5.5, width_factor=1.8)
loaded.bus.execute('drawing.text_styles.set', TextStyleTable((TextStyle(), style)).to_mapping(), 'local')
window._sync_drawing_layers()
frame = FeatureControlFrame('c' * 32, (ToleranceRow('position', 0.1, 2, True, 'M', (DatumReference('A基准'),)), ToleranceRow('flatness', 0.02, 2)), (10, 10), rotation_deg=37, text_style_id='wide', leader_target_mm=(150, 70))
width = tools._layout(frame).bounds.width()
angle = math.radians(37)
frame = replace(frame, leader_anchor_offset=(width * math.cos(angle) + 4.714285714 * math.sin(angle), width * math.sin(angle) - 4.714285714 * math.cos(angle)))
loaded.bus.execute('drawing.tolerance.batch', {'add_frames': [frame.to_mapping()]}, 'local')
window._sync_drawing_layers()
editor.canvas.fit_view()
qt.processEvents()
folder = Path(__file__).parent
assert editor.canvas.grab().save(str(folder / 'canvas.png'))
preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True, graphic_frame_widths=tools.graphic_frame_export_widths((frame,)), graphic_frame_glyphs=tools.graphic_frame_export_glyphs((frame,)))
preview.write(folder / 'graphic.dxf')
print('frame_width', width, 'warnings', preview.report.warnings, flush=True)
os._exit(0)
