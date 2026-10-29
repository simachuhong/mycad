# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Replayable adoption/update/detachment of independent source documents."""

from mycad.commands.spec import CliSyntax, CommandSpec

REFERENCE_COMMAND_SPECS = tuple(
    CommandSpec(
        id=f"reference.{operation}",
        version=1,
        summary_en=f"{operation.title()} a document reference",
        label_zh=label,
        params_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reference_id": {"type": "string", "minLength": 32, "maxLength": 36},
                **(
                    {}
                    if operation == "detach"
                    else {
                        "file_id": {"type": "string"},
                        "kind": {"type": "string", "enum": ["sketch", "part"]},
                        "path": {"type": "string"},
                        "object_id": {"type": "string"},
                        "fingerprint": {"type": "string"},
                        "archive": {"type": "object"},
                    }
                ),
            },
            "required": ["reference_id"]
            if operation == "detach"
            else ["reference_id", "file_id", "kind", "path", "object_id", "fingerprint", "archive"],
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=4,
    )
    for operation, label in (
        ("attach", "关联来源"),
        ("update", "更新来源"),
        ("detach", "解除来源关联"),
    )
)
