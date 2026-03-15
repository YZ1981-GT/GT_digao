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
    REPORT_REVIEW = "report_review"


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
    table_contexts: List[str] = Field(default_factory=list, description="每个表格前最近的段落文本（按文档顺序）")
    table_after_para_idx: List[int] = Field(default_factory=list, description="每个表格前最近的段落索引（精确位置关联）")


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
    previously_generated: Optional[List[Dict[str, str]]] = Field(None, description="前面已生成章节的标题和内容摘要，用于避免重复")


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


# ═══════════════════════════════════════════════════════════════════
# 审计报告复核相关模型（Audit Report Review）
# ═══════════════════════════════════════════════════════════════════

# ─── 审计报告复核枚举 ───

class ReportFileType(str, Enum):
    """审计报告文件类型（Req 1.5）"""
    AUDIT_REPORT_BODY = "audit_report_body"
    FINANCIAL_STATEMENT = "financial_statement"
    NOTES_TO_STATEMENTS = "notes_to_statements"


class StatementType(str, Enum):
    """报表类型（Req 2.5）"""
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    EQUITY_CHANGE = "equity_change"


class ReportReviewFindingCategory(str, Enum):
    """复核发现分类（Req 12.2）"""
    AMOUNT_INCONSISTENCY = "amount_inconsistency"
    RECONCILIATION_ERROR = "reconciliation_error"
    CHANGE_ABNORMAL = "change_abnormal"
    NOTE_MISSING = "note_missing"
    REPORT_BODY_COMPLIANCE = "report_body_compliance"
    NOTE_CONTENT = "note_content"
    TEXT_QUALITY = "text_quality"


class FindingConfirmationStatus(str, Enum):
    """发现确认状态（Req 11.1-11.6）"""
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class ReportTemplateType(str, Enum):
    """审计报告模板类型（Req 1.6, Req 9）"""
    SOE = "soe"
    LISTED = "listed"


class TemplateCategory(str, Enum):
    """模板分类（Req 9.1）"""
    REPORT_BODY = "report_body"
    NOTES = "notes"


# ─── 报表科目与附注数据模型 ───

class StatementItem(BaseModel):
    """报表科目条目（Req 2.1, 2.2）"""
    id: str = Field(..., description="科目ID（UUID）")
    account_name: str = Field(..., description="科目名称")
    statement_type: StatementType = Field(..., description="所属报表类型")
    sheet_name: str = Field(..., description="来源 Sheet 名称")
    opening_balance: Optional[float] = Field(None, description="期初余额/上期金额（合并）")
    closing_balance: Optional[float] = Field(None, description="期末余额/本期金额（合并）")
    company_opening_balance: Optional[float] = Field(None, description="期初余额/上期金额（公司）")
    company_closing_balance: Optional[float] = Field(None, description="期末余额/本期金额（公司）")
    is_consolidated: bool = Field(False, description="是否为合并报表（含合并+公司列）")
    parent_id: Optional[str] = Field(None, description="父科目ID（其中项时指向主科目）")
    is_sub_item: bool = Field(False, description="是否为其中项明细")
    row_index: int = Field(..., description="在报表中的行号")
    parse_warnings: List[str] = Field(default_factory=list, description="解析警告（Req 2.9）")


class NoteTable(BaseModel):
    """附注表格（Req 2.3）"""
    id: str = Field(..., description="表格ID（UUID）")
    account_name: str = Field(..., description="对应科目名称")
    section_title: str = Field(..., description="附注章节标题")
    headers: List[str] = Field(default_factory=list, description="表头行（合并后的单行语义表头）")
    header_rows: List[List[str]] = Field(default_factory=list, description="原始多行表头（用于前端展示合并单元格）")
    rows: List[List[Any]] = Field(default_factory=list, description="数据行")
    source_location: str = Field("", description="在源文档中的位置描述")


class NoteSection(BaseModel):
    """附注层级节点 - 按附注文档的标题层级组织"""
    id: str = Field(..., description="节点ID")
    title: str = Field(..., description="标题文本（如 '一、公司基本情况'）")
    level: int = Field(..., description="层级：1=一级标题, 2=二级, 3=三级, 4=四级")
    content_paragraphs: List[str] = Field(default_factory=list, description="该节点下的正文段落")
    note_table_ids: List[str] = Field(default_factory=list, description="该节点下的附注表格ID")
    children: List['NoteSection'] = Field(default_factory=list, description="子节点")

