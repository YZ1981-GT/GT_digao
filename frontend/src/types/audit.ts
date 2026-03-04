/**
 * 审计底稿复核与文档生成相关类型定义
 * 与后端 Pydantic 模型 (backend/app/models/audit_schemas.py) 对应
 */

// ─── 枚举/联合类型 ───

/** 风险等级 */
export type RiskLevel = 'high' | 'medium' | 'low';

/** 底稿类型 */
export type WorkpaperType =
  | 'B'  // 业务层面控制
  | 'C'  // 控制测试
  | 'D'  // 实质性测试-销售循环
  | 'E'  // 实质性测试-货币资金循环
  | 'F'  // 实质性测试-存货循环
  | 'G'  // 实质性测试-投资循环
  | 'H'  // 实质性测试-固定资产循环
  | 'I'  // 实质性测试-无形资产循环
  | 'J'  // 实质性测试-职工薪酬循环
  | 'K'  // 实质性测试-管理循环
  | 'L'  // 实质性测试-债务循环
  | 'M'  // 实质性测试-权益循环
  | 'Q'; // 关联方循环

/** 复核维度 */
export type ReviewDimension =
  | 'format'
  | 'data_reconciliation'
  | 'accounting_compliance'
  | 'audit_procedure'
  | 'evidence_sufficiency';

/** 问题处理状态 */
export type FindingStatus = 'open' | 'resolved';

/** 用户角色 */
export type UserRole = 'partner' | 'manager' | 'auditor' | 'qc';

/** 模板类型 */
export type TemplateType = 'audit_plan' | 'audit_summary' | 'due_diligence' | 'audit_report' | 'custom';

/** 工作模式 */
export type WorkMode = 'review' | 'generate';

/** 提示词来源 */
export type PromptSource = 'preset' | 'user_modified' | 'user_replaced' | 'user_appended';


// ─── 底稿解析相关 ───

/** Excel单元格数据 */
export interface CellData {
  row: number;
  col: number;
  value: any;
  formula?: string;
  is_merged: boolean;
}

/** Excel工作表数据 */
export interface SheetData {
  name: string;
  cells: CellData[];
  merged_ranges: string[];
}

/** Excel解析结果 */
export interface ExcelParseResult {
  sheets: SheetData[];
  sheet_names: string[];
}

/** Word解析结果 */
export interface WordParseResult {
  paragraphs: Array<Record<string, any>>;
  tables: string[][][];
  headings: Array<Record<string, any>>;
  comments: Array<Record<string, string>>;
}

/** PDF解析结果 */
export interface PdfParseResult {
  text: string;
  tables: string[][][];
  page_count: number;
}

/** 底稿分类信息 */
export interface WorkpaperClassification {
  workpaper_type?: WorkpaperType;
  business_cycle?: string;
  workpaper_id?: string;
}

/** 底稿解析结果 */
export interface WorkpaperParseResult {
  id: string;
  filename: string;
  file_format: string;
  file_size: number;
  classification: WorkpaperClassification;
  content_text: string;
  structured_data?: Record<string, any>;
  parse_status: string;
  error_message?: string;
  parsed_at: string;
}

/** 底稿上传响应 */
export interface WorkpaperUploadResponse {
  success: boolean;
  message: string;
  workpaper?: WorkpaperParseResult;
}


// ─── 复核相关 ───

/** 复核请求 */
export interface ReviewRequest {
  workpaper_ids: string[];
  dimensions: ReviewDimension[];
  custom_dimensions?: string[];
  project_id?: string;
  prompt_id?: string;
  custom_prompt?: string;
  supplementary_material_ids?: string[];
}

/** 复核发现 */
export interface ReviewFinding {
  id: string;
  dimension: string;
  risk_level: RiskLevel;
  location: string;
  description: string;
  reference: string;
  suggestion: string;
  status: FindingStatus;
  resolved_at?: string;
}

/** 复核报告 */
export interface ReviewReport {
  id: string;
  workpaper_ids: string[];
  dimensions: string[];
  findings: ReviewFinding[];
  summary: { high: number; medium: number; low: number };
  conclusion: string;
  reviewed_at: string;
  project_id?: string;
}

