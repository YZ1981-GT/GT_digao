"""审计报告复核数据模型单元测试 — Task 1.10

验证枚举值完整性、Pydantic 模型序列化/反序列化、必填字段校验、默认值正确性。
"""
import pytest
from pydantic import ValidationError

from app.models.audit_schemas import (
    # 枚举
    WorkMode,
    ReportFileType,
    StatementType,
    ReportReviewFindingCategory,
    FindingConfirmationStatus,
    ReportTemplateType,
    TemplateCategory,
    RiskLevel,
    FindingStatus,
    # 报表科目与附注
    StatementItem,
    NoteTable,
    ReportSheetData,
    # 表格结构识别
    TableStructureRow,
    TableStructureColumn,
    TableStructure,
    # 匹配映射
    MatchingEntry,
    MatchingMap,
    # 复核会话与结果
    ReportReviewSession,
    ReportReviewFinding,
    ReportReviewConfig,
    ReportReviewResult,
    SourcePreviewData,
    ChangeAnalysis,
    MatchingAnalysis,
    # 模板
    ReportTemplateSection,
    ReportTemplateDocument,
    NarrativeSection,
    TemplateTocEntry,
    # 对话
    FindingConversationMessage,
    FindingConversation,
)


# ═══════════════════════════════════════════════════════════════
# 枚举值完整性
# ═══════════════════════════════════════════════════════════════

class TestEnumCompleteness:
    """验证所有审计报告复核相关枚举包含预期成员。"""

    def test_work_mode_has_report_review(self):
        assert "report_review" in [m.value for m in WorkMode]

    def test_report_file_type_values(self):
        expected = {"audit_report_body", "financial_statement", "notes_to_statements"}
        assert {m.value for m in ReportFileType} == expected

    def test_statement_type_values(self):
        expected = {"balance_sheet", "income_statement", "cash_flow", "equity_change"}
        assert {m.value for m in StatementType} == expected

    def test_finding_category_values(self):
        expected = {
            "amount_inconsistency", "reconciliation_error", "change_abnormal",
            "note_missing", "report_body_compliance", "note_content", "text_quality",
        }
        assert {m.value for m in ReportReviewFindingCategory} == expected

    def test_finding_confirmation_status_values(self):
        expected = {"pending_confirmation", "confirmed", "dismissed"}
        assert {m.value for m in FindingConfirmationStatus} == expected

    def test_report_template_type_values(self):
        expected = {"soe", "listed"}
        assert {m.value for m in ReportTemplateType} == expected

    def test_template_category_values(self):
        expected = {"report_body", "notes"}
        assert {m.value for m in TemplateCategory} == expected


# ═══════════════════════════════════════════════════════════════
# 必填字段校验 — 缺少必填字段时应抛出 ValidationError
# ═══════════════════════════════════════════════════════════════

class TestRequiredFields:

    def test_statement_item_requires_id(self):
        with pytest.raises(ValidationError):
            StatementItem(
                account_name="货币资金",
                statement_type=StatementType.BALANCE_SHEET,
                sheet_name="资产负债表",
                row_index=5,
            )

    def test_note_table_requires_section_title(self):
        with pytest.raises(ValidationError):
            NoteTable(id="n1", account_name="货币资金")

    def test_report_review_session_requires_template_type(self):
        with pytest.raises(ValidationError):
            ReportReviewSession(id="s1", created_at="2026-01-01T00:00:00")

    def test_report_review_finding_requires_category(self):
        with pytest.raises(ValidationError):
            ReportReviewFinding(
                id="f1",
                risk_level=RiskLevel.HIGH,
                account_name="应收账款",
                location="A1",
                description="金额不一致",
            )

    def test_narrative_section_requires_content(self):
        with pytest.raises(ValidationError):
            NarrativeSection(
                id="ns1",
                section_type="basic_info",
                title="基本情况",
            )

    def test_report_template_document_requires_full_content(self):
        with pytest.raises(ValidationError):
            ReportTemplateDocument(
                template_type=ReportTemplateType.SOE,
                template_category=TemplateCategory.REPORT_BODY,
            )

    def test_finding_conversation_message_requires_role(self):
        with pytest.raises(ValidationError):
            FindingConversationMessage(
                id="m1",
                content="test",
                created_at="2026-01-01T00:00:00",
            )