NoteSection.model_rebuild()


class ReportSheetData(BaseModel):
    """审计报告 Excel Sheet 解析数据（Req 1.1, 1.2）"""
    sheet_name: str = Field(..., description="Sheet 名称")
    statement_type: StatementType = Field(..., description="自动识别的报表类型")
    row_count: int = Field(0, description="数据行数")
    headers: List[str] = Field(default_factory=list, description="表头行（合并后的语义表头）")
    header_rows: List[List[str]] = Field(default_factory=list, description="原始多行表头（用于前端展示）")
    raw_data: List[List[Any]] = Field(default_factory=list, description="原始数据行")
    is_consolidated: bool = Field(False, description="是否为合并报表（含合并+公司列）")
    column_map: Dict[str, int] = Field(default_factory=dict, description="语义列映射：closing_consolidated/closing_company/opening_consolidated/opening_company → 列索引")
    data_col_end: Optional[int] = Field(None, description="有效数据列的右边界索引（公司列为最右有效列）")


# ─── 表格结构识别模型 ───

class TableStructureRow(BaseModel):
    """表格行的语义标注（由 LLM 识别）"""
    row_index: int = Field(..., description="行索引")
    role: str = Field(..., description="行角色：data/total/subtotal/sub_item/header")
    parent_row_index: Optional[int] = Field(None, description="父行索引（其中项时指向所属主项行）")
    indent_level: int = Field(0, description="缩进层级")
    label: str = Field("", description="行标签/科目名称")
    sign: int = Field(1, description="纵向加总符号：1=加，-1=减（如'减：未确认融资费用'）")


class TableStructureColumn(BaseModel):
    """表格列的语义标注（由 LLM 识别）"""
    col_index: int = Field(..., description="列索引")
    semantic: str = Field(..., description="列语义：opening_balance/closing_balance/current_increase/current_decrease/prior_period/current_period/total/label/other")
    period: Optional[str] = Field(None, description="所属期间")


class TableStructure(BaseModel):
    """附注表格语义结构（由 Table_Structure_Analyzer LLM 识别，Req 3, Req 4）"""
    note_table_id: str = Field(..., description="对应的 NoteTable ID")
    rows: List[TableStructureRow] = Field(default_factory=list, description="各行语义标注")
    columns: List[TableStructureColumn] = Field(default_factory=list, description="各列语义标注")
    has_balance_formula: bool = Field(False, description="是否含期初+增加-减少=期末结构")
    total_row_indices: List[int] = Field(default_factory=list, description="合计行索引")
    subtotal_row_indices: List[int] = Field(default_factory=list, description="小计行索引")
    closing_balance_cell: Optional[str] = Field(None, description="期末余额合计单元格位置")
    opening_balance_cell: Optional[str] = Field(None, description="期初余额合计单元格位置")
    structure_confidence: str = Field("high", description="结构识别置信度：high/low")
    raw_llm_response: Optional[str] = Field(None, description="LLM 原始响应（调试用）")


# ─── 匹配映射模型 ───

class MatchingEntry(BaseModel):
    """科目匹配映射条目（Req 2.4）"""
    statement_item_id: str = Field(..., description="报表科目ID")
    note_table_ids: List[str] = Field(default_factory=list, description="匹配的附注表格ID列表")
    match_confidence: float = Field(0.0, description="匹配置信度 0-1")
    is_manual: bool = Field(False, description="是否为用户手动调整")


class MatchingMap(BaseModel):
    """科目匹配映射表（Req 2.4, 2.8）"""
    entries: List[MatchingEntry] = Field(default_factory=list, description="匹配条目列表")
    unmatched_items: List[str] = Field(default_factory=list, description="未匹配的科目ID（标记附注缺失）")
    unmatched_notes: List[str] = Field(default_factory=list, description="未匹配的附注表格ID")


# ─── 复核会话与结果模型 ───

