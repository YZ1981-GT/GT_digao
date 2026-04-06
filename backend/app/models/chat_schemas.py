"""聊天功能相关数据模型"""
from pydantic import BaseModel, Field
from typing import List, Optional


class ChatMessage(BaseModel):
    """聊天消息"""
    role: str = Field(..., description="角色: user/assistant/system")
    content: str = Field(..., description="消息内容")


class ChatStreamRequest(BaseModel):
    """流式聊天请求"""
    messages: List[ChatMessage] = Field(..., description="对话历史")
    knowledge_library_ids: Optional[List[str]] = Field(None, description="要检索的知识库 ID 列表，非空时自动启用 RAG 检索")
    document_context: Optional[str] = Field(None, description="上传文档的文本内容")
    image_ocr_context: Optional[str] = Field(None, description="上传图片的 OCR 文本")


class ChatUploadResponse(BaseModel):
    """文档上传响应"""
    success: bool
    filename: str
    size: int
    content: str = ""
    ocr_method: str = ""
    error: Optional[str] = None


class SpeechToTextResponse(BaseModel):
    """语音识别响应"""
    success: bool
    text: str = ""
    error: Optional[str] = None


class ExportWordRequest(BaseModel):
    """Word 导出请求"""
    content: str = Field(..., description="Markdown 内容")
    filename: Optional[str] = Field(None, description="文件名（不含扩展名）")


class NoteCreateRequest(BaseModel):
    """笔记创建请求"""
    title: str = Field(..., description="笔记标题")
    content: str = Field(..., description="笔记内容 Markdown")
    date: Optional[str] = Field(None, description="日期 YYYY-MM-DD，默认今天")


class NoteItem(BaseModel):
    """笔记条目"""
    id: str
    title: str
    created_at: str
    size: int


class NoteGroup(BaseModel):
    """按日期分组的笔记"""
    date: str
    notes: List[NoteItem]


class NotesListResponse(BaseModel):
    """笔记列表响应"""
    groups: List[NoteGroup]
    total_count: int
    total_size: int


class CleanupSuggestRequest(BaseModel):
    """清理建议请求"""
    threshold_count: int = Field(50, description="笔记数量阈值")
    threshold_size_mb: float = Field(5.0, description="笔记总大小阈值（MB）")


class CleanupSuggestion(BaseModel):
    """清理建议条目"""
    doc_id: str
    title: str
    created_at: str
    reason: str
    last_rag_reference: Optional[str] = None


class CleanupSuggestResponse(BaseModel):
    """清理建议响应"""
    suggestions: List[CleanupSuggestion]


class PolishRequest(BaseModel):
    """AI 润色请求"""
    content: str = Field(..., description="待润色的 Markdown 内容")


class KnowledgeMoveRequest(BaseModel):
    """知识库文档移动/复制请求"""
    doc_ids: List[str] = Field(..., description="文档 ID 列表")
    source_library_id: str = Field(..., description="源知识库 ID")
    target_library_id: str = Field(..., description="目标知识库 ID")
    target_date_folder: Optional[str] = Field(None, description="目标日期文件夹（仅笔记库）")
