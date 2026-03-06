/**
 * PromptSelector - 提示词选择组件
 *
 * 展示 Prompt_Library 中的预置提示词列表，支持按会计科目筛选。
 * 展示提示词名称、适用科目、来源标识、摘要和使用次数。
 * 提供提示词预览区域展示完整内容。
 * 提供自定义提示词输入区域和"保存为提示词"选项。
 * 支持提示词编辑、替换、恢复默认操作。
 *
 * Requirements: 2.9, 2.10, 13.1-13.12
 */
import React, { useState, useEffect, useCallback } from 'react';
import { promptApi } from '../services/api';
import type { ReviewPromptInfo, ReviewPromptDetail, PromptSource } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface PromptSelectorProps {
  selectedPromptId: string | null;
  customPrompt: string;
  onPromptSelect: (promptId: string | null) => void;
  onCustomPromptChange: (prompt: string) => void;
}

/** 会计科目筛选选项 */
const SUBJECT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: '全部科目' },
  { value: 'monetary_funds', label: '货币资金' },
  { value: 'accounts_receivable', label: '应收账款' },
  { value: 'inventory', label: '存货' },
  { value: 'fixed_assets', label: '固定资产' },
  { value: 'long_term_equity_investment', label: '长期股权投资' },
  { value: 'revenue', label: '收入' },
  { value: 'cost', label: '成本' },
  { value: 'intangible_assets', label: '无形资产' },
  { value: 'employee_compensation', label: '职工薪酬' },
  { value: 'taxes_payable', label: '应交税费' },
  { value: 'other_payables', label: '其他应付款' },
  { value: 'accounts_payable', label: '应付账款' },
  { value: 'construction_in_progress', label: '在建工程' },
  { value: 'investment_property', label: '投资性房地产' },
  { value: 'borrowings', label: '借款' },
  { value: 'equity', label: '所有者权益' },
  { value: 'audit_plan', label: '审计方案' },
  { value: 'overall_strategy', label: '总体审计策略及具体审计计划' },
  { value: 'other', label: '其他' },
];

/** 来源标识映射 */
const SOURCE_LABELS: Record<PromptSource, { text: string; color: string }> = {
  preset: { text: '预置', color: 'var(--gt-primary)' },
  user_modified: { text: '已修改', color: 'var(--gt-teal)' },
  user_replaced: { text: '已替换', color: 'var(--gt-coral)' },
  user_appended: { text: '用户追加', color: 'var(--gt-wheat)' },
};

