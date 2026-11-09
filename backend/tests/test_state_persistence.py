"""路由状态持久化回归测试：确认匹配落盘、文档分析章节写回与快照恢复。"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.analysis_schemas import AnalysisChapter, AnalysisDocumentInfo, AnalysisProject
from app.models.audit_schemas import MatchingMap, ReportReviewSession, ReportTemplateType
from app.routers import analysis as analysis_router
from app.routers import report_review as rr_router
from app.services import json_snapshot

client = TestClient(app)


@pytest.fixture
def tmp_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(json_snapshot, "_BASE_DIR", str(tmp_path))
    return tmp_path


def test_confirm_matching_saves_session(monkeypatch):
    saved = {}
    monkeypatch.setattr(rr_router.session_store, "save_session",
                        lambda sid, s: saved.setdefault(sid, s))
    sid = "t-cm-001"
    rr_router._sessions[sid] = ReportReviewSession(
        id=sid, template_type=ReportTemplateType.SOE, created_at="t")
    try:
        resp = client.post("/api/report-review/confirm-matching", json={
            "session_id": sid, "matching_map": MatchingMap().model_dump()})
        assert resp.status_code == 200
        assert sid in saved and saved[sid].status == "matched"
    finally:
        rr_router._sessions.pop(sid, None)


def _make_project():
    doc = AnalysisDocumentInfo(
        id="d-1", filename="a.txt", file_format=".txt", file_size=1,
        content_text="原文", parsed_at="t", original_file_path="x/a.txt")
    proj = AnalysisProject(
        id="p-1", documents=[doc],
        outline=[AnalysisChapter(id="c1", title="第一章")], created_at="t")
    return doc, proj


def test_generate_chapter_writes_back_and_persists(tmp_snapshots, monkeypatch):
    doc, proj = _make_project()
    analysis_router._analysis_documents[doc.id] = doc
    analysis_router._analysis_projects[proj.id] = proj

    async def fake_gen(**kwargs):
        yield 'data: {"status": "streaming", "content": "片段"}\n\n'
        payload = {"status": "completed", "content": "生成的正文",
                   "sources": [{"doc_id": "d-1", "doc_name": "a.txt", "excerpt": "原文"}]}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    monkeypatch.setattr(analysis_router.analysis_service, "generate_chapter_content", fake_gen)
    try:
        resp = client.post("/api/analysis/generate-chapter",
                           json={"project_id": "p-1", "chapter_id": "c1"})
        assert resp.status_code == 200
        _ = resp.text  # 消费完 SSE 流
        assert proj.outline[0].content == "生成的正文"
        assert proj.outline[0].sources[0].doc_id == "d-1"

        # 项目快照只存文档 ID，恢复时按 ID 关联文档
        analysis_router._persist_doc(doc)
        raw = json_snapshot.load_all("analysis_projects")["p-1"]
        assert raw["document_ids"] == ["d-1"] and "documents" not in raw
        restored = analysis_router._build_project(raw)
        assert restored.outline[0].content == "生成的正文"
        assert restored.documents[0].content_text == "原文"
    finally:
        analysis_router._analysis_documents.pop(doc.id, None)
        analysis_router._analysis_projects.pop(proj.id, None)


def test_build_project_accepts_legacy_snapshot():
    doc, proj = _make_project()
    legacy = proj.model_dump(mode="json")  # 旧格式：documents 为完整 dict
    restored = analysis_router._build_project(legacy)
    assert restored.documents[0].id == "d-1"


def test_delete_document_cascades_to_projects(tmp_snapshots):
    doc, proj = _make_project()
    analysis_router._analysis_documents[doc.id] = doc
    analysis_router._analysis_projects[proj.id] = proj
    try:
        resp = client.delete("/api/analysis/document/d-1")
        assert resp.status_code == 200
        assert proj.documents == []
        assert json_snapshot.load_all("analysis_projects")["p-1"]["document_ids"] == []
    finally:
        analysis_router._analysis_documents.pop(doc.id, None)
        analysis_router._analysis_projects.pop(proj.id, None)
