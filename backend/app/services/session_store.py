"""会话持久化存储。

将 _sessions / _findings / _conversations 落盘到 data/sessions/ 目录，
服务重启后自动恢复。采用 JSON 文件存储，每个 session 一个子目录。

目录结构：
  data/sessions/{session_id}/
    session.json      — ReportReviewSession
    findings.json     — List[ReportReviewFinding]
    conversations.json — Dict[finding_id, FindingConversation]
"""
import json
import logging
import os
import threading
from typing import Dict, List, Optional

from ..models.audit_schemas import (
    FindingConversation,
    ReportReviewFinding,
    ReportReviewSession,
)

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "sessions")
_lock = threading.Lock()


def _ensure_dir(session_id: str) -> str:
    d = os.path.join(_BASE_DIR, session_id)
    os.makedirs(d, exist_ok=True)
    return d


# ─── Session ───

def save_session(session_id: str, session: ReportReviewSession) -> None:
    try:
        d = _ensure_dir(session_id)
        path = os.path.join(d, "session.json")
        data = session.model_dump(mode="json")
        with _lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("保存 session %s 失败: %s", session_id, e)


def load_session(session_id: str) -> Optional[ReportReviewSession]:
    path = os.path.join(_BASE_DIR, session_id, "session.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ReportReviewSession(**data)
    except Exception as e:
        logger.warning("加载 session %s 失败: %s", session_id, e)
        return None


# ─── Findings ───

def save_findings(session_id: str, findings: List[ReportReviewFinding]) -> None:
    try:
        d = _ensure_dir(session_id)
        path = os.path.join(d, "findings.json")
        data = [f.model_dump(mode="json") for f in findings]
        with _lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("保存 findings %s 失败: %s", session_id, e)


def load_findings(session_id: str) -> Optional[List[ReportReviewFinding]]:
    path = os.path.join(_BASE_DIR, session_id, "findings.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [ReportReviewFinding(**item) for item in data]
    except Exception as e:
        logger.warning("加载 findings %s 失败: %s", session_id, e)
        return None


# ─── Conversations ───

def save_conversations(session_id: str, convs: Dict[str, FindingConversation]) -> None:
    try:
        d = _ensure_dir(session_id)
        path = os.path.join(d, "conversations.json")
        data = {k: v.model_dump(mode="json") for k, v in convs.items()}
        with _lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("保存 conversations %s 失败: %s", session_id, e)


def load_conversations(session_id: str) -> Optional[Dict[str, FindingConversation]]:
    path = os.path.join(_BASE_DIR, session_id, "conversations.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: FindingConversation(**v) for k, v in data.items()}
    except Exception as e:
        logger.warning("加载 conversations %s 失败: %s", session_id, e)
        return None


# ─── 启动时恢复所有会话 ───

def restore_all() -> tuple:
    """恢复所有持久化的会话数据。

    Returns:
        (sessions_dict, findings_dict, conversations_dict)
    """
    sessions: Dict[str, ReportReviewSession] = {}
    findings: Dict[str, List[ReportReviewFinding]] = {}
    conversations: Dict[str, FindingConversation] = {}

    if not os.path.isdir(_BASE_DIR):
        return sessions, findings, conversations

    for sid in os.listdir(_BASE_DIR):
        sid_dir = os.path.join(_BASE_DIR, sid)
        if not os.path.isdir(sid_dir):
            continue
        s = load_session(sid)
        if s:
            sessions[sid] = s
        f = load_findings(sid)
        if f is not None:
            findings[sid] = f
        c = load_conversations(sid)
        if c:
            conversations.update(c)

    if sessions:
        logger.info("从磁盘恢复 %d 个会话、%d 组 findings",
                     len(sessions), len(findings))
    return sessions, findings, conversations
