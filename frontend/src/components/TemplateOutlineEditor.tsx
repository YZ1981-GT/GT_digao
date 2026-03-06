/**
 * TemplateOutlineEditor - 模板大纲确认与调整组件
 *
 * 展示 LLM 自动识别的模板章节大纲（树形结构），支持增删改章节、调整层级和顺序。
 * 参照现有 OutlineEdit.tsx 的大纲编辑交互模式。
 * 用户确认后进入逐章节生成阶段。
 *
 * Requirements: 12.17
 */
import React, { useState, useEffect, useCallback } from 'react';
import type { TemplateOutlineItem } from '../types/audit';
import { generateApi } from '../services/api';
import '../styles/gt-design-tokens.css';

interface TemplateOutlineEditorProps {
  templateId: string;
  outline: TemplateOutlineItem[];
  onOutlineChange: (outline: TemplateOutlineItem[]) => void;
  onConfirm: () => void;
}

/** Reorder item IDs recursively after structural changes */
const reorderItems = (
  items: TemplateOutlineItem[],
  parentPrefix = '',
): TemplateOutlineItem[] =>
  items.map((item, idx) => {
    const newId = parentPrefix ? `${parentPrefix}.${idx + 1}` : `${idx + 1}`;
    return {
      ...item,
      id: newId,
      children: item.children?.length ? reorderItems(item.children, newId) : item.children,
    };
  });

