# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Formal shared ``$defs`` table for the eight built-in commands (T7a).

``COMMAND_SCHEMA_DEFS`` contains the shared definitions from plan Appendix
A.0 (#round9-7) plus anchor-aware interactive selector variants. Every
built-in command schema references shared objects through
``{"$ref": "#/$defs/<Name>"}`` where a reusable definition applies, and the
T3 validator receives this table via ``CommandRegistry(schema_defs=...)`` at
the composition root. The T7a test suite AST-guards that no second
``COMMAND_SCHEMA_DEFS`` assignment exists anywhere under ``src/``.

Transcription notes (T7a deviations vs. raw A.0 text):

* ``description`` / ``const`` / ``default`` are kept verbatim — the T3
  validator's fixed keyword set explicitly supports all three (A0 recon).
* ``Profile``'s ``radius`` / ``width`` / ``height`` use ``$ref Positive``
  where A.0 spells the positive-number constraint inline — semantically
  identical, mandated by the no-copy rule (deviation D2).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["COMMAND_SCHEMA_DEFS"]

#: Appendix A.0 shared definitions plus anchor-aware interactive selectors.
COMMAND_SCHEMA_DEFS: Mapping[str, Any] = {
    "BodySelector": {
        "type": "object",
        "required": ["volume_mm3", "center_mm", "bounds_mm"],
        "additionalProperties": False,
        "properties": {
            "volume_mm3": {"type": "number", "exclusiveMinimum": 0.0},
            "center_mm": {"$ref": "#/$defs/Center3"},
            "bounds_mm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 6,
                "maxItems": 6,
            },
            "rank": {"type": "integer", "minimum": 0},
        },
        "description": "几何体积/质心/包围框锚点；重复匹配时用 rank 区分，不保存临时 BodyId。",
    },
    "BodyTransform": {
        "oneOf": [
            {
                "type": "object",
                "required": ["operation", "translation_mm"],
                "properties": {
                    "operation": {"const": "move"},
                    "translation_mm": {"$ref": "#/$defs/Center3"},
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["operation", "translation_mm"],
                "properties": {
                    "operation": {"const": "copy"},
                    "translation_mm": {"$ref": "#/$defs/Center3"},
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["operation", "axis_unit", "center_mm", "angle_deg"],
                "properties": {
                    "operation": {"const": "rotate"},
                    "axis_unit": {"$ref": "#/$defs/Center3"},
                    "center_mm": {"$ref": "#/$defs/Center3"},
                    "angle_deg": {"type": "number"},
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["operation", "plane_normal_unit", "plane_origin_mm"],
                "properties": {
                    "operation": {"const": "mirror"},
                    "plane_normal_unit": {"$ref": "#/$defs/Center3"},
                    "plane_origin_mm": {"$ref": "#/$defs/Center3"},
                },
                "additionalProperties": False,
            },
        ],
        "description": "移动/旋转/镜像替换所选实体；复制保留原实体并按位移创建副本。",
    },
    "BodyPattern": {
        "oneOf": [
            {
                "type": "object",
                "required": ["kind", "count", "spacing_mm"],
                "properties": {
                    "kind": {"const": "linear"},
                    "count": {"type": "integer", "minimum": 2, "maximum": 64},
                    "spacing_mm": {"$ref": "#/$defs/Center3"},
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["kind", "count", "axis_unit", "center_mm", "angle_deg"],
                "properties": {
                    "kind": {"const": "circular"},
                    "count": {"type": "integer", "minimum": 2, "maximum": 64},
                    "axis_unit": {"$ref": "#/$defs/Center3"},
                    "center_mm": {"$ref": "#/$defs/Center3"},
                    "angle_deg": {
                        "type": "number",
                        "exclusiveMinimum": 0.0,
                        "maximum": 360.0,
                    },
                },
                "additionalProperties": False,
            },
        ],
        "description": "count 包含种子；完整 360° 不重复末端实例，部分角度包含两端。",
    },
    "ExtrudeProfile": {
        "oneOf": [
            {"$ref": "#/$defs/Profile"},
            {
                "type": "object",
                "required": ["type", "target_face"],
                "additionalProperties": False,
                "properties": {
                    "type": {"const": "face"},
                    "target_face": {
                        "oneOf": [
                            {"$ref": "#/$defs/FaceSelector"},
                            {"$ref": "#/$defs/InteractiveFaceSelector"},
                        ]
                    },
                },
                "description": "模型平面的完整边界（含内环），沿外法向拉伸；不构造替代圆形。",
            },
        ]
    },
    "SketchProfileReference": {
        "type": "object",
        "required": ["type", "sketch_id"],
        "additionalProperties": False,
        "properties": {
            "type": {"const": "sketch"},
            "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
        },
        "description": ("引用命令历史中先前创建的闭合草图；草图尺寸变化后，重放会重新构建该特征。"),
    },
    "SketchExtrudeProfile": {
        "oneOf": [
            {"$ref": "#/$defs/ExtrudeProfile"},
            {"$ref": "#/$defs/SketchProfileReference"},
        ]
    },
    "SketchRevolveProfile": {
        "oneOf": [
            {"$ref": "#/$defs/Profile"},
            {"$ref": "#/$defs/SketchProfileReference"},
        ]
    },
    "SketchHole": {
        "type": "object",
        "required": ["profile", "target_face", "depth"],
        "additionalProperties": False,
        "properties": {
            "profile": {"$ref": "#/$defs/SketchProfileReference"},
            "target_face": {
                "oneOf": [
                    {"$ref": "#/$defs/FaceSelector"},
                    {"$ref": "#/$defs/InteractiveFaceSelector"},
                ]
            },
            "depth": {"$ref": "#/$defs/Depth"},
        },
        "description": ("草图中的非构造圆图元作为孔中心和直径；支撑面与草图平面必须重合。"),
    },
    "FaceSelector": {
        "oneOf": [
            {
                "type": "object",
                "required": ["surface", "axis"],
                "additionalProperties": False,
                "properties": {
                    "surface": {"const": "plane"},
                    "axis": {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]},
                    "rank": {"type": "integer", "minimum": 0},
                },
                "description": (
                    "平面分支：axis 必填且只允许六个带符号轴值（外法向方向）；"
                    "不允许空串/缺省（schema 层即拒绝，不等到 geom 执行）。rank 可选。"
                ),
            },
            {
                "type": "object",
                "required": ["surface"],
                "additionalProperties": False,
                "properties": {
                    "surface": {"const": "cylinder"},
                    "axis": {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z", ""]},
                    "rank": {"type": "integer", "minimum": 0},
                },
                "description": (
                    "圆柱面分支：axis 可缺省；缺键（经 normalize_params 将空串删除后）"
                    "=全部圆柱面，给带符号轴则按无向轴向匹配，+Z/-Z 等价。"
                    "wire 形态绝不写 null（#round9-3/#round10-NB1）。"
                ),
            },
        ],
        "description": (
            "解析语义（权威，见 T2 selectors.py）：plane 缺 axis 在 schema 校验期即 "
            "ValidationError（执行前校验契约）；过滤 surface→按 axis 匹配→候选按面积降序、"
            "等面积按面心(x,y,z)字典序升序全序排列；rank 给定时取第 rank 个"
            "（越界 TopologyReferenceError），省略时候选必须恰好 1 个面，"
            "0 或多个均 TopologyReferenceError(no-match/ambiguous)。禁止裸拓扑索引。"
        ),
    },
    "InteractiveFaceSelector": {
        "oneOf": [
            {
                "type": "object",
                "required": ["surface", "center_mm"],
                "additionalProperties": False,
                "properties": {
                    "surface": {"const": "plane"},
                    "axis": {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]},
                    "rank": {"type": "integer", "minimum": 0},
                    "center_mm": {"$ref": "#/$defs/Center3"},
                },
                "description": "鼠标选中的平面定位器：surface + 面心锚点。",
            },
            {
                "type": "object",
                "required": ["surface", "center_mm"],
                "additionalProperties": False,
                "properties": {
                    "surface": {"const": "cylinder"},
                    "axis": {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z", ""]},
                    "rank": {"type": "integer", "minimum": 0},
                    "center_mm": {"$ref": "#/$defs/Center3"},
                    "radius_mm": {"type": "number", "exclusiveMinimum": 0.0},
                },
                "description": "鼠标选中的圆柱面定位器：面心与半径锚点。",
            },
        ],
        "description": "运行时拓扑身份转换成可重放的几何锚点，不保存临时拓扑 ID。",
    },
    "PlanarFaceSelector": {
        "oneOf": [
            {
                "type": "object",
                "required": ["surface", "axis"],
                "additionalProperties": False,
                "properties": {
                    "surface": {"const": "plane"},
                    "axis": {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]},
                    "rank": {"type": "integer", "minimum": 0},
                },
            },
            {
                "type": "object",
                "required": ["surface", "center_mm"],
                "additionalProperties": False,
                "properties": {
                    "surface": {"const": "plane"},
                    "axis": {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]},
                    "rank": {"type": "integer", "minimum": 0},
                    "center_mm": {"$ref": "#/$defs/Center3"},
                },
            },
        ],
        "description": "到面终止只接受稳定或鼠标选择得到的平面面定位器。",
    },
    "EdgeSelector": {
        "type": "object",
        "required": ["parent_faces"],
        "additionalProperties": False,
        "properties": {
            "parent_faces": {
                "type": "array",
                "items": {"$ref": "#/$defs/FaceSelector"},
                "minItems": 1,
            },
            "curve": {"type": "string", "enum": ["line", "circle", ""]},
        },
    },
    "InteractiveEdgeSelector": {
        "type": "object",
        "required": ["parent_faces", "center_mm"],
        "additionalProperties": False,
        "properties": {
            "parent_faces": {
                "type": "array",
                "items": {"$ref": "#/$defs/InteractiveFaceSelector"},
                "minItems": 1,
            },
            "curve": {"type": "string", "enum": ["line", "circle"]},
            "center_mm": {"$ref": "#/$defs/Center3"},
            "radius_mm": {"type": "number", "exclusiveMinimum": 0.0},
        },
        "description": "鼠标选中的边定位器：相邻面 + 曲线类型 + 边心锚点。",
    },
    "Position": {
        "default": {"kind": "center"},
        "oneOf": [
            {
                "type": "object",
                "properties": {"kind": {"const": "center"}},
                "required": ["kind"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "point"},
                    "point": {"$ref": "#/$defs/Center3"},
                },
                "required": ["kind", "point"],
                "additionalProperties": False,
            },
        ],
        "description": "面心或所选平面上的世界坐标点（mm）；点位随命令存档并重放。",
    },
    "Depth": {
        "oneOf": [
            {
                "type": "object",
                "properties": {"kind": {"const": "through_all"}},
                "required": ["kind"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "blind"},
                    "value": {"type": "number", "exclusiveMinimum": 0.0},
                },
                "required": ["kind", "value"],
                "additionalProperties": False,
            },
        ]
    },
    "Pattern": {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "polar"},
                    "radius": {"type": "number", "exclusiveMinimum": 0.0},
                    "count": {"type": "integer", "minimum": 2, "maximum": 64},
                    "start_angle_deg": {"type": "number", "default": 0.0},
                },
                "required": ["kind", "radius", "count"],
                "additionalProperties": False,
            }
        ],
        "description": (
            "v1 仅 polar；kind=linear 必须 ValidationError（未实现，不静默接受）。"
            "start_angle_deg=0 对应全局 +X 轴，正向为从 +X 朝 +Y（自 +Z 俯视逆时针），"
            "角度定义在全局 XY 平面。阶段 0 限制：base_hole.target_face 必须解析为"
            "外法向平行全局 Z 的水平面（+Z/-Z，|n·ẑ|≥1−1e-9），否则 geom 执行时固定抛 "
            "TopologyReferenceError(reason='pattern-target-not-horizontal')；"
            "一般斜面局部坐标系（+X 在面内投影、退化用 +Y）为阶段 1 演进口。"
        ),
    },
    "Profile": {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "type": {"const": "circle"},
                    "radius": {"$ref": "#/$defs/Positive"},
                    "center": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                        "default": [0.0, 0.0],
                    },
                },
                "required": ["type", "radius"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"const": "rect"},
                    "width": {"$ref": "#/$defs/Positive"},
                    "height": {"$ref": "#/$defs/Positive"},
                    "center": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                        "default": [0.0, 0.0],
                    },
                },
                "required": ["type", "width", "height"],
                "additionalProperties": False,
            },
        ],
        "description": "截面位于 XY 工作平面 z=0。",
    },
    "Mode": {"type": "string", "enum": ["new", "add", "cut"], "default": "new"},
    "Center3": {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
        "default": [0.0, 0.0, 0.0],
    },
    "Positive": {"type": "number", "exclusiveMinimum": 0.0},
    "Tool": {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "type": {"const": "box"},
                    "size_x": {"$ref": "#/$defs/Positive"},
                    "size_y": {"$ref": "#/$defs/Positive"},
                    "size_z": {"$ref": "#/$defs/Positive"},
                    "center": {"$ref": "#/$defs/Center3"},
                },
                "required": ["type", "size_x", "size_y", "size_z"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"const": "cylinder"},
                    "radius": {"$ref": "#/$defs/Positive"},
                    "height": {"$ref": "#/$defs/Positive"},
                    "center": {"$ref": "#/$defs/Center3"},
                },
                "required": ["type", "radius", "height"],
                "additionalProperties": False,
            },
        ],
        "description": "modify.boolean_cut/boolean_intersect 共享；内联盒/圆柱工具体，v1 不支持具名引用。",
    },
    "Hole": {
        "type": "object",
        "required": ["target_face", "position", "diameter", "depth"],
        "additionalProperties": False,
        "properties": {
            "target_face": {
                "oneOf": [
                    {"$ref": "#/$defs/FaceSelector"},
                    {"$ref": "#/$defs/InteractiveFaceSelector"},
                ]
            },
            "position": {"$ref": "#/$defs/Position"},
            "diameter": {"$ref": "#/$defs/Positive"},
            "depth": {"$ref": "#/$defs/Depth"},
        },
        "description": (
            "#round11-3：feature.hole 全部参数的共享定义；feature.hole 以根级 $ref 引用本定义，"
            "feature.hole_pattern.base_hole 以 $ref 复用——消除 T7 “禁止复制子结构”与 "
            "base_hole 字段集复用的矛盾；键序取本 properties 声明顺序 "
            "target_face/position/diameter/depth。"
        ),
    },
}
