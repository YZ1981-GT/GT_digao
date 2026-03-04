"""文档处理相关API路由"""
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from ..models.schemas import FileUploadResponse, AnalysisRequest, AnalysisType, WordExportRequest
from ..config import settings
from ..services.file_service import FileService
from ..services.openai_service import OpenAIService
from ..services.word_service import WordExportService
from ..utils.sse import sse_response, sse_with_heartbeat
from ..utils.prompt_manager import document_overview_system_prompt, document_requirements_system_prompt
import json
from urllib.parse import quote

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/document", tags=["文档处理"])


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """上传文档文件并提取文本内容"""
    try:
        # 检查文件类型（优先用扩展名判断，兼容不同浏览器的MIME类型）
        filename = file.filename or ""
        ext = filename.lower().split('.')[-1] if '.' in filename else ""
        
        allowed_types = [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ]
        
        # 某些浏览器对 .docx/.pdf 发送 application/octet-stream，此时仅靠扩展名判断
        is_octet_stream = file.content_type == "application/octet-stream"
        if ext not in settings.allowed_extensions and (not is_octet_stream and file.content_type not in allowed_types):
            return FileUploadResponse(
                success=False,
                message=f"不支持的文件类型，请上传PDF或Word文档（当前: {ext}, {file.content_type}）"
            )
        
        # 处理文件并提取文本
        file_content = await FileService.process_uploaded_file(file)
        
        return FileUploadResponse(
            success=True,
            message=f"文件 {file.filename} 上传成功",
            file_content=file_content
        )
        
    except Exception as e:
        return FileUploadResponse(
            success=False,
            message=f"文件处理失败: {str(e)}"
        )


@router.post("/analyze-stream")
async def analyze_document_stream(request: AnalysisRequest):
    """流式分析文档内容"""
    try:
        # 创建OpenAI服务实例（内部会加载配置）
        openai_service = OpenAIService()
        
        if not openai_service.api_key:
            raise HTTPException(status_code=400, detail="请先配置OpenAI API密钥")
        
        async def generate():
            # 构建分析提示词
            if request.analysis_type == AnalysisType.OVERVIEW:
                system_prompt = document_overview_system_prompt()
            else:  # requirements
                system_prompt = document_requirements_system_prompt()
            
            analysis_type_cn = "项目概述" if request.analysis_type == AnalysisType.OVERVIEW else "技术评分要求"
            user_prompt = f"请分析以下文档内容，提取{analysis_type_cn}信息：\n\n{request.file_content}"
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            # 流式返回分析结果
            async for chunk in openai_service.stream_chat_completion(messages, temperature=0.3):
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            
            # 发送结束信号
            yield "data: [DONE]\n\n"
        
        return sse_response(sse_with_heartbeat(generate()))
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档分析失败: {str(e)}")


@router.post("/export-word")
async def export_word(request: WordExportRequest):
    """根据目录数据导出Word文档"""
    try:
        service = WordExportService()
        buffer = service.build_document(
            outline_items=request.outline,
            project_name=request.project_name,
            project_overview=request.project_overview,
        )

        filename = f"{request.project_name or '审计文档'}.docx"
        encoded_filename = quote(filename)
        content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"
        headers = {"Content-Disposition": content_disposition}

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers,
        )
    except Exception as e:
        logger.error(f"导出Word失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出Word失败: {str(e)}")
