"""审计底稿复核与文档生成相关数据模型"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


# ─── 枚举类型 ───

class RiskLevel(str, Enum):
    """风险等级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WorkpaperType(str, Enum):
    """底稿类型"""
    B = "B"   # 业务层面控制
    C = "C"   # 控制测试
    D = "D"   # 实质性测试-销售循环
    E = "E"   # 实质性测试-货币资金循环
    F = "F"   # 实质性测试-存货循环
    G = "G"   # 实质性测试-投资循环
    H = "H"   # 实质性测试-固定资产循环
    I = "I"   # 实质性测试-无形资产循环
    J = "J"   # 实质性测试-职工薪酬循环
    K = "K"   # 实质性测试-管理循环
    L = "L"   # 实质性测试-债务循环
    M = "M"   # 实质性测试-权益循环
    Q = "Q"   # 关联方循环


class ReviewDimension(str, Enum):
    """复核维度"""
    FORMAT = "format"
    DATA_RECONCILIATION = "data_reconciliation"
    ACCOUNTING_COMPLIANCE = "accounting_compliance"
    AUDIT_PROCEDURE = "audit_procedure"
    EVIDENCE_SUFFICIENCY = "evidence_sufficiency"


class FindingStatus(str, Enum):
    """问题处理状态"""
    OPEN = "open"
    RESOLVED = "resolved"


class UserRole(str, Enum):
    """用户角色"""
    PARTNER = "partner"
    MANAGER = "manager"
    AUDITOR = "auditor"
    QC = "qc"


class TemplateType(str, Enum):
    """模板类型"""
    AUDIT_PLAN = "audit_plan"
    AUDIT_SUMMARY = "audit_summary"
    DUE_DILIGENCE = "due_diligence"
    AUDIT_REPORT = "audit_report"
    CUSTOM = "custom"


class WorkMode(str, Enum):
    """工作模式"""
    REVIEW = "review"
    GENERATE = "generate"


class PromptSource(str, Enum):
    """提示词来源"""
    PRESET = "preset"                  # 预置提示词（TSJ目录原始版本）
    USER_MODIFIED = "user_modified"    # 用户修改预置提示词
    USER_REPLACED = "user_replaced"    # 用户替换预置提示词
    USER_APPENDED = "user_appended"    # 用户追加的自定义提示词


# ─── 底稿解析相关 ───

class CellData(BaseModel):
    """Excel单元格数据"""
    row: int = Field(..., description="行号")
    col: int = Field(..., description="列号")
    value: Any = Field(None, description="单元格值")
    formula: Optional[str] = Field(None, description="单元格公式")
    is_merged: bool = Field(False, description="是否为合并单元格")


class SheetData(BaseModel):
    """Excel工作表数据"""
    name: str = Field(..., description="工作表名称")
    cells: List[CellData] = Field(default_factory=list, description="单元格数据")
    merged_ranges: List[str] = Field(default_factory=list, description="合并单元格范围")


class ExcelParseResult(BaseModel):
    """Excel解析结果"""
    sheets: List[SheetData] = Field(..., description="所有工作表数据")
    sheet_names: List[str] = Field(..., description="工作表名称列表")


class WordParseResult(BaseModel):
    """Word解析结果"""
    paragraphs: List[Dict[str, Any]] = Field(..., description="段落列表（含文本、样式、层级）")
    tables: List[List[List[str]]] = Field(default_factory=list, description="表格数据")
    headings: List[Dict[str, Any]] = Field(default_factory=list, description="标题层级")
    comments: List[Dict[str, str]] = Field(default_factory=list, description="批注内容")


class PdfParseResult(BaseModel):
    """PDF解析结果"""
    text: str = Field(..., description="提取的文本内容")
    tables: List[List[List[str]]] = Field(default_factory=list, description="表格数据")
    page_count: int = Field(..., description="页数")


class WorkpaperClassification(BaseModel):
    """底稿分类信息"""
    workpaper_type: Optional[WorkpaperType] = Field(None, description="底稿类型（B/C/D-M）")
    business_cycle: Optional[str] = Field(None, description="业务循环名称")
    workpaper_id: Optional[str] = Field(None, description="底稿编号")


