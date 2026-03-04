"""数据模型定义"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

from ..config import settings


class ConfigRequest(BaseModel):
    """OpenAI配置请求"""
    model_config = {"protected_namespaces": ()}
    
    api_key: str = Field(..., description="OpenAI API密钥")
    base_url: Optional[str] = Field(None, description="Base URL")
    model_name: str = Field(default=settings.default_model, description="模型名称")
    word_count: Optional[int] = Field(None, description="目标字数")


class ConfigResponse(BaseModel):
    """配置响应"""
    success: bool
    message: str


class ModelListResponse(BaseModel):
    """模型列表响应"""
    models: List[str]
    success: bool
    message: str = ""


class FileUploadResponse(BaseModel):
    """文件上传响应"""
    success: bool
    message: str
    file_content: Optional[str] = None
    old_outline: Optional[str] = None


class AnalysisType(str, Enum):
    """分析类型"""
    OVERVIEW = "overview"
    REQUIREMENTS = "requirements"


class AnalysisRequest(BaseModel):
    """文档分析请求"""
    file_content: str = Field(..., description="文档内容")
    analysis_type: AnalysisType = Field(..., description="分析类型")


class OutlineItem(BaseModel):
    """目录项"""
    id: str
    title: str
    description: str
    children: Optional[List['OutlineItem']] = None
    content: Optional[str] = None
    target_word_count: Optional[int] = None


# 解决循环引用
OutlineItem.model_rebuild()


class OutlineResponse(BaseModel):
    """目录响应"""
    outline: List[OutlineItem]


class OutlineRequest(BaseModel):
    """目录生成请求"""
    overview: str = Field(..., description="项目概述")
    requirements: str = Field(..., description="技术评分要求")
    uploaded_expand: Optional[bool] = Field(False, description="是否已上传方案扩写文件")
    old_outline: Optional[str] = Field(None, description="上传的方案扩写文件解析出的旧目录JSON")
    old_document: Optional[str] = Field(None, description="上传的方案扩写文件解析出的旧文档")

class ChapterContentRequest(BaseModel):
    """单章节内容生成请求"""
    chapter: Dict[str, Any] = Field(..., description="章节信息")
    parent_chapters: Optional[List[Dict[str, Any]]] = Field(None, description="上级章节列表")
    sibling_chapters: Optional[List[Dict[str, Any]]] = Field(None, description="同级章节列表")
    project_overview: str = Field("", description="项目概述")
    library_ids: Optional[List[str]] = Field(None, description="要使用的知识库ID列表")
    library_docs: Optional[Dict[str, List[str]]] = Field(None, description="要使用的具体文档，格式: {库ID: [文档ID列表]}")
    web_references: Optional[List[Dict[str, str]]] = Field(None, description="网络搜索参考资料，格式: [{title, url, content}]")


class ErrorResponse(BaseModel):
    """错误响应 - 保留用于 OpenAPI 文档中的错误响应模型"""
    error: str
    detail: Optional[str] = None


class WordExportRequest(BaseModel):
    """Word导出请求"""
    project_name: Optional[str] = Field(None, description="项目名称")
    project_overview: Optional[str] = Field(None, description="项目概述")
    outline: List[OutlineItem] = Field(..., description="目录结构，包含内容")


class ChapterRevisionMessage(BaseModel):
    """章节修改对话消息"""
    role: str = Field(..., description="角色: user 或 assistant")
    content: str = Field(..., description="消息内容")


class ChapterRevisionRequest(BaseModel):
    """章节修改请求"""
    chapter: Dict[str, Any] = Field(..., description="章节信息")
    current_content: str = Field(..., description="当前章节内容")
    messages: List[ChapterRevisionMessage] = Field(..., description="对话历史")
    user_instruction: str = Field(..., description="用户修改指令")
    project_overview: str = Field("", description="项目概述")
    parent_chapters: Optional[List[Dict[str, Any]]] = Field(None, description="上级章节列表")
    sibling_chapters: Optional[List[Dict[str, Any]]] = Field(None, description="同级章节列表")
    library_docs: Optional[Dict[str, List[str]]] = Field(None, description="要使用的具体文档")
    web_references: Optional[List[Dict[str, str]]] = Field(None, description="网络搜索参考资料")