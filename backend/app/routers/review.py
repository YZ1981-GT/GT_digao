"""复核相关 API 路由

提供底稿上传、批量上传、引用检查、补充材料上传、
复核启动（SSE 流式）、报告查看/导出、问题状态更新和交叉引用分析等端点。
"""

import json
import logging
import os
import shutil
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ..models.audit_schemas import (
    ExportRequest,
    FindingStatusUpdate,
    ReferenceCheckRequest,
    ReviewRequest,
    SupplementaryMaterial,
)
from ..services.report_generator import ReportGenerator
from ..services.review_engine import ReviewEngine
from ..services.workpaper_parser import WorkpaperParser
from ..utils.sse import sse_response, sse_with_heartbeat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["review"])

# Service instances
workpaper_parser = WorkpaperParser()
review_engine = ReviewEngine()
report_generator = ReportGenerator()

# In-memory stores (production would use a database)
_parsed_workpapers: dict = {}  # id -> WorkpaperParseResult
_supplementary_materials: dict = {}  # id -> SupplementaryMaterial
_review_reports: dict = {}  # id -> ReviewReport


@router.post("/upload")
async def upload_workpaper(file: UploadFile = File(...)):
    """上传底稿文件（校验大小和格式）"""
    try:
        filename = file.filename or "unknown"
        ext = os.path.splitext(filename)[1].lower()

        if ext not in workpaper_parser.SUPPORTED_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式: {ext}，支持: {', '.join(workpaper_parser.SUPPORTED_FORMATS)}",
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            file_size = os.path.getsize(tmp_path)
            if file_size > workpaper_parser.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件大小超过限制（最大 {workpaper_parser.MAX_FILE_SIZE // (1024*1024)}MB）",
                )

            result = await workpaper_parser.parse_file(tmp_path, filename)
            _parsed_workpapers[result.id] = result
            return {"success": True, "message": "底稿上传成功", "workpaper": result.model_dump()}
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("底稿上传失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"底稿上传失败: {str(e)}")


@router.post("/upload-batch")
async def upload_batch(files: list[UploadFile] = File(...)):
    """批量上传底稿"""
    try:
        results = []
        for file in files:
            filename = file.filename or "unknown"
            ext = os.path.splitext(filename)[1].lower()

            if ext not in workpaper_parser.SUPPORTED_FORMATS:
                results.append({"success": False, "filename": filename, "error": f"不支持的文件格式: {ext}"})
                continue

            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                shutil.copyfileobj(file.file, tmp)
                tmp_path = tmp.name

            try:
                file_size = os.path.getsize(tmp_path)
                if file_size > workpaper_parser.MAX_FILE_SIZE:
                    results.append({"success": False, "filename": filename, "error": "文件大小超过限制"})
                    continue

                result = await workpaper_parser.parse_file(tmp_path, filename)
                _parsed_workpapers[result.id] = result
                results.append({"success": True, "workpaper": result.model_dump()})
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        return {"success": True, "results": results}
    except Exception as e:
        logger.error("批量上传失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量上传失败: {str(e)}")


@router.post("/check-references")
async def check_references(request: ReferenceCheckRequest):
    """检查复核所需的相关底稿"""
    try:
        workpapers = [_parsed_workpapers[wid] for wid in request.workpaper_ids if wid in _parsed_workpapers]
        if not workpapers:
            raise HTTPException(status_code=404, detail="未找到指定底稿")

        refs = await review_engine.check_required_references(
            workpapers[0], request.workpaper_ids
        )
        return {"success": True, "references": [r.model_dump() for r in refs]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("引用检查失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"引用检查失败: {str(e)}")


@router.post("/upload-supplementary")
async def upload_supplementary(
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
):
    """上传补充材料（文件或文本）"""
    try:
        from datetime import datetime, timezone

        material_id = uuid.uuid4().hex[:12]
        parsed_content = ""
        mat_type = "text"
        fname = None

        if file and file.filename:
            mat_type = "file"
            fname = file.filename
            ext = os.path.splitext(fname)[1].lower()

            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                shutil.copyfileobj(file.file, tmp)
                tmp_path = tmp.name

            try:
                result = await workpaper_parser.parse_file(tmp_path, fname)
                parsed_content = result.content_text
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        elif text_content:
            parsed_content = text_content
        else:
            raise HTTPException(status_code=400, detail="请提供文件或文本内容")

        material = SupplementaryMaterial(
            id=material_id,
            type=mat_type,
            filename=fname,
            text_content=text_content,
            parsed_content=parsed_content,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
        )
        _supplementary_materials[material_id] = material
        return {"success": True, "material": material.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("补充材料上传失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"补充材料上传失败: {str(e)}")


@router.post("/start")
async def start_review(request: ReviewRequest):
    """发起复核（SSE 流式响应）"""
    try:
        workpapers = [_parsed_workpapers[wid] for wid in request.workpaper_ids if wid in _parsed_workpapers]
        if not workpapers:
            raise HTTPException(status_code=404, detail="未找到指定底稿")

        # Gather supplementary materials
        supplementary = None
        if request.supplementary_material_ids:
            supplementary = [
                _supplementary_materials[mid]
                for mid in request.supplementary_material_ids
                if mid in _supplementary_materials
            ]

        async def generate():
            try:
                report = None
                async for event_str in review_engine.review_workpaper_stream(
                    workpaper=workpapers[0],
                    dimensions=[d.value for d in request.dimensions],
                    custom_dimensions=request.custom_dimensions,
                    prompt_id=request.prompt_id,
                    custom_prompt=request.custom_prompt,
                    supplementary_materials=supplementary,
                ):
                    yield f"data: {event_str}\n\n"
                    # Try to capture the completed report
                    try:
                        evt = json.loads(event_str)
                        if evt.get("status") == "completed" and "report" in evt:
                            from ..models.audit_schemas import ReviewReport
                            report = ReviewReport(**evt["report"])
                            _review_reports[report.id] = report
                    except (json.JSONDecodeError, Exception):
                        pass
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return sse_response(sse_with_heartbeat(generate()))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("复核启动失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"复核启动失败: {str(e)}")


@router.get("/report/{review_id}")
async def get_report(review_id: str):
    """获取复核报告"""
    report = _review_reports.get(review_id)
    if not report:
        raise HTTPException(status_code=404, detail="复核报告不存在")
    return {"success": True, "report": report.model_dump()}


@router.post("/report/{review_id}/export")
async def export_report(review_id: str, request: ExportRequest):
    """导出复核报告（Word/PDF）"""
    try:
        report = _review_reports.get(review_id)
        if not report:
            raise HTTPException(status_code=404, detail="复核报告不存在")

        fmt = request.format.lower()
        if fmt == "word":
            content = report_generator.export_to_word(report)
            return Response(
                content=content,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f'attachment; filename="review_report_{review_id}.docx"'},
            )
        elif fmt == "pdf":
            content = report_generator.export_to_pdf(report)
            return Response(
                content=content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="review_report_{review_id}.pdf"'},
            )
        else:
            raise HTTPException(status_code=400, detail=f"不支持的导出格式: {fmt}，支持: word, pdf")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("报告导出失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"报告导出失败: {str(e)}")


@router.patch("/finding/{finding_id}/status")
async def update_finding_status(finding_id: str, request: FindingStatusUpdate):
    """更新问题处理状态"""
    try:
        from datetime import datetime, timezone

        for report in _review_reports.values():
            for finding in report.findings:
                if finding.id == finding_id:
                    finding.status = request.status
                    if request.status.value == "resolved":
                        finding.resolved_at = datetime.now(timezone.utc).isoformat()
                    return {"success": True, "message": "状态已更新"}

        raise HTTPException(status_code=404, detail="未找到指定问题")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("状态更新失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"状态更新失败: {str(e)}")


@router.get("/cross-references/{project_id}")
async def get_cross_references(project_id: str):
    """获取交叉引用分析"""
    try:
        # Gather all workpapers for the project
        workpapers = list(_parsed_workpapers.values())
        if not workpapers:
            return {"success": True, "analysis": {"references": [], "missing_references": [], "consistency_findings": []}}

        analysis = await review_engine.analyze_cross_references(workpapers)
        return {"success": True, "analysis": analysis.model_dump()}
    except Exception as e:
        logger.error("交叉引用分析失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"交叉引用分析失败: {str(e)}")