class WorkpaperParseResult(BaseModel):
    """底稿解析结果"""
    id: str = Field(..., description="解析结果ID（UUID）")
    filename: str = Field(..., description="原始文件名")
    file_format: str = Field(..., description="文件格式")
    file_size: int = Field(..., description="文件大小（字节）")
    classification: WorkpaperClassification = Field(..., description="底稿分类")
    content_text: str = Field(..., description="提取的文本内容")
    structured_data: Optional[Dict[str, Any]] = Field(None, description="结构化数据（Excel/Word特有）")
    parse_status: str = Field("success", description="解析状态：success/error")
    error_message: Optional[str] = Field(None, description="解析错误信息")
    parsed_at: str = Field(..., description="解析时间ISO格式")


class WorkpaperUploadResponse(BaseModel):
    """底稿上传响应"""
    success: bool
    message: str
    workpaper: Optional[WorkpaperParseResult] = None


# ─── 复核相关 ───

class ReviewRequest(BaseModel):
    """复核请求"""
    workpaper_ids: List[str] = Field(..., description="待复核底稿ID列表")
    dimensions: List[ReviewDimension] = Field(..., description="复核维度列表")
    custom_dimensions: Optional[List[str]] = Field(None, description="自定义复核关注点")
    project_id: Optional[str] = Field(None, description="所属项目ID")
    prompt_id: Optional[str] = Field(None, description="选择的预置提示词ID")
    custom_prompt: Optional[str] = Field(None, description="用户自定义提示词内容")
    supplementary_material_ids: Optional[List[str]] = Field(None, description="补充材料ID列表")


class ReviewFinding(BaseModel):
    """复核发现"""
    id: str = Field(..., description="发现ID（UUID）")
    dimension: str = Field(..., description="所属复核维度")
    risk_level: RiskLevel = Field(..., description="风险等级")
    location: str = Field(..., description="问题定位（底稿位置）")
    description: str = Field(..., description="问题描述")
    reference: str = Field(..., description="参考依据（准则条款或模板要求）")
    suggestion: str = Field(..., description="修改建议")
    status: FindingStatus = Field(FindingStatus.OPEN, description="处理状态")
    resolved_at: Optional[str] = Field(None, description="处理时间")


class ReviewReport(BaseModel):
    """复核报告"""
    id: str = Field(..., description="报告ID（UUID）")
    workpaper_ids: List[str] = Field(..., description="复核的底稿ID列表")
    dimensions: List[str] = Field(..., description="复核维度")
    findings: List[ReviewFinding] = Field(default_factory=list, description="问题清单")
    summary: Dict[str, int] = Field(..., description="风险等级统计：{high: n, medium: n, low: n}")
    conclusion: str = Field(..., description="复核结论")
    reviewed_at: str = Field(..., description="复核时间")
    project_id: Optional[str] = Field(None, description="所属项目ID")


class FindingStatusUpdate(BaseModel):
    """问题状态更新请求"""
    status: FindingStatus = Field(..., description="新状态")


class ExportRequest(BaseModel):
    """报告导出请求"""
    format: str = Field(..., description="导出格式：word/pdf")


# ─── 提示词相关 ───

class ReviewPromptInfo(BaseModel):
    """提示词摘要信息"""
    id: str = Field(..., description="提示词ID")
    name: str = Field(..., description="提示词名称")
    subject: Optional[str] = Field(None, description="适用会计科目（如货币资金、应收账款等）")
    source_file: Optional[str] = Field(None, description="TSJ目录中的源文件名（预置提示词）")
    summary: str = Field(..., description="提示词摘要（前100字）")
    source: PromptSource = Field(PromptSource.PRESET, description="提示词来源（preset/user_modified/user_replaced/user_appended）")
    is_preset: bool = Field(True, description="是否为预置提示词（来自TSJ目录）")
    usage_count: int = Field(0, description="使用次数")
    created_at: str = Field(..., description="创建时间")


