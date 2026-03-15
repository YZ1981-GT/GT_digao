"""母公司/合并口径附注匹配测试。

覆盖：
- NoteSection 层级树中的母公司附注识别
- 合并报表科目仅有母公司附注时使用公司余额
- 同时有合并和母公司附注时各自用对应口径
- section_title 不含母公司关键词但祖先节点包含时的正确识别
"""
import uuid

import pytest

from app.models.audit_schemas import (
    MatchingEntry,
    MatchingMap,
    NoteSection,
    NoteTable,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from app.services.reconciliation_engine import ReconciliationEngine

engine = ReconciliationEngine()


# ─── helpers ───

def _item(name, opening=100.0, closing=200.0,
          company_opening=None, company_closing=None,
          is_consolidated=False, stmt_type=None):
    return StatementItem(
        id=str(uuid.uuid4()), account_name=name,
        statement_type=stmt_type or StatementType.BALANCE_SHEET,
        sheet_name="资产负债表",
        opening_balance=opening, closing_balance=closing,
        company_opening_balance=company_opening,
        company_closing_balance=company_closing,
        is_consolidated=is_consolidated, row_index=1,
    )


def _note(name, title=None, rows=None):
    if title is None:
        title = name
    return NoteTable(
        id=str(uuid.uuid4()), account_name=name,
        section_title=title,
        headers=["项目", "期初余额", "期末余额"],
        rows=rows or [["A", 50, 100], ["B", 50, 100], ["合计", 100, 200]],
    )


def _ts(note_id, closing_cell="R2C2", opening_cell="R2C1", is_income=False):
    cols = [
        TableStructureColumn(col_index=0, semantic="label"),
        TableStructureColumn(col_index=1, semantic="opening_balance" if not is_income else "prior_period_amount"),
        TableStructureColumn(col_index=2, semantic="closing_balance" if not is_income else "current_period_amount"),
    ]
    return TableStructure(
        note_table_id=note_id,
        rows=[
            TableStructureRow(row_index=0, role="data", label="A"),
            TableStructureRow(row_index=1, role="data", label="B"),
            TableStructureRow(row_index=2, role="total", label="合计"),
        ],
        columns=cols,
        total_row_indices=[2],
        subtotal_row_indices=[],
        closing_balance_cell=closing_cell,
        opening_balance_cell=opening_cell,
        has_balance_formula=False,
        structure_confidence="high",
    )


def _build_sections_with_parent(note_consolidated_id=None, note_parent_id=None):
    """构建典型的附注层级树：合并报表项目注释 + 母公司报表项目注释。"""
    children_consolidated = []
    children_parent = []

    if note_consolidated_id:
        children_consolidated.append(NoteSection(
            id="sec-c-child", title="长期股权投资",
            level=3, note_table_ids=[note_consolidated_id],
        ))
    if note_parent_id:
        children_parent.append(NoteSection(
            id="sec-p-child", title="长期股权投资",
            level=3, note_table_ids=[note_parent_id],
        ))

    sections = []
    if children_consolidated:
        sections.append(NoteSection(
            id="sec-consolidated", title="合并财务报表项目注释",
            level=2, children=children_consolidated,
        ))
    if children_parent:
        sections.append(NoteSection(
            id="sec-parent", title="母公司财务报表主要项目注释",
            level=2, children=children_parent,
        ))

    return [NoteSection(
        id="sec-root", title="五、重要会计政策及会计估计",
        level=1, children=sections,
    )]


# ─── Tests ───

class TestBuildNoteParentSectionMap:
    """测试 _build_note_parent_section_map 构建祖先标题映射。"""

    def test_basic_hierarchy(self):
        note_id = "note-123"
        sections = _build_sections_with_parent(note_consolidated_id=note_id)
        result = engine._build_note_parent_section_map(sections)
        assert note_id in result
        titles = result[note_id]
        assert any("合并财务报表" in t for t in titles)
        assert not any("母公司" in t for t in titles)

    def test_parent_company_hierarchy(self):
        note_id = "note-456"
        sections = _build_sections_with_parent(note_parent_id=note_id)
        result = engine._build_note_parent_section_map(sections)
        assert note_id in result
        titles = result[note_id]
        assert any("母公司" in t for t in titles)

    def test_both_notes(self):
        c_id, p_id = "note-c", "note-p"
        sections = _build_sections_with_parent(
            note_consolidated_id=c_id, note_parent_id=p_id,
        )
        result = engine._build_note_parent_section_map(sections)
        assert c_id in result
        assert p_id in result
        assert not any("母公司" in t for t in result[c_id])
        assert any("母公司" in t for t in result[p_id])

    def test_empty_sections(self):
        result = engine._build_note_parent_section_map([])
        assert result == {}


class TestIsParentCompanyNote:
    """测试 _is_parent_company_note 使用祖先标题判断。"""

    def test_section_title_contains_keyword(self):
        """section_title 本身包含母公司关键词（兜底逻辑）。"""
        note = _note("长期股权投资", title="母公司财务报表主要项目注释-长期股权投资")
        assert engine._is_parent_company_note(note) is True

    def test_section_title_no_keyword(self):
        """section_title 不含母公司关键词，无祖先信息 → 非母公司。"""
        note = _note("长期股权投资", title="长期股权投资")
        assert engine._is_parent_company_note(note) is False

    def test_ancestor_contains_keyword(self):
        """section_title 不含关键词，但祖先标题包含 → 母公司。"""
        note = _note("长期股权投资", title="长期股权投资")
        ancestors = ["五、重要会计政策及会计估计", "母公司财务报表主要项目注释", "长期股权投资"]
        assert engine._is_parent_company_note(note, ancestors) is True

    def test_ancestor_consolidated(self):
        """祖先标题是合并口径 → 非母公司。"""
        note = _note("长期股权投资", title="长期股权投资")
        ancestors = ["五、重要会计政策及会计估计", "合并财务报表项目注释", "长期股权投资"]
        assert engine._is_parent_company_note(note, ancestors) is False


class TestParentScopeAmountConsistency:
    """测试 check_amount_consistency 中母公司/合并口径的正确选择。"""

    def test_only_parent_note_uses_company_balance(self):
        """仅有母公司附注时，合并报表科目应使用公司余额比对。"""
        item = _item(
            "长期股权投资",
            opening=5000, closing=8000,           # 合并数
            company_opening=600, company_closing=800,  # 母公司数
            is_consolidated=True,
        )
        # 附注表格：母公司口径，金额与公司余额一致
        note_p = _note("长期股权投资", title="长期股权投资",
                        rows=[["对子公司投资", 600, 800], ["合计", 600, 800]])
        ts_p = _ts(note_p.id)

        # 构建 NoteSection 层级树：仅母公司节点
        sections = _build_sections_with_parent(note_parent_id=note_p.id)

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_p.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_p], {note_p.id: ts_p},
            note_sections=sections,
        )
        # 母公司余额 800/600 与附注 800/600 一致 → 无 finding
        assert len(findings) == 0

    def test_only_parent_note_without_sections_uses_heuristic(self):
        """无 note_sections 时，启发式推断附注与公司余额更接近 → 用母公司口径。"""
        item = _item(
            "长期股权投资",
            opening=5000, closing=8000,
            company_opening=600, company_closing=800,
            is_consolidated=True,
        )
        note_p = _note("长期股权投资", title="长期股权投资",
                        rows=[["对子公司投资", 600, 800], ["合计", 600, 800]])
        ts_p = _ts(note_p.id)

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_p.id],
            match_confidence=1.0,
        )])

        # 不传 note_sections → 启发式推断附注800与公司余额800一致 → 母公司口径 → 通过
        findings = engine.check_amount_consistency(
            mm, [item], [note_p], {note_p.id: ts_p},
        )
        assert len(findings) == 0

    def test_both_notes_with_sections(self):
        """同时有合并和母公司附注，通过 NoteSection 层级正确区分口径。"""
        item = _item(
            "长期股权投资",
            opening=3000, closing=5000,
            company_opening=600, company_closing=800,
            is_consolidated=True,
        )
        note_c = _note("长期股权投资", title="长期股权投资",
                        rows=[["对联营企业投资", 3000, 5000], ["合计", 3000, 5000]])
        note_p = _note("长期股权投资", title="长期股权投资",
                        rows=[["对子公司投资", 600, 800], ["合计", 600, 800]])
        ts_c = _ts(note_c.id)
        ts_p = _ts(note_p.id)

        sections = _build_sections_with_parent(
            note_consolidated_id=note_c.id,
            note_parent_id=note_p.id,
        )

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_c.id, note_p.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_c, note_p],
            {note_c.id: ts_c, note_p.id: ts_p},
            note_sections=sections,
        )
        # 合并 5000/3000 vs 附注合并 5000/3000 ✓
        # 母公司 800/600 vs 附注母公司 800/600 ✓
        assert len(findings) == 0

    def test_parent_note_mismatch_reports_company_scope(self):
        """母公司附注金额不一致时，finding 描述应包含"母公司"。"""
        item = _item(
            "长期股权投资",
            opening=3000, closing=5000,
            company_opening=600, company_closing=900,  # 公司期末 900
            is_consolidated=True,
        )
        note_p = _note("长期股权投资", title="长期股权投资",
                        rows=[["对子公司投资", 600, 800], ["合计", 600, 800]])  # 附注期末 800
        ts_p = _ts(note_p.id)

        sections = _build_sections_with_parent(note_parent_id=note_p.id)

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_p.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_p], {note_p.id: ts_p},
            note_sections=sections,
        )
        # 母公司期末 900 vs 附注 800 → 不一致
        assert len(findings) >= 1
        f = findings[0]
        assert "母公司" in f.description
        assert "900" in f.description  # 使用的是公司余额，不是合并余额 5000

    def test_investment_income_parent_scope(self):
        """投资收益等利润表科目也能正确识别母公司口径。"""
        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            opening_balance=1000, closing_balance=2000,
            company_opening_balance=300, company_closing_balance=500,
            is_consolidated=True, row_index=1,
        )
        note_inv_income_p = _note(
            "投资收益", title="投资收益",
            rows=[["对子公司投资收益", 300, 500], ["合计", 300, 500]],
        )
        ts_map = {}
        ts_map[note_inv_income_p.id] = _ts(note_inv_income_p.id, is_income=True)

        sections = _build_sections_with_parent(note_parent_id=note_inv_income_p.id)

        all_items = [item]
        all_notes = [note_inv_income_p]
        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_inv_income_p.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, all_items, all_notes, ts_map,
            note_sections=sections,
        )
        # 母公司 500/300 vs 附注 500/300 → 一致
        assert len(findings) == 0

    def test_investment_income_parent_mismatch_with_consolidated_match(self):
        """上市版：合并投资收益一致但母公司投资收益不一致时，应报告母公司差异。"""
        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            opening_balance=1000, closing_balance=2000,
            company_opening_balance=300, company_closing_balance=500,
            is_consolidated=True, row_index=1,
        )
        # 合并附注：2000/1000 → 与合并报表一致
        note_consolidated = _note(
            "投资收益", title="投资收益",
            rows=[["权益法投资收益", 1000, 2000], ["合计", 1000, 2000]],
        )
        # 母公司附注：999/300 → 期末与母公司报表500不一致
        note_parent = _note(
            "投资收益", title="投资收益",
            rows=[["对子公司投资收益", 300, 999], ["合计", 300, 999]],
        )
        ts_map = {
            note_consolidated.id: _ts(note_consolidated.id, is_income=True),
            note_parent.id: _ts(note_parent.id, is_income=True),
        }

        sections = _build_sections_with_parent(
            note_consolidated_id=note_consolidated.id,
            note_parent_id=note_parent.id,
        )

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_consolidated.id, note_parent.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_consolidated, note_parent], ts_map,
            note_sections=sections,
        )
        # 合并 2000/1000 vs 附注 2000/1000 → 一致（无 finding）
        # 母公司 500/300 vs 附注 999/300 → 期末不一致（应有 finding）
        assert len(findings) >= 1
        parent_findings = [f for f in findings if "母公司" in f.description]
        assert len(parent_findings) >= 1
        assert "500" in parent_findings[0].description or "999" in parent_findings[0].description

    def test_parent_scope_heuristic_when_ancestor_map_empty(self):
        """当 note_sections 为空导致 ancestor_map 无法识别母公司附注时，
        启发式金额推断应正确将附注归入母公司口径。"""
        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            closing_balance=50000000, opening_balance=40000000,
            company_closing_balance=5981811.76, company_opening_balance=171681711.32,
            is_consolidated=True, row_index=1,
        )
        # 合并附注：50000000/40000000 → 与合并报表一致
        note_consolidated = _note(
            "投资收益", title="投资收益",
            rows=[["权益法投资收益", 40000000, 50000000],
                  ["合计", 40000000, 50000000]],
        )
        # 母公司附注：5981811.76/4243663.30 → 期末与母公司一致，期初不一致
        note_parent = _note(
            "投资收益", title="投资收益",
            rows=[["投资收益", 4243663.30, 5367048.22],
                  ["债券利息", 0, 614763.54],
                  ["合计", 4243663.30, 5981811.76]],
        )
        ts_map = {
            note_consolidated.id: _ts(note_consolidated.id, is_income=True),
            note_parent.id: _ts(note_parent.id, is_income=True),
        }

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_consolidated.id, note_parent.id],
            match_confidence=1.0,
        )])

        # 不传 note_sections → ancestor_map 为空
        findings = engine.check_amount_consistency(
            mm, [item], [note_consolidated, note_parent], ts_map,
            note_sections=None,
        )
        # 合并 50000000/40000000 vs 附注 50000000/40000000 → 一致
        # 母公司 5981811.76/171681711.32 vs 附注 5981811.76/4243663.30
        #   → 期末一致，期初不一致（差异 167438048.02）
        assert len(findings) >= 1
        parent_findings = [f for f in findings if "母公司" in f.description]
        assert len(parent_findings) >= 1
        assert "171681711.32" in parent_findings[0].description or "167438048.02" in parent_findings[0].description

    def test_parent_scope_heuristic_no_false_positive(self):
        """启发式推断不应将合并附注误判为母公司附注。"""
        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            closing_balance=50000, opening_balance=30000,
            company_closing_balance=5000, company_opening_balance=3000,
            is_consolidated=True, row_index=1,
        )
        # 只有合并附注，金额与合并余额一致
        note_c = _note(
            "投资收益", title="投资收益",
            rows=[["合计", 30000, 50000]],
        )
        ts_map = {note_c.id: _ts(note_c.id, is_income=True)}

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_c.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_c], ts_map, note_sections=None,
        )
        # 合并附注匹配合并余额 → 不应误报
        assert len(findings) == 0


    def test_parent_note_closing_equals_consolidated_opening_differs(self):
        """当母公司附注期末值恰好等于合并期末值时，启发式无法区分口径，
        导致母公司期初不一致被遗漏。应通过 ancestor_map 或其他方式正确识别。"""
        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            # 合并：期末5000, 期初3000
            closing_balance=5000, opening_balance=3000,
            # 母公司：期末5000（与合并相同!）, 期初8000（与合并不同）
            company_closing_balance=5000, company_opening_balance=8000,
            is_consolidated=True, row_index=1,
        )
        # 合并附注：5000/3000 → 与合并报表一致
        note_consolidated = _note(
            "投资收益", title="投资收益",
            rows=[["权益法投资收益", 3000, 5000], ["合计", 3000, 5000]],
        )
        # 母公司附注：5000/6000 → 期末与母公司一致，期初与母公司8000不一致
        note_parent = _note(
            "投资收益", title="投资收益",
            rows=[["对子公司投资收益", 6000, 5000], ["合计", 6000, 5000]],
        )
        ts_map = {
            note_consolidated.id: _ts(note_consolidated.id, is_income=True),
            note_parent.id: _ts(note_parent.id, is_income=True),
        }

        # 使用 note_sections 正确标识母公司附注
        sections = _build_sections_with_parent(
            note_consolidated_id=note_consolidated.id,
            note_parent_id=note_parent.id,
        )

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_consolidated.id, note_parent.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_consolidated, note_parent], ts_map,
            note_sections=sections,
        )
        # 合并 5000/3000 vs 附注 5000/3000 → 一致
        # 母公司 5000/8000 vs 附注 5000/6000 → 期末一致，期初不一致（差异 2000）
        parent_findings = [f for f in findings if "母公司" in f.description]
        assert len(parent_findings) >= 1, (
            f"应检出母公司期初不一致，但实际 findings={[f.description for f in findings]}"
        )

    def test_parent_note_closing_equals_consolidated_no_sections(self):
        """无 note_sections 时，母公司附注期末值等于合并期末值，
        启发式无法区分 → 应通过期初金额差异补充推断。"""
        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            closing_balance=5000, opening_balance=3000,
            company_closing_balance=5000, company_opening_balance=8000,
            is_consolidated=True, row_index=1,
        )
        # 合并附注
        note_consolidated = _note(
            "投资收益", title="投资收益",
            rows=[["权益法投资收益", 3000, 5000], ["合计", 3000, 5000]],
        )
        # 母公司附注：期末5000（=合并），期初6000（≠合并3000，≠母公司8000）
        note_parent = _note(
            "投资收益", title="投资收益",
            rows=[["对子公司投资收益", 6000, 5000], ["合计", 6000, 5000]],
        )
        ts_map = {
            note_consolidated.id: _ts(note_consolidated.id, is_income=True),
            note_parent.id: _ts(note_parent.id, is_income=True),
        }

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_consolidated.id, note_parent.id],
            match_confidence=1.0,
        )])

        # 不传 note_sections
        findings = engine.check_amount_consistency(
            mm, [item], [note_consolidated, note_parent], ts_map,
            note_sections=None,
        )
        # 母公司期初 8000 vs 附注 6000 → 应检出不一致
        parent_findings = [f for f in findings if "母公司" in f.description]
        assert len(parent_findings) >= 1, (
            f"应检出母公司期初不一致，但实际 findings={[f.description for f in findings]}"
        )

    def test_parent_note_misplaced_under_consolidated_section(self):
        """当 note_sections 将母公司附注错误地放在合并报表项目注释下时，
        ancestor_map 会将其识别为合并口径。如果期末值恰好等于合并期末值，
        启发式也无法补救 → 母公司期初不一致被遗漏。"""
        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            closing_balance=5000, opening_balance=3000,
            company_closing_balance=5000, company_opening_balance=8000,
            is_consolidated=True, row_index=1,
        )
        # 合并附注
        note_consolidated = _note(
            "投资收益", title="投资收益",
            rows=[["权益法投资收益", 3000, 5000], ["合计", 3000, 5000]],
        )
        # 母公司附注（期末=合并期末=5000，期初6000≠母公司8000）
        note_parent = _note(
            "投资收益", title="投资收益",
            rows=[["对子公司投资收益", 6000, 5000], ["合计", 6000, 5000]],
        )
        ts_map = {
            note_consolidated.id: _ts(note_consolidated.id, is_income=True),
            note_parent.id: _ts(note_parent.id, is_income=True),
        }

        # 错误的 note_sections：两个附注都在合并报表项目注释下
        sections = [NoteSection(
            id="sec-root", title="五、重要会计政策及会计估计",
            level=1, children=[
                NoteSection(
                    id="sec-consolidated", title="合并财务报表项目注释",
                    level=2, children=[
                        NoteSection(
                            id="sec-c-child", title="投资收益",
                            level=3, note_table_ids=[note_consolidated.id, note_parent.id],
                        ),
                    ],
                ),
            ],
        )]

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_consolidated.id, note_parent.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_consolidated, note_parent], ts_map,
            note_sections=sections,
        )
        # 合并 5000/3000 vs 附注 5000/3000 → 一致
        # 母公司 5000/8000 vs 附注 5000/6000 → 期初不一致
        # 但由于 ancestor_map 将两个附注都归为合并口径，
        # 且期末值=合并期末值，启发式也不会触发
        # → 母公司期初不一致可能被遗漏
        parent_findings = [f for f in findings if "母公司" in f.description]
        assert len(parent_findings) >= 1, (
            f"应检出母公司期初不一致，但实际 findings={[f.description for f in findings]}"
        )

    def test_parent_note_closing_matches_consolidated_not_company(self):
        """母公司附注期末值等于合并期末值但不等于母公司期末值时，
        启发式将其归为合并口径 → 母公司期初不一致被遗漏。
        这是实际生产中最可能出现的场景。"""
        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            closing_balance=50000000, opening_balance=40000000,
            company_closing_balance=5981811.76, company_opening_balance=171681711.32,
            is_consolidated=True, row_index=1,
        )
        # 合并附注：50000000/40000000 → 与合并报表一致
        note_consolidated = _note(
            "投资收益", title="投资收益",
            rows=[["权益法投资收益", 40000000, 50000000],
                  ["合计", 40000000, 50000000]],
        )
        # 母公司附注：LLM 识别的 closing_balance_cell 指向了错误的值（50000000而非5981811.76）
        # 但实际表格中合计行的值是 5981811.76/4243663.30
        # 这种情况下 _get_cell_value 返回的是 LLM 指向的值
        # 而 _extract_note_totals_by_rules 返回的是规则引擎提取的合计行值
        note_parent = _note(
            "投资收益", title="投资收益",
            rows=[["投资收益", 4243663.30, 5981811.76],
                  ["合计", 4243663.30, 5981811.76]],
        )
        ts_map = {
            note_consolidated.id: _ts(note_consolidated.id, is_income=True),
            note_parent.id: _ts(note_parent.id, is_income=True),
        }

        # 不传 note_sections → ancestor_map 为空，依赖启发式
        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_consolidated.id, note_parent.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_consolidated, note_parent], ts_map,
            note_sections=None,
        )
        # 合并 50000000/40000000 vs 附注 50000000/40000000 → 一致
        # 母公司 5981811.76/171681711.32 vs 附注 5981811.76/4243663.30
        #   → 期末一致，期初不一致
        parent_findings = [f for f in findings if "母公司" in f.description]
        assert len(parent_findings) >= 1, (
            f"应检出母公司期初不一致，但实际 findings={[f.description for f in findings]}"
        )

    def test_parent_note_excluded_by_matching_limit(self):
        """修复：匹配映射上限从3提升到10，确保母公司附注不被截断。"""
        from app.services.reconciliation_engine import ReconciliationEngine
        engine2 = ReconciliationEngine()

        item = StatementItem(
            id=str(uuid.uuid4()), account_name="投资收益",
            statement_type=StatementType.INCOME_STATEMENT,
            sheet_name="利润表",
            closing_balance=50000000, opening_balance=40000000,
            company_closing_balance=5981811.76, company_opening_balance=171681711.32,
            is_consolidated=True, row_index=1,
        )
        # 4 个附注表格都叫"投资收益"
        note1 = _note("投资收益", title="投资收益", rows=[["权益法投资收益", 40000000, 50000000], ["合计", 40000000, 50000000]])
        note2 = _note("投资收益", title="投资收益明细", rows=[["子公司A", 20000000, 25000000]])
        note3 = _note("投资收益", title="投资收益-按类型", rows=[["股权投资", 30000000, 40000000]])
        note4 = _note("投资收益", title="投资收益", rows=[["对子公司投资收益", 4243663.30, 5981811.76], ["合计", 4243663.30, 5981811.76]])

        all_notes = [note1, note2, note3, note4]
        mm = engine2.build_matching_map([item], all_notes)

        # 检查匹配映射中是否包含所有4个附注
        entry = mm.entries[0]
        assert len(entry.note_table_ids) >= 4 or note4.id in entry.note_table_ids, (
            f"母公司附注(note4)被排除在匹配映射之外! "
            f"matched={entry.note_table_ids}, note4.id={note4.id}"
        )

    def test_parent_scope_fallback_when_no_note_identified_as_parent(self):
        """当 ancestor_map 和启发式都未能识别母公司附注时，
        补充校验应使用公司余额与非合并口径附注比对，检出母公司不一致。"""
        engine = ReconciliationEngine()
        # 合并期末=5000, 期初=3000; 母公司期末=800, 期初=600
        item = _item(
            "投资收益",
            closing=5000, opening=3000,
            company_closing=800, company_opening=600,
            is_consolidated=True,
            stmt_type=StatementType.INCOME_STATEMENT,
        )
        # 合并附注：值=5000/3000（与合并余额一致）
        note_c = _note("投资收益", title="投资收益", rows=[
            ["合计", 3000, 5000],
        ])
        # 母公司附注：值=800/500（期初与母公司余额600不一致）
        # section_title 不含母公司关键词，ancestor_map 也为空
        note_p = _note("投资收益", title="投资收益", rows=[
            ["合计", 500, 800],
        ])
        ts_c = _ts(note_c.id, closing_cell="R0C2", opening_cell="R0C1")
        ts_p = _ts(note_p.id, closing_cell="R0C2", opening_cell="R0C1")
        ts_map = {note_c.id: ts_c, note_p.id: ts_p}

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_c.id, note_p.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_c, note_p], ts_map, note_sections=None,
        )
        # 母公司期初 600 vs 附注 500 → 应检出不一致
        parent_opening_findings = [
            f for f in findings
            if "母公司" in f.description and "期初" in f.description
        ]
        assert len(parent_opening_findings) >= 1, (
            f"应检出母公司期初不一致，实际 findings={[f.description for f in findings]}"
        )

    def test_parent_scope_fallback_both_notes_same_closing(self):
        """当合并和母公司期末值相同但期初不同时，
        补充校验应在启发式失败的情况下检出母公司期初不一致。"""
        engine = ReconciliationEngine()
        # 合并和母公司期末都是5000，但期初不同
        item = _item(
            "投资收益",
            closing=5000, opening=3000,
            company_closing=5000, company_opening=2000,
            is_consolidated=True,
            stmt_type=StatementType.INCOME_STATEMENT,
        )
        # 合并附注：5000/3000
        note_c = _note("投资收益", title="投资收益", rows=[
            ["合计", 3000, 5000],
        ])
        # 母公司附注：5000/1500（期初与母公司余额2000不一致）
        note_p = _note("投资收益", title="投资收益", rows=[
            ["合计", 1500, 5000],
        ])
        ts_c = _ts(note_c.id, closing_cell="R0C2", opening_cell="R0C1")
        ts_p = _ts(note_p.id, closing_cell="R0C2", opening_cell="R0C1")
        ts_map = {note_c.id: ts_c, note_p.id: ts_p}

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_c.id, note_p.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_c, note_p], ts_map, note_sections=None,
        )
        # 母公司期初 2000 vs 附注 1500 → 应检出
        parent_findings = [f for f in findings if "母公司" in f.description]
        assert len(parent_findings) >= 1, (
            f"应检出母公司不一致，实际 findings={[f.description for f in findings]}"
        )

    def test_parent_scope_fallback_no_false_positive_when_matched(self):
        """当母公司附注金额与公司余额一致时，补充校验不应产生误报。"""
        engine = ReconciliationEngine()
        item = _item(
            "投资收益",
            closing=5000, opening=3000,
            company_closing=800, company_opening=600,
            is_consolidated=True,
            stmt_type=StatementType.INCOME_STATEMENT,
        )
        note_c = _note("投资收益", title="投资收益", rows=[
            ["合计", 3000, 5000],
        ])
        # 母公司附注金额与公司余额完全一致
        note_p = _note("投资收益", title="投资收益", rows=[
            ["合计", 600, 800],
        ])
        ts_c = _ts(note_c.id, closing_cell="R0C2", opening_cell="R0C1")
        ts_p = _ts(note_p.id, closing_cell="R0C2", opening_cell="R0C1")
        ts_map = {note_c.id: ts_c, note_p.id: ts_p}

        mm = MatchingMap(entries=[MatchingEntry(
            statement_item_id=item.id,
            note_table_ids=[note_c.id, note_p.id],
            match_confidence=1.0,
        )])

        findings = engine.check_amount_consistency(
            mm, [item], [note_c, note_p], ts_map, note_sections=None,
        )
        # 合并 5000/3000 一致，母公司 800/600 一致 → 无 finding
        assert len(findings) == 0, (
            f"不应有 finding，实际={[f.description for f in findings]}"
        )
