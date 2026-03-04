"""项目管理 API 路由

提供项目创建、列表、详情、底稿关联、复核概览、底稿筛选和模板关联等端点。
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..models.audit_schemas import ProjectCreateRequest
from ..services.project_service import ProjectService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/project", tags=["project"])

# Service instance
project_service = ProjectService()


class WorkpaperLinkRequest(BaseModel):
    workpaper_id: str


class TemplateLinkRequest(BaseModel):
    template_id: str


@router.post("/create")
async def create_project(request: ProjectCreateRequest):
    """创建项目"""
    try:
        project = project_service.create_project(request)
        return {"success": True, "project": project.model_dump()}
    except Exception as e:
        logger.error("项目创建失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"项目创建失败: {str(e)}")


@router.get("/list")
async def list_projects(
    user_id: Optional[str] = Query(None),
    user_role: Optional[str] = Query(None),
):
    """获取项目列表（按权限过滤）"""
    try:
        projects = project_service.list_projects(
            user_id=user_id or "",
            user_role=user_role or "partner",
        )
        return {"success": True, "projects": [p.model_dump() for p in projects]}
    except Exception as e:
        logger.error("获取项目列表失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取项目列表失败: {str(e)}")


@router.get("/{project_id}")
async def get_project(project_id: str):
    """获取项目详情"""
    try:
        project = project_service.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        return {"success": True, "project": project.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取项目详情失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取项目详情失败: {str(e)}")


@router.post("/{project_id}/workpapers")
async def add_workpaper(project_id: str, request: WorkpaperLinkRequest):
    """关联底稿到项目"""
    try:
        success = project_service.add_workpaper_to_project(project_id, request.workpaper_id)
        if not success:
            raise HTTPException(status_code=404, detail="项目不存在")
        return {"success": True, "message": "底稿已关联到项目"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("底稿关联失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"底稿关联失败: {str(e)}")


@router.get("/{project_id}/summary")
async def get_project_summary(project_id: str):
    """获取复核进度概览"""
    try:
        summary = project_service.get_project_review_summary(project_id)
        return {"success": True, "summary": summary.model_dump()}
    except Exception as e:
        logger.error("获取复核概览失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取复核概览失败: {str(e)}")


@router.get("/{project_id}/workpapers")
async def filter_workpapers(
    project_id: str,
    business_cycle: Optional[str] = Query(None),
    workpaper_type: Optional[str] = Query(None),
):
    """获取项目底稿列表（支持筛选）"""
    try:
        workpapers = project_service.filter_workpapers(
            project_id=project_id,
            business_cycle=business_cycle,
            workpaper_type=workpaper_type,
        )
        return {"success": True, "workpapers": [w.model_dump() if hasattr(w, 'model_dump') else w for w in workpapers]}
    except Exception as e:
        logger.error("底稿筛选失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"底稿筛选失败: {str(e)}")


@router.post("/{project_id}/templates")
async def link_template(project_id: str, request: TemplateLinkRequest):
    """关联模板到项目"""
    try:
        success = project_service.link_template_to_project(project_id, request.template_id)
        if not success:
            raise HTTPException(status_code=404, detail="项目不存在")
        return {"success": True, "message": "模板已关联到项目"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("模板关联失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"模板关联失败: {str(e)}")