/** 问题状态更新请求 */
export interface FindingStatusUpdate {
  status: FindingStatus;
}

/** 报告导出请求 */
export interface ExportRequest {
  format: 'word' | 'pdf';
}

// ─── 提示词相关 ───

/** 提示词摘要信息 */
export interface ReviewPromptInfo {
  id: string;
  name: string;
  subject?: string;
  source_file?: string;
  summary: string;
  source: PromptSource;
  is_preset: boolean;
  usage_count: number;
  created_at: string;
}

/** 提示词完整详情 */
export interface ReviewPromptDetail {
  id: string;
  name: string;
  subject?: string;
  source_file?: string;
  content: string;
  original_content?: string;
  has_file_placeholder: boolean;
  has_custom_version: boolean;
  source: PromptSource;
  is_preset: boolean;
  usage_count: number;
}

/** 保存用户追加自定义提示词请求 */
export interface SavePromptRequest {
  name: string;
  content: string;
  subject?: string;
}

/** 编辑预置提示词请求 */
export interface EditPromptRequest {
  content: string;
}

/** 替换预置提示词请求 */
export interface ReplacePromptRequest {
  content: string;
}


// ─── Git版本管理相关 ───

/** Git仓库配置 */
export interface GitConfig {
  repo_url: string;
  auth_type: 'ssh_key' | 'token';
  auth_credential: string;
  branch: string;
}

/** Git同步结果 */
export interface GitSyncResult {
  success: boolean;
  message: string;
  added_files: string[];
  updated_files: string[];
  deleted_files: string[];
  has_conflicts: boolean;
  conflicts: string[];
}

/** Git提交历史 */
export interface GitCommitHistory {
  commit_hash: string;
  message: string;
  author: string;
  committed_at: string;
  changed_files: string[];
}

/** Git冲突信息 */
export interface GitConflictInfo {
  file_path: string;
  local_content: string;
  remote_content: string;
  base_content?: string;
}

/** Git冲突解决请求 */
export interface GitResolveRequest {
  file_path: string;
  resolution: 'keep_local' | 'use_remote' | 'manual_merge';
  merged_content?: string;
}

/** Git推送请求 */
export interface GitPushRequest {
  prompt_id: string;
  change_type: 'modify' | 'replace' | 'append';
  operator: string;
}

/** Git标签创建请求 */
export interface GitTagRequest {
  tag_name: string;
  message: string;
}

// ─── 补充材料相关 ───

/** 补充材料 */
export interface SupplementaryMaterial {
  id: string;
  type: 'file' | 'text';
  filename?: string;
  text_content?: string;
  parsed_content: string;
  uploaded_at: string;
}

/** 复核所需的相关底稿引用 */
export interface RequiredReference {
  workpaper_ref: string;
  description: string;
  is_uploaded: boolean;
}

/** 引用检查请求 */
export interface ReferenceCheckRequest {
  workpaper_ids: string[];
}

// ─── 字体设置相关 ───

/** 文档导出字体设置 */
export interface FontSettings {
  chinese_font: string;
  english_font: string;
  title_font_size?: number;
  body_font_size?: number;
}

// ─── 交叉引用相关 ───

/** 交叉引用关系 */
export interface CrossReference {
  source_workpaper_id: string;
  source_workpaper_name: string;
  target_workpaper_id?: string;
  target_workpaper_ref: string;
  is_missing: boolean;
  reference_type: string;
}

/** 交叉引用分析结果 */
export interface CrossReferenceAnalysis {
  references: CrossReference[];
  missing_references: CrossReference[];
  consistency_findings: ReviewFinding[];
}


// ─── 模板相关 ───

/** 模板章节 */
export interface TemplateSection {
  index: number;
  title: string;
  level: number;
  has_table: boolean;
  fillable_fields: string[];
  children?: TemplateSection[];
}

/** 模板结构 */
export interface TemplateStructure {
  sections: TemplateSection[];
  tables: Array<Record<string, any>>;
}

