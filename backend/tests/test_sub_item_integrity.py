"""测试其中项勾稽逻辑：合计=按单项+按组合，按组合=账龄组合+关联方组合，sub_item不重复计入合计。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.audit_schemas import NoteTable, TableStructure
from app.services.table_structure_analyzer import TableStructureAnalyzer
from app.services.reconciliation_engine import reconciliation_engine


def test_sub_item_detection():
    """验证 _analyze_with_rules 正确识别其中项明细行"""
    note = NoteTable(
        id="t1", account_name="应收账款", section_title="坏账准备",
        headers=["项目", "期末余额", "期初余额"],
        rows=[
            ["按单项计提坏账准备", 100, 80],           # row 0: data
            ["按组合计提坏账准备金额", 500, 400],       # row 1: data
            ["其中：", None, None],                     # row 2: sub_item header
            ["账龄组合", 300, 250],                     # row 3: sub_item (parent=1)
            ["关联方组合", 200, 150],                   # row 4: sub_item (parent=1)
            ["合计", 600, 480],                         # row 5: total = 100+500
        ],
    )
    analyzer = TableStructureAnalyzer()
    ts = analyzer._analyze_with_rules(note)

    roles = {r.row_index: r.role for r in ts.rows}
    parents = {r.row_index: r.parent_row_index for r in ts.rows}

    print("行角色:", roles)
    print("父行:", parents)

    assert roles[0] == "data", f"按单项应为data，实际{roles[0]}"
    assert roles[1] == "data", f"按组合应为data，实际{roles[1]}"
    assert roles[2] == "sub_item", f"其中：应为sub_item，实际{roles[2]}"
    assert roles[3] == "sub_item", f"账龄组合应为sub_item，实际{roles[3]}"
    assert roles[4] == "sub_item", f"关联方组合应为sub_item，实际{roles[4]}"
    assert roles[5] == "total", f"合计应为total，实际{roles[5]}"

    # 其中项的 parent 应指向"按组合计提"(row 1)
    assert parents[3] == 1, f"账龄组合的parent应为1，实际{parents[3]}"
    assert parents[4] == 1, f"关联方组合的parent应为1，实际{parents[4]}"

    print("✅ 其中项角色识别正确")


def test_total_excludes_sub_items():
    """验证合计行加总只包含顶层data行，不包含sub_item"""
    note = NoteTable(
        id="t2", account_name="应收账款", section_title="坏账准备",
        headers=["项目", "期末余额", "期初余额"],
        rows=[
            ["按单项计提坏账准备", 100, 80],
            ["按组合计提坏账准备金额", 500, 400],
            ["其中：", None, None],
            ["账龄组合", 300, 250],
            ["关联方组合", 200, 150],
            ["合计", 600, 480],  # 100+500=600 ✓
        ],
    )
    analyzer = TableStructureAnalyzer()
    ts = analyzer._analyze_with_rules(note)

    # 纵向加总校验不应报错（600 = 100+500）
    findings = reconciliation_engine.check_note_table_integrity(note, ts)
    print(f"纵向加总 findings: {len(findings)}")
    for f in findings:
        print(f"  - {f.description}")

    assert len(findings) == 0, f"不应有勾稽错误，但发现 {len(findings)} 个: {[f.description for f in findings]}"
    print("✅ 合计行加总正确排除了其中项")


def test_sub_item_check():
    """验证其中项校验：账龄组合+关联方组合 ≤ 按组合计提"""
    note = NoteTable(
        id="t3", account_name="应收账款", section_title="坏账准备",
        headers=["项目", "期末余额", "期初余额"],
        rows=[
            ["按单项计提坏账准备", 100, 80],
            ["按组合计提坏账准备金额", 500, 400],
            ["其中：", None, None],
            ["账龄组合", 300, 250],
            ["关联方组合", 200, 150],
            ["合计", 600, 480],
        ],
    )
    analyzer = TableStructureAnalyzer()
    ts = analyzer._analyze_with_rules(note)

    findings = reconciliation_engine.check_sub_items(note, ts)
    print(f"其中项校验 findings: {len(findings)}")
    for f in findings:
        print(f"  - {f.description}")

    # 300+200=500 == 按组合500，不应报错
    assert len(findings) == 0, f"其中项之和等于父项，不应报错"
    print("✅ 其中项校验正确")


def test_sub_item_exceeds_parent():
    """其中项之和超过父项时应报错"""
    note = NoteTable(
        id="t4", account_name="应收账款", section_title="坏账准备",
        headers=["项目", "期末余额", "期初余额"],
        rows=[
            ["按单项计提坏账准备", 100, 80],
            ["按组合计提坏账准备金额", 500, 400],
            ["其中：", None, None],
            ["账龄组合", 350, 250],   # 350+200=550 > 500
            ["关联方组合", 200, 150],
            ["合计", 600, 480],
        ],
    )
    analyzer = TableStructureAnalyzer()
    ts = analyzer._analyze_with_rules(note)

    findings = reconciliation_engine.check_sub_items(note, ts)
    assert len(findings) > 0, "其中项之和超过父项，应报错"
    print(f"✅ 其中项超额检测正确: {findings[0].description}")


def test_total_mismatch_detected():
    """合计行不等于顶层data之和时应报错"""
    note = NoteTable(
        id="t5", account_name="应收账款", section_title="坏账准备",
        headers=["项目", "期末余额", "期初余额"],
        rows=[
            ["按单项计提坏账准备", 100, 80],
            ["按组合计提坏账准备金额", 500, 400],
            ["其中：", None, None],
            ["账龄组合", 300, 250],
            ["关联方组合", 200, 150],
            ["合计", 999, 480],  # 999 != 100+500=600
        ],
    )
    analyzer = TableStructureAnalyzer()
    ts = analyzer._analyze_with_rules(note)

    findings = reconciliation_engine.check_note_table_integrity(note, ts)
    assert len(findings) > 0, "合计不平应报错"
    print(f"✅ 合计不平检测正确: {findings[0].description}")


def test_multiple_sub_item_groups():
    """多组其中项场景"""
    note = NoteTable(
        id="t6", account_name="应收账款", section_title="坏账准备",
        headers=["项目", "期末余额"],
        rows=[
            ["按单项计提", 100],           # row 0: data
            ["其中：", None],               # row 1: sub_item
            ["A类", 60],                    # row 2: sub_item (parent=0)
            ["B类", 40],                    # row 3: sub_item (parent=0)
            ["按组合计提", 500],            # row 4: data (新的顶层项)
            ["其中：", None],               # row 5: sub_item
            ["账龄组合", 300],              # row 6: sub_item (parent=4)
            ["关联方组合", 200],            # row 7: sub_item (parent=4)
            ["合计", 600],                  # row 8: total = 100+500
        ],
    )
    analyzer = TableStructureAnalyzer()
    ts = analyzer._analyze_with_rules(note)

    roles = {r.row_index: r.role for r in ts.rows}
    parents = {r.row_index: r.parent_row_index for r in ts.rows}
    print("多组其中项 roles:", roles)
    print("多组其中项 parents:", parents)

    assert roles[0] == "data"
    assert roles[2] == "sub_item" and parents[2] == 0
    assert roles[3] == "sub_item" and parents[3] == 0
    assert roles[4] == "data"
    assert roles[6] == "sub_item" and parents[6] == 4
    assert roles[7] == "sub_item" and parents[7] == 4
    assert roles[8] == "total"

    findings = reconciliation_engine.check_note_table_integrity(note, ts)
    assert len(findings) == 0, f"不应有勾稽错误: {[f.description for f in findings]}"
    print("✅ 多组其中项场景正确")


if __name__ == "__main__":
    test_sub_item_detection()
    test_total_excludes_sub_items()
    test_sub_item_check()
    test_sub_item_exceeds_parent()
    test_total_mismatch_detected()
    test_multiple_sub_item_groups()
    print("\n🎉 全部测试通过！")
