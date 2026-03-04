from fastapi import APIRouter, UploadFile, File
from ..models.schemas import FileUploadResponse
from ..config import settings
from ..services.file_service import FileService
from ..utils import prompt_manager
from ..services.openai_service import OpenAIService
import json

router = APIRouter(prefix="/api/expand", tags=["文档扩写"])


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """上传文档文件并提取文本内容"""
    try:
        # 检查 API Key 配置（通过 OpenAIService 加载）
        openai_service = OpenAIService()
        if not openai_service.api_key:
            return FileUploadResponse(
                success=False,
                message="请先配置API Key后再上传参考目录"
            )

        # 检查文件类型（优先用扩展名判断）
        filename = file.filename or ""
        ext = filename.lower().split('.')[-1] if '.' in filename else ""
        
        allowed_types = [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ]
        
        is_octet_stream = file.content_type == "application/octet-stream"
        if ext not in settings.allowed_extensions and (not is_octet_stream and file.content_type not in allowed_types):
            return FileUploadResponse(
                success=False,
                message=f"不支持的文件类型，请上传PDF或Word文档（当前: {ext}）"
            )
        
        # 处理文件并提取文本
        file_content = await FileService.process_uploaded_file(file)
        
        # 提取目录（复用前面已创建的 openai_service）
        messages = [
            {"role": "system", "content": prompt_manager.read_expand_outline_prompt()},
            {"role": "user", "content": file_content}
        ]
        full_content = ""
        async for chunk in openai_service.stream_chat_completion(messages, temperature=0.7, response_format={"type": "json_object"}):
            full_content += chunk
        
        # 校验返回的JSON是否有效
        try:
            json.loads(full_content)
        except json.JSONDecodeError as e:
            return FileUploadResponse(
                success=False,
                message=f"AI返回的目录结构解析失败: {str(e)}"
            )
        
        return FileUploadResponse(
            success=True,
            message=f"文件 {file.filename} 上传成功",
            file_content=file_content,
            old_outline=full_content
        )
        
    except Exception as e:
        return FileUploadResponse(
            success=False,
            message=f"文件处理失败: {str(e)}"
        )