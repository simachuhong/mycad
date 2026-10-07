# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Double independent transcription check of the formal ``$defs`` table.

The expected literals below are handwritten from plan Appendix A.0 — they
are NOT imported from ``mycad.builtin_commands.defs`` nor reverse-derived
from it, so a transcription error on either side fails loudly.

Two realizations come from the T7a task spec rather than raw A.0 text:

* ``description`` / ``const`` / ``default`` are kept verbatim (the T3
  validator's fixed keyword set supports all three — A0 recon conclusion).
* ``Profile``'s ``radius`` / ``width`` / ``height`` reference
  ``#/$defs/Positive`` where A.0 spells the constraint inline
  (``{"type": "number", "exclusiveMinimum": 0.0}``) — semantically
  identical, mandated by the no-copy rule (deviation D2).
"""

from __future__ import annotations

from pathlib import Path

from mycad.builtin_commands.defs import COMMAND_SCHEMA_DEFS

REPO = Path(__file__).resolve().parents[2]

EXPECTED_DEF_NAMES: tuple[str, ...] = (
    "Center3",
    "Depth",
    "EdgeSelector",
    "FaceSelector",
    "Hole",
    "Mode",
    "Pattern",
    "Position",
    "Positive",
    "Profile",
    "Tool",
)

EXPECTED_FACE_SELECTOR: dict[str, object] = {
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
}

EXPECTED_DEPTH: dict[str, object] = {
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
    ],
}

EXPECTED_PATTERN: dict[str, object] = {
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
}

EXPECTED_PROFILE: dict[str, object] = {
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
}

EXPECTED_TOOL: dict[str, object] = {
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
    "description": "仅 modify.boolean_cut 使用；内联工具体，v1 不支持具名引用。",
}

EXPECTED_HOLE: dict[str, object] = {
    "type": "object",
    "required": ["target_face", "position", "diameter", "depth"],
    "additionalProperties": False,
    "properties": {
        "target_face": {"$ref": "#/$defs/FaceSelector"},
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
}

# ---------------------------------------------------------------------------
# key set + full-field equality (independent transcription)
# ---------------------------------------------------------------------------


def test_defs_key_set_is_exactly_the_eleven_names() -> None:
    assert sorted(COMMAND_SCHEMA_DEFS) == sorted(EXPECTED_DEF_NAMES)
    assert len(COMMAND_SCHEMA_DEFS) == 11


def test_face_selector_matches_independent_transcription() -> None:
    assert COMMAND_SCHEMA_DEFS["FaceSelector"] == EXPECTED_FACE_SELECTOR


def test_depth_matches_independent_transcription() -> None:
    assert COMMAND_SCHEMA_DEFS["Depth"] == EXPECTED_DEPTH


def test_pattern_matches_independent_transcription() -> None:
    assert COMMAND_SCHEMA_DEFS["Pattern"] == EXPECTED_PATTERN


def test_profile_matches_independent_transcription() -> None:
    assert COMMAND_SCHEMA_DEFS["Profile"] == EXPECTED_PROFILE


def test_tool_matches_independent_transcription() -> None:
    assert COMMAND_SCHEMA_DEFS["Tool"] == EXPECTED_TOOL


def test_hole_matches_independent_transcription() -> None:
    assert COMMAND_SCHEMA_DEFS["Hole"] == EXPECTED_HOLE


# ---------------------------------------------------------------------------
# key-field assertions for the remaining five defs
# ---------------------------------------------------------------------------


def test_edge_selector_key_fields() -> None:
    edge = COMMAND_SCHEMA_DEFS["EdgeSelector"]
    assert edge["type"] == "object"
    assert edge["required"] == ["parent_faces"]
    assert edge["additionalProperties"] is False
    assert edge["properties"]["parent_faces"] == {
        "type": "array",
        "items": {"$ref": "#/$defs/FaceSelector"},
        "minItems": 1,
    }
    assert edge["properties"]["curve"] == {"type": "string", "enum": ["line", "circle", ""]}


def test_position_key_fields() -> None:
    branches = COMMAND_SCHEMA_DEFS["Position"]["oneOf"]
    assert len(branches) == 1
    branch = branches[0]
    assert branch["type"] == "object"
    assert branch["properties"] == {"kind": {"const": "center"}}
    assert branch["required"] == ["kind"]
    assert branch["additionalProperties"] is False


def test_mode_key_fields() -> None:
    assert COMMAND_SCHEMA_DEFS["Mode"] == {
        "type": "string",
        "enum": ["new", "add", "cut"],
        "default": "new",
    }


def test_center3_key_fields() -> None:
    assert COMMAND_SCHEMA_DEFS["Center3"] == {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
        "default": [0.0, 0.0, 0.0],
    }


def test_positive_key_fields() -> None:
    assert COMMAND_SCHEMA_DEFS["Positive"] == {"type": "number", "exclusiveMinimum": 0.0}


# ---------------------------------------------------------------------------
# $ref shape + no-copy guards
# ---------------------------------------------------------------------------


def test_hole_properties_are_pure_refs() -> None:
    assert COMMAND_SCHEMA_DEFS["Hole"]["properties"] == {
        "target_face": {"$ref": "#/$defs/FaceSelector"},
        "position": {"$ref": "#/$defs/Position"},
        "diameter": {"$ref": "#/$defs/Positive"},
        "depth": {"$ref": "#/$defs/Depth"},
    }


def test_tool_branches_use_refs_for_positive_and_center3() -> None:
    box_branch, cylinder_branch = COMMAND_SCHEMA_DEFS["Tool"]["oneOf"]
    for key in ("size_x", "size_y", "size_z"):
        assert box_branch["properties"][key] == {"$ref": "#/$defs/Positive"}
    assert box_branch["properties"]["center"] == {"$ref": "#/$defs/Center3"}
    for key in ("radius", "height"):
        assert cylinder_branch["properties"][key] == {"$ref": "#/$defs/Positive"}
    assert cylinder_branch["properties"]["center"] == {"$ref": "#/$defs/Center3"}


def test_no_duplicated_positive_constraint_substructure() -> None:
    """Only Positive, Depth.blind.value and Pattern.radius spell the bound inline.

    The T7a task spec announced a count of 2 (assuming Pattern.radius also
    went through ``$ref``); A.0 and the task spec's own Pattern clause keep
    it inline, so the adjusted — still meaningful — guard is 3 (deviation D2).
    """
    source = (REPO / "src" / "mycad" / "builtin_commands" / "defs.py").read_text("utf-8")
    assert source.count('"exclusiveMinimum": 0.0') == 3
