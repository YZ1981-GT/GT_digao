"""模板管理 API 路由

提供模板上传、列表、详情、删除和更新等端点。
"""

import logging
import os
import shutil
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..services.template_service import TemplateManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/template", tags=["template"])

# Service instance
template_manager = TemplateManager()

SUPPORTED_FORMATS = {".docx", ".xlsx", ".xls", ".pdf"}


@router.post("/upload")
async def upload_template(
    file: UploadFile = File(...),
    template_type: str = Form("custom"),
):
    """上传模板"""
    try:
        filename = file.filename or "unknown"
        ext = os.path.splitext(filename)[1].lower()

        if ext not in SUPPORTED_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式: {ext}，支持: {', '.join(SUPPORTED_FORMATS)}",
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            info = await template_manager.upload_template(tmp_path, filename, template_type)
            return {"success": True, "template": info.model_dump()}
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("模板上传失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"模板上传失败: {str(e)}")


@router.get("/list")
async def list_templates():
    """获取模板列表"""
    try:
        templates = template_manager.list_templates()
        return {"success": True, "templates": [t.model_dump() for t in templates]}
    except Exception as e:
        logger.error("获取模板列表失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取模板列表失败: {str(e)}")


@router.get("/{template_id}")
async def get_template(template_id: str):
    """获取模板详情"""
    try:
        info = template_manager.get_template(template_id)
        if not info:
            raise HTTPException(status_code=404, detail="模板不存在")
        return {"success": True, "template": info.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取模板详情失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取模板详情失败: {str(e)}")


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    """删除模板"""
    try:
        success = template_manager.delete_template(template_id)
        if not success:
            raise HTTPException(status_code=404, detail="模板不存在")
        return {"success": True, "message": "模板已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("模板删除失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"模板删除失败: {str(e)}")


@router.put("/{template_id}")
async def update_template(template_id: str, file: UploadFile = File(...)):
    """更新模板（重新上传）"""
    try:
        filename = file.filename or "unknown"
        ext = os.path.splitext(filename)[1].lower()

        if ext not in SUPPORTED_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式: {ext}，支持: {', '.join(SUPPORTED_FORMATS)}",
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            info = await template_manager.update_template(template_id, tmp_path, filename)
            return {"success": True, "template": info.model_dump()}
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("模板更新失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"模板更新失败: {str(e)}")
