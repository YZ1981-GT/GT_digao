"""模块状态 JSON 快照存储。

为 review / generate / analysis 这类原先只在进程内存中保存状态的路由提供最小持久化：
  data/snapshots/{namespace}/{item_id}.json

特点：
- 原子写入（先写临时文件再 os.replace），避免进程中断留下半截 JSON；
- 保存失败记录 error 日志并返回 False，不影响主流程；
- 启动恢复时单个文件损坏只跳过并记日志，不阻断服务启动。
"""
import json
import logging
import os
import re
import tempfile
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "snapshots")
)
_lock = threading.Lock()
# namespace / item_id 只允许安全字符，防止路径穿越
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]+$")


def _dir_for(namespace: str) -> str:
    if not _SAFE_NAME.match(namespace):
        raise ValueError(f"非法的快照命名空间: {namespace!r}")
    return os.path.join(_BASE_DIR, namespace)


def _path_for(namespace: str, item_id: str) -> str:
    if not _SAFE_NAME.match(item_id):
        raise ValueError(f"非法的快照 ID: {item_id!r}")
    return os.path.join(_dir_for(namespace), f"{item_id}.json")


def save(namespace: str, item_id: str, data: Dict[str, Any]) -> bool:
    """原子写入一个快照；成功返回 True。"""
    try:
        path = _path_for(namespace, item_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock:
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp_path, path)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
        return True
    except Exception as e:
        logger.error("保存快照失败 %s/%s: %s", namespace, item_id, e)
        return False


def delete(namespace: str, item_id: str) -> None:
    try:
        path = _path_for(namespace, item_id)
        with _lock:
            if os.path.isfile(path):
                os.remove(path)
    except Exception as e:
        logger.warning("删除快照失败 %s/%s: %s", namespace, item_id, e)


def load_all(namespace: str, builder: Optional[Callable[[Dict[str, Any]], Any]] = None) -> Dict[str, Any]:
    """读取命名空间下全部快照，返回 {item_id: 对象}。

    builder 将 JSON dict 转为业务对象；某个文件解析/构建失败时跳过该文件。
    """
    result: Dict[str, Any] = {}
    try:
        d = _dir_for(namespace)
    except ValueError as e:
        logger.error("%s", e)
        return result
    if not os.path.isdir(d):
        return result
    for name in os.listdir(d):
        if not name.endswith(".json"):
            continue
        item_id = name[:-5]
        try:
            with open(os.path.join(d, name), "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            result[item_id] = builder(data) if builder else data
        except Exception as e:
            logger.warning("跳过无法恢复的快照 %s/%s: %s", namespace, name, e)
    return result
