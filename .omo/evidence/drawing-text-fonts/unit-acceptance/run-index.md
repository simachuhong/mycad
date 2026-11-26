# 本轮定向运行索引

项目根目录执行。表中开始时间及耗时取自 JUnit；结束时间为开始加耗时的近似值。退出码为执行工具返回的进程状态。每条命令还带 `-q -ra --junitxml=<同名 XML>`，通过 `set -o pipefail` 将标准输出/错误写入同名 log；`-k` 与其他选项的顺序不影响 pytest 语义。

| 运行 | 开始（本地时间） | 结束（约） | 场景 | 失败/跳过 | 退出码 |
| --- | --- | --- | ---: | ---: | ---: |
| [U01-U06-20261117](U01-U06-20261117.xml) | 2026-11-17T12:55:34+08:00 | 2026-11-17T12:55:35+08:00 | 27 | 0/0 | 0 |
| [U07-U08-20261117](U07-U08-20261117.xml) | 2026-11-17T12:55:58+08:00 | 2026-11-17T12:56:08+08:00 | 4 | 0/0 | 0 |
| [X01-X07-X08-red](X01-X07-X08-red.xml) | 2026-11-17T12:57:02+08:00 | 2026-11-17T12:57:05+08:00 | 21 | 1/0 | 1 |
| [X07-shx-green](X07-shx-green.xml) | 2026-11-17T12:57:19+08:00 | 2026-11-17T12:57:21+08:00 | 1 | 0/0 | 0 |
| [U12-U15-20261117](U12-U15-20261117.xml) | 2026-11-17T12:58:00+08:00 | 2026-11-17T12:58:10+08:00 | 14 | 0/0 | 0 |
| [I01-I04-20261117](I01-I04-20261117.xml) | 2026-11-17T12:58:57+08:00 | 2026-11-17T12:59:08+08:00 | 17 | 1/0 | 1 |
| [I01-I02-audit-green](I01-I02-audit-green.xml) | 2026-11-17T12:59:22+08:00 | 2026-11-17T12:59:31+08:00 | 1 | 0/0 | 0 |
| [X07-columns](X07-columns.xml) | 2026-11-17T13:01:08+08:00 | 2026-11-17T13:01:10+08:00 | 1 | 0/0 | 0 |
| [I09-matrix-initial](I09-matrix-initial.xml) | 2026-11-17T13:00:34+08:00 | 2026-11-17T13:01:36+08:00 | 18 | 0/0 | 0 |
| [I09-geometry-matrix](I09-geometry-matrix.xml) | 2026-11-17T13:01:59+08:00 | 2026-11-17T13:02:43+08:00 | 12 | 0/0 | 0 |
| [U16-properties](U16-properties.xml) | 2026-11-17T13:02:43+08:00 | 2026-11-17T13:02:54+08:00 | 9 | 0/0 | 0 |
| [I08-I10-initial](I08-I10-initial.xml) | 2026-11-17T13:03:35+08:00 | 2026-11-17T13:03:52+08:00 | 2 | 1/0 | 1 |
| [I10-switch-green](I10-switch-green.xml) | 2026-11-17T13:04:12+08:00 | 2026-11-17T13:04:24+08:00 | 1 | 0/0 | 0 |
| [I11-guards](I11-guards.xml) | 2026-11-17T13:05:20+08:00 | 2026-11-17T13:05:37+08:00 | 3 | 0/0 | 0 |
| [I01-I02-extra](I01-I02-extra.xml) | 2026-11-17T13:06:08+08:00 | 2026-11-17T13:06:16+08:00 | 2 | 0/0 | 0 |
| [I07-repeat-paste](I07-repeat-paste.xml) | 2026-11-17T13:07:37+08:00 | 2026-11-17T13:07:50+08:00 | 1 | 0/0 | 0 |
| [I05-profile](I05-profile.xml) | 2026-11-17T13:08:09+08:00 | 2026-11-17T13:08:22+08:00 | 1 | 0/0 | 0 |
| [I09-I11-public-input](I09-I11-public-input.xml) | 2026-11-17T13:07:04+08:00 | 2026-11-17T13:08:26+08:00 | 21 | 0/0 | 0 |
| [I07-clipboard-e2e](I07-clipboard-e2e.xml) | 2026-11-17T13:09:15+08:00 | 2026-11-17T13:09:28+08:00 | 1 | 0/0 | 0 |
| [U15-zoom](U15-zoom.xml) | 2026-11-17T13:10:11+08:00 | 2026-11-17T13:10:21+08:00 | 1 | 0/0 | 0 |
| [U04-style-dialog](U04-style-dialog.xml) | 2026-11-17T13:10:41+08:00 | 2026-11-17T13:10:52+08:00 | 1 | 0/0 | 0 |
| [I12-session-regression](I12-session-regression.xml) | 2026-11-17T13:11:06+08:00 | 2026-11-17T13:11:23+08:00 | 1 | 0/0 | 0 |
| [I02-full-fields](I02-full-fields.xml) | 2026-11-17T13:11:53+08:00 | 2026-11-17T13:12:02+08:00 | 1 | 0/0 | 0 |
| [I06-invalid-style](I06-invalid-style.xml) | 2026-11-17T13:12:16+08:00 | 2026-11-17T13:12:24+08:00 | 1 | 0/0 | 0 |
| [U14-U16-extra](U14-U16-extra.xml) | 2026-11-17T13:12:33+08:00 | 2026-11-17T13:12:43+08:00 | 2 | 0/0 | 0 |
| [U10-real-import](U10-real-import.xml) | 2026-11-17T13:13:06+08:00 | 2026-11-17T13:13:16+08:00 | 1 | 0/0 | 0 |
| [U10-real-import-final](U10-real-import-final.xml) | 2026-11-17T13:13:52+08:00 | 2026-11-17T13:14:04+08:00 | 1 | 0/0 | 0 |
| [I10-create-red](I10-create-red.xml) | 2026-11-17T13:14:35+08:00 | 2026-11-17T13:14:49+08:00 | 1 | 1/0 | 1 |
| [I10-navigation-green](I10-navigation-green.xml) | 2026-11-17T13:15:34+08:00 | 2026-11-17T13:15:46+08:00 | 1 | 0/0 | 0 |
| [I10-open-green](I10-open-green.xml) | 2026-11-17T13:16:08+08:00 | 2026-11-17T13:16:29+08:00 | 1 | 0/0 | 0 |
| [I12-session-final](I12-session-final.xml) | 2026-11-17T13:16:08+08:00 | 2026-11-17T13:16:30+08:00 | 1 | 0/0 | 0 |
| [U08-unwritable](U08-unwritable.xml) | 2026-11-17T13:16:42+08:00 | 2026-11-17T13:16:52+08:00 | 1 | 0/0 | 0 |
| [U08-unwritable-final](U08-unwritable-final.xml) | 2026-11-17T13:17:05+08:00 | 2026-11-17T13:17:17+08:00 | 1 | 0/0 | 0 |
| [U13-font-samples](U13-font-samples.xml) | 2026-11-17T13:17:24+08:00 | 2026-11-17T13:17:35+08:00 | 2 | 0/0 | 0 |

