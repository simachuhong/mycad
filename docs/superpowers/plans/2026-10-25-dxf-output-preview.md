# DXF output preview implementation plan

Execute inline under existing P2 G authorization, using executing-plans and test-driven-development.

## Goal and design

P2-35 requires a checkable 2D output preview. Render the actual prepared DXF modelspace with the established ezdxf drawing/SVG backend, including its standard dimension blocks. Display a zoomable/pannable read-only Qt SVG preview, exchange report and explicit Export/Cancel controls. Export the exact prepared DXF bytes after confirmation, using an atomic replacement. Do not reconstruct a separate imitation drawing in Qt.

Keep renderer imports lazy and only add necessary rendering runtime dependencies to the desktop extra. Headless DXF export must continue working without the viewer dependencies. Preparation uses the existing serialized worker. Bind preview to session/document revision; stale results cannot export. Existing format-provider selection remains authoritative.

## Steps

- [x] Add immutable prepared-export DTO and rendering adapter; tests cover generated dimension graphics, hidden layers, warnings, exact bytes and atomic write failure.
- [x] Add Qt SVG preview dialog with fit/zoom/pan, report, Export/Cancel; test rendering validity and explicit acceptance.
- [x] Integrate built-in DXF export preparation through serialized worker; test cancellation, confirmation and stale source rejection without document writes.
- [x] Run scoped four gates, inspect rendered output, update P2-35 evidence and audit.

## Research

ezdxf official Drawing / Export Add-on documents `Frontend(RenderContext(doc), SVGBackend()).draw_layout(modelspace)` and `get_string(Page(...))`. Reuse the renderer for DIMENSION block decomposition, fonts, line styles and weights. Source: https://ezdxf.readthedocs.io/en/stable/addons/drawing.html

Prototype finding: installed ezdxf drawing frontend imports `PIL.Image`; current desktop environment lacks Pillow. Add its explicit desktop runtime requirement before integrating, keeping imports lazy so headless installation stays unchanged.
