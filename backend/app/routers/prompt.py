"""提示词管理 API 路由

提供提示词列表、详情、保存、编辑、替换、恢复、删除等端点，
以及 Git 版本管理相关端点（配置、同步、推送、历史、冲突、标签）。

NOTE: Static path routes (/list, /save, /git/*) are defined BEFORE
parameterized routes (/{prompt_id}) to avoid FastAPI path conflicts.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..models.audit_schemas import (
    EditPromptRequest,
    GitConfig,
    GitPushRequest,
    GitResolveRequest,
    GitTagRequest,
    ReplacePromptRequest,
    SavePromptRequest,
)
from ..services.prompt_library import PromptLibrary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompt", tags=["prompt"])

# Service instance
prompt_library = PromptLibrary()


# ─── Static path routes (MUST come before /{prompt_id}) ───


@router.get("/list")
async def list_prompts(subject: Optional[str] = Query(None, description="会计科目筛选")):
    """获取提示词列表（支持会计科目筛选）"""
    try:
        prompts = prompt_library.list_prompts(subject=subject)
        return {"success": True, "prompts": [p.model_dump() for p in prompts]}
    except Exception as e:
        logger.error("获取提示词列表失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取提示词列表失败: {str(e)}")


@router.post("/save")
async def save_prompt(request: SavePromptRequest):
    """保存用户追加的自定义提示词"""
    try:
        info = prompt_library.save_custom_prompt(
            name=request.name,
            content=request.content,
            subject=request.subject,
        )
        return {"success": True, "prompt": info.model_dump()}
    except Exception as e:
        logger.error("保存提示词失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存提示词失败: {str(e)}")


# ─── Git 版本管理 (static paths, MUST come before /{prompt_id}) ───


@router.post("/git/config")
async def configure_git(config: GitConfig):
    """配置 Git 仓库关联"""
    try:
        result = prompt_library.git_service.configure(config)
        return {"success": result.success, "message": result.message}
    except Exception as e:
        logger.error("Git 配置失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Git 配置失败: {str(e)}")


@router.get("/git/config")
async def get_git_config():
    """获取 Git 仓库配置"""
    try:
        config = prompt_library.git_service.get_config()
        if not config:
            return {"success": True, "config": None}
        return {"success": True, "config": config.model_dump()}
    except Exception as e:
        logger.error("获取 Git 配置失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取 Git 配置失败: {str(e)}")


@router.post("/git/sync")
async def sync_git():
    """从 Git 仓库拉取同步最新提示词"""
    try:
        result = prompt_library.git_service.pull_latest()
        if result.success:
            prompt_library.refresh_presets()
        return {"success": result.success, "result": result.model_dump()}
    except Exception as e:
        logger.error("Git 同步失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Git 同步失败: {str(e)}")


@router.post("/git/push")
async def push_git(request: GitPushRequest):
    """将本地变更提交到 Git 仓库"""
    try:
        detail = prompt_library.get_prompt(request.prompt_id)
        if not detail:
            raise HTTPException(status_code=404, detail="提示词不存在")

        # Use source_file (actual filename) for git operations; fall back to name + .md
        changed_file = detail.source_file or f"{detail.name}.md"

        result = prompt_library.git_service.commit_and_push(
            changed_files=[changed_file],
            change_type=request.change_type,
            prompt_name=detail.name,
            operator=request.operator,
        )
        return {"success": result.success, "result": result.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Git 推送失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Git 推送失败: {str(e)}")


@router.get("/git/history")
async def get_git_history(
    file_path: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """获取 Git 版本历史"""
    try:
        history = prompt_library.git_service.get_commit_history(
            file_path=file_path, limit=limit
        )
        return {"success": True, "history": [h.model_dump() for h in history]}
    except Exception as e:
        logger.error("获取 Git 历史失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取 Git 历史失败: {str(e)}")


@router.get("/git/conflicts")
async def get_git_conflicts():
    """检测 Git 冲突"""
    try:
        conflicts = prompt_library.git_service.detect_conflicts()
        return {"success": True, "conflicts": [c.model_dump() for c in conflicts]}
    except Exception as e:
        logger.error("冲突检测失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"冲突检测失败: {str(e)}")


@router.post("/git/resolve")
async def resolve_git_conflict(request: GitResolveRequest):
    """解决 Git 冲突"""
    try:
        success = prompt_library.git_service.resolve_conflict(
            file_path=request.file_path,
            resolution=request.resolution,
            merged_content=request.merged_content,
        )
        return {"success": success, "message": "冲突已解决" if success else "冲突解决失败"}
    except Exception as e:
        logger.error("冲突解决失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"冲突解决失败: {str(e)}")


@router.post("/git/tag")
async def create_git_tag(request: GitTagRequest):
    """创建 Git 版本标签"""
    try:
        result = prompt_library.git_service.create_tag(
            tag_name=request.tag_name, message=request.message
        )
        return {"success": result.success, "message": result.message}
    except Exception as e:
        logger.error("标签创建失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"标签创建失败: {str(e)}")


@router.get("/git/tags")
async def list_git_tags():
    """列出所有 Git 标签"""
    try:
        tags = prompt_library.git_service.list_tags()
        return {"success": True, "tags": tags}
    except Exception as e:
        logger.error("获取标签列表失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取标签列表失败: {str(e)}")


# ─── Parameterized routes (MUST come after static paths) ───


@router.get("/{prompt_id}")
async def get_prompt(prompt_id: str):
    """获取提示词详情"""
    try:
        detail = prompt_library.get_prompt(prompt_id)
        if not detail:
            raise HTTPException(status_code=404, detail="提示词不存在")
        return {"success": True, "prompt": detail.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取提示词详情失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取提示词详情失败: {str(e)}")


@router.put("/{prompt_id}/edit")
async def edit_prompt(prompt_id: str, request: EditPromptRequest):
    """编辑预置提示词（保存为用户修改版本）"""
    try:
        info = prompt_library.edit_preset_prompt(prompt_id, request.content)
        return {"success": True, "prompt": info.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("编辑提示词失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"编辑提示词失败: {str(e)}")


@router.put("/{prompt_id}/replace")
async def replace_prompt(prompt_id: str, request: ReplacePromptRequest):
    """替换预置提示词（完全替换内容）"""
    try:
        info = prompt_library.replace_preset_prompt(prompt_id, request.content)
        return {"success": True, "prompt": info.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("替换提示词失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"替换提示词失败: {str(e)}")


@router.post("/{prompt_id}/restore")
async def restore_prompt(prompt_id: str):
    """恢复预置提示词为默认版本"""
    try:
        info = prompt_library.restore_preset_default(prompt_id)
        return {"success": True, "prompt": info.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("恢复提示词失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"恢复提示词失败: {str(e)}")


@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: str):
    """删除自定义提示词（预置提示词不可删除）"""
    try:
        prompt_library.delete_prompt(prompt_id)
        return {"success": True, "message": "提示词已删除"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("删除提示词失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除提示词失败: {str(e)}")