class ReviewPromptDetail(BaseModel):
    """提示词完整详情"""
    id: str = Field(..., description="提示词ID")
    name: str = Field(..., description="提示词名称")
    subject: Optional[str] = Field(None, description="适用会计科目")
    source_file: Optional[str] = Field(None, description="来源文件名（含扩展名）")
    content: str = Field(..., description="提示词完整内容（当前生效版本）")
    original_content: Optional[str] = Field(None, description="原始预置内容（仅预置提示词有值，用于恢复默认和差异对比）")
    has_file_placeholder: bool = Field(False, description="内容中是否包含{{#sys.files#}}占位符")
    has_custom_version: bool = Field(False, description="是否存在用户自定义版本（修改或替换）")
    source: PromptSource = Field(PromptSource.PRESET, description="提示词来源")
    is_preset: bool = Field(True, description="是否为预置提示词")
    usage_count: int = Field(0, description="使用次数")


class SavePromptRequest(BaseModel):
    """保存用户追加自定义提示词请求"""
    name: str = Field(..., description="提示词名称")
    content: str = Field(..., description="提示词内容")
    subject: Optional[str] = Field(None, description="适用会计科目")


class EditPromptRequest(BaseModel):
    """编辑预置提示词请求"""
    content: str = Field(..., description="修改后的提示词内容")


class ReplacePromptRequest(BaseModel):
    """替换预置提示词请求"""
    content: str = Field(..., description="替换的提示词内容")


# ─── Git版本管理相关 ───

class GitConfig(BaseModel):
    """Git仓库配置"""
    repo_url: str = Field(..., description="Git仓库URL（如 git@github.com:YZ1981-GT/GT_digao.git）")
    auth_type: str = Field("token", description="认证方式：ssh_key 或 token")
    auth_credential: str = Field(..., description="认证凭据（SSH私钥路径或Token值）")
    branch: str = Field("main", description="目标分支名称")


class GitSyncResult(BaseModel):
    """Git同步结果"""
    success: bool = Field(..., description="同步是否成功")
    message: str = Field(..., description="同步结果描述")
    added_files: List[str] = Field(default_factory=list, description="新增的文件列表")
    updated_files: List[str] = Field(default_factory=list, description="更新的文件列表")
    deleted_files: List[str] = Field(default_factory=list, description="删除的文件列表")
    has_conflicts: bool = Field(False, description="是否存在冲突")
    conflicts: List[str] = Field(default_factory=list, description="冲突文件列表")


class GitCommitHistory(BaseModel):
    """Git提交历史"""
    commit_hash: str = Field(..., description="提交哈希")
    message: str = Field(..., description="提交信息")
    author: str = Field(..., description="提交者")
    committed_at: str = Field(..., description="提交时间ISO格式")
    changed_files: List[str] = Field(default_factory=list, description="变更的文件列表")


class GitConflictInfo(BaseModel):
    """Git冲突信息"""
    file_path: str = Field(..., description="冲突文件路径")
    local_content: str = Field(..., description="本地版本内容")
    remote_content: str = Field(..., description="远程版本内容")
    base_content: Optional[str] = Field(None, description="共同祖先版本内容")


class GitResolveRequest(BaseModel):
    """Git冲突解决请求"""
    file_path: str = Field(..., description="冲突文件路径")
    resolution: str = Field(..., description="解决方式：keep_local/use_remote/manual_merge")
    merged_content: Optional[str] = Field(None, description="手动合并后的内容（仅manual_merge时需要）")


class GitPushRequest(BaseModel):
    """Git推送请求"""
    prompt_id: str = Field(..., description="提示词ID")
    change_type: str = Field(..., description="变更类型：modify/replace/append")
    operator: str = Field(..., description="操作用户")


class GitTagRequest(BaseModel):
    """Git标签创建请求"""
    tag_name: str = Field(..., description="标签名称")
    message: str = Field("", description="标签说明信息")
    message: str = Field("", description="标签描述")


# ─── 补充材料相关 ───

class SupplementaryMaterial(BaseModel):
    """补充材料"""
    id: str = Field(..., description="材料ID（UUID）")
    type: str = Field(..., description="材料类型：file/text")
    filename: Optional[str] = Field(None, description="文件名（file类型）")
    text_content: Optional[str] = Field(None, description="文本内容（text类型）")
    parsed_content: str = Field(..., description="解析后的文本内容")
    uploaded_at: str = Field(..., description="上传时间")


class RequiredReference(BaseModel):
    """复核所需的相关底稿引用"""
    workpaper_ref: str = Field(..., description="底稿编号")
    description: str = Field(..., description="需要该底稿的原因")
    is_uploaded: bool = Field(False, description="是否已上传")


