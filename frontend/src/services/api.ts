/**
 * API服务
 */
import axios from 'axios';
import type { ConfigData, OutlineItem } from '../types';
import type {
  WorkpaperUploadResponse as AuditWorkpaperUploadResponse,
  ReviewRequest,
  ReviewReport,
  ExportRequest,
  FindingStatusUpdate,
  CrossReferenceAnalysis,
  ReferenceCheckRequest,
  GenerateRequest,
  SectionGenerateRequest,
  SectionRevisionRequest,
  DocumentExportRequest,
  ReviewPromptInfo,
  ReviewPromptDetail,
  SavePromptRequest,
  EditPromptRequest,
  ReplacePromptRequest,
  GitConfig,
  GitSyncResult,
  GitCommitHistory,
  GitConflictInfo,
  GitResolveRequest,
  GitPushRequest,
  GitTagRequest,
  TemplateInfo,
  ProjectCreateRequest,
  ProjectDetail,
  ProjectReviewSummary,
  SupplementaryMaterial,
} from '../types/audit';

const API_BASE_URL = process.env.REACT_APP_API_URL || '';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
});

// 响应拦截器 - 统一错误处理
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API请求错误:', error);
    // 统一错误消息格式
    if (error.response?.data) {
      const data = error.response.data;
      const message = data.detail || data.message || data.error || '请求失败';
      error.message = message;
    }
    return Promise.reject(error);
  }
);

export type { ConfigData };

export interface FileUploadResponse {
  success: boolean;
  message: string;
  file_content?: string;
  old_outline?: string;
}

export interface AnalysisRequest {
  file_content: string;
  analysis_type: 'overview' | 'requirements';
}

export interface OutlineRequest {
  overview: string;
  requirements: string;
  uploaded_expand?: boolean;
  old_outline?: string;
  old_document?: string;
}

export interface ChapterContentRequest {
  chapter: OutlineItem;
  parent_chapters?: OutlineItem[];
  sibling_chapters?: OutlineItem[];
  project_overview: string;
  library_ids?: string[];
  library_docs?: {[key: string]: string[]};
  web_references?: Array<{title: string; url: string; content: string}>;
  signal?: AbortSignal;
}

export interface ChapterRevisionRequest {
  chapter: OutlineItem;
  current_content: string;
  messages: Array<{role: string; content: string}>;
  user_instruction: string;
  project_overview: string;
  parent_chapters?: OutlineItem[];
  sibling_chapters?: OutlineItem[];
  library_docs?: {[key: string]: string[]};
  web_references?: Array<{title: string; url: string; content: string}>;
  signal?: AbortSignal;
}

// 配置相关API
export const configApi = {
  // 保存配置
  saveConfig: (config: ConfigData) =>
    api.post('/api/config/save', config),

  // 加载配置
  loadConfig: () =>
    api.get('/api/config/load'),

  // 获取可用模型
  getModels: (config: ConfigData) =>
    api.post('/api/config/models', config),

  // 获取所有供应商
  getProviders: () =>
    api.get('/api/config/providers'),

  // 保存供应商
  saveProvider: (data: { id: string; name: string; api_key: string; base_url: string }) =>
    api.post('/api/config/providers/save', data),

  // 删除供应商
  deleteProvider: (providerId: string) =>
    api.delete(`/api/config/providers/${providerId}`),

  // 切换供应商
  activateProvider: (providerId: string) =>
    api.post(`/api/config/providers/activate/${providerId}`),

  // 获取使用统计
  getUsageStats: () =>
    api.get('/api/config/usage'),
};

// 文档相关API
export const documentApi = {
  // 上传文件
  uploadFile: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<FileUploadResponse>('/api/document/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  // 流式分析文档
  analyzeDocumentStream: (data: AnalysisRequest) =>
    fetch(`${API_BASE_URL}/api/document/analyze-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    }),

  // 导出Word文档
  exportWord: (data: { project_name?: string; project_overview?: string; outline: OutlineItem[] }) =>
    fetch(`${API_BASE_URL}/api/document/export-word`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    }),
};

// 目录相关API
export const outlineApi = {
  // 流式生成目录
  generateOutlineStream: (data: OutlineRequest) =>
    fetch(`${API_BASE_URL}/api/outline/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    }),
};

