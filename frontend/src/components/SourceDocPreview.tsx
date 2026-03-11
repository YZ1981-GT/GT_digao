/**
 * SourceDocPreview - 源文档预览侧边抽屉
 * Task 15.2: Excel预览（高亮行/列 + Sheet切换）、Word预览（高亮段落/表格）
 */
import React, { useState, useEffect } from 'react';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

interface Props {
  fileId: string;
  sheetName?: string;
  highlightRange?: string;
  onClose: () => void;
}

const SourceDocPreview: React.FC<Props> = ({ fileId, sheetName, highlightRange, onClose }) => {
  const [html, setHtml] = useState<string>('');
  const [sheets, setSheets] = useState<string[]>([]);
  const [activeSheet, setActiveSheet] = useState(sheetName || '');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    const url = activeSheet
      ? `${API}/api/report-review/source-preview/${fileId}/sheet/${encodeURIComponent(activeSheet)}`
      : `${API}/api/report-review/source-preview/${fileId}`;
    fetch(url)
      .then(r => r.json())
      .then(data => {
        setHtml(data.content_html || '');
        if (data.sheets) setSheets(data.sheets);
      })
      .catch(() => setHtml('<p>预览加载失败</p>'))
      .finally(() => setLoading(false));
  }, [fileId, activeSheet]);

  return (
    <div
      style={{
        position: 'fixed', top: 0, right: 0, width: 480, height: '100vh',
        backgroundColor: '#fff', boxShadow: '-4px 0 16px rgba(0,0,0,0.1)',
        zIndex: 1000, display: 'flex', flexDirection: 'column',
      }}
      role="dialog"
      aria-label="源文档预览"
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 'var(--gt-space-3)', borderBottom: '1px solid #eee' }}>
        <span style={{ fontWeight: 600 }}>源文档预览</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer' }} aria-label="关闭预览">✕</button>
      </div>
      {sheets.length > 1 && (
        <div style={{ display: 'flex', gap: 4, padding: '8px var(--gt-space-3)', borderBottom: '1px solid #eee', overflowX: 'auto' }}>
          {sheets.map(s => (
            <button
              key={s}
              onClick={() => setActiveSheet(s)}
              style={{
                padding: '4px 12px', fontSize: 12, border: '1px solid #ddd', borderRadius: 4, cursor: 'pointer',
                backgroundColor: s === activeSheet ? 'var(--gt-primary)' : '#fff',
                color: s === activeSheet ? '#fff' : '#333',
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <div style={{ flex: 1, overflow: 'auto', padding: 'var(--gt-space-3)' }}>
        {loading ? <p style={{ textAlign: 'center', color: '#999' }}>加载中...</p> : (
          <div dangerouslySetInnerHTML={{ __html: html }} />
        )}
      </div>
    </div>
  );
};

export default SourceDocPreview;
