/**
 * 类型定义
 */

export interface ConfigData {
  api_key: string;
  base_url?: string;
  model_name: string;
  word_count?: number;
  has_api_key?: boolean;
  providers?: ProviderInfo[];
}

export interface ProviderInfo {
  id: string;
  name: string;
  base_url: string;
  api_key_masked: string;
  has_key: boolean;
  is_active: boolean;
  created_at: string;
}

export interface PresetProvider {
  id: string;
  name: string;
  base_url: string;
}

export interface ProviderUsage {
  provider_id: string;
  provider_name: string;
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  last_used: string;
  models: Array<{
    model: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    last_used: string;
  }>;
}

export interface OutlineItem {
  id: string;
  title: string;
  description: string;
  children?: OutlineItem[];
  content?: string;
  target_word_count?: number;
}

export interface OutlineData {
  outline: OutlineItem[];
  project_name?: string;
  project_overview?: string;
}

export interface AppState {
  currentStep: number;
  config: ConfigData;
  fileContent: string;
  projectOverview: string;
  techRequirements: string;
  outlineData: OutlineData | null;
  selectedChapter: string;
}

// 知识库相关类型
export interface KnowledgeLibrary {
  id: string;
  name: string;
  desc: string;
  doc_count: number;
}

export interface KnowledgeDocument {
  id: string;
  filename: string;
  size: number;
  created_at: string;
}

// 搜索相关类型
export interface SearchResult {
  title: string;
  href: string;
  body: string;
}

export interface WebReference {
  title: string;
  url: string;
  content: string;
}