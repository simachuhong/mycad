# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""MyCAD desktop shell (``mycad gui``).

Phase-1 UI package: the five-zone main window and its panels live here.
Layering contract (tests/test_layering.py): this package must never import
``mycad.geom`` — panels drive the model only through the command bus and
the ``mycad.app`` composition root.
"""