class ReferenceCheckRequest(BaseModel):
    """引用检查请求"""
    workpaper_ids: List[str] = Field(..., description="已上传底稿ID列表")


# ─── 字体设置相关 ───

class FontSettings(BaseModel):
    """文档导出字体设置（参照word_service.py的DEFAULT_FONT_NAME机制）"""
    chinese_font: str = Field("宋体", description="中文字体名称")
    english_font: str = Field("Times New Roman", description="英文字体名称")
    title_font_size: Optional[int] = Field(None, description="标题字号（磅），None表示使用模板默认")
    body_font_size: Optional[int] = Field(None, description="正文字号（磅），None表示使用模板默认")


# ─── 交叉引用相关 ───

class CrossReference(BaseModel):
    """交叉引用关系"""
    source_workpaper_id: str = Field(..., description="引用方底稿ID")
    source_workpaper_name: str = Field(..., description="引用方底稿名称")
    target_workpaper_id: Optional[str] = Field(None, description="被引用底稿ID（None表示缺失）")
    target_workpaper_ref: str = Field(..., description="被引用底稿编号")
    is_missing: bool = Field(False, description="被引用底稿是否缺失")
    reference_type: str = Field(..., description="引用类型描述")


class CrossReferenceAnalysis(BaseModel):
    """交叉引用分析结果"""
    references: List[CrossReference] = Field(default_factory=list, description="引用关系列表")
    missing_references: List[CrossReference] = Field(default_factory=list, description="缺失引用列表")
    consistency_findings: List[ReviewFinding] = Field(default_factory=list, description="一致性问题")


# ─── 模板相关 ───

class TemplateSection(BaseModel):
    """模板章节"""
    index: int = Field(..., description="章节序号")
    title: str = Field(..., description="章节标题")
    level: int = Field(1, description="标题层级")
    has_table: bool = Field(False, description="是否包含表格")
    fillable_fields: List[str] = Field(default_factory=list, description="需要填充的字段")
    children: Optional[List['TemplateSection']] = None


TemplateSection.model_rebuild()


class TemplateStructure(BaseModel):
    """模板结构"""
    sections: List[TemplateSection] = Field(..., description="章节列表")
    tables: List[Dict[str, Any]] = Field(default_factory=list, description="表格结构")


class TemplateInfo(BaseModel):
    """模板信息"""
    id: str = Field(..., description="模板ID（UUID）")
    name: str = Field(..., description="模板名称")
    template_type: TemplateType = Field(..., description="模板类型")
    file_format: str = Field(..., description="文件格式")
    structure: Optional[TemplateStructure] = Field(None, description="解析后的模板结构")
    uploaded_at: str = Field(..., description="上传时间")
    file_size: int = Field(0, description="文件大小")


class TemplateOutlineItem(BaseModel):
    """模板大纲项（复用现有 OutlineItem 格式）"""
    id: str = Field(..., description="章节编号，如 '1', '1.1', '1.1.1'")
    title: str = Field(..., description="章节标题")
    description: str = Field("", description="章节描述")
    target_word_count: Optional[int] = Field(None, description="目标字数")
    fillable_fields: Optional[List[str]] = Field(None, description="需要填充的字段（模板特有）")
    children: Optional[List['TemplateOutlineItem']] = None
    content: Optional[str] = Field(None, description="已生成的内容")


TemplateOutlineItem.model_rebuild()


# ─── 文档生成相关 ───

class ProjectInfo(BaseModel):
    """项目特定信息（用于文档生成）"""
    client_name: str = Field(..., description="客户名称")
    audit_period: str = Field(..., description="审计期间")
    preparer_name: Optional[str] = Field(None, description="编制人姓名")
    preparer_role: Optional[str] = Field(None, description="编制人角色：assistant/project_manager/manager/senior_manager/partner")
    key_matters: Optional[str] = Field(None, description="重要事项")
    additional_info: Optional[Dict[str, str]] = Field(None, description="其他补充信息")


class GenerateRequest(BaseModel):
    """文档生成请求"""
    template_id: str = Field(..., description="模板ID")
    outline: List[Dict[str, Any]] = Field(..., description="用户确认后的章节大纲（OutlineItem格式）")
    knowledge_library_ids: List[str] = Field(default_factory=list, description="关联知识库ID列表")
    project_info: ProjectInfo = Field(..., description="项目特定信息")
    project_id: Optional[str] = Field(None, description="所属项目ID")