# ═══════════════════════════════════════════════════════════════
# 默认值正确性
# ═══════════════════════════════════════════════════════════════

class TestDefaultValues:

    def test_statement_item_defaults(self):
        item = StatementItem(
            id="si1",
            account_name="货币资金",
            statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表",
            row_index=3,
        )
        assert item.opening_balance is None
        assert item.closing_balance is None
        assert item.parent_id is None
        assert item.is_sub_item is False
        assert item.parse_warnings == []

    def test_table_structure_defaults(self):
        ts = TableStructure(note_table_id="nt1")
        assert ts.rows == []
        assert ts.columns == []
        assert ts.has_balance_formula is False
        assert ts.total_row_indices == []
        assert ts.subtotal_row_indices == []
        assert ts.closing_balance_cell is None
        assert ts.opening_balance_cell is None
        assert ts.structure_confidence == "high"
        assert ts.raw_llm_response is None

    def test_matching_entry_defaults(self):
        entry = MatchingEntry(statement_item_id="si1")
        assert entry.note_table_ids == []
        assert entry.match_confidence == 0.0
        assert entry.is_manual is False

    def test_report_review_finding_default_status(self):
        finding = ReportReviewFinding(
            id="f1",
            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
            risk_level=RiskLevel.HIGH,
            account_name="应收账款",
            location="Sheet1!A5",
            description="期末余额不一致",
        )
        assert finding.confirmation_status == FindingConfirmationStatus.PENDING_CONFIRMATION
        assert finding.status == FindingStatus.OPEN
        assert finding.reference == ""
        assert finding.suggestion == ""
        assert finding.template_reference is None
        assert finding.analysis_reasoning is None

    def test_report_review_config_default_threshold(self):
        cfg = ReportReviewConfig(
            session_id="s1",
            template_type=ReportTemplateType.SOE,
        )
        assert cfg.change_threshold == 0.3
        assert cfg.prompt_id is None
        assert cfg.custom_prompt is None

    def test_change_analysis_defaults(self):
        ca = ChangeAnalysis(
            statement_item_id="si1",
            account_name="货币资金",
        )
        assert ca.exceeds_threshold is False
        assert ca.change_amount is None
        assert ca.change_percentage is None

    def test_source_preview_data_defaults(self):
        sp = SourcePreviewData(file_id="f1", file_type="excel")
        assert sp.highlight_range is None
        assert sp.content_html == ""

    def test_report_sheet_data_defaults(self):
        rsd = ReportSheetData(
            sheet_name="资产负债表",
            statement_type=StatementType.BALANCE_SHEET,
        )
        assert rsd.row_count == 0
        assert rsd.headers == []
        assert rsd.raw_data == []

    def test_finding_conversation_message_defaults(self):
        msg = FindingConversationMessage(
            id="m1", role="user", content="为什么？", created_at="2026-01-01T00:00:00",
        )
        assert msg.message_type == "chat"
        assert msg.trace_type is None

    def test_report_review_session_defaults(self):
        session = ReportReviewSession(
            id="s1",
            template_type=ReportTemplateType.SOE,
            created_at="2026-01-01T00:00:00",
        )
        assert session.file_ids == []
        assert session.file_classifications == {}
        assert session.sheet_data == {}
        assert session.statement_items == []
        assert session.note_tables == []
        assert session.table_structures == {}
        assert session.matching_map is None
        assert session.finding_conversations == {}
        assert session.status == "created"


