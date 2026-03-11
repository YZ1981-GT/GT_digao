/**
 * AuditReportUpload - 审计报告文件上传组件
 * Task 14.3: 多文件上传、模板类型选择、文件列表展示
 */
import React, { useState, useCallback, useRef } from 'react';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

interface Props {
  onComplete: (sessionId: string, templateType: 'soe' | 'listed') => void;
}

const AuditReportUpload: React.FC<Props> = ({ onComplete }) => {
  const [templateType, setTemplateType] = useState<'soe' | 'listed'>('soe');
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(prev => [...prev, ...Array.from(e.target.files!)]);
      setError(null);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files) {
      setFiles(prev => [...prev, ...Array.from(e.dataTransfer.files)]);
      setError(null);
    }
  }, []);

  const removeFile = useCallback((idx: number) => {
    setFiles(prev => prev.filter((_, i) => i !== idx));
  }, []);

  const handleUpload = useCallback(async () => {
    if (files.length === 0) { setError('请选择文件'); return; }
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      files.forEach(f => formData.append('files', f));
      formData.append('template_type', templateType);
      const resp = await fetch(`${API}/api/report-review/upload`, { method: 'POST', body: formData });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      onComplete(data.session_id, templateType);
    } catch (e: any) {
      setError(e.message || '上传失败');
    } finally {
      setUploading(false);
    }
  }, [files, templateType, onComplete]);

  return (
    <div>
      {/* 模板类型选择 */}
      <div style={{ marginBottom: 'var(--gt-space-4)' }}>
        <h3 style={{ marginBottom: 'var(--gt-space-2)', fontSize: 16 }}>选择模板类型</h3>
        <div className="gt-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--gt-space-3)' }}>
          {(['soe', 'listed'] as const).map(type => (
            <div
              key={type}
              className={`gt-card ${templateType === type ? 'gt-active' : ''}`}
              style={{
                padding: 'var(--gt-space-3)', cursor: 'pointer', textAlign: 'center',
                border: templateType === type ? '2px solid var(--gt-primary, #4b2d77)' : '1px solid #ddd',
              }}
              onClick={() => setTemplateType(type)}
              role="radio"
              aria-checked={templateType === type}
              tabIndex={0}
            >
              <div style={{ fontWeight: 600, fontSize: 16 }}>{type === 'soe' ? '国企版' : '上市版'}</div>
              <div style={{ fontSize: 13, color: '#666', marginTop: 4 }}>
                {type === 'soe' ? '适用于国有企业审计报告' : '适用于上市公司审计报告'}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 文件上传区域 */}
      <div
        className="gt-card"
        style={{ padding: 'var(--gt-space-6)', textAlign: 'center', border: '2px dashed #ccc', cursor: 'pointer' }}
        onDrop={handleDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => fileInputRef.current?.click()}
        role="button"
        aria-label="点击或拖拽上传文件"
        tabIndex={0}
      >
        <p style={{ fontSize: 16, color: '#666' }}>点击或拖拽上传审计报告文件</p>
        <p style={{ fontSize: 13, color: '#999' }}>支持 .xlsx .xls .docx .doc 格式</p>
        <input ref={fileInputRef} type="file" multiple accept=".xlsx,.xls,.docx,.doc" onChange={handleFileSelect} style={{ display: 'none' }} />
      </div>

      {/* 文件列表 */}
      {files.length > 0 && (
        <table className="gt-table" style={{ width: '100%', marginTop: 'var(--gt-space-3)' }}>
          <caption className="sr-only">已选择的文件列表</caption>
          <thead>
            <tr><th scope="col">文件名</th><th scope="col">大小</th><th scope="col">操作</th></tr>
          </thead>
          <tbody>
            {files.map((f, i) => (
              <tr key={i}>
                <td>{f.name}</td>
                <td>{(f.size / 1024).toFixed(1)} KB</td>
                <td><button onClick={() => removeFile(i)} style={{ color: 'var(--gt-danger, red)', cursor: 'pointer', background: 'none', border: 'none' }}>移除</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {error && <div className="gt-error" style={{ marginTop: 'var(--gt-space-2)', color: 'var(--gt-danger, red)', borderLeft: '3px solid var(--gt-danger, red)', paddingLeft: 8 }}>{error}</div>}

      <button
        className="gt-button"
        style={{ marginTop: 'var(--gt-space-4)', backgroundColor: 'var(--gt-primary, #4b2d77)', color: '#fff', padding: '8px 24px', border: 'none', borderRadius: 'var(--gt-radius-md, 8px)', cursor: 'pointer' }}
        onClick={handleUpload}
        disabled={uploading || files.length === 0}
      >
        {uploading ? '上传中...' : '上传并解析'}
      </button>
    </div>
  );
};

export default AuditReportUpload;
