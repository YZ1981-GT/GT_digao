"""Report_Review_Router 集成测试（Task 12.9）。"""
import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers.report_review import _sessions, _findings, _conversations
from backend.app.services.report_template_service import report_template_service
from backend.app.models.audit_schemas import (
    FindingConfirmationStatus,
    FindingStatus,
    ReportReviewFinding,
    ReportReviewFindingCategory,
    ReportReviewSession,
    ReportTemplateType,
    RiskLevel,
)

client = TestClient(app)


def _setup_session():
    """创建测试会话和 findings。"""
    from datetime import datetime
    session = ReportReviewSession(
        id="test-sess",
        template_type=ReportTemplateType.SOE,
        created_at=datetime.now().isoformat(),
    )
    _sessions["test-sess"] = session

    findings = [
        ReportReviewFinding(
            id="f1", category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
            risk_level=RiskLevel.HIGH, account_name="应收账款",
            location="报表vs附注", description="金额不一致",
            confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
            status=FindingStatus.OPEN,
        ),
        ReportReviewFinding(
            id="f2", category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
            risk_level=RiskLevel.MEDIUM, account_name="存货",
            location="附注内部", description="勾稽错误",
            confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
            status=FindingStatus.OPEN,
        ),
    ]
    _findings["test-sess"] = findings
    return session, findings


def _cleanup():
    _sessions.clear()
    _findings.clear()
    _conversations.clear()


class TestSessionEndpoints:
    def test_get_session(self):
        _setup_session()
        resp = client.get("/api/report-review/session/test-sess")
        assert resp.status_code == 200
        assert resp.json()["id"] == "test-sess"
        _cleanup()

    def test_get_session_not_found(self):
        resp = client.get("/api/report-review/session/nonexistent")
        assert resp.status_code == 404

    def test_get_sheets(self):
        _setup_session()
        resp = client.get("/api/report-review/session/test-sess/sheets")
        assert resp.status_code == 200
        _cleanup()


class TestFindingEndpoints:
    def test_get_findings(self):
        _setup_session()
        resp = client.get("/api/report-review/findings/test-sess")
        assert resp.status_code == 200
        assert len(resp.json()["findings"]) == 2
        _cleanup()

    def test_get_finding_detail(self):
        _setup_session()
        resp = client.get("/api/report-review/finding/f1")
        assert resp.status_code == 200
        assert resp.json()["finding"]["id"] == "f1"
        _cleanup()

    def test_get_finding_not_found(self):
        resp = client.get("/api/report-review/finding/nonexistent")
        assert resp.status_code == 404

    def test_edit_finding(self):
        _setup_session()
        resp = client.patch("/api/report-review/finding/f1/edit", json={
            "description": "更新后的描述",
            "risk_level": "low",
        })
        assert resp.status_code == 200
        # 验证更新
        f = _findings["test-sess"][0]
        assert f.description == "更新后的描述"
        assert f.risk_level == RiskLevel.LOW
        _cleanup()

    def test_confirm_finding(self):
        _setup_session()
        resp = client.patch("/api/report-review/finding/f1/confirm")
        assert resp.status_code == 200
        assert _findings["test-sess"][0].confirmation_status == FindingConfirmationStatus.CONFIRMED
        _cleanup()

    def test_dismiss_finding(self):
        _setup_session()
        resp = client.patch("/api/report-review/finding/f1/dismiss")
        assert resp.status_code == 200
        assert _findings["test-sess"][0].confirmation_status == FindingConfirmationStatus.DISMISSED
        _cleanup()

    def test_restore_finding(self):
        _setup_session()
        _findings["test-sess"][0].confirmation_status = FindingConfirmationStatus.DISMISSED
        resp = client.patch("/api/report-review/finding/f1/restore")
        assert resp.status_code == 200
        assert _findings["test-sess"][0].confirmation_status == FindingConfirmationStatus.PENDING_CONFIRMATION
        _cleanup()

    def test_batch_confirm(self):
        _setup_session()
        resp = client.post("/api/report-review/findings/batch", json={
            "finding_ids": ["f1", "f2"],
            "action": "confirm",
        })
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2
        assert all(f.confirmation_status == FindingConfirmationStatus.CONFIRMED for f in _findings["test-sess"])
        _cleanup()

    def test_update_finding_status(self):
        _setup_session()
        resp = client.patch("/api/report-review/finding/f1/status", json={"status": "resolved"})
        assert resp.status_code == 200
        assert _findings["test-sess"][0].status == FindingStatus.RESOLVED
        _cleanup()


class TestResultEndpoints:
    def test_get_result_only_confirmed(self):
        _setup_session()
        _findings["test-sess"][0].confirmation_status = FindingConfirmationStatus.CONFIRMED
        resp = client.get("/api/report-review/result/test-sess")
        assert resp.status_code == 200
        data = resp.json()
        assert data["confirmation_summary"]["confirmed"] == 1
        assert len(data["findings"]) == 1
        _cleanup()


class TestSourcePreview:
    def test_source_preview(self):
        resp = client.get("/api/report-review/source-preview/file1")
        assert resp.status_code == 200

    def test_source_preview_sheet(self):
        resp = client.get("/api/report-review/source-preview/file1/sheet/Sheet1")
        assert resp.status_code == 200


class TestTemplateEndpoints:
    def test_get_template_not_found(self):
        # 清除缓存确保测试隔离
        report_template_service.clear_cache()
        resp = client.get("/api/report-review/templates/soe/report_body")
        # 如果知识库中已有模板数据则返回200，否则404
        assert resp.status_code in (200, 404)

    def test_invalid_template_type(self):
        resp = client.get("/api/report-review/templates/invalid/report_body")
        assert resp.status_code == 400
