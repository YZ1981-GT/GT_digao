"""文档分析处理相关数据模型"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class AnalysisMode(str, Enum):
    """分析模式"""
    SUMMARY = "summary"           # 总结分析
    CONSOLIDATION = "consolidation"  # 整理汇总
    LEDGER = "ledger"             # 生成汇总台账


# 各模式默认目标字数
ANALYSIS_MODE_CONFIG: Dict[str, Dict[str, Any]] = {
    "summary": {"label": "总结分析", "default_word_count": 3000, "description": "对上传文档进行总结提炼，提取核心要点"},
    "consolidation": {"label": "整理汇总", "default_word_count": 5000, "description": "对多个文档进行整理汇总，形成统一报告"},
    "ledger": {"label": "生成汇总台账", "default_word_count": 8000, "description": "基于文档内容生成结构化汇总台账"},
}


class AnalysisDocumentInfo(BaseModel):
    """上传文档的解析缓存信息"""
    id: str = Field(..., description="文档ID（UUID）")
    filename: str = Field(..., description="原始文件名")
    file_format: str = Field(..., description="文件格式")
    file_size: int = Field(..., description="文件大小（字节）")
    content_text: str = Field(..., description="提取的全文文本")
    structured_data: Optional[Dict[str, Any]] = Field(None, description="结构化数据")
    parse_status: str = Field("success", description="解析状态")
    error_message: Optional[str] = Field(None, description="解析错误信息")
    parsed_at: str = Field(..., description="解析时间")
    original_file_path: Optional[str] = Field(None, description="原始文件存储路径（服务端内部使用）", exclude=True)


class AnalysisSourceRef(BaseModel):
    """引用来源标注"""
    doc_id: str = Field(..., description="来源文档ID")
    doc_name: str = Field(..., description="来源文档名称")
    excerpt: str = Field(..., description="引用的原文片段")
    location: Optional[str] = Field(None, description="在原文中的位置描述")


class AnalysisChapter(BaseModel):
    """分析结果章节"""
    id: str = Field(..., description="章节ID")
    title: str = Field(..., description="章节标题")
    annotation: str = Field("", description="章节简短注释说明")
    target_word_count: int = Field(800, description="目标字数")
    content: Optional[str] = Field(None, description="生成的内容")
    sources: List[AnalysisSourceRef] = Field(default_factory=list, description="引用来源列表")
    children: Optional[List['AnalysisChapter']] = None


AnalysisChapter.model_rebuild()


class AnalysisProject(BaseModel):
    """文档分析项目"""
    id: str = Field(..., description="项目ID（UUID）")
    documents: List[AnalysisDocumentInfo] = Field(default_factory=list, description="上传的文档列表")
    mode: AnalysisMode = Field(AnalysisMode.SUMMARY, description="分析模式")
    custom_instruction: Optional[str] = Field(None, description="用户自定义要求")
    target_word_count: int = Field(3000, description="目标总字数")
    outline: List[AnalysisChapter] = Field(default_factory=list, description="章节框架")
    created_at: str = Field(..., description="创建时间")


# ─── 请求/响应模型 ───

class AnalysisUploadResponse(BaseModel):
    """文档上传响应"""
    success: bool
    message: str
    document: Optional[AnalysisDocumentInfo] = None


class UpdateDocumentRequest(BaseModel):
    """更新文档缓存内容请求"""
    content_text: str = Field(..., description="用户编辑后的文本内容")


class FormatDocumentRequest(BaseModel):
    """排版处理请求"""
    custom_instruction: Optional[str] = Field(None, description="用户自定义排版要求")


class GenerateOutlineRequest(BaseModel):
    """生成章节框架请求"""
    project_id: str = Field(..., description="项目ID")
    mode: AnalysisMode = Field(..., description="分析模式")
    custom_instruction: Optional[str] = Field(None, description="用户自定义要求")
    target_word_count: int = Field(3000, description="目标总字数")


class ConfirmOutlineRequest(BaseModel):
    """确认章节框架请求"""
    project_id: str = Field(..., description="项目ID")
    outline: List[Dict[str, Any]] = Field(..., description="用户确认/编辑后的章节框架")


class GenerateChapterRequest(BaseModel):
    """生成单章节内容请求"""
    project_id: str = Field(..., description="项目ID")
    chapter_id: str = Field(..., description="章节ID")
    custom_instruction: Optional[str] = Field(None, description="用户对该章节的额外要求")


class ReviseChapterRequest(BaseModel):
    """修改章节内容请求"""
    project_id: str = Field(..., description="项目ID")
    chapter_id: str = Field(..., description="章节ID")
    current_content: str = Field(..., description="当前内容")
    user_instruction: str = Field(..., description="修改指令")
    selected_text: Optional[str] = Field(None, description="选中文本")
    selection_start: Optional[int] = Field(None, description="选中起始位置")
    selection_end: Optional[int] = Field(None, description="选中结束位置")
    messages: List[Dict[str, str]] = Field(default_factory=list, description="对话历史")