/** 模板信息 */
export interface TemplateInfo {
  id: string;
  name: string;
  template_type: TemplateType;
  file_format: string;
  structure?: TemplateStructure;
  uploaded_at: string;
  file_size: number;
}

/** 模板大纲项（复用现有 OutlineItem 格式） */
export interface TemplateOutlineItem {
  id: string;
  title: string;
  description: string;
  target_word_count?: number;
  fillable_fields?: string[];
  children?: TemplateOutlineItem[];
  content?: string;
}

// ─── 文档生成相关 ───

/** 项目特定信息（用于文档生成） */
export interface ProjectInfo {
  client_name: string;
  audit_period: string;
  key_matters?: string;
  additional_info?: Record<string, string>;
}

/** 文档生成请求 */
export interface GenerateRequest {
  template_id: string;
  outline: Array<Record<string, any>>;
  knowledge_library_ids: string[];
  project_info: ProjectInfo;
  project_id?: string;
}

/** 单章节内容生成请求 */
export interface SectionGenerateRequest {
  document_id: string;
  section: Record<string, any>;
  parent_sections?: Array<Record<string, any>>;
  sibling_sections?: Array<Record<string, any>>;
  project_info: ProjectInfo;
  knowledge_library_ids?: string[];
  library_docs?: Record<string, string[]>;
}

/** 生成的文档章节 */
export interface GeneratedSection {
  index: number;
  title: string;
  content: string;
  is_placeholder: boolean;
}

/** 生成的文档 */
export interface GeneratedDocument {
  id: string;
  template_id: string;
  outline: TemplateOutlineItem[];
  sections: GeneratedSection[];
  project_info: ProjectInfo;
  generated_at: string;
}

/** 章节修改请求 */
export interface SectionRevisionRequest {
  document_id: string;
  section_index: number;
  current_content: string;
  user_instruction: string;
  selected_text?: string;
  selection_start?: number;
  selection_end?: number;
  messages: Array<Record<string, string>>;
}

/** 文档导出请求 */
export interface DocumentExportRequest {
  document_id: string;
  sections: GeneratedSection[];
  template_id: string;
  font_settings?: FontSettings;
}


// ─── 项目管理相关 ───

/** 项目创建请求 */
export interface ProjectCreateRequest {
  name: string;
  client_name: string;
  audit_period: string;
  members: Array<{ user_id: string; role: string }>;
}

/** 项目详情 */
export interface ProjectDetail {
  id: string;
  name: string;
  client_name: string;
  audit_period: string;
  status: string;
  members: Array<{ user_id: string; role: UserRole }>;
  workpaper_count: number;
  template_ids: string[];
  created_at: string;
}

/** 项目复核进度概览 */
export interface ProjectReviewSummary {
  total_workpapers: number;
  reviewed_workpapers: number;
  pending_workpapers: number;
  high_risk_count: number;
  medium_risk_count: number;
  low_risk_count: number;
}

// ─── 章节编辑状态（参照 ContentEdit.tsx 的 ManualEditState 模式） ───

/** 章节编辑状态 */
export interface SectionEditState {
  isEditing: boolean;
  sectionIndex: number;
  sectionTitle: string;
  editContent: string;
  aiInput: string;
  aiProcessing: boolean;
  selectedText: string;
  selectionStart: number;
  selectionEnd: number;
  messages: Array<{ role: string; content: string }>;
  targetWordCount?: number;
}

// ─── 常量映射 ───

/** 风险等级颜色映射（GT Design System 功能色） */
export const RISK_LEVEL_COLORS: Record<RiskLevel, string> = {
  high: '#DC3545',    // GT危险色
  medium: '#FFC107',  // GT警告色
  low: '#17A2B8',     // GT信息色
};

/** 复核维度中文名映射 */
export const DIMENSION_LABELS: Record<ReviewDimension, string> = {
  format: '格式规范性',
  data_reconciliation: '数据勾稽关系',
  accounting_compliance: '会计准则合规性',
  audit_procedure: '审计程序完整性',
  evidence_sufficiency: '审计证据充分性',
};
