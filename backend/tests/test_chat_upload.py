"""POST /api/chat/upload 端点单元测试。"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ─── 辅助：创建临时文件并返回路径 ───

def _tmp_file(content: bytes, suffix: str) -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(content)
    f.close()
    return f.name


# ─── TXT 上传 ───

def test_upload_txt():
    path = _tmp_file("Hello 你好".encode("utf-8"), ".txt")
    try:
        with open(path, "rb") as f:
            resp = client.post(
                "/api/chat/upload",
                files={"file": ("test.txt", f, "text/plain")},
            )
        data = resp.json()
        assert resp.status_code == 200
        assert data["success"] is True
        assert data["filename"] == "test.txt"
        assert "Hello 你好" in data["content"]
        assert data["size"] > 0
    finally:
        os.unlink(path)


# ─── Markdown 上传 ───

def test_upload_md():
    path = _tmp_file("# Title\n\nSome content".encode("utf-8"), ".md")
    try:
        with open(path, "rb") as f:
            resp = client.post(
                "/api/chat/upload",
                files={"file": ("notes.md", f, "text/markdown")},
            )
        data = resp.json()
        assert data["success"] is True
        assert "# Title" in data["content"]
    finally:
        os.unlink(path)


# ─── CSV 上传 ───

def test_upload_csv():
    csv_content = "Name,Age,City\nAlice,30,Beijing\nBob,25,Shanghai\n"
    path = _tmp_file(csv_content.encode("utf-8"), ".csv")
    try:
        with open(path, "rb") as f:
            resp = client.post(
                "/api/chat/upload",
                files={"file": ("data.csv", f, "text/csv")},
            )
        data = resp.json()
        assert data["success"] is True
        assert "Alice" in data["content"]
        assert "Beijing" in data["content"]
    finally:
        os.unlink(path)


# ─── 不支持的格式 ───

def test_upload_unsupported_format():
    path = _tmp_file(b"binary data", ".zip")
    try:
        with open(path, "rb") as f:
            resp = client.post(
                "/api/chat/upload",
                files={"file": ("archive.zip", f, "application/zip")},
            )
        data = resp.json()
        assert data["success"] is False
        assert "不支持" in data["error"]
    finally:
        os.unlink(path)


# ─── 文件大小超限 ───

def test_upload_exceeds_size_limit():
    """用一个小文件模拟，通过 monkey-patch _MAX_UPLOAD_SIZE 来测试。"""
    from app.routers import chat as chat_module

    original = chat_module._MAX_UPLOAD_SIZE
    chat_module._MAX_UPLOAD_SIZE = 10  # 10 bytes

    path = _tmp_file(b"x" * 100, ".txt")
    try:
        with open(path, "rb") as f:
            resp = client.post(
                "/api/chat/upload",
                files={"file": ("big.txt", f, "text/plain")},
            )
        data = resp.json()
        assert data["success"] is False
        assert "超过限制" in data["error"]
    finally:
        chat_module._MAX_UPLOAD_SIZE = original
        os.unlink(path)


# ─── Excel 上传 ───

def test_upload_xlsx():
    """创建一个简单的 xlsx 文件并上传。"""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["科目", "金额"])
    ws.append(["现金", 1000])
    ws.append(["银行存款", 5000])

    path = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx").name
    wb.save(path)
    wb.close()

    try:
        with open(path, "rb") as f:
            resp = client.post(
                "/api/chat/upload",
                files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        data = resp.json()
        assert data["success"] is True
        assert "现金" in data["content"]
        assert "5000" in data["content"]
        assert "Sheet1" in data["content"]
    finally:
        os.unlink(path)
