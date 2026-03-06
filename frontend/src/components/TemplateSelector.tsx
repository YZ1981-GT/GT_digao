/**
 * TemplateSelector - 模板选择与上传组件
 *
 * 支持上传模板文件（docx/xlsx/xls/pdf），展示已上传模板列表（名称、类型、上传时间、格式），
 * 支持模板删除和更新，展示可关联的知识库列表（支持勾选），
 * 提供项目特定信息输入表单（客户名称、审计期间、重要事项）。
 *
 * Requirements: 11.1-11.6, 12.2, 12.3
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { templateApi, knowledgeApi } from '../services/api';
import type { TemplateInfo, TemplateType, ProjectInfo } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface TemplateSelectorProps {
  selectedTemplateId: string;
  projectInfo: ProjectInfo;
  knowledgeLibraryIds: string[];
  knowledgeLibraryDocs: Record<string, string[]>;
  onTemplateSelect: (templateId: string) => void;
  onProjectInfoChange: (info: ProjectInfo) => void;
  onKnowledgeLibraryIdsChange: (ids: string[]) => void;
  onKnowledgeLibraryDocsChange: (docs: Record<string, string[]>) => void;
}

/** Template type labels */
const TEMPLATE_TYPE_LABELS: Record<TemplateType, string> = {
  audit_plan: '审计计划',
  audit_summary: '审计小结',
  due_diligence: '尽调报告',
  audit_report: '审计报告',
  custom: '其他自定义',
};

const TEMPLATE_TYPE_OPTIONS: Array<{ value: TemplateType; label: string }> = [
  { value: 'audit_plan', label: '审计计划' },
  { value: 'audit_summary', label: '审计小结' },
  { value: 'due_diligence', label: '尽调报告' },
  { value: 'audit_report', label: '审计报告' },
  { value: 'custom', label: '其他自定义' },
];

const ACCEPTED_FORMATS = '.docx,.xlsx,.xls,.pdf';

interface KnowledgeLibrary {
  id: string;
  name: string;
  description?: string;
  document_count?: number;
}

interface KnowledgeDocument {
  id: string;
  filename: string;
  size?: number;
  created_at?: string;
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function getFormatLabel(format: string): string {
  const map: Record<string, string> = {
    docx: 'Word (.docx)',
    xlsx: 'Excel (.xlsx)',
    xls: 'Excel (.xls)',
    pdf: 'PDF',
  };
  return map[format] || format;
}

const TemplateSelector: React.FC<TemplateSelectorProps> = ({
  selectedTemplateId,
  projectInfo,
  knowledgeLibraryIds,
  knowledgeLibraryDocs,
  onTemplateSelect,
  onProjectInfoChange,
  onKnowledgeLibraryIdsChange,
  onKnowledgeLibraryDocsChange,
}) => {
  // Template state
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showResumePrompt, setShowResumePrompt] = useState(false);
  const resumeCheckedRef = useRef(false);
  const [templateSearch, setTemplateSearch] = useState('');

  // Upload state
  const [uploadType, setUploadType] = useState<TemplateType>('audit_plan');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const updateFileInputRef = useRef<HTMLInputElement>(null);
  const [updatingTemplateId, setUpdatingTemplateId] = useState<string | null>(null);

  // Knowledge library state
  const [libraries, setLibraries] = useState<KnowledgeLibrary[]>([]);
  const [librariesLoading, setLibrariesLoading] = useState(false);
  const [expandedLibraries, setExpandedLibraries] = useState<Set<string>>(new Set());
  const [libraryDocs, setLibraryDocs] = useState<Record<string, KnowledgeDocument[]>>({});
  const [loadingDocs, setLoadingDocs] = useState<Set<string>>(new Set());
  const [knowledgeSectionOpen, setKnowledgeSectionOpen] = useState(false);

