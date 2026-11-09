"""JSON 快照存储的回归测试。"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import json_snapshot as snap


@pytest.fixture(autouse=True)
def _tmp_base(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "_BASE_DIR", str(tmp_path))


def test_save_and_load_roundtrip():
    assert snap.save("ns", "a1", {"x": 1, "t": "中文"}) is True
    assert snap.load_all("ns") == {"a1": {"x": 1, "t": "中文"}}


def test_builder_applied_and_corrupt_file_skipped(tmp_path):
    snap.save("ns", "ok", {"v": 2})
    ns_dir = tmp_path / "ns"
    (ns_dir / "bad.json").write_text("{not json", encoding="utf-8")
    result = snap.load_all("ns", lambda d: d["v"] * 10)
    assert result == {"ok": 20}


def test_illegal_ids_rejected():
    assert snap.save("ns", "../evil", {}) is False
    assert snap.save("../ns", "a", {}) is False
    assert snap.load_all("../ns") == {}


def test_no_tmp_files_left_behind(tmp_path):
    snap.save("ns", "a", {"x": 1})
    assert [p.name for p in (tmp_path / "ns").iterdir()] == ["a.json"]


def test_delete():
    snap.save("ns", "a", {"x": 1})
    snap.delete("ns", "a")
    snap.delete("ns", "missing")  # 不存在也不报错
    assert snap.load_all("ns") == {}


def test_prune_removes_only_old_snapshots(tmp_path):
    snap.save("ns", "old", {"x": 1})
    snap.save("ns", "new", {"x": 2})
    old_path = tmp_path / "ns" / "old.json"
    past = time.time() - 100 * 86400
    os.utime(old_path, (past, past))
    assert snap.prune("ns", max_age_days=90) == 1
    assert set(snap.load_all("ns")) == {"new"}