class ReportReviewSession(BaseModel):
    """审计报告复核会话（Req 1.3, 1.6）"""
    id: str = Field(..., description="会话ID（UUID）")
    template_type: ReportTemplateType = Field(..., description="模板类型：soe/listed")
    file_ids: List[str] = Field(default_factory=list, description="上传文件ID列表")
    file_classifications: Dict[str, ReportFileType] = Field(default_factory=dict, description="文件分类映射")
    sheet_data: Dict[str, List[ReportSheetData]] = Field(default_factory=dict, description="Excel Sheet 解析数据 {file_id: [ReportSheetData]}")
    statement_items: List[StatementItem] = Field(default_factory=list)
    note_tables: List[NoteTable] = Field(default_factory=list)
    note_sections: List[NoteSection] = Field(default_factory=list, description="附注层级结构树")
    audit_report_content: List[Dict[str, Any]] = Field(default_factory=list, description="审计报告正文段落 [{text, level, is_bold}]")
    table_structures: Dict[str, TableStructure] = Field(default_factory=dict, description="表格结构识别结果 {note_table_id: TableStructure}")
    matching_map: Optional[MatchingMap] = Field(None)
    finding_conversations: Dict[str, 'FindingConversation'] = Field(default_factory=dict, description="问题确认对话")
    page_image_dir: Optional[str] = Field(None, description="页面截图存储目录路径")
    source_file_names: Dict[str, str] = Field(default_factory=dict, description="file_id → 原始文件名映射")
    status: str = Field("created", description="会话状态：created/parsed/matched/analyzing_structure/reviewing/completed")
    created_at: str = Field(..., description="创建时间ISO格式")


class ReportReviewFinding(BaseModel):
    """审计报告复核发现（Req 3.4, 11.1）"""
    id: str = Field(..., description="发现ID（UUID）")
    category: ReportReviewFindingCategory = Field(..., description="发现分类")
    risk_level: RiskLevel = Field(..., description="风险等级")
    account_name: str = Field(..., description="相关科目名称")
    statement_amount: Optional[float] = Field(None, description="报表金额")
    note_amount: Optional[float] = Field(None, description="附注金额")
    difference: Optional[float] = Field(None, description="差异金额")
    location: str = Field(..., description="问题定位")
    description: str = Field(..., description="问题描述")
    reference: str = Field("", description="参考依据")
    template_reference: Optional[str] = Field(None, description="模板参考文本")
    suggestion: str = Field("", description="修改建议")
    analysis_reasoning: Optional[str] = Field(None, description="分析推理过程")
    note_table_ids: List[str] = Field(default_factory=list, description="关联的附注表格ID列表（用于前端预览溯源）")
    source_page: Optional[int] = Field(None, description="问题所在源文档页码（1-based）")
    source_file: Optional[str] = Field(None, description="问题所在源文件名")
    confirmation_status: FindingConfirmationStatus = Field(
        FindingConfirmationStatus.PENDING_CONFIRMATION,
        description="确认状态"
    )
    status: FindingStatus = Field(FindingStatus.OPEN, description="处理状态")


class ReportReviewConfig(BaseModel):
    """复核配置请求（Req 5.2, Req 10）"""
    session_id: str = Field(..., description="会话ID")
    template_type: ReportTemplateType = Field(..., description="模板类型")
    prompt_id: Optional[str] = Field(None, description="选择的提示词ID")
    custom_prompt: Optional[str] = Field(None, description="自定义复核要求")
    change_threshold: float = Field(0.3, description="变动阈值，默认30%")


class ReportReviewResult(BaseModel):
    """审计报告复核结果（Req 12.1, 12.2）"""
    id: str = Field(..., description="结果ID（UUID）")
    session_id: str = Field(..., description="会话ID")
    findings: List[ReportReviewFinding] = Field(default_factory=list, description="已确认的 Finding 列表")
    category_summary: Dict[str, int] = Field(default_factory=dict, description="按分类统计已确认问题")
    risk_summary: Dict[str, int] = Field(default_factory=dict, description="按风险等级统计已确认问题")
    reconciliation_summary: Dict[str, int] = Field(default_factory=dict, description="匹配/不匹配/未检查统计")
    confirmation_summary: Dict[str, int] = Field(default_factory=dict, description="确认统计")
    conclusion: str = Field(..., description="复核结论")
    reviewed_at: str = Field(..., description="复核时间")


