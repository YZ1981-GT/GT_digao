"""文档生成 API 路由

提供模板大纲提取、大纲确认、逐章节生成（SSE）、
单章节生成（SSE）、章节修改（SSE）和文档导出等端点。
"""

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..models.audit_schemas import (
    DocumentExportRequest,
    GenerateRequest,
    GeneratedDocument,
    SectionGenerateRequest,
    SectionRevisionRequest,
)
from ..services.document_generator import DocumentGenerator
from ..utils.sse import sse_response, sse_with_heartbeat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/generate", tags=["generate"])

# Service instance
document_generator = DocumentGenerator()

# In-memory stores
_confirmed_outlines: dict = {}  # template_id -> outline
_generated_documents: dict = {}  # document_id -> GeneratedDocument


class ExtractOutlineRequest(BaseModel):
    template_id: str


class ConfirmOutlineRequest(BaseModel):
    template_id: str
    outline: List[Dict[str, Any]]


@router.post("/extract-outline")
async def extract_outline(request: ExtractOutlineRequest):
    """从模板提取章节大纲"""
    try:
        outline = await document_generator.extract_template_outline(request.template_id)
        return {"success": True, "outline": outline}
    except Exception as e:
        logger.error("大纲提取失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"大纲提取失败: {str(e)}")


@router.put("/confirm-outline")
async def confirm_outline(request: ConfirmOutlineRequest):
    """用户确认/调整大纲"""
    try:
        _confirmed_outlines[request.template_id] = request.outline
        return {"success": True, "message": "大纲已确认"}
    except Exception as e:
        logger.error("大纲确认失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"大纲确认失败: {str(e)}")


@router.post("/start")
async def start_generate(request: GenerateRequest):
    """逐章节生成文档（SSE 流式响应）"""
    try:
        async def generate():
            try:
                document = None
                async for event_str in document_generator.generate_document_stream(
                    template_id=request.template_id,
                    outline=request.outline,
                    knowledge_library_ids=request.knowledge_library_ids,
                    project_info=request.project_info,
                ):
                    yield f"data: {event_str}\n\n"
                    try:
                        evt = json.loads(event_str)
                        if evt.get("status") == "completed" and "document" in evt:
                            document = GeneratedDocument(**evt["document"])
                            _generated_documents[document.id] = document
                    except (json.JSONDecodeError, Exception):
                        pass
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return sse_response(sse_with_heartbeat(generate()))
    except Exception as e:
        logger.error("文档生成失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"文档生成失败: {str(e)}")


@router.post("/generate-section")
async def generate_section(request: SectionGenerateRequest):
    """单章节内容生成（SSE 流式）"""
    try:
        async def generate():
            try:
                full_content = ""
                async for chunk in document_generator._generate_section_content(
                    section=request.section,
                    parent_sections=request.parent_sections,
                    sibling_sections=request.sibling_sections,
                    project_info=request.project_info,
                    knowledge_context="",
                    target_word_count=request.section.get("target_word_count", 1500),
                ):
                    full_content += chunk
                    yield f"data: {json.dumps({'status': 'streaming', 'content': chunk}, ensure_ascii=False)}\n\n"

                yield f"data: {json.dumps({'status': 'completed', 'content': full_content}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return sse_response(sse_with_heartbeat(generate()))
    except Exception as e:
        logger.error("章节生成失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"章节生成失败: {str(e)}")


@router.post("/revise-section")
async def revise_section(request: SectionRevisionRequest):
    """AI 修改章节（SSE 流式）"""
    try:
        async def generate():
            try:
                full_content = ""
                async for chunk in document_generator.revise_section_stream(
                    section_index=request.section_index,
                    current_content=request.current_content,
                    user_instruction=request.user_instruction,
                    document_context=None,
                    messages=request.messages,
                    selected_text=request.selected_text,
                ):
                    full_content += chunk
                    yield f"data: {json.dumps({'status': 'streaming', 'content': chunk}, ensure_ascii=False)}\n\n"

                yield f"data: {json.dumps({'status': 'completed', 'content': full_content}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return sse_response(sse_with_heartbeat(generate()))
    except Exception as e:
        logger.error("章节修改失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"章节修改失败: {str(e)}")


@router.post("/export")
async def export_document(request: DocumentExportRequest):
    """导出生成文档（Word 格式）"""
    try:
        doc = _generated_documents.get(request.document_id)
        if not doc:
            # Build a minimal GeneratedDocument from the request
            doc = GeneratedDocument(
                id=request.document_id,
                template_id=request.template_id,
                sections=request.sections,
                project_info={"client_name": "", "audit_period": ""},
                generated_at="",
            )

        content = await document_generator.export_to_word(
            document=doc,
            template_id=request.template_id,
            font_settings=request.font_settings,
        )
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="document_{request.document_id}.docx"'},
        )
    except Exception as e:
        logger.error("文档导出失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"文档导出失败: {str(e)}")