// 内容相关API
export const contentApi = {
  // 预加载知识库（SSE 流式接口，返回 fetch Response）
  preloadKnowledgeStream: (data: { library_ids?: string[]; library_docs?: {[key: string]: string[]} }) =>
    fetch(`${API_BASE_URL}/api/content/preload-knowledge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // 流式生成单章节内容
  generateChapterContentStream: (data: ChapterContentRequest) => {
    const { signal, ...body } = data;
    return fetch(`${API_BASE_URL}/api/content/generate-chapter-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal,
    });
  },

  // 流式修改章节内容
  reviseChapterStream: (data: ChapterRevisionRequest) => {
    const { signal, ...body } = data;
    return fetch(`${API_BASE_URL}/api/content/revise-chapter-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal,
    });
  },
};

// 方案扩写相关API
export const expandApi = {
  // 上传方案扩写文件
  uploadExpandFile: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<FileUploadResponse>('/api/expand/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 300000,
    });
  },
};

// 知识库相关API
export const knowledgeApi = {
  // 获取所有知识库列表
  getLibraries: () =>
    api.get('/api/knowledge/libraries'),

  // 获取某个知识库的文档列表
  getDocuments: (libraryId: string) =>
    api.get(`/api/knowledge/documents/${libraryId}`),

  // 上传文档到知识库
  uploadDocument: (libraryId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/api/knowledge/upload/${libraryId}`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 300000,
    });
  },

  // 删除文档
  deleteDocument: (libraryId: string, docId: string) =>
    api.delete(`/api/knowledge/documents/${libraryId}/${docId}`),

  // 搜索知识库
  searchKnowledge: (libraryIds: string[], query: string) =>
    api.post('/api/knowledge/search', { library_ids: libraryIds, query }),

  // 预览文档内容
  previewDocument: (libraryId: string, docId: string) =>
    api.get(`/api/knowledge/preview/${libraryId}/${docId}`),
};

// 搜索相关API
export const searchApi = {
  // 执行搜索
  search: (query: string, maxResults: number = 5) =>
    api.post('/api/search/', { query, max_results: maxResults }),

  // 读取URL内容
  loadUrl: (url: string, maxChars: number = 5000) =>
    api.post('/api/search/load-url', { url, max_chars: maxChars }),
};

export default api;

// ─── 审计底稿复核与文档生成 API ───