const TemplateOutlineEditor: React.FC<TemplateOutlineEditorProps> = ({
  templateId,
  outline,
  onOutlineChange,
  onConfirm,
}) => {
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');

  /* ── Auto-extract outline on mount when outline is empty ── */
  useEffect(() => {
    if (outline.length === 0 && templateId) {
      let cancelled = false;
      const extract = async () => {
        setLoading(true);
        setError(null);
        try {
          const res = await generateApi.extractOutline({ template_id: templateId });
          if (!cancelled) {
            const data: TemplateOutlineItem[] = res.data?.outline ?? res.data ?? [];
            onOutlineChange(data);
          }
        } catch (err: any) {
          if (!cancelled) {
            setError(err?.response?.data?.message ?? err?.message ?? '大纲提取失败');
          }
        } finally {
          if (!cancelled) setLoading(false);
        }
      };
      extract();
      return () => { cancelled = true; };
    }
  }, [templateId]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Re-extract outline (force LLM) ── */
  const handleReExtract = useCallback(async (forceLlm: boolean) => {
    if (!templateId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await generateApi.extractOutline({ template_id: templateId, force_llm: forceLlm });
      const data: TemplateOutlineItem[] = res.data?.outline ?? res.data ?? [];
      onOutlineChange(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.response?.data?.message ?? err?.message ?? '大纲提取失败');
    } finally {
      setLoading(false);
    }
  }, [templateId, onOutlineChange]);

  /* ── Expand all items when outline changes ── */
  useEffect(() => {
    if (outline.length > 0) {
      const ids = new Set<string>();
      const collect = (items: TemplateOutlineItem[]) => {
        items.forEach((it) => {
          ids.add(it.id);
          if (it.children?.length) collect(it.children);
        });
      };
      collect(outline);
      setExpandedIds(ids);
    }
  }, [outline]);

  /* ── Toggle expand / collapse ── */
  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  /* ── Editing helpers ── */
  const startEdit = (item: TemplateOutlineItem) => {
    setEditingId(item.id);
    setEditTitle(item.title);
    setEditDescription(item.description);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditTitle('');
    setEditDescription('');
  };

  const saveEdit = () => {
    if (!editingId) return;
    const update = (items: TemplateOutlineItem[]): TemplateOutlineItem[] =>
      items.map((it) =>
        it.id === editingId
          ? { ...it, title: editTitle.trim(), description: editDescription.trim() }
          : { ...it, children: it.children?.length ? update(it.children) : it.children },
      );
    onOutlineChange(update(outline));
    cancelEdit();
  };

  /* ── Delete item ── */
  const deleteItem = (id: string) => {
    const remove = (items: TemplateOutlineItem[]): TemplateOutlineItem[] =>
      items
        .filter((it) => it.id !== id)
        .map((it) => ({
          ...it,
          children: it.children?.length ? remove(it.children) : it.children,
        }));
    onOutlineChange(reorderItems(remove(outline)));
  };

  /* ── Add child item ── */
  const addChild = (parentId: string) => {
    const add = (items: TemplateOutlineItem[]): TemplateOutlineItem[] =>
      items.map((it) => {
        if (it.id === parentId) {
          const childCount = it.children?.length ?? 0;
          const newItem: TemplateOutlineItem = {
            id: `${parentId}.${childCount + 1}`,
            title: '新章节',
            description: '',
            children: [],
          };
          return { ...it, children: [...(it.children ?? []), newItem] };
        }
        return { ...it, children: it.children?.length ? add(it.children) : it.children };
      });
    const updated = add(outline);
    onOutlineChange(updated);
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.add(parentId);
      return next;
    });
  };

  /* ── Add root item ── */
  const addRoot = () => {
    const newItem: TemplateOutlineItem = {
      id: `${outline.length + 1}`,
      title: '新章节',
      description: '',
      children: [],
    };
    onOutlineChange([...outline, newItem]);
  };

  /* ── Move item up / down within siblings ── */
  const moveItem = (id: string, direction: 'up' | 'down') => {
    const swap = (items: TemplateOutlineItem[]): TemplateOutlineItem[] => {
      const idx = items.findIndex((it) => it.id === id);
      if (idx !== -1) {
        const targetIdx = direction === 'up' ? idx - 1 : idx + 1;
        if (targetIdx < 0 || targetIdx >= items.length) return items;
        const copy = [...items];
        [copy[idx], copy[targetIdx]] = [copy[targetIdx], copy[idx]];
        return copy;
      }
      return items.map((it) => ({
        ...it,
        children: it.children?.length ? swap(it.children) : it.children,
      }));
    };
    onOutlineChange(reorderItems(swap(outline)));
  };

  /* ── Confirm outline ── */
  const handleConfirm = async () => {
    setConfirming(true);
    setError(null);
    try {
      await generateApi.confirmOutline({ template_id: templateId, outline: outline as any });
      onConfirm();
    } catch (err: any) {
      setError(err?.response?.data?.message ?? err?.message ?? '大纲确认失败');
    } finally {
      setConfirming(false);
    }
  };

  /* ── Render a single outline tree item ── */
  const renderItem = (item: TemplateOutlineItem, level = 0) => {
    const hasChildren = (item.children?.length ?? 0) > 0;
    const isExpanded = expandedIds.has(item.id);
    const isEditing = editingId === item.id;

    return (
      <li
        key={item.id}
        role="treeitem"
        aria-expanded={hasChildren ? isExpanded : undefined}
        aria-level={level + 1}
        style={{ listStyle: 'none' }}
      >
        <div
          className="gt-outline-row"
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 'var(--gt-space-2)',
            padding: 'var(--gt-space-2) var(--gt-space-3)',
            marginLeft: `${level * 24}px`,
            borderRadius: 'var(--gt-radius-sm)',
          }}
        >
          {/* Expand / collapse toggle */}
          {hasChildren ? (
            <button
              onClick={() => toggleExpand(item.id)}
              aria-label={isExpanded ? '折叠' : '展开'}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: '2px',
                marginTop: '2px',
                color: 'var(--gt-text-secondary)',
                fontSize: 'var(--gt-font-sm)',
              }}
            >
              {isExpanded ? '▾' : '▸'}
            </button>
          ) : (
            <span
              aria-hidden="true"
              style={{
                display: 'inline-block',
                width: '18px',
                textAlign: 'center',
                color: 'var(--gt-text-secondary)',
                fontSize: 'var(--gt-font-sm)',
                marginTop: '2px',
              }}
            >
              •
            </span>
          )}

          {/* Content area */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {isEditing ? (
              /* ── Edit mode ── */
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-2)' }}>
                <label style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
                  章节标题
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    style={{
                      display: 'block',
                      width: '100%',
                      padding: 'var(--gt-space-1) var(--gt-space-2)',
                      border: '1px solid #ccc',
                      borderRadius: 'var(--gt-radius-sm)',
                      fontSize: 'var(--gt-font-sm)',
                      marginTop: '2px',
                    }}
                  />
                </label>
                <label style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
                  章节描述
                  <textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    rows={2}
                    style={{
                      display: 'block',
                      width: '100%',
                      padding: 'var(--gt-space-1) var(--gt-space-2)',
                      border: '1px solid #ccc',
                      borderRadius: 'var(--gt-radius-sm)',
                      fontSize: 'var(--gt-font-xs)',
                      resize: 'vertical',
                      marginTop: '2px',
                    }}
                  />
                </label>
                <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
                  <button className="gt-button gt-button--primary" onClick={saveEdit} style={{ fontSize: 'var(--gt-font-xs)', padding: 'var(--gt-space-1) var(--gt-space-3)' }}>
                    保存
                  </button>
                  <button className="gt-button gt-button--secondary" onClick={cancelEdit} style={{ fontSize: 'var(--gt-font-xs)', padding: 'var(--gt-space-1) var(--gt-space-3)' }}>
                    取消
                  </button>
                </div>
              </div>
            ) : (
              /* ── Display mode ── */
              <>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span
                    style={{
                      fontSize: 'var(--gt-font-sm)',
                      fontWeight: 600,
                      color: level === 0 ? 'var(--gt-primary)' : 'var(--gt-text-primary)',
                    }}
                  >
                    {item.id} {item.title}
                  </span>

                  {/* Action buttons */}
                  <span style={{ display: 'inline-flex', gap: 'var(--gt-space-1)', flexShrink: 0 }}>
                    <button aria-label="编辑章节" title="编辑" onClick={() => startEdit(item)} style={actionBtnStyle}>✎</button>
                    <button aria-label="上移" title="上移" onClick={() => moveItem(item.id, 'up')} style={actionBtnStyle}>↑</button>
                    <button aria-label="下移" title="下移" onClick={() => moveItem(item.id, 'down')} style={actionBtnStyle}>↓</button>
                    <button aria-label="添加子章节" title="添加子章节" onClick={() => addChild(item.id)} style={actionBtnStyle}>＋</button>
                    <button aria-label="删除章节" title="删除" onClick={() => deleteItem(item.id)} style={{ ...actionBtnStyle, color: 'var(--gt-danger)' }}>✕</button>
                  </span>
                </div>
                {item.description && (
                  <p style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', margin: '2px 0 0' }}>
                    {item.description}
                  </p>
                )}
              </>
            )}
          </div>
        </div>

        {/* Children */}
        {hasChildren && isExpanded && (
          <ul role="group" style={{ margin: 0, padding: 0 }}>
            {item.children!.map((child) => renderItem(child, level + 1))}
          </ul>
        )}
      </li>
    );
  };

  /* ── Loading state ── */
  if (loading) {
    return (
      <div className="gt-card">
        <div className="gt-card-header">大纲识别中</div>
        <div className="gt-card-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--gt-space-2)', padding: 'var(--gt-space-8) var(--gt-space-4)' }}>
          <p style={{ color: 'var(--gt-text-secondary)', margin: 0 }}>正在从模板中提取章节大纲，请稍候…</p>
          <div style={{ width: 16, height: 16, border: '2px solid #e9ecef', borderTopColor: 'var(--gt-primary)', borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite', flexShrink: 0 }} />
        </div>
      </div>
    );
  }

  return (
    <div className="gt-card">
      <div className="gt-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>模板章节大纲</span>
        <span style={{ display: 'inline-flex', gap: 'var(--gt-space-2)' }}>
          <button
            className="gt-button gt-button--secondary"
            onClick={() => handleReExtract(false)}
            disabled={loading}
            aria-label="重新识别大纲"
            title="使用模板标题样式重新提取大纲"
            style={{ fontSize: 'var(--gt-font-xs)', padding: 'var(--gt-space-1) var(--gt-space-3)' }}
          >
            🔄 重新识别
          </button>
          <button
            className="gt-button gt-button--secondary"
            onClick={() => handleReExtract(true)}
            disabled={loading}
            aria-label="AI 重新识别大纲"
            title="调用 AI 模型重新分析模板结构"
            style={{ fontSize: 'var(--gt-font-xs)', padding: 'var(--gt-space-1) var(--gt-space-3)' }}
          >
            🤖 AI 重新识别
          </button>
          <button
            className="gt-button gt-button--secondary"
            onClick={addRoot}
            aria-label="添加根章节"
            style={{ fontSize: 'var(--gt-font-xs)', padding: 'var(--gt-space-1) var(--gt-space-3)' }}
          >
            ＋ 添加章节
          </button>
        </span>
      </div>

      <div className="gt-card-content">
        {error && (
          <div role="alert" style={{ padding: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-3)', background: '#fef2f2', border: '1px solid var(--gt-danger)', borderRadius: 'var(--gt-radius-sm)', color: 'var(--gt-danger)', fontSize: 'var(--gt-font-sm)' }}>
            {error}
          </div>
        )}

        {outline.length === 0 && !error ? (
          <p style={{ color: 'var(--gt-text-secondary)', textAlign: 'center', padding: 'var(--gt-space-6)' }}>
            暂无大纲数据。请先上传模板以自动提取章节结构。
          </p>
        ) : (
          <ul role="tree" aria-label="模板章节大纲" style={{ margin: 0, padding: 0, maxHeight: '480px', overflowY: 'auto' }}>
            {outline.map((item) => renderItem(item))}
          </ul>
        )}

        {/* Confirm button */}
        {outline.length > 0 && (
          <div style={{ marginTop: 'var(--gt-space-4)', textAlign: 'right' }}>
            <button
              className="gt-button gt-button--primary"
              onClick={handleConfirm}
              disabled={confirming}
              aria-label="确认大纲"
            >
              {confirming ? '确认中…' : '确认大纲'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

/** Shared inline style for small action buttons */
const actionBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  padding: '2px 4px',
  fontSize: 'var(--gt-font-sm)',
  color: 'var(--gt-text-secondary)',
  borderRadius: 'var(--gt-radius-sm)',
  lineHeight: 1,
};

export default TemplateOutlineEditor;