  /** Fetch template list */
  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await templateApi.listTemplates();
      const list = response.data.templates ?? [];
      setTemplates(list);
      // If templates exist and we haven't checked yet, show resume prompt
      if (list.length > 0 && !resumeCheckedRef.current) {
        resumeCheckedRef.current = true;
        // Auto-select the most recently uploaded template
        const sorted = [...list].sort((a, b) =>
          new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime()
        );
        if (!selectedTemplateId) {
          onTemplateSelect(sorted[0].id);
        }
        setShowResumePrompt(true);
      }
    } catch (err: any) {
      setError(err.message || '加载模板列表失败');
    } finally {
      setLoading(false);
    }
  }, [selectedTemplateId, onTemplateSelect]);

  /** Fetch knowledge libraries */
  const fetchLibraries = useCallback(async () => {
    setLibrariesLoading(true);
    try {
      const response = await knowledgeApi.getLibraries();
      const data = response.data;
      // Backend returns { success, libraries: [...], cache_info }
      const libsArray = data?.libraries ?? data;
      if (Array.isArray(libsArray)) {
        setLibraries(libsArray.map((lib: any) => ({
          id: lib.id,
          name: lib.name || lib.id,
          description: lib.desc || lib.description || '',
          document_count: lib.doc_count ?? lib.document_count ?? 0,
        })));
      }
    } catch {
      // Silently fail - libraries are optional
    } finally {
      setLibrariesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTemplates();
    fetchLibraries();
  }, [fetchTemplates, fetchLibraries]);

  /** Handle template file upload */
  const handleUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError(null);
      try {
        const response = await templateApi.uploadTemplate(file, uploadType);
        const newTemplate = response.data.template;
        setTemplates((prev) => [...prev, newTemplate]);
        // Auto-select the newly uploaded template
        onTemplateSelect(newTemplate.id);
      } catch (err: any) {
        setError(err.message || '模板上传失败');
      } finally {
        setUploading(false);
      }
    },
    [uploadType, onTemplateSelect]
  );

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        handleUpload(file);
        e.target.value = '';
      }
    },
    [handleUpload]
  );

  /** Handle template delete */
  const handleDelete = useCallback(
    async (templateId: string) => {
      setError(null);
      try {
        await templateApi.deleteTemplate(templateId);
        setTemplates((prev) => prev.filter((t) => t.id !== templateId));
        if (selectedTemplateId === templateId) {
          onTemplateSelect('');
        }
      } catch (err: any) {
        setError(err.message || '删除模板失败');
      }
    },
    [selectedTemplateId, onTemplateSelect]
  );

  /** Handle template update */
  const handleUpdateClick = useCallback((templateId: string) => {
    setUpdatingTemplateId(templateId);
    updateFileInputRef.current?.click();
  }, []);

  const handleUpdateFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file && updatingTemplateId) {
        setError(null);
        try {
          const response = await templateApi.updateTemplate(updatingTemplateId, file);
          const updated = response.data.template;
          setTemplates((prev) =>
            prev.map((t) => (t.id === updatingTemplateId ? updated : t))
          );
        } catch (err: any) {
          setError(err.message || '更新模板失败');
        }
      }
      setUpdatingTemplateId(null);
      e.target.value = '';
    },
    [updatingTemplateId]
  );

  /** Toggle library expand/collapse and load docs */
  const handleLibraryExpand = useCallback(
    async (libraryId: string) => {
      setExpandedLibraries((prev) => {
        const next = new Set(prev);
        if (next.has(libraryId)) {
          next.delete(libraryId);
        } else {
          next.add(libraryId);
        }
        return next;
      });
      // Load docs if not already loaded
      if (!libraryDocs[libraryId]) {
        setLoadingDocs((prev) => new Set(prev).add(libraryId));
        try {
          const response = await knowledgeApi.getDocuments(libraryId);
          const docs = response.data?.documents ?? response.data ?? [];
          setLibraryDocs((prev) => ({ ...prev, [libraryId]: docs }));
        } catch {
          setLibraryDocs((prev) => ({ ...prev, [libraryId]: [] }));
        } finally {
          setLoadingDocs((prev) => {
            const next = new Set(prev);
            next.delete(libraryId);
            return next;
          });
        }
      }
    },
    [libraryDocs]
  );

  /** Toggle all docs in a library (select all / deselect all) */
  const handleLibraryToggle = useCallback(
    (libraryId: string) => {
      const docs = libraryDocs[libraryId] || [];
      const currentSelected = knowledgeLibraryDocs[libraryId] || [];
      const allSelected = docs.length > 0 && currentSelected.length === docs.length;

      const newDocs = { ...knowledgeLibraryDocs };
      if (allSelected) {
        // Deselect all
        delete newDocs[libraryId];
      } else {
        // Select all
        newDocs[libraryId] = docs.map((d) => d.id);
      }
      onKnowledgeLibraryDocsChange(newDocs);
      // Update library ids
      onKnowledgeLibraryIdsChange(Object.keys(newDocs).filter((k) => (newDocs[k]?.length ?? 0) > 0));
    },
    [libraryDocs, knowledgeLibraryDocs, onKnowledgeLibraryDocsChange, onKnowledgeLibraryIdsChange]
  );

  /** Toggle a single document */
  const handleDocToggle = useCallback(
    (libraryId: string, docId: string) => {
      const currentSelected = knowledgeLibraryDocs[libraryId] || [];
      const newDocs = { ...knowledgeLibraryDocs };
      if (currentSelected.includes(docId)) {
        const filtered = currentSelected.filter((id) => id !== docId);
        if (filtered.length === 0) {
          delete newDocs[libraryId];
        } else {
          newDocs[libraryId] = filtered;
        }
      } else {
        newDocs[libraryId] = [...currentSelected, docId];
      }
      onKnowledgeLibraryDocsChange(newDocs);
      onKnowledgeLibraryIdsChange(Object.keys(newDocs).filter((k) => (newDocs[k]?.length ?? 0) > 0));
    },
    [knowledgeLibraryDocs, onKnowledgeLibraryDocsChange, onKnowledgeLibraryIdsChange]
  );

  /** Handle project info field change */
  const handleProjectInfoField = useCallback(
    (field: keyof ProjectInfo, value: string) => {
      onProjectInfoChange({ ...projectInfo, [field]: value });
    },
    [projectInfo, onProjectInfoChange]
  );

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: 'var(--gt-space-2) var(--gt-space-3)',
    fontSize: 'var(--gt-font-sm)',
    borderRadius: 'var(--gt-radius-sm)',
    border: '1px solid #d0d0d0',
    color: 'var(--gt-text-primary)',
    boxSizing: 'border-box',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: 'var(--gt-font-sm)',
    fontWeight: 600,
    color: 'var(--gt-text-primary)',
    marginBottom: 'var(--gt-space-1)',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-4)' }}>
      {/* Error message */}
      {error && (
        <div
          role="alert"
          style={{
            padding: 'var(--gt-space-2) var(--gt-space-3)',
            backgroundColor: 'rgba(220, 53, 69, 0.08)',
            color: 'var(--gt-danger)',
            borderRadius: 'var(--gt-radius-sm)',
            fontSize: 'var(--gt-font-sm)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            aria-label="关闭错误提示"
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--gt-danger)',
              fontWeight: 600,
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Resume prompt — shown when templates already exist */}
      {showResumePrompt && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 100,
            backgroundColor: 'rgba(0,0,0,0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 'var(--gt-space-4)',
          }}
          role="dialog"
          aria-modal="true"
          aria-label="确认是否更新模板"
        >
          <div
            className="gt-card"
            style={{ maxWidth: 460, width: '100%' }}
          >
            <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
              检测到已上传模板
            </div>
            <div className="gt-card-content" style={{ fontSize: 'var(--gt-font-sm)', lineHeight: 1.7 }}>
              <p style={{ marginBottom: 'var(--gt-space-2)' }}>
                已有 {templates.length} 个模板，当前选中：
              </p>
              <p style={{ fontWeight: 600, color: 'var(--gt-primary)', marginBottom: 'var(--gt-space-3)' }}>
                {templates.find((t) => t.id === selectedTemplateId)?.name || '未选择'}
              </p>
              <p>是否需要更新上传新模板？选择「使用已有模板」将直接使用当前模板继续。</p>
            </div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: 'var(--gt-space-2)',
                padding: '0 var(--gt-space-4) var(--gt-space-4)',
              }}
            >
              <button
                className="gt-button gt-button--primary"
                onClick={() => setShowResumePrompt(false)}
              >
                使用已有模板
              </button>
              <button
                className="gt-button gt-button--secondary"
                onClick={() => {
                  setShowResumePrompt(false);
                  // Stay on page, user can upload new template
                }}
              >
                重新上传
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Section 1: Template Upload ─── */}
      <div className="gt-card">
        <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
          模板上传
        </div>
        <div className="gt-card-content">
          <div style={{ display: 'flex', gap: 'var(--gt-space-3)', alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 200px', minWidth: 160 }}>
              <label htmlFor="template-type-select" style={labelStyle}>
                模板类型
              </label>
              <select
                id="template-type-select"
                value={uploadType}
                onChange={(e) => setUploadType(e.target.value as TemplateType)}
                aria-label="选择模板类型"
                style={inputStyle}
              >
                {TEMPLATE_TYPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <button
                className="gt-button gt-button--primary"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                aria-label="选择模板文件上传"
              >
                {uploading ? '上传中...' : '选择文件上传'}
              </button>
            </div>
          </div>
          <p style={{ marginTop: 'var(--gt-space-2)', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
            支持 .docx、.xlsx、.xls、.pdf 格式
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_FORMATS}
            onChange={handleFileInputChange}
            style={{ display: 'none' }}
            aria-hidden="true"
          />
          {/* Hidden input for template update */}
          <input
            ref={updateFileInputRef}
            type="file"
            accept={ACCEPTED_FORMATS}
            onChange={handleUpdateFileChange}
            style={{ display: 'none' }}
            aria-hidden="true"
          />
        </div>
      </div>

      {/* ─── Section 2: Template List ─── */}
      <div className="gt-card">
        <div className="gt-card-header" style={{ color: 'var(--gt-primary)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>已上传模板</span>
          {templates.length > 0 && (
            <input
              type="text"
              value={templateSearch}
              onChange={(e) => setTemplateSearch(e.target.value)}
              placeholder="🔍 搜索模板名称..."
              style={{
                ...inputStyle,
                width: 220,
                padding: '4px 10px',
                fontSize: 'var(--gt-font-xs)',
                fontWeight: 400,
              }}
            />
          )}
        </div>
        <div className="gt-card-content">
          {loading ? (
            <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)' }}>
              加载中...
            </div>
          ) : templates.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
              暂无已上传模板，请先上传模板文件
            </div>
          ) : (() => {
            const keyword = templateSearch.trim().toLowerCase();
            const filteredTemplates = keyword
              ? templates.filter((t) =>
                  t.name.toLowerCase().includes(keyword) ||
                  (TEMPLATE_TYPE_LABELS[t.template_type] || '').includes(keyword)
                )
              : templates;
            return filteredTemplates.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
                未找到匹配的模板
              </div>
            ) : (
            <table className="gt-table" aria-label="已上传模板列表">
              <caption
                style={{
                  textAlign: 'left',
                  padding: 'var(--gt-space-2) 0',
                  fontWeight: 600,
                  fontSize: 'var(--gt-font-sm)',
                  color: 'var(--gt-text-primary)',
                }}
              >
                {keyword ? `搜索结果（${filteredTemplates.length} / ${templates.length} 个）` : `模板列表（${templates.length} 个）`}
              </caption>
              <thead>
                <tr>
                  <th scope="col">名称</th>
                  <th scope="col">类型</th>
                  <th scope="col">格式</th>
                  <th scope="col">上传时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredTemplates.map((tpl) => {
                  const isSelected = selectedTemplateId === tpl.id;
                  return (
                    <tr
                      key={tpl.id}
                      onClick={() => onTemplateSelect(tpl.id)}
                      role="row"
                      aria-selected={isSelected}
                      style={{
                        cursor: 'pointer',
                        backgroundColor: isSelected ? 'rgba(75, 45, 119, 0.06)' : undefined,
                      }}
                    >
                      <td
                        style={{
                          fontWeight: isSelected ? 600 : 400,
                          color: isSelected ? 'var(--gt-primary)' : 'var(--gt-text-primary)',
                          maxWidth: 200,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                        title={tpl.name}
                      >
                        {tpl.name}
                      </td>
                      <td style={{ fontSize: 'var(--gt-font-xs)' }}>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '2px 8px',
                            borderRadius: 'var(--gt-radius-sm)',
                            fontSize: 'var(--gt-font-xs)',
                            fontWeight: 600,
                            color: '#fff',
                            backgroundColor: 'var(--gt-primary)',
                          }}
                        >
                          {TEMPLATE_TYPE_LABELS[tpl.template_type] || tpl.template_type}
                        </span>
                      </td>
                      <td style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
                        {getFormatLabel(tpl.file_format)}
                      </td>
                      <td style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
                        {formatDate(tpl.uploaded_at)}
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 'var(--gt-space-1)' }}>
                          <button
                            className="gt-button gt-button--secondary"
                            style={{ padding: '2px 8px', fontSize: 'var(--gt-font-xs)' }}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleUpdateClick(tpl.id);
                            }}
                            aria-label={`更新模板 ${tpl.name}`}
                          >
                            更新
                          </button>
                          <button
                            className="gt-button gt-button--secondary"
                            style={{
                              padding: '2px 8px',
                              fontSize: 'var(--gt-font-xs)',
                              color: 'var(--gt-danger)',
                              borderColor: 'var(--gt-danger)',
                            }}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(tpl.id);
                            }}
                            aria-label={`删除模板 ${tpl.name}`}
                          >
                            删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            );
          })()}
        </div>
      </div>

      {/* ─── Section 3: Knowledge Library Selection ─── */}
      <div className="gt-card">
        <div
          className="gt-card-header"
          style={{
            color: 'var(--gt-primary)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            userSelect: 'none',
          }}
          onClick={() => setKnowledgeSectionOpen((v) => !v)}
          role="button"
          aria-expanded={knowledgeSectionOpen}
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setKnowledgeSectionOpen((v) => !v); } }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, fontSize: 14, fontWeight: 600, color: '#6b7280', border: '1px solid #d1d5db', borderRadius: 3, lineHeight: 1 }}>{knowledgeSectionOpen ? '−' : '+'}</span>
            关联知识库
            {knowledgeLibraryIds.length > 0 && (
              <span style={{ fontSize: 'var(--gt-font-xs)', fontWeight: 400, color: 'var(--gt-text-secondary)' }}>
                （已选 {knowledgeLibraryIds.length} 个库）
              </span>
            )}
          </span>
          <span style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', fontWeight: 400 }}>
            {knowledgeSectionOpen ? '收起' : '展开'}
          </span>
        </div>
        {knowledgeSectionOpen && (
        <div className="gt-card-content">
          <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', marginBottom: 'var(--gt-space-3)' }}>
            选择需要关联的知识库和文档，文档生成时将参考所选内容。点击知识库名称展开查看文档列表。
          </p>
          {librariesLoading ? (
            <div style={{ textAlign: 'center', padding: 'var(--gt-space-4)', color: 'var(--gt-text-secondary)' }}>
              加载知识库列表...
            </div>
          ) : libraries.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 'var(--gt-space-4)', color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
              暂无可用知识库
            </div>
          ) : (
            <fieldset style={{ border: 'none', padding: 0, margin: 0 }}>
              <legend style={{ ...labelStyle, marginBottom: 'var(--gt-space-2)' }}>
                可用知识库（已选 {knowledgeLibraryIds.length} 个）
              </legend>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-2)' }}>
                {libraries.map((lib) => {
                  const isExpanded = expandedLibraries.has(lib.id);
                  const docs = libraryDocs[lib.id] || [];
                  const selectedDocIds = knowledgeLibraryDocs[lib.id] || [];
                  const isDocsLoading = loadingDocs.has(lib.id);
                  const allSelected = docs.length > 0 && selectedDocIds.length === docs.length;
                  const someSelected = selectedDocIds.length > 0 && selectedDocIds.length < docs.length;
                  const hasSelection = selectedDocIds.length > 0;

                  return (
                    <div
                      key={lib.id}
                      style={{
                        borderRadius: 'var(--gt-radius-sm)',
                        border: `1px solid ${hasSelection ? 'var(--gt-primary)' : '#e8e8e8'}`,
                        backgroundColor: hasSelection ? 'rgba(75, 45, 119, 0.04)' : 'transparent',
                        overflow: 'hidden',
                        transition: 'border-color 0.2s, background-color 0.2s',
                      }}
                    >
                      {/* Library header - clickable to expand */}
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 'var(--gt-space-2)',
                          padding: 'var(--gt-space-2) var(--gt-space-3)',
                          cursor: 'pointer',
                          userSelect: 'none',
                        }}
                        onClick={() => handleLibraryExpand(lib.id)}
                        role="button"
                        aria-expanded={isExpanded}
                        aria-label={`${isExpanded ? '收起' : '展开'}知识库: ${lib.name}`}
                        tabIndex={0}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleLibraryExpand(lib.id); } }}
                      >
                        {/* Expand/collapse toggle */}
                        <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, fontSize: 14, fontWeight: 600, color: '#6b7280', border: '1px solid #d1d5db', borderRadius: 3, lineHeight: 1, flexShrink: 0 }}>
                          {isExpanded ? '−' : '+'}
                        </span>
                        {/* Library-level checkbox */}
                        <input
                          type="checkbox"
                          checked={allSelected}
                          ref={(el) => { if (el) el.indeterminate = someSelected; }}
                          onChange={(e) => { e.stopPropagation(); handleLibraryToggle(lib.id); }}
                          onClick={(e) => e.stopPropagation()}
                          aria-label={`全选知识库: ${lib.name}`}
                          style={{ accentColor: 'var(--gt-primary)' }}
                        />
                        <div style={{ flex: 1 }}>
                          <span style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)' }}>
                            {lib.name}
                          </span>
                          {lib.description && (
                            <span style={{ display: 'block', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginTop: 1 }}>
                              {lib.description}
                            </span>
                          )}
                        </div>
                        <span style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', whiteSpace: 'nowrap' }}>
                          {hasSelection ? `${selectedDocIds.length}/` : ''}{lib.document_count ?? 0} 个文档
                        </span>
                      </div>

                      {/* Expanded document list */}
                      {isExpanded && (
                        <div style={{ borderTop: '1px solid #e8e8e8', padding: 'var(--gt-space-2) var(--gt-space-3)', paddingLeft: 'calc(var(--gt-space-3) + 32px)', backgroundColor: 'rgba(0,0,0,0.01)' }}>
                          {isDocsLoading ? (
                            <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', padding: 'var(--gt-space-2) 0' }}>
                              加载文档列表...
                            </div>
                          ) : docs.length === 0 ? (
                            <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', padding: 'var(--gt-space-2) 0' }}>
                              该知识库暂无文档
                            </div>
                          ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                              {docs.map((doc) => {
                                const isDocSelected = selectedDocIds.includes(doc.id);
                                return (
                                  <label
                                    key={doc.id}
                                    style={{
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: 'var(--gt-space-2)',
                                      padding: '4px 8px',
                                      borderRadius: 'var(--gt-radius-sm)',
                                      cursor: 'pointer',
                                      backgroundColor: isDocSelected ? 'rgba(75, 45, 119, 0.06)' : 'transparent',
                                      fontSize: 'var(--gt-font-xs)',
                                    }}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={isDocSelected}
                                      onChange={() => handleDocToggle(lib.id, doc.id)}
                                      aria-label={`选择文档: ${doc.filename}`}
                                      style={{ accentColor: 'var(--gt-primary)' }}
                                    />
                                    <span style={{ flex: 1, color: 'var(--gt-text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={doc.filename}>
                                      {doc.filename}
                                    </span>
                                    {doc.created_at && (
                                      <span style={{ color: 'var(--gt-text-secondary)', whiteSpace: 'nowrap', fontSize: 11 }}>
                                        {doc.created_at}
                                      </span>
                                    )}
                                  </label>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </fieldset>
          )}
        </div>
        )}
      </div>

      {/* ─── Section 4: Project Info Form ─── */}
      <div className="gt-card">
        <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
          项目信息
        </div>
        <div className="gt-card-content">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-4)' }}>
            <div>
              <label htmlFor="project-client-name" style={labelStyle}>
                客户名称 <span style={{ color: 'var(--gt-danger)' }}>*</span>
              </label>
              <input
                id="project-client-name"
                type="text"
                value={projectInfo.client_name}
                onChange={(e) => handleProjectInfoField('client_name', e.target.value)}
                placeholder="请输入客户名称"
                required
                aria-required="true"
                style={inputStyle}
              />
            </div>
            <div>
              <label htmlFor="project-audit-period" style={labelStyle}>
                审计期间 <span style={{ color: 'var(--gt-danger)' }}>*</span>
              </label>
              <input
                id="project-audit-period"
                type="text"
                value={projectInfo.audit_period}
                onChange={(e) => handleProjectInfoField('audit_period', e.target.value)}
                placeholder="例如：2024年1月1日至2024年12月31日"
                required
                aria-required="true"
                style={inputStyle}
              />
            </div>
            <div style={{ display: 'flex', gap: 'var(--gt-space-3)' }}>
              <div style={{ flex: 1 }}>
                <label htmlFor="project-preparer-name" style={labelStyle}>
                  编制人
                </label>
                <input
                  id="project-preparer-name"
                  type="text"
                  value={projectInfo.preparer_name || ''}
                  onChange={(e) => handleProjectInfoField('preparer_name', e.target.value)}
                  placeholder="请输入编制人姓名"
                  style={inputStyle}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label htmlFor="project-preparer-role" style={labelStyle}>
                  角色
                </label>
                <select
                  id="project-preparer-role"
                  value={projectInfo.preparer_role || ''}
                  onChange={(e) => handleProjectInfoField('preparer_role', e.target.value)}
                  aria-label="选择编制人角色"
                  style={inputStyle}
                >
                  <option value="">请选择角色</option>
                  <option value="assistant">助理</option>
                  <option value="project_manager">项目经理</option>
                  <option value="manager">经理</option>
                  <option value="senior_manager">高级经理</option>
                  <option value="partner">合伙人</option>
                </select>
              </div>
            </div>
            <div>
              <label htmlFor="project-key-matters" style={labelStyle}>
                重要事项
              </label>
              <textarea
                id="project-key-matters"
                value={projectInfo.key_matters || ''}
                onChange={(e) => handleProjectInfoField('key_matters', e.target.value)}
                placeholder="请输入需要特别关注的重要事项（可选）"
                rows={3}
                aria-label="重要事项"
                style={{
                  ...inputStyle,
                  resize: 'vertical',
                  fontFamily: 'inherit',
                }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TemplateSelector;
