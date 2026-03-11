/**
 * 文档分析处理相关类型定义
 * 与后端 analysis_schemas.py 对应
 */

/** 分析模式 */
export type AnalysisMode = 'summary' | 'consolidation' | 'ledger';

/** 分析模式配置 */
export interface AnalysisModeConfig {
  label: string;
  default_word_count: number;
  description: string;
}

/** 上传文档的解析缓存信息 */
export interface AnalysisDocumentInfo {
  id: string;
  filename: string;
  file_format: string;
  file_size: number;
  content_text: string;
  structured_data?: Record<string, any>;
  parse_status: string;
  error_message?: string;
  parsed_at: string;
}

/** 引用来源标注 */
export interface AnalysisSourceRef {
  doc_id: string;
  doc_name: string;
  excerpt: string;
  location?: string;
}

/** 分析结果章节 */
export interface AnalysisChapter {
  id: string;
  title: string;
  annotation: string;
  target_word_count: number;
  content?: string;
  sources: AnalysisSourceRef[];
  children?: AnalysisChapter[];
}
