"""Report_Review_Engine 单元测试（Task 11.9）。"""
import asyncio
import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.models.audit_schemas import (
    ChangeAnalysis,
    FindingConfirmationStatus,
    FindingConversation,
    FindingConversationMessage,
    FindingStatus,
    MatchingEntry,
    MatchingMap,
    NoteTable,
    ReportReviewConfig,
    ReportReviewFinding,
    ReportReviewFindingCategory,
    ReportReviewSession,
    ReportTemplateType,
    RiskLevel,
    StatementItem,
    StatementType,
)
from app.services.report_review_engine import ReportReviewEngine


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_oai():
    svc = MagicMock()
    async def mock_stream(messages, temperature=0.3):
        yield "[]"
    svc.stream_chat_completion = mock_stream
    return svc


# ─── 变动计算 ───

class TestChangeCalculation:
    def test_calculate_changes(self):
        engine = ReportReviewEngine()
        items = [
            StatementItem(id="1", account_name="应收账款", statement_type=StatementType.BALANCE_SHEET,
                          sheet_name="资产负债表", opening_balance=100, closing_balance=200, row_index=1),
            StatementItem(id="2", account_name="存货", statement_type=StatementType.BALANCE_SHEET,
                          sheet_name="资产负债表", opening_balance=500, closing_balance=400, row_index=2),
        ]
        changes = engine.calculate_changes(items)
        assert len(changes) == 2
        assert changes[0].change_amount == 100.0
        assert changes[0].change_percentage == 1.0  # 100/100
        assert changes[1].change_amount == -100.0

    def test_skip_sub_items(self):
        engine = ReportReviewEngine()
        items = [
            StatementItem(id="1", account_name="应收账款", statement_type=StatementType.BALANCE_SHEET,
                          sheet_name="资产负债表", opening_balance=100, closing_balance=200, row_index=1),
            StatementItem(id="2", account_name="其中：A", statement_type=StatementType.BALANCE_SHEET,
                          sheet_name="资产负债表", opening_balance=50, closing_balance=100, row_index=2,
                          is_sub_item=True, parent_id="1"),
        ]
        changes = engine.calculate_changes(items)
        assert len(changes) == 1

    def test_zero_opening_balance(self):
        engine = ReportReviewEngine()
        items = [
            StatementItem(id="1", account_name="新科目", statement_type=StatementType.BALANCE_SHEET,
                          sheet_name="资产负债表", opening_balance=0, closing_balance=100, row_index=1),
        ]
        changes = engine.calculate_changes(items)
        assert changes[0].change_amount == 100.0
        assert changes[0].change_percentage is None  # 0 opening


class TestThresholdFlagging:
    def test_flag_above_threshold(self):
        engine = ReportReviewEngine()
        changes = [
            ChangeAnalysis(statement_item_id="1", account_name="A",
                           opening_balance=100, closing_balance=200,
                           change_amount=100, change_percentage=1.0),
            ChangeAnalysis(statement_item_id="2", account_name="B",
                           opening_balance=100, closing_balance=110,
                           change_amount=10, change_percentage=0.1),
        ]
        engine.flag_abnormal_changes(changes, threshold=0.3)
        assert changes[0].exceeds_threshold is True
        assert changes[1].exceeds_threshold is False

    def test_below_threshold_no_flag(self):
        engine = ReportReviewEngine()
        changes = [
            ChangeAnalysis(statement_item_id="1", account_name="A",
                           opening_balance=100, closing_balance=120,
                           change_amount=20, change_percentage=0.2),
        ]
        engine.flag_abnormal_changes(changes, threshold=0.3)
        assert changes[0].exceeds_threshold is False


# ─── 结论生成 ───

class TestConclusion:
    def test_no_findings(self):
        engine = ReportReviewEngine()
        conclusion = engine._generate_conclusion([])
        assert "未发现" in conclusion

    def test_with_findings(self):
        engine = ReportReviewEngine()
        findings = [
            ReportReviewFinding(
                id="1", category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                risk_level=RiskLevel.HIGH, account_name="A", location="L",
                description="D", confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                status=FindingStatus.OPEN,
            ),
        ]
        conclusion = engine._generate_conclusion(findings)
        assert "1 个" in conclusion
        assert "高风险" in conclusion


# ─── SSE 流 ───

class TestSSEStream:
    def test_stream_starts_and_completes(self):
        engine = ReportReviewEngine()
        # Mock openai_service
        engine.openai_service  # trigger property

        session = ReportReviewSession(
            id="test-session",
            template_type=ReportTemplateType.SOE,
            statement_items=[],
            note_tables=[],
            created_at=datetime.now().isoformat(),
        )
        config = ReportReviewConfig(
            session_id="test-session",
            template_type=ReportTemplateType.SOE,
        )

        async def run():
            events = []
            async for event_str in engine.review_stream(session, config):
                events.append(json.loads(event_str))
            return events

        events = _run(run())
        statuses = [e["status"] for e in events]
        assert statuses[0] == "started"
        assert statuses[-1] == "completed"


# ─── 对话 ───

class TestFindingChat:
    def test_chat_records_messages(self):
        engine = ReportReviewEngine()
        finding = ReportReviewFinding(
            id="f1", category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
            risk_level=RiskLevel.HIGH, account_name="A", location="L",
            description="金额不一致", confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
            status=FindingStatus.OPEN,
        )
        conversation = FindingConversation(finding_id="f1")

        mock_svc = MagicMock()
        async def mock_stream(messages, temperature=0.5):
            yield "这是回复"
        mock_svc.stream_chat_completion = mock_stream

        async def run():
            events = []
            async for e in engine.chat_about_finding(finding, "为什么不一致？", conversation, mock_svc):
                events.append(json.loads(e))
            return events

        events = _run(run())
        assert len(conversation.messages) == 2  # user + assistant
        assert conversation.messages[0].role == "user"
        assert conversation.messages[1].role == "assistant"
        assert conversation.messages[1].content == "这是回复"


class TestTraceAnalysis:
    def test_trace_cross_reference(self):
        engine = ReportReviewEngine()
        finding = ReportReviewFinding(
            id="f1", category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
            risk_level=RiskLevel.HIGH, account_name="A", location="L",
            description="问题", confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
            status=FindingStatus.OPEN,
        )
        conversation = FindingConversation(finding_id="f1")

        mock_svc = MagicMock()
        async def mock_stream(messages, temperature=0.3):
            yield "溯源结果"
        mock_svc.stream_chat_completion = mock_stream

        async def run():
            events = []
            async for e in engine.trace_finding(finding, "cross_reference", conversation, mock_svc):
                events.append(json.loads(e))
            return events

        events = _run(run())
        assert len(conversation.messages) == 1
        assert conversation.messages[0].message_type == "trace"
        assert conversation.messages[0].trace_type == "cross_reference"
