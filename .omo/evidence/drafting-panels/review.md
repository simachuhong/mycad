# 独立审查与修复

审查者：fresh-context drafting_panels_review，read-only review。

无 Critical、无 Minor，两个 Important 均确认：
1. 尺寸编辑中导航选择被拒绝后焦点留在树，Esc 无法取消。新增真实鼠标/键盘测试，停靠和浮动两种情况均 RED。拒绝导航后恢复活动输入/画布及所属窗口焦点，打开图中输入时激活所属窗口，GREEN。
2. 树重建后 current item 丢失，Down 键跳到根。新增保留第二图元/current column 并按 Down 选择第三图元的测试，RED。按稳定身份保留 current item 和列，NoUpdate 恢复不改变选择，GREEN。

验证：tests/ui/test_drafting_panels.py，19 passed in 12.41s。
Declined to judge: 无。无遗留审查问题。最终全量1945项通过，唯一旧 F7 聚焦用例已按分页布局适配并扩充，28项专项复测通过；无未解决失败。
