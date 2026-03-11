"""Report_Body_Reviewer / Note_Content_Reviewer / Text_Quality_Analyzer 单元测试。

Tasks 7.5, 8.4, 9.3 — 使用 Mock LLM 测试。
"""
import asyncio
import json
import uuid
from unittest.mock import MagicMock

import pytest

from backend.app.models.audit_schemas import (
    FindingConfirmationStatus,
    NarrativeSection,
    NoteTable,
    ReportReviewFindingCategory,
    ReportTemplateDocument,
    ReportTemplateType,
    RiskLevel,
    StatementItem,
    StatementType,
    TemplateCategory,
)
from backend.app.services.report_body_reviewer import ReportBodyReviewer
from backend.app.services.note_content_reviewer import NoteContentReviewer
from backend.app.services.text_quality_analyzer import TextQualityAnalyzer


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_llm_service(response_json):
    """创建返回指定 JSON 的 mock LLM service。"""
    svc = MagicMock()
    response_text = json.dumps(response_json, ensure_ascii=False)

    async def mock_stream(messages, temperature=0.3):
        yield response_text

    svc.stream_chat_completion = mock_stream
    return svc


def _mock_llm_failure():
    """创建会抛异常的 mock LLM service。"""
    svc = MagicMock()

    async def mock_stream(messages, temperature=0.3):
        raise Exception("LLM API error")
        yield

    svc.stream_chat_completion = mock_stream
    return svc


# ─── Report Body Reviewer ───

class TestReportBodyReviewer:
    def test_name_consistency_with_llm(self):
        findings_data = [
            {"location": "第2段", "description": "名称不一致", "suggestion": "统一名称", "risk_level": "medium"}
        ]
        reviewer = ReportBodyReviewer()
        items = [StatementItem(
            id="1", account_name="应收账款", statement_type=StatementType.BALANCE_SHEET,
            sheet_name="资产负债表", row_index=1,
        )]
        notes = [NoteTable(id="1", account_name="应收账款", section_title="应收账款", headers=[], rows=[])]
        result = _run(reviewer.check_entity_name_consistency(
            "XX公司审计报告正文", items, notes, _mock_llm_service(findings_data)
        ))
        assert len(result) == 1
        assert result[0].confirmation_status == FindingConfirmationStatus.PENDING_CONFIRMATION

    def test_llm_failure_returns_empty(self):
        reviewer = ReportBodyReviewer()
        result = _run(reviewer.check_entity_name_consistency(
            "正文", [], [], _mock_llm_failure()
        ))
        assert len(result) == 0

    def test_template_compliance_no_template(self):
        reviewer = ReportBodyReviewer(template_service=None)
        result = _run(reviewer.check_template_compliance(
            "正文", ReportTemplateType.SOE, _mock_llm_service([])
        ))
        assert len(result) == 0  # 无模板，跳过

    def test_abbreviation_check(self):
        findings_data = [
            {"location": "第3段", "description": "简称不统一", "suggestion": "统一简称", "risk_level": "low"}
        ]
        reviewer = ReportBodyReviewer()
        result = _run(reviewer.check_abbreviation_consistency(
            "正文内容", "附注内容", _mock_llm_service(findings_data)
        ))
        assert len(result) == 1

    def test_empty_text_returns_empty(self):
        reviewer = ReportBodyReviewer()
        result = _run(reviewer.check_entity_name_consistency("", [], []))
        assert len(result) == 0


# ─── Note Content Reviewer ───

class TestNoteContentReviewer:
    def test_extract_narrative_sections(self):
        text = "一、公司基本情况\n公司成立于2020年。\n二、会计政策\n采用权责发生制。\n三、税项\n增值税率13%。"
        reviewer = NoteContentReviewer()
        sections = reviewer.extract_narrative_sections(text)
        assert len(sections) >= 3
        types = [s.section_type for s in sections]
        assert "basic_info" in types
        assert "accounting_policy" in types
        assert "tax" in types

    def test_expression_quality_with_llm(self):
        findings_data = [
            {"location": "第1段", "description": "表达不通顺", "suggestion": "修改", "risk_level": "low"}
        ]
        reviewer = NoteContentReviewer()
        section = NarrativeSection(
            id="1", section_type="basic_info", title="基本情况",
            content="公司成立于2020年", source_location="附注",
        )
        result = _run(reviewer.check_expression_quality(section, _mock_llm_service(findings_data)))
        assert len(result) == 1
        assert result[0].category == ReportReviewFindingCategory.NOTE_CONTENT
        assert result[0].confirmation_status == FindingConfirmationStatus.PENDING_CONFIRMATION

    def test_llm_failure_returns_empty(self):
        reviewer = NoteContentReviewer()
        section = NarrativeSection(
            id="1", section_type="basic_info", title="基本情况",
            content="内容", source_location="附注",
        )
        result = _run(reviewer.check_expression_quality(section, _mock_llm_failure()))
        assert len(result) == 0

    def test_policy_compliance_no_template(self):
        reviewer = NoteContentReviewer(template_service=None)
        section = NarrativeSection(
            id="1", section_type="accounting_policy", title="会计政策",
            content="内容", source_location="附注",
        )
        result = _run(reviewer.check_policy_template_compliance(
            section, ReportTemplateType.SOE, _mock_llm_service([])
        ))
        assert len(result) == 0


# ─── Text Quality Analyzer ───

class TestTextQualityAnalyzer:
    def test_mixed_punctuation_detection(self):
        analyzer = TextQualityAnalyzer()
        text = "这是一个测试,包含英文逗号的中文文本。"
        result = _run(analyzer.analyze_punctuation(text))
        assert len(result) >= 1
        assert result[0].category == ReportReviewFindingCategory.TEXT_QUALITY
        assert result[0].confirmation_status == FindingConfirmationStatus.PENDING_CONFIRMATION

    def test_no_issues_clean_text(self):
        analyzer = TextQualityAnalyzer()
        text = "这是一个正确的中文文本，没有标点问题。"
        result = _run(analyzer.analyze_punctuation(text))
        assert len(result) == 0

    def test_typos_with_llm(self):
        findings_data = [
            {"location": "第1行", "description": "错别字", "suggestion": "修正", "risk_level": "low"}
        ]
        analyzer = TextQualityAnalyzer()
        result = _run(analyzer.analyze_typos("审计报告文本", _mock_llm_service(findings_data)))
        assert len(result) == 1

    def test_llm_failure_returns_empty(self):
        analyzer = TextQualityAnalyzer()
        result = _run(analyzer.analyze_typos("文本", _mock_llm_failure()))
        assert len(result) == 0

    def test_empty_text(self):
        analyzer = TextQualityAnalyzer()
        result = _run(analyzer.analyze_punctuation(""))
        assert len(result) == 0
