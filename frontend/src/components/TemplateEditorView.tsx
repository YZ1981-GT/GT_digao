/**
 * TemplateEditorView - 模板编辑视图
 * Task 19.1: 左侧导航树、右侧Markdown编辑器、工具栏（保存/导入/重置）
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ReportTemplateType, ReportTemplateCategory, TemplateTocEntry,
  REPORT_TEMPLATE_TYPE_LABELS,
} from '../types/audit';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

type TemplateKey = `${ReportTemplateType}_${ReportTemplateCategory}`;

const TEMPLATE_TREE: Array<{ type: ReportTemplateType; category: ReportTemplateCategory; label: string }> = [
  { type: 'soe', category: 'report_body', label: '国企版 - 报告正文' },
  { type: 'soe', category: 'notes', label: '国企版 - 附注' },
  { type: 'listed', category: 'report_body', label: '上市版 - 报告正文' },
  { type: 'listed', category: 'notes', label: '上市版 - 附注' },
];

const TemplateEditorView: React.FC = () => {
  const [activeKey, setActiveKey] = useState<TemplateKey>('soe_report_body');
  const [content, setContent] = useState('');
  const [toc, setToc] = useState<TemplateTocEntry[]>([]);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const activeType = activeKey.slice(0, activeKey.indexOf('_')) as ReportTemplateType;
  const activeCategory = activeKey.slice(activeKey.indexOf('_') + 1) as ReportTemplateCategory;

  const loadTemplate = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/report-review/templates/${activeType}/${activeCategory}`);
      if (r.ok) {
        const data = await r.json();
        setContent(data.full_content || '');
      } else {
        setContent('');
      }
    } catch { setContent(''); }
  }, [activeType, activeCategory]);

  const loadToc = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/report-review/templates/${activeType}/${activeCategory}/toc`);
      if (r.ok) {
        const data = await r.json();
        setToc(data.toc || []);
      } else setToc([]);
    } catch { setToc([]); }
  }, [activeType, activeCategory]);

  useEffect(() => { loadTemplate(); loadToc(); }, [loadTemplate, loadToc]);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const r = await fetch(`${API}/api/report-review/templates/${activeType}/${activeCategory}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      if (!r.ok) throw new Error(await r.text());
      setMessage('保存成功');
      loadToc();
    } catch (e: any) {
      setMessage(`保存失败: ${e.message}`);
    }
    setSaving(false);
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('template_type', activeType);
    formData.append('template_category', activeCategory);
    try {
      const r = await fetch(`${API}/api/report-review/templates/import`, { method: 'POST', body: formData });
      if (!r.ok) throw new Error(await r.text());
      setMessage('导入成功');
      loadTemplate();
      loadToc();
    } catch (e: any) {
      setMessage(`导入失败: ${e.message}`);
    }
  };

  const toggleExpand = (path: string) => {
    setExpandedPaths(prev => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  };

  return (
    <div style={{ display: 'flex', height: '70vh' }}>
      {/* Left: navigation tree */}
      <div style={{ width: 240, borderRight: '1px solid #eee', overflowY: 'auto', padding: 'var(--gt-space-2)' }}>
        <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--gt-primary)' }}>模板导航</h4>
        {TEMPLATE_TREE.map(t => {
          const key: TemplateKey = `${t.type}_${t.category}`;
          return (
            <div
              key={key}
              onClick={() => setActiveKey(key)}
              style={{
                padding: '6px 10px', cursor: 'pointer', borderRadius: 4, fontSize: 13, marginBottom: 2,
                backgroundColor: activeKey === key ? 'var(--gt-primary)' : 'transparent',
                color: activeKey === key ? '#fff' : '#333',
              }}
              role="button"
              tabIndex={0}
            >
              {t.label}
            </div>
          );
        })}

        {/* TOC for active template */}
        {toc.length > 0 && (
          <div style={{ marginTop: 12, borderTop: '1px solid #eee', paddingTop: 8 }}>
            <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>目录结构</div>
            {toc.map(entry => (
              <div
                key={entry.path}
                style={{ paddingLeft: (entry.level - 1) * 12 + 4, fontSize: 12, padding: '2px 4px', cursor: 'pointer', color: '#555' }}
                onClick={() => entry.has_children && toggleExpand(entry.path)}
              >
                {entry.has_children && <span style={{ marginRight: 4 }}>{expandedPaths.has(entry.path) ? '▼' : '▶'}</span>}
                {entry.title}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Right: editor */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* Toolbar */}
        <div style={{ display: 'flex', gap: 8, padding: 'var(--gt-space-2)', borderBottom: '1px solid #eee', alignItems: 'center' }}>
          <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>
            {REPORT_TEMPLATE_TYPE_LABELS[activeType]} - {activeCategory === 'report_body' ? '报告正文' : '附注'}
          </span>
          <button onClick={handleSave} disabled={saving} style={{ fontSize: 12, padding: '4px 14px', backgroundColor: 'var(--gt-primary)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
            {saving ? '保存中...' : '保存'}
          </button>
          <button onClick={() => fileInputRef.current?.click()} style={{ fontSize: 12, padding: '4px 14px', border: '1px solid #ddd', borderRadius: 4, cursor: 'pointer', background: '#fff' }}>
            Word 导入
          </button>
          <button onClick={() => { setContent(''); setMessage(null); }} style={{ fontSize: 12, padding: '4px 14px', border: '1px solid #ddd', borderRadius: 4, cursor: 'pointer', background: '#fff' }}>
            重置
          </button>
          <input ref={fileInputRef} type="file" accept=".docx,.doc" onChange={handleImport} style={{ display: 'none' }} />
        </div>

        {message && (
          <div style={{ padding: '4px 12px', fontSize: 12, color: message.includes('失败') ? 'var(--gt-danger)' : 'var(--gt-success, green)', borderBottom: '1px solid #eee' }}>
            {message}
          </div>
        )}

        {/* Editor + Preview */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            style={{ flex: 1, padding: 12, border: 'none', borderRight: '1px solid #eee', fontFamily: 'monospace', fontSize: 13, resize: 'none', outline: 'none' }}
            placeholder="在此编辑 Markdown 模板内容..."
            aria-label="模板编辑器"
          />
          <div style={{ flex: 1, padding: 12, overflowY: 'auto', fontSize: 13 }}>
            <div style={{ color: '#888', fontSize: 11, marginBottom: 8 }}>预览</div>
            {content.split('\n').map((line, i) => {
              if (line.startsWith('### ')) return <h5 key={i} style={{ fontSize: 13, fontWeight: 600, margin: '8px 0 4px' }}>{line.slice(4)}</h5>;
              if (line.startsWith('## ')) return <h4 key={i} style={{ fontSize: 14, fontWeight: 600, margin: '12px 0 4px', color: 'var(--gt-primary)' }}>{line.slice(3)}</h4>;
              if (line.startsWith('# ')) return <h3 key={i} style={{ fontSize: 16, fontWeight: 700, margin: '16px 0 8px' }}>{line.slice(2)}</h3>;
              if (line.trim() === '') return <br key={i} />;
              return <p key={i} style={{ margin: '2px 0', lineHeight: 1.6 }}>{line}</p>;
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

export default TemplateEditorView;