class SourcePreviewData(BaseModel):
    """源文档预览数据（Req 2.7）"""
    file_id: str = Field(..., description="文件ID")
    file_type: str = Field(..., description="文件类型：excel/word")
    highlight_range: Optional[str] = Field(None, description="高亮区域")
    content_html: str = Field("", description="渲染后的HTML预览内容")


class ChangeAnalysis(BaseModel):
    """科目变动分析结果（Req 5.1, 5.2）"""
    statement_item_id: str = Field(..., description="报表科目ID")
    account_name: str = Field(..., description="科目名称")
    opening_balance: Optional[float] = Field(None, description="期初余额")
    closing_balance: Optional[float] = Field(None, description="期末余额")
    change_amount: Optional[float] = Field(None, description="变动金额")
    change_percentage: Optional[float] = Field(None, description="变动百分比")
    exceeds_threshold: bool = Field(False, description="是否超过阈值")


class MatchingAnalysis(BaseModel):
    """科目与附注表格匹配分析结果（Req 3.1）"""
    statement_item_id: str = Field(..., description="报表科目ID")
    note_table_id: str = Field(..., description="附注表格ID")
    matched_cell_closing: Optional[str] = Field(None, description="附注中对应期末余额的单元格位置")
    matched_cell_opening: Optional[str] = Field(None, description="附注中对应期初余额的单元格位置")
    mapping_description: str = Field("", description="映射关系描述")
    confidence: float = Field(0.0, description="匹配置信度 0-1")


# ─── 模板相关数据模型 ───

class ReportTemplateSection(BaseModel):
    """审计报告模板章节（Req 9.2）"""
    path: str = Field(..., description="章节路径，如 '会计政策/收入确认'")
    level: int = Field(..., description="层级：1=H1, 2=H2, 3=H3")
    title: str = Field(..., description="章节标题")
    content: str = Field("", description="章节 Markdown 内容")


class ReportTemplateDocument(BaseModel):
    """审计报告模板文档（Req 9.1, 9.2）"""
    template_type: ReportTemplateType = Field(..., description="模板类型")
    template_category: TemplateCategory = Field(..., description="模板分类")
    full_content: str = Field(..., description="完整 Markdown 内容")
    sections: List[ReportTemplateSection] = Field(default_factory=list, description="按层级解析的章节列表")
    version: str = Field("", description="版本标识")
    updated_at: str = Field("", description="最后更新时间")


class NarrativeSection(BaseModel):
    """附注叙述性章节（Req 7.1）"""
    id: str = Field(..., description="章节ID")
    section_type: str = Field(..., description="章节类型：basic_info/accounting_policy/tax/related_party/other")
    title: str = Field(..., description="章节标题")
    content: str = Field(..., description="章节文本内容")
    source_location: str = Field("", description="在源文档中的位置")


class TemplateTocEntry(BaseModel):
    """模板目录条目（Req 9.7, 9.8）"""
    path: str = Field(..., description="章节路径")
    level: int = Field(..., description="层级：1=H1, 2=H2, 3=H3")
    title: str = Field(..., description="章节标题")
    has_children: bool = Field(False, description="是否有子章节")


# ─── 问题确认对话模型 ───

class FindingConversationMessage(BaseModel):
    """问题确认对话消息（Req 11.4, 11.6）"""
    id: str = Field(..., description="消息ID（UUID）")
    role: str = Field(..., description="消息角色：user/assistant")
    content: str = Field(..., description="消息内容")
    message_type: str = Field("chat", description="消息类型：chat/trace/edit")
    trace_type: Optional[str] = Field(None, description="溯源类型：cross_reference/template_compare/data_drill_down")
    created_at: str = Field(..., description="创建时间ISO格式")


class FindingConversation(BaseModel):
    """问题确认对话记录（Req 11.6）"""
    finding_id: str = Field(..., description="关联的 Finding ID")
    messages: List[FindingConversationMessage] = Field(default_factory=list, description="对话消息列表")
    edit_history: List[Dict[str, Any]] = Field(default_factory=list, description="编辑历史")


# 解决 ReportReviewSession 中的前向引用
ReportReviewSession.model_rebuild()