## 命令及输出

- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/core/test_drawing_text_acceptance.py -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U01-U06-20261117.xml`；[输出](U01-U06-20261117.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_font_acceptance.py -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U07-U08-20261117.xml`；[输出](U07-U08-20261117.log)
- `uv run --no-sync pytest tests/formats/test_dxf_text_exchange.py -k 'all_native_box_anchors or mtext_baseline_export or native_shx_style or native_stacked_mtext' -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/X01-X07-X08-red.xml`；[输出](X01-X07-X08-red.log)
- `uv run --no-sync pytest tests/formats/test_dxf_text_exchange.py::test_native_shx_style_import_reports_unavailable_glyphs -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/X07-shx-green.xml`；[输出](X07-shx-green.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_drawing_text_acceptance.py -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U12-U15-20261117.xml`；[输出](U12-U15-20261117.log)
- `uv run --no-sync pytest tests/app/test_drawing_text_acceptance.py -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I01-I04-20261117.xml`；[输出](I01-I04-20261117.log)
- `uv run --no-sync pytest tests/app/test_drawing_text_acceptance.py::test_five_commands_audit_fields_survive_save_and_replay -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I01-I02-audit-green.xml`；[输出](I01-I02-audit-green.log)
- `uv run --no-sync pytest tests/formats/test_dxf_text_exchange.py::test_native_mtext_columns_are_reported -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/X07-columns.xml`；[输出](X07-columns.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_transform_acceptance.py -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I09-matrix-initial.xml`；[输出](I09-matrix-initial.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_transform_acceptance.py -k 'draft or saved' -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I09-geometry-matrix.xml`；[输出](I09-geometry-matrix.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_drawing_text_acceptance.py::test_multiselection_only_changes_the_chosen_property -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U16-properties.xml`；[输出](U16-properties.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_entry_acceptance.py -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I08-I10-initial.xml`；[输出](I08-I10-initial.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_entry_acceptance.py::test_pending_text_blocks_switch_and_close_until_cancelled -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I10-switch-green.xml`；[输出](I10-switch-green.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_transform_acceptance.py::test_mixed_transform_rejects_complex_or_stale_source_without_mutation -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I11-guards.xml`；[输出](I11-guards.log)
- `uv run --no-sync pytest tests/app/test_drawing_text_acceptance.py -k 'pre_text_v3 or failed_duplicate' -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I01-I02-extra.xml`；[输出](I01-I02-extra.log)
- `uv run --no-sync pytest tests/app/test_drawing_text_import.py::test_repeat_mixed_paste_collision_undo_redo_and_reopen -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I07-repeat-paste.xml`；[输出](I07-repeat-paste.log)
- `uv run --no-sync pytest tests/app/test_drawing_text_acceptance.py::test_text_does_not_change_sketch_constraints_or_closed_regions -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I05-profile.xml`；[输出](I05-profile.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_transform_acceptance.py -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I09-I11-public-input.xml`；[输出](I09-I11-public-input.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_clipboard_acceptance.py -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I07-clipboard-e2e.xml`；[输出](I07-clipboard-e2e.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_drawing_text_acceptance.py::test_rotated_text_remains_pickable_after_canvas_zoom -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U15-zoom.xml`；[输出](U15-zoom.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_drawing_text_acceptance.py::test_style_dialog_rejects_casefold_duplicate_and_empty_name -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U04-style-dialog.xml`；[输出](U04-style-dialog.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_document_session.py::test_workspaces_have_independent_history_and_keep_draft -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I12-session-regression.xml`；[输出](I12-session-regression.log)
- `uv run --no-sync pytest tests/app/test_drawing_text_acceptance.py::test_archive_reopens_all_explicit_text_fields_and_missing_font -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I02-full-fields.xml`；[输出](I02-full-fields.log)
- `uv run --no-sync pytest tests/app/test_drawing_text_import.py::test_invalid_imported_style_does_not_publish_any_part -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I06-invalid-style.xml`；[输出](I06-invalid-style.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_drawing_text_acceptance.py -k 'double_click_existing_text or multiselection_layer_change' -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U14-U16-extra.xml`；[输出](U14-U16-extra.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_font_acceptance.py::test_real_font_import_survives_cancelling_resource_dialog -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U10-real-import.xml`；[输出](U10-real-import.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_font_acceptance.py::test_real_font_import_survives_cancelling_resource_dialog -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U10-real-import-final.xml`；[输出](U10-real-import-final.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_entry_acceptance.py::test_pending_text_blocks_switch_and_close_until_cancelled -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I10-create-red.xml`；[输出](I10-create-red.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_entry_acceptance.py::test_pending_text_blocks_switch_and_close_until_cancelled -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I10-navigation-green.xml`；[输出](I10-navigation-green.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_text_entry_acceptance.py::test_pending_text_blocks_open_before_starting_session_work -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I10-open-green.xml`；[输出](I10-open-green.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_document_session.py::test_workspaces_have_independent_history_and_keep_draft -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/I12-session-final.xml`；[输出](I12-session-final.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_font_acceptance.py::test_unwritable_font_destination_reports_error_without_staging -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U08-unwritable.xml`；[输出](U08-unwritable.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_font_acceptance.py::test_unwritable_font_destination_reports_error_without_staging -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U08-unwritable-final.xml`；[输出](U08-unwritable-final.log)
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_font_acceptance.py::test_imported_font_can_shape_text_without_missing_glyphs -q -ra --junitxml=.omo/evidence/drawing-text-fonts/unit-acceptance/U13-font-samples.xml`；[输出](U13-font-samples.log)
