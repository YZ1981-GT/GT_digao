"""审计项目管理服务。

存储路径：~/.gt_audit_helper/projects/{project_id}/
采用 JSON 文件存储项目元数据，与 ConfigManager 的文件存储模式一致。
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..models.audit_schemas import (
    ProjectCreateRequest,
    ProjectDetail,
    ProjectReviewSummary,
    RiskLevel,
)

logger = logging.getLogger(__name__)

# 角色权限映射
ROLE_PERMISSIONS: Dict[str, set] = {
    "partner": {
        "create_project",
        "delete_project",
        "manage_members",
        "review",
        "export",
        "delete_workpaper",
        "manage_templates",
    },
    "manager": {
        "create_project",
        "manage_members",
        "review",
        "export",
        "delete_workpaper",
        "manage_templates",
    },
    "senior_auditor": {"review", "export", "manage_templates"},
    "auditor": {"review", "export"},
    "qc": {"review"},
}


class ProjectService:
    """审计项目管理服务。

    项目数据以 JSON 文件存储在 ~/.gt_audit_helper/projects/{project_id}/ 目录下。
    """

    PROJECT_DIR = os.path.join(
        os.path.expanduser("~"), ".gt_audit_helper", "projects"
    )

    def __init__(self) -> None:
        os.makedirs(self.PROJECT_DIR, exist_ok=True)

    # ─── 内部工具方法 ───

    def _project_dir(self, project_id: str) -> str:
        """返回项目目录路径。"""
        return os.path.join(self.PROJECT_DIR, project_id)

    def _project_json_path(self, project_id: str) -> str:
        """返回项目 JSON 文件路径。"""
        return os.path.join(self._project_dir(project_id), "project.json")

    def _reviews_dir(self, project_id: str) -> str:
        """返回项目复核结果目录路径。"""
        return os.path.join(self._project_dir(project_id), "reviews")

    def _load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """从磁盘加载项目 JSON 数据。"""
        path = self._project_json_path(project_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load project %s: %s", project_id, exc)
            return None

    def _save_project(self, data: Dict[str, Any]) -> None:
        """将项目数据写入磁盘。"""
        project_id = data["id"]
        proj_dir = self._project_dir(project_id)
        os.makedirs(proj_dir, exist_ok=True)
        path = self._project_json_path(project_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ─── 公开接口 ───

    def create_project(self, request: ProjectCreateRequest) -> ProjectDetail:
        """创建审计项目。"""
        project_id = str(uuid4())
        now = self._now_iso()

        data: Dict[str, Any] = {
            "id": project_id,
            "name": request.name,
            "client_name": request.client_name,
            "audit_period": request.audit_period,
            "members": request.members,
            "workpaper_ids": [],
            "template_ids": [],
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }

        # 确保 reviews 子目录也创建
        os.makedirs(self._reviews_dir(project_id), exist_ok=True)
        self._save_project(data)

        logger.info("Created project %s (%s)", project_id, request.name)
        return self._to_detail(data)

    def get_project(self, project_id: str) -> Optional[ProjectDetail]:
        """获取项目详情。"""
        data = self._load_project(project_id)
        if data is None:
            return None
        return self._to_detail(data)

    def list_projects(
        self, user_id: Optional[str] = None, user_role: Optional[str] = None
    ) -> List[ProjectDetail]:
        """列出用户有权限访问的项目。

        - partner / qc 角色可查看所有项目。
        - 其他角色仅可查看自己作为成员的项目。
        - 若 user_id 和 user_role 均为 None，返回全部项目。
        """
        results: List[ProjectDetail] = []
        if not os.path.isdir(self.PROJECT_DIR):
            return results

        for entry in os.listdir(self.PROJECT_DIR):
            proj_dir = os.path.join(self.PROJECT_DIR, entry)
            if not os.path.isdir(proj_dir):
                continue
            data = self._load_project(entry)
            if data is None:
                continue

            # 权限过滤
            if user_id is not None and user_role is not None:
                if user_role in ("partner", "qc"):
                    pass  # 可查看所有项目
                else:
                    member_ids = [m.get("user_id") for m in data.get("members", [])]
                    if user_id not in member_ids:
                        continue

            results.append(self._to_detail(data))

        return results

    def add_workpaper_to_project(
        self, project_id: str, workpaper_id: str
    ) -> bool:
        """将底稿关联到项目。"""
        data = self._load_project(project_id)
        if data is None:
            return False

        wp_ids: List[str] = data.get("workpaper_ids", [])
        if workpaper_id not in wp_ids:
            wp_ids.append(workpaper_id)
            data["workpaper_ids"] = wp_ids
            data["updated_at"] = self._now_iso()
            self._save_project(data)

        return True

    def check_permission(self, user_role: str, action: str) -> bool:
        """检查用户角色是否有执行指定操作的权限。"""
        allowed = ROLE_PERMISSIONS.get(user_role, set())
        return action in allowed

    def get_project_review_summary(
        self, project_id: str
    ) -> ProjectReviewSummary:
        """计算项目复核进度概览。

        扫描 reviews 目录下的 JSON 文件，统计已复核/待复核数量和各风险等级问题数。
        """
        data = self._load_project(project_id)
        total = len(data.get("workpaper_ids", [])) if data else 0

        reviewed_count = 0
        high = 0
        medium = 0
        low = 0

        reviews_path = self._reviews_dir(project_id)
        if os.path.isdir(reviews_path):
            for fname in os.listdir(reviews_path):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(reviews_path, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        review = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue

                reviewed_count += 1
                for finding in review.get("findings", []):
                    level = finding.get("risk_level", "")
                    if level == RiskLevel.HIGH.value:
                        high += 1
                    elif level == RiskLevel.MEDIUM.value:
                        medium += 1
                    elif level == RiskLevel.LOW.value:
                        low += 1

        pending = max(total - reviewed_count, 0)

        return ProjectReviewSummary(
            total_workpapers=total,
            reviewed_workpapers=reviewed_count,
            pending_workpapers=pending,
            high_risk_count=high,
            medium_risk_count=medium,
            low_risk_count=low,
        )

    def filter_workpapers(
        self,
        project_id: str,
        business_cycle: Optional[str] = None,
        workpaper_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按业务循环和底稿类型筛选项目底稿。

        底稿元数据存储在项目目录下的 workpapers/ 子目录中。
        若无底稿元数据文件，则返回空列表。
        """
        data = self._load_project(project_id)
        if data is None:
            return []

        workpapers_dir = os.path.join(self._project_dir(project_id), "workpapers")
        if not os.path.isdir(workpapers_dir):
            return []

        results: List[Dict[str, Any]] = []
        for fname in os.listdir(workpapers_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(workpapers_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    wp = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            classification = wp.get("classification", {})

            if business_cycle and classification.get("business_cycle") != business_cycle:
                continue
            if workpaper_type and classification.get("workpaper_type") != workpaper_type:
                continue

            results.append(wp)

        return results

    def link_template_to_project(
        self, project_id: str, template_id: str
    ) -> bool:
        """将模板关联到项目。"""
        data = self._load_project(project_id)
        if data is None:
            return False

        tpl_ids: List[str] = data.get("template_ids", [])
        if template_id not in tpl_ids:
            tpl_ids.append(template_id)
            data["template_ids"] = tpl_ids
            data["updated_at"] = self._now_iso()
            self._save_project(data)

        return True

    # ─── 内部转换 ───

    @staticmethod
    def _to_detail(data: Dict[str, Any]) -> ProjectDetail:
        """将原始 dict 转换为 ProjectDetail 模型。"""
        return ProjectDetail(
            id=data["id"],
            name=data["name"],
            client_name=data["client_name"],
            audit_period=data.get("audit_period", ""),
            status=data.get("status", "active"),
            members=data.get("members", []),
            workpaper_count=len(data.get("workpaper_ids", [])),
            template_ids=data.get("template_ids", []),
            created_at=data["created_at"],
        )