class SectionGenerateRequest(BaseModel):
    """单章节内容生成请求（参照现有 ChapterContentRequest）"""
    document_id: str = Field(..., description="文档ID")
    section: Dict[str, Any] = Field(..., description="章节信息（OutlineItem格式）")
    parent_sections: Optional[List[Dict[str, Any]]] = Field(None, description="上级章节列表")
    sibling_sections: Optional[List[Dict[str, Any]]] = Field(None, description="同级章节列表")
    project_info: ProjectInfo = Field(..., description="项目特定信息")
    knowledge_library_ids: Optional[List[str]] = Field(None, description="关联知识库ID列表")
    library_docs: Optional[Dict[str, List[str]]] = Field(None, description="要使用的具体文档，格式: {库ID: [文档ID列表]}")


class GeneratedSection(BaseModel):
    """生成的文档章节"""
    index: int = Field(..., description="章节序号")
    title: str = Field(..., description="章节标题")
    content: str = Field(..., description="生成的内容")
    is_placeholder: bool = Field(False, description="是否包含【待补充】占位符")


class GeneratedDocument(BaseModel):
    """生成的文档"""
    id: str = Field(..., description="文档ID（UUID）")
    template_id: str = Field(..., description="使用的模板ID")
    outline: List[TemplateOutlineItem] = Field(default_factory=list, description="用户确认后的模板大纲结构（章节拆分结果）")
    sections: List[GeneratedSection] = Field(..., description="章节列表")
    project_info: ProjectInfo = Field(..., description="项目信息")
    generated_at: str = Field(..., description="生成时间")


class SectionRevisionRequest(BaseModel):
    """章节修改请求"""
    document_id: str = Field(..., description="文档ID")
    section_index: int = Field(..., description="章节索引")
    current_content: str = Field(..., description="当前章节内容")
    user_instruction: str = Field(..., description="用户修改指令")
    selected_text: Optional[str] = Field(None, description="用户选中的文本（局部修改时使用，参照ContentEdit.tsx的ManualEditState模式）")
    selection_start: Optional[int] = Field(None, description="选中文本起始位置")
    selection_end: Optional[int] = Field(None, description="选中文本结束位置")
    messages: List[Dict[str, str]] = Field(default_factory=list, description="对话历史")


class DocumentExportRequest(BaseModel):
    """文档导出请求"""
    document_id: str = Field(..., description="文档ID")
    sections: List[GeneratedSection] = Field(..., description="章节列表（含用户编辑后内容）")
    template_id: str = Field(..., description="模板ID")
    font_settings: Optional[FontSettings] = Field(None, description="字体设置，None表示使用默认字体")


# ─── 项目管理相关 ───

class ProjectCreateRequest(BaseModel):
    """项目创建请求"""
    name: str = Field(..., description="项目名称")
    client_name: str = Field(..., description="客户名称")
    audit_period: str = Field(..., description="审计期间")
    members: List[Dict[str, str]] = Field(default_factory=list, description="项目组成员 [{user_id, role}]")


class ProjectDetail(BaseModel):
    """项目详情"""
    id: str = Field(..., description="项目ID（UUID）")
    name: str = Field(..., description="项目名称")
    client_name: str = Field(..., description="客户名称")
    audit_period: str = Field(..., description="审计期间")
    status: str = Field("active", description="项目状态")
    members: List[Dict[str, str]] = Field(default_factory=list, description="项目组成员")
    workpaper_count: int = Field(0, description="底稿数量")
    template_ids: List[str] = Field(default_factory=list, description="关联模板ID列表")
    created_at: str = Field(..., description="创建时间")


class ProjectReviewSummary(BaseModel):
    """项目复核进度概览"""
    total_workpapers: int = Field(0, description="总底稿数")
    reviewed_workpapers: int = Field(0, description="已复核底稿数")
    pending_workpapers: int = Field(0, description="待复核底稿数")
    high_risk_count: int = Field(0, description="高风险问题数")
    medium_risk_count: int = Field(0, description="中风险问题数")
    low_risk_count: int = Field(0, description="低风险问题数")