// 复核相关 API
export const reviewApi = {
  /** 上传底稿文件 */
  upload: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<AuditWorkpaperUploadResponse>('/api/review/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  /** 批量上传底稿 */
  uploadBatch: (files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    return api.post<AuditWorkpaperUploadResponse[]>('/api/review/upload-batch', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  /** 检查所需相关底稿 */
  checkReferences: (data: ReferenceCheckRequest) =>
    api.post('/api/review/check-references', data),

  /** 上传补充材料 */
  uploadSupplementary: (file?: File, textContent?: string) => {
    const formData = new FormData();
    if (file) formData.append('file', file);
    if (textContent) formData.append('text_content', textContent);
    return api.post<SupplementaryMaterial>('/api/review/upload-supplementary', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  /** 发起复核（SSE流式），返回 fetch Response 供 SSEParser 使用 */
  startReview: (data: ReviewRequest) =>
    fetch(`${API_BASE_URL}/api/review/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  /** 获取复核报告 */
  getReport: (reviewId: string) =>
    api.get<ReviewReport>(`/api/review/report/${reviewId}`),

  /** 导出复核报告（返回 Blob） */
  exportReport: (reviewId: string, data: ExportRequest) =>
    api.post(`/api/review/report/${reviewId}/export`, data, {
      responseType: 'blob',
    }),

  /** 更新问题处理状态 */
  updateFindingStatus: (findingId: string, data: FindingStatusUpdate) =>
    api.patch(`/api/review/finding/${findingId}/status`, data),

  /** 获取交叉引用分析 */
  getCrossReferences: (projectId: string) =>
    api.get<CrossReferenceAnalysis>(`/api/review/cross-references/${projectId}`),
};

// 文档生成相关 API
export const generateApi = {
  /** 从模板提取章节大纲 */
  extractOutline: (data: { template_id: string }) =>
    api.post('/api/generate/extract-outline', data),

  /** 用户确认/调整大纲 */
  confirmOutline: (data: { template_id: string; outline: Array<Record<string, any>> }) =>
    api.put('/api/generate/confirm-outline', data),

  /** 逐章节生成（SSE流式），返回 fetch Response 供 SSEParser 使用 */
  startGenerate: (data: GenerateRequest) =>
    fetch(`${API_BASE_URL}/api/generate/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  /** 单章节内容生成（SSE流式），返回 fetch Response 供 SSEParser 使用 */
  generateSection: (data: SectionGenerateRequest) =>
    fetch(`${API_BASE_URL}/api/generate/generate-section`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  /** AI修改章节（SSE流式），返回 fetch Response 供 SSEParser 使用 */
  reviseSection: (data: SectionRevisionRequest) =>
    fetch(`${API_BASE_URL}/api/generate/revise-section`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  /** 导出生成文档（返回 Blob） */
  exportDocument: (data: DocumentExportRequest) =>
    api.post('/api/generate/export', data, {
      responseType: 'blob',
    }),
};

// 提示词管理相关 API
export const promptApi = {
  /** 获取提示词列表（支持会计科目筛选） */
  listPrompts: (subject?: string) =>
    api.get<ReviewPromptInfo[]>('/api/prompt/list', {
      params: subject ? { subject } : undefined,
    }),

  /** 获取提示词详情 */
  getPrompt: (promptId: string) =>
    api.get<ReviewPromptDetail>(`/api/prompt/${promptId}`),

  /** 保存用户追加的自定义提示词 */
  savePrompt: (data: SavePromptRequest) =>
    api.post<ReviewPromptInfo>('/api/prompt/save', data),

  /** 编辑预置提示词（保存为用户修改版本） */
  editPrompt: (promptId: string, data: EditPromptRequest) =>
    api.put<ReviewPromptInfo>(`/api/prompt/${promptId}/edit`, data),

  /** 替换预置提示词（完全替换内容） */
  replacePrompt: (promptId: string, data: ReplacePromptRequest) =>
    api.put<ReviewPromptInfo>(`/api/prompt/${promptId}/replace`, data),

  /** 恢复预置提示词为默认版本 */
  restorePrompt: (promptId: string) =>
    api.post<ReviewPromptInfo>(`/api/prompt/${promptId}/restore`),

  /** 删除自定义提示词 */
  deletePrompt: (promptId: string) =>
    api.delete(`/api/prompt/${promptId}`),
};

// 提示词 Git 版本管理相关 API
export const promptGitApi = {
  /** 配置 Git 仓库关联 */
  configGit: (data: GitConfig) =>
    api.post('/api/prompt/git/config', data),

  /** 获取 Git 仓库配置 */
  getGitConfig: () =>
    api.get<GitConfig>('/api/prompt/git/config'),

  /** 从 Git 仓库拉取同步 */
  syncGit: () =>
    api.post<GitSyncResult>('/api/prompt/git/sync'),

  /** 将变更提交到 Git 仓库 */
  pushGit: (data: GitPushRequest) =>
    api.post<GitSyncResult>('/api/prompt/git/push', data),

  /** 获取 Git 版本历史 */
  getGitHistory: (filePath?: string, limit: number = 50) =>
    api.get<GitCommitHistory[]>('/api/prompt/git/history', {
      params: { file_path: filePath, limit },
    }),

  /** 检测 Git 冲突 */
  getGitConflicts: () =>
    api.get<GitConflictInfo[]>('/api/prompt/git/conflicts'),

  /** 解决 Git 冲突 */
  resolveGitConflict: (data: GitResolveRequest) =>
    api.post('/api/prompt/git/resolve', data),

  /** 创建 Git 版本标签 */
  createGitTag: (data: GitTagRequest) =>
    api.post('/api/prompt/git/tag', data),

  /** 列出所有 Git 标签 */
  listGitTags: () =>
    api.get('/api/prompt/git/tags'),
};

// 模板管理相关 API
export const templateApi = {
  /** 上传模板 */
  uploadTemplate: (file: File, templateType: string) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('template_type', templateType);
    return api.post<TemplateInfo>('/api/template/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  /** 获取模板列表 */
  listTemplates: () =>
    api.get<TemplateInfo[]>('/api/template/list'),

  /** 获取模板详情 */
  getTemplate: (templateId: string) =>
    api.get<TemplateInfo>(`/api/template/${templateId}`),

  /** 删除模板 */
  deleteTemplate: (templateId: string) =>
    api.delete(`/api/template/${templateId}`),

  /** 更新模板 */
  updateTemplate: (templateId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.put<TemplateInfo>(`/api/template/${templateId}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

// 项目管理相关 API
export const projectApi = {
  /** 创建项目 */
  createProject: (data: ProjectCreateRequest) =>
    api.post<ProjectDetail>('/api/project/create', data),

  /** 获取项目列表 */
  listProjects: () =>
    api.get<ProjectDetail[]>('/api/project/list'),

  /** 获取项目详情 */
  getProject: (projectId: string) =>
    api.get<ProjectDetail>(`/api/project/${projectId}`),

  /** 关联底稿到项目 */
  addWorkpaperToProject: (projectId: string, data: { workpaper_id: string }) =>
    api.post(`/api/project/${projectId}/workpapers`, data),

  /** 获取复核进度概览 */
  getProjectSummary: (projectId: string) =>
    api.get<ProjectReviewSummary>(`/api/project/${projectId}/summary`),

  /** 获取项目底稿列表（支持筛选） */
  filterWorkpapers: (projectId: string, params?: { cycle?: string; type?: string }) =>
    api.get(`/api/project/${projectId}/workpapers`, { params }),

  /** 关联模板到项目 */
  linkTemplateToProject: (projectId: string, data: { template_id: string }) =>
    api.post(`/api/project/${projectId}/templates`, data),
};