const PromptSelector: React.FC<PromptSelectorProps> = ({
  selectedPromptId,
  customPrompt,
  onPromptSelect,
  onCustomPromptChange,
}) => {
  const [prompts, setPrompts] = useState<ReviewPromptInfo[]>([]);
  const [subjectFilter, setSubjectFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Preview state
  const [previewDetail, setPreviewDetail] = useState<ReviewPromptDetail | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Edit state
  const [editMode, setEditMode] = useState<'edit' | 'replace' | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editSaving, setEditSaving] = useState(false);

  // Save custom prompt state
  const [showSaveForm, setShowSaveForm] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saveSubject, setSaveSubject] = useState('');
  const [saving, setSaving] = useState(false);

  /** Fetch prompt list */
  const fetchPrompts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await promptApi.listPrompts(subjectFilter || undefined);
      const data = response.data as any;
      setPrompts(data?.prompts ?? (Array.isArray(data) ? data : []));
    } catch (err: any) {
      setError(err.message || '加载提示词列表失败');
    } finally {
      setLoading(false);
    }
  }, [subjectFilter]);

  useEffect(() => {
    fetchPrompts();
  }, [fetchPrompts]);

  /** Fetch prompt detail for preview */
  const handlePromptClick = useCallback(
    async (promptId: string) => {
      onPromptSelect(promptId);
      setPreviewLoading(true);
      setEditMode(null);
      try {
        const response = await promptApi.getPrompt(promptId);
        const data = response.data as any;
        setPreviewDetail(data?.prompt ?? data ?? null);
      } catch (err: any) {
        setPreviewDetail(null);
      } finally {
        setPreviewLoading(false);
      }
    },
    [onPromptSelect]
  );

  /** Deselect prompt */
  const handleDeselect = useCallback(() => {
    onPromptSelect(null);
    setPreviewDetail(null);
    setEditMode(null);
  }, [onPromptSelect]);

  /** Start edit mode */
  const handleStartEdit = useCallback(() => {
    if (previewDetail) {
      setEditContent(previewDetail.content);
      setEditMode('edit');
    }
  }, [previewDetail]);

  /** Start replace mode */
  const handleStartReplace = useCallback(() => {
    setEditContent('');
    setEditMode('replace');
  }, []);

  /** Cancel edit */
  const handleCancelEdit = useCallback(() => {
    setEditMode(null);
    setEditContent('');
  }, []);

  /** Save edit */
  const handleSaveEdit = useCallback(async () => {
    if (!previewDetail || !editContent.trim()) return;
    setEditSaving(true);
    try {
      if (editMode === 'edit') {
        await promptApi.editPrompt(previewDetail.id, { content: editContent });
      } else if (editMode === 'replace') {
        await promptApi.replacePrompt(previewDetail.id, { content: editContent });
      }
      setEditMode(null);
      setEditContent('');
      // Refresh preview and list
      const response = await promptApi.getPrompt(previewDetail.id);
      const rData = response.data as any;
      setPreviewDetail(rData?.prompt ?? rData ?? null);
      fetchPrompts();
    } catch (err: any) {
      setError(err.message || '保存失败');
    } finally {
      setEditSaving(false);
    }
  }, [previewDetail, editContent, editMode, fetchPrompts]);

  /** Restore preset default */
  const handleRestore = useCallback(async () => {
    if (!previewDetail) return;
    setEditSaving(true);
    try {
      await promptApi.restorePrompt(previewDetail.id);
      const response = await promptApi.getPrompt(previewDetail.id);
      const rData2 = response.data as any;
      setPreviewDetail(rData2?.prompt ?? rData2 ?? null);
      fetchPrompts();
    } catch (err: any) {
      setError(err.message || '恢复默认失败');
    } finally {
      setEditSaving(false);
    }
  }, [previewDetail, fetchPrompts]);

  /** Delete user-appended prompt */
  const handleDelete = useCallback(async () => {
    if (!previewDetail) return;
    try {
      await promptApi.deletePrompt(previewDetail.id);
      onPromptSelect(null);
      setPreviewDetail(null);
      fetchPrompts();
    } catch (err: any) {
      setError(err.message || '删除失败');
    }
  }, [previewDetail, onPromptSelect, fetchPrompts]);

  /** Save custom prompt to library */
  const handleSaveCustomPrompt = useCallback(async () => {
    if (!saveName.trim() || !customPrompt.trim()) return;
    setSaving(true);
    try {
      await promptApi.savePrompt({
        name: saveName,
        content: customPrompt,
        subject: saveSubject || undefined,
      });
      setShowSaveForm(false);
      setSaveName('');
      setSaveSubject('');
      fetchPrompts();
    } catch (err: any) {
      setError(err.message || '保存提示词失败');
    } finally {
      setSaving(false);
    }
  }, [saveName, customPrompt, saveSubject, fetchPrompts]);

  return (
    <div className="gt-card">
      <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
        提示词选择
      </div>
      <div className="gt-card-content">
        {/* Subject filter */}
        <div style={{ marginBottom: 'var(--gt-space-4)' }}>
          <label
            htmlFor="prompt-subject-filter"
            style={{
              display: 'block',
              fontSize: 'var(--gt-font-sm)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-1)',
            }}
          >
            按会计科目筛选
          </label>
          <select
            id="prompt-subject-filter"
            value={subjectFilter}
            onChange={(e) => setSubjectFilter(e.target.value)}
            aria-label="按会计科目筛选提示词"
            style={{
              width: '100%',
              maxWidth: 320,
              padding: 'var(--gt-space-2) var(--gt-space-3)',
              fontSize: 'var(--gt-font-sm)',
              borderRadius: 'var(--gt-radius-sm)',
              border: '1px solid #d0d0d0',
              color: 'var(--gt-text-primary)',
            }}
          >
            {SUBJECT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Error message */}
        {error && (
          <div
            role="alert"
            style={{
              padding: 'var(--gt-space-2) var(--gt-space-3)',
              marginBottom: 'var(--gt-space-3)',
              backgroundColor: 'rgba(220, 53, 69, 0.08)',
              color: 'var(--gt-danger)',
              borderRadius: 'var(--gt-radius-sm)',
              fontSize: 'var(--gt-font-sm)',
            }}
          >
            {error}
            <button
              onClick={() => setError(null)}
              aria-label="关闭错误提示"
              style={{
                marginLeft: 'var(--gt-space-2)',
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

        {/* Prompt list table */}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)' }}>
            加载中...
          </div>
        ) : prompts.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
            暂无提示词
          </div>
        ) : (
          <div style={{ maxHeight: 320, overflowY: 'auto', marginBottom: 'var(--gt-space-4)' }}>
            <table className="gt-table" aria-label="提示词列表">
              <caption
                style={{
                  textAlign: 'left',
                  padding: 'var(--gt-space-2) 0',
                  fontWeight: 600,
                  fontSize: 'var(--gt-font-sm)',
                  color: 'var(--gt-text-primary)',
                }}
              >
                可用提示词（{prompts.length} 个）
              </caption>
              <thead>
                <tr>
                  <th scope="col">名称</th>
                  <th scope="col">适用科目</th>
                  <th scope="col">来源</th>
                  <th scope="col">摘要</th>
                  <th scope="col">使用次数</th>
                </tr>
              </thead>
              <tbody>
                {prompts.map((prompt) => {
                  const isSelected = selectedPromptId === prompt.id;
                  const sourceInfo = SOURCE_LABELS[prompt.source] || SOURCE_LABELS.preset;
                  return (
                    <tr
                      key={prompt.id}
                      onClick={() => handlePromptClick(prompt.id)}
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
                          maxWidth: 180,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                        title={prompt.name}
                      >
                        {prompt.name}
                      </td>
                      <td style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
                        {prompt.subject || '—'}
                      </td>
                      <td>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '2px 8px',
                            borderRadius: 'var(--gt-radius-sm)',
                            fontSize: 'var(--gt-font-xs)',
                            fontWeight: 600,
                            color: '#fff',
                            backgroundColor: sourceInfo.color,
                          }}
                        >
                          {sourceInfo.text}
                        </span>
                      </td>
                      <td
                        style={{
                          maxWidth: 200,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          fontSize: 'var(--gt-font-xs)',
                          color: 'var(--gt-text-secondary)',
                        }}
                        title={prompt.summary}
                      >
                        {prompt.summary}
                      </td>
                      <td style={{ textAlign: 'center', fontSize: 'var(--gt-font-xs)' }}>
                        {prompt.usage_count}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Prompt preview area */}
        {selectedPromptId && (
          <div
            style={{
              marginBottom: 'var(--gt-space-4)',
              border: '1px solid #e8e8e8',
              borderRadius: 'var(--gt-radius-md)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: 'var(--gt-space-3) var(--gt-space-4)',
                backgroundColor: 'rgba(75, 45, 119, 0.04)',
                borderBottom: '1px solid #e8e8e8',
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)' }}>
                提示词预览
                {previewDetail && (
                  <span style={{ marginLeft: 'var(--gt-space-2)', fontWeight: 400, color: 'var(--gt-text-secondary)' }}>
                    — {previewDetail.name}
                  </span>
                )}
              </span>
              <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
                {/* Action buttons for preset prompts */}
                {previewDetail && previewDetail.is_preset && editMode === null && (
                  <>
                    <button
                      className="gt-button gt-button--secondary"
                      style={{ padding: '2px 10px', fontSize: 'var(--gt-font-xs)' }}
                      onClick={handleStartEdit}
                      aria-label="编辑提示词"
                    >
                      编辑
                    </button>
                    <button
                      className="gt-button gt-button--secondary"
                      style={{ padding: '2px 10px', fontSize: 'var(--gt-font-xs)' }}
                      onClick={handleStartReplace}
                      aria-label="替换提示词"
                    >
                      替换
                    </button>
                    {previewDetail.has_custom_version && (
                      <button
                        className="gt-button gt-button--secondary"
                        style={{ padding: '2px 10px', fontSize: 'var(--gt-font-xs)' }}
                        onClick={handleRestore}
                        disabled={editSaving}
                        aria-label="恢复默认提示词"
                      >
                        恢复默认
                      </button>
                    )}
                  </>
                )}
                {/* Delete button for user-appended prompts */}
                {previewDetail && previewDetail.source === 'user_appended' && editMode === null && (
                  <button
                    className="gt-button gt-button--secondary"
                    style={{
                      padding: '2px 10px',
                      fontSize: 'var(--gt-font-xs)',
                      color: 'var(--gt-danger)',
                      borderColor: 'var(--gt-danger)',
                    }}
                    onClick={handleDelete}
                    aria-label="删除提示词"
                  >
                    删除
                  </button>
                )}
                <button
                  className="gt-button gt-button--secondary"
                  style={{ padding: '2px 10px', fontSize: 'var(--gt-font-xs)' }}
                  onClick={handleDeselect}
                  aria-label="取消选择提示词"
                >
                  取消选择
                </button>
              </div>
            </div>

            <div style={{ padding: 'var(--gt-space-4)' }}>
              {previewLoading ? (
                <div style={{ textAlign: 'center', padding: 'var(--gt-space-4)', color: 'var(--gt-text-secondary)' }}>
                  加载中...
                </div>
              ) : editMode !== null ? (
                /* Edit / Replace mode */
                <div>
                  <label
                    htmlFor="prompt-edit-textarea"
                    style={{
                      display: 'block',
                      fontSize: 'var(--gt-font-sm)',
                      fontWeight: 600,
                      color: 'var(--gt-text-primary)',
                      marginBottom: 'var(--gt-space-2)',
                    }}
                  >
                    {editMode === 'edit' ? '编辑提示词内容' : '输入替换内容'}
                  </label>
                  <textarea
                    id="prompt-edit-textarea"
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    aria-label={editMode === 'edit' ? '编辑提示词内容' : '输入替换提示词内容'}
                    rows={10}
                    style={{
                      width: '100%',
                      padding: 'var(--gt-space-3)',
                      fontSize: 'var(--gt-font-sm)',
                      borderRadius: 'var(--gt-radius-sm)',
                      border: '1px solid #d0d0d0',
                      resize: 'vertical',
                      fontFamily: 'inherit',
                      color: 'var(--gt-text-primary)',
                      boxSizing: 'border-box',
                    }}
                  />
                  <div style={{ display: 'flex', gap: 'var(--gt-space-2)', marginTop: 'var(--gt-space-3)' }}>
                    <button
                      className="gt-button gt-button--primary"
                      onClick={handleSaveEdit}
                      disabled={editSaving || !editContent.trim()}
                      aria-label="保存修改"
                    >
                      {editSaving ? '保存中...' : '保存'}
                    </button>
                    <button
                      className="gt-button gt-button--secondary"
                      onClick={handleCancelEdit}
                      disabled={editSaving}
                      aria-label="取消编辑"
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : previewDetail ? (
                /* Preview content */
                <pre
                  style={{
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    fontSize: 'var(--gt-font-sm)',
                    color: 'var(--gt-text-primary)',
                    lineHeight: 1.6,
                    maxHeight: 300,
                    overflowY: 'auto',
                    margin: 0,
                    fontFamily: 'inherit',
                  }}
                >
                  {previewDetail.content}
                </pre>
              ) : null}
            </div>
          </div>
        )}

        {/* Custom prompt textarea */}
        <div style={{ marginBottom: 'var(--gt-space-4)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--gt-space-2)' }}>
            <label
              htmlFor="custom-prompt-textarea"
              style={{
                fontSize: 'var(--gt-font-sm)',
                fontWeight: 600,
                color: 'var(--gt-text-primary)',
              }}
            >
              自定义提示词
            </label>
            {customPrompt.trim() && (
              <button
                className="gt-button gt-button--secondary"
                style={{ padding: '2px 10px', fontSize: 'var(--gt-font-xs)' }}
                onClick={() => setShowSaveForm(true)}
                aria-label="保存为提示词"
              >
                保存为提示词
              </button>
            )}
          </div>
          <textarea
            id="custom-prompt-textarea"
            value={customPrompt}
            onChange={(e) => onCustomPromptChange(e.target.value)}
            placeholder="输入自定义复核提示词，可替代或补充预置提示词..."
            aria-label="自定义提示词输入区域"
            rows={4}
            style={{
              width: '100%',
              padding: 'var(--gt-space-3)',
              fontSize: 'var(--gt-font-sm)',
              borderRadius: 'var(--gt-radius-sm)',
              border: '1px solid #d0d0d0',
              resize: 'vertical',
              fontFamily: 'inherit',
              color: 'var(--gt-text-primary)',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {/* Save custom prompt form */}
        {showSaveForm && (
          <div
            style={{
              padding: 'var(--gt-space-4)',
              border: '1px solid #e8e8e8',
              borderRadius: 'var(--gt-radius-md)',
              backgroundColor: 'rgba(75, 45, 119, 0.02)',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-3)' }}>
              保存为提示词
            </div>
            <div style={{ marginBottom: 'var(--gt-space-3)' }}>
              <label
                htmlFor="save-prompt-name"
                style={{
                  display: 'block',
                  fontSize: 'var(--gt-font-sm)',
                  color: 'var(--gt-text-primary)',
                  marginBottom: 'var(--gt-space-1)',
                }}
              >
                提示词名称
              </label>
              <input
                id="save-prompt-name"
                type="text"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder="输入提示词名称"
                aria-label="提示词名称"
                style={{
                  width: '100%',
                  padding: 'var(--gt-space-2) var(--gt-space-3)',
                  fontSize: 'var(--gt-font-sm)',
                  borderRadius: 'var(--gt-radius-sm)',
                  border: '1px solid #d0d0d0',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <div style={{ marginBottom: 'var(--gt-space-3)' }}>
              <label
                htmlFor="save-prompt-subject"
                style={{
                  display: 'block',
                  fontSize: 'var(--gt-font-sm)',
                  color: 'var(--gt-text-primary)',
                  marginBottom: 'var(--gt-space-1)',
                }}
              >
                适用会计科目（可选）
              </label>
              <select
                id="save-prompt-subject"
                value={saveSubject}
                onChange={(e) => setSaveSubject(e.target.value)}
                aria-label="选择适用会计科目"
                style={{
                  width: '100%',
                  maxWidth: 320,
                  padding: 'var(--gt-space-2) var(--gt-space-3)',
                  fontSize: 'var(--gt-font-sm)',
                  borderRadius: 'var(--gt-radius-sm)',
                  border: '1px solid #d0d0d0',
                }}
              >
                <option value="">不指定</option>
                {SUBJECT_OPTIONS.filter((o) => o.value !== '').map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
              <button
                className="gt-button gt-button--primary"
                onClick={handleSaveCustomPrompt}
                disabled={saving || !saveName.trim() || !customPrompt.trim()}
                aria-label="确认保存提示词"
              >
                {saving ? '保存中...' : '保存'}
              </button>
              <button
                className="gt-button gt-button--secondary"
                onClick={() => {
                  setShowSaveForm(false);
                  setSaveName('');
                  setSaveSubject('');
                }}
                disabled={saving}
                aria-label="取消保存提示词"
              >
                取消
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default PromptSelector;
