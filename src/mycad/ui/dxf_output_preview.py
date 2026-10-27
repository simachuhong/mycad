# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Read-only, zoomable preview of the actual prepared DXF output."""

from __future__ import annotations

from typing import override

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QPainter, QResizeEvent, QWheelEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad.formats.dxf_preview import DxfOutputPreview


class _OutputView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget) -> None:
        super().__init__(scene, parent)
        self._zoom_steps = 0
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def fit_output(self) -> None:
        self._zoom_steps = 0
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, steps: int) -> None:
        proposed = max(-12, min(24, self._zoom_steps + steps))
        self.scale(1.25 ** (proposed - self._zoom_steps), 1.25 ** (proposed - self._zoom_steps))
        self._zoom_steps = proposed

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y():
            self.zoom(1 if event.angleDelta().y() > 0 else -1)
        event.accept()

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._zoom_steps == 0:
            self.fit_output()


class DxfOutputPreviewDialog(QDialog):
    """Only acceptance authorizes the caller to write its prepared payload."""

    def __init__(
        self, preview: DxfOutputPreview, filename: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"DXF 输出预览 — {filename}")
        self.resize(980, 720)
        self.renderer = QSvgRenderer(QByteArray(preview.svg_bytes), self)
        if not self.renderer.isValid():
            raise ValueError("无法显示 DXF 输出预览，请重新生成。")
        root = QVBoxLayout(self)
        instructions = QLabel(
            "核对图元、尺寸文字/箭头及图层显示后导出。滚轮缩放，拖动平移。\n"
            "当前按窗口适配显示，DXF 长度单位为 mm；显示缩放不会改变输出尺寸。\n"
            "字体按本机可用字形显示，目标 CAD 中的字体和布局仍需核对。"
        )
        instructions.setWordWrap(True)
        root.addWidget(instructions)
        scene = QGraphicsScene(self)
        item = QGraphicsSvgItem()
        item.setSharedRenderer(self.renderer)
        scene.addItem(item)
        scene.setSceneRect(item.boundingRect())
        self.view = _OutputView(scene, self)
        root.addWidget(self.view, 1)
        self.report_label = QLabel("\n".join((str(preview.report), *preview.notices)))
        self.report_label.setWordWrap(True)
        self.report_label.setTextFormat(Qt.TextFormat.PlainText)
        self.report_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.report_label)
        actions = QHBoxLayout()
        self.zoom_in_button = QPushButton("放大")
        self.zoom_out_button = QPushButton("缩小")
        self.fit_button = QPushButton("适合窗口")
        self.export_button = QPushButton("确认导出")
        self.cancel_button = QPushButton("取消")
        for button in (self.zoom_in_button, self.zoom_out_button, self.fit_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.export_button)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)
        self.zoom_in_button.clicked.connect(lambda: self.view.zoom(1))
        self.zoom_out_button.clicked.connect(lambda: self.view.zoom(-1))
        self.fit_button.clicked.connect(self.view.fit_output)
        self.export_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setDefault(True)