# ═══════════════════════════════════════════════════════════════
# 序列化 / 反序列化 round-trip
# ═══════════════════════════════════════════════════════════════

class TestSerialization:

    def test_statement_item_round_trip(self):
        item = StatementItem(
            id="si1",
            account_name="应收账款",
            statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表",
            opening_balance=1000.0,
            closing_balance=1500.0,
            row_index=10,
            is_sub_item=True,
            parent_id="si0",
        )
        data = item.model_dump()
        restored = StatementItem(**data)
        assert restored == item

    def test_report_review_finding_round_trip(self):
        finding = ReportReviewFinding(
            id="f1",
            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
            risk_level=RiskLevel.MEDIUM,
            account_name="存货",
            location="附注表5",
            description="横向加总不平",
            statement_amount=100.0,
            note_amount=99.5,
            difference=0.5,
        )
        data = finding.model_dump()
        restored = ReportReviewFinding(**data)
        assert restored.category == ReportReviewFindingCategory.RECONCILIATION_ERROR
        assert restored.difference == 0.5

    def test_table_structure_round_trip(self):
        ts = TableStructure(
            note_table_id="nt1",
            rows=[TableStructureRow(row_index=0, role="header", label="项目")],
            columns=[TableStructureColumn(col_index=0, semantic="label")],
            has_balance_formula=True,
            total_row_indices=[5],
            closing_balance_cell="C6",
            opening_balance_cell="B6",
        )
        data = ts.model_dump()
        restored = TableStructure(**data)
        assert restored.has_balance_formula is True
        assert len(restored.rows) == 1
        assert restored.rows[0].role == "header"

    def test_matching_map_round_trip(self):
        mm = MatchingMap(
            entries=[MatchingEntry(statement_item_id="si1", note_table_ids=["nt1"], match_confidence=0.95)],
            unmatched_items=["si2"],
            unmatched_notes=["nt3"],
        )
        data = mm.model_dump()
        restored = MatchingMap(**data)
        assert len(restored.entries) == 1
        assert restored.unmatched_items == ["si2"]

    def test_report_review_result_round_trip(self):
        result = ReportReviewResult(
            id="r1",
            session_id="s1",
            category_summary={"amount_inconsistency": 3},
            risk_summary={"high": 1, "medium": 2},
            reconciliation_summary={"matched": 10, "mismatched": 2},
            confirmation_summary={"confirmed": 3},
            conclusion="复核完成",
            reviewed_at="2026-03-11T10:00:00",
        )
        data = result.model_dump()
        restored = ReportReviewResult(**data)
        assert restored.conclusion == "复核完成"

    def test_report_template_document_round_trip(self):
        doc = ReportTemplateDocument(
            template_type=ReportTemplateType.LISTED,
            template_category=TemplateCategory.NOTES,
            full_content="# 附注模板\n## 会计政策",
            sections=[ReportTemplateSection(path="会计政策", level=2, title="会计政策", content="内容")],
            version="v1",
            updated_at="2026-03-11",
        )
        data = doc.model_dump()
        restored = ReportTemplateDocument(**data)
        assert restored.template_type == ReportTemplateType.LISTED
        assert len(restored.sections) == 1

    def test_finding_conversation_round_trip(self):
        conv = FindingConversation(
            finding_id="f1",
            messages=[
                FindingConversationMessage(
                    id="m1", role="user", content="请解释", created_at="2026-01-01T00:00:00",
                ),
                FindingConversationMessage(
                    id="m2", role="assistant", content="分析如下...",
                    message_type="trace", trace_type="cross_reference",
                    created_at="2026-01-01T00:01:00",
                ),
            ],
            edit_history=[{"field": "description", "old": "旧", "new": "新"}],
        )
        data = conv.model_dump()
        restored = FindingConversation(**data)
        assert len(restored.messages) == 2
        assert restored.messages[1].trace_type == "cross_reference"
