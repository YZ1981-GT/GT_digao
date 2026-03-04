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
  onTemplateSelect: (templateId: string) => void;
  onProjectInfoChange: (info: ProjectInfo) => void;
  onKnowledgeLibraryIdsChange: (ids: string[]) => void;
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
  onTemplateSelect,
  onProjectInfoChange,
  onKnowledgeLibraryIdsChange,
}) => {
  // Template state
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Upload state
  const [uploadType, setUploadType] = useState<TemplateType>('audit_plan');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const updateFileInputRef = useRef<HTMLInputElement>(null);
  const [updatingTemplateId, setUpdatingTemplateId] = useState<string | null>(null);

  // Knowledge library state
  const [libraries, setLibraries] = useState<KnowledgeLibrary[]>([]);
  const [librariesLoading, setLibrariesLoading] = useState(false);

  /** Fetch template list */
  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await templateApi.listTemplates();
      setTemplates(response.data);
    } catch (err: any) {
      setError(err.message || '加载模板列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  /** Fetch knowledge libraries */
  const fetchLibraries = useCallback(async () => {
    setLibrariesLoading(true);
    try {
      const response = await knowledgeApi.getLibraries();
      const data = response.data;
      // Handle both array and object formats
      if (Array.isArray(data)) {
        setLibraries(data);
      } else if (data && typeof data === 'object') {
        const libs: KnowledgeLibrary[] = Object.entries(data).map(([id, info]: [string, any]) => ({
          id,
          name: info.name || id,
          description: info.description || '',
          document_count: info.document_count ?? info.documents?.length ?? 0,
        }));
        setLibraries(libs);
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
        const newTemplate = response.data;
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
          const updated = response.data;
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

  /** Handle knowledge library checkbox toggle */
  const handleLibraryToggle = useCallback(
    (libraryId: string) => {
      const newIds = knowledgeLibraryIds.includes(libraryId)
        ? knowledgeLibraryIds.filter((id) => id !== libraryId)
        : [...knowledgeLibraryIds, libraryId];
      onKnowledgeLibraryIdsChange(newIds);
    },
    [knowledgeLibraryIds, onKnowledgeLibraryIdsChange]
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
        <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
          已上传模板
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
                模板列表（{templates.length} 个）
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
                {templates.map((tpl) => {
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
          )}
        </div>
      </div>

      {/* ─── Section 3: Knowledge Library Selection ─── */}
      <div className="gt-card">
        <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
          关联知识库
        </div>
        <div className="gt-card-content">
          <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', marginBottom: 'var(--gt-space-3)' }}>
            选择需要关联的知识库，文档生成时将参考所选知识库中的内容。
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
                  const isChecked = knowledgeLibraryIds.includes(lib.id);
                  return (
                    <label
                      key={lib.id}
                      style={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: 'var(--gt-space-2)',
                        padding: 'var(--gt-space-2) var(--gt-space-3)',
                        borderRadius: 'var(--gt-radius-sm)',
                        border: `1px solid ${isChecked ? 'var(--gt-primary)' : '#e8e8e8'}`,
                        backgroundColor: isChecked ? 'rgba(75, 45, 119, 0.04)' : 'transparent',
                        cursor: 'pointer',
                        transition: 'border-color 0.2s, background-color 0.2s',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => handleLibraryToggle(lib.id)}
                        aria-label={`关联知识库: ${lib.name}`}
                        style={{ marginTop: 2, accentColor: 'var(--gt-primary)' }}
                      />
                      <div style={{ flex: 1 }}>
                        <span style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)' }}>
                          {lib.name}
                        </span>
                        {lib.description && (
                          <span style={{ display: 'block', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginTop: 2 }}>
                            {lib.description}
                          </span>
                        )}
                        {lib.document_count !== undefined && (
                          <span style={{ display: 'block', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginTop: 2 }}>
                            {lib.document_count} 个文档
                          </span>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}
        </div>
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
