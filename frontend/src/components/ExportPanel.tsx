/**
 * ExportPanel - 文档生成导出步骤面板
 *
 * 展示文档预览（所有章节标题+内容），提供 Word 导出按钮。
 * 调用 generateApi.exportDocument() 获取 blob 并触发浏览器下载。
 *
 * Requirements: 12.9
 */
import React, { useState, useCallback } from 'react';
import type { GeneratedSection, FontSettings } from '../types/audit';
import { generateApi } from '../services/api';
import FontSettingsComponent from './FontSettings';
import '../styles/gt-design-tokens.css';

interface ExportPanelProps {
  sections: GeneratedSection[];
  documentId: string;
  templateId: string;
  fontSettings: FontSettings;
  onFontSettingsChange: (settings: FontSettings) => void;
}

const ExportPanel: React.FC<ExportPanelProps> = ({
  sections,
  documentId,
  templateId,
  fontSettings,
  onFontSettingsChange,
}) => {
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = useCallback(async () => {
    setExporting(true);
    setError(null);
    try {
      const response = await generateApi.exportDocument({
        document_id: documentId,
        sections,
        template_id: templateId,
        font_settings: fontSettings,
      });

      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `审计文档_${documentId}.docx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message || '导出失败，请重试');
    } finally {
      setExporting(false);
    }
  }, [documentId, sections, templateId, fontSettings]);

  return (
    <section className="gt-section" aria-label="文档导出">
      {/* Font settings */}
      <FontSettingsComponent fontSettings={fontSettings} onChange={onFontSettingsChange} />

      {/* Document preview */}
      <div className="gt-card" style={{ marginBottom: 'var(--gt-space-4)' }}>
        <div className="gt-card-header" id="preview-heading">文档预览</div>
        <div
          className="gt-card-content"
          aria-labelledby="preview-heading"
          style={{ maxHeight: '480px', overflowY: 'auto' }}
        >
          {sections.length === 0 ? (
            <p style={{ color: 'var(--gt-text-secondary)' }}>暂无生成内容</p>
          ) : (
            sections.map((section) => (
              <article
                key={section.index}
                style={{ marginBottom: 'var(--gt-space-6)' }}
                aria-label={`章节：${section.title}`}
              >
                <h4 className="gt-h4" style={{ marginBottom: 'var(--gt-space-2)' }}>
                  {section.title}
                </h4>
                <div
                  style={{
                    whiteSpace: 'pre-wrap',
                    fontSize: 'var(--gt-font-sm)',
                    color: section.is_placeholder
                      ? 'var(--gt-text-secondary)'
                      : 'var(--gt-text-primary)',
                    lineHeight: 1.7,
                  }}
                >
                  {section.content}
                </div>
              </article>
            ))
          )}
        </div>
      </div>

      {/* Export action */}
      {error && (
        <p role="alert" className="gt-error" style={{ marginBottom: 'var(--gt-space-3)', fontSize: 'var(--gt-font-sm)' }}>
          {error}
        </p>
      )}
      <button
        className={`gt-button gt-button--primary${exporting ? ' gt-loading' : ''}`}
        onClick={handleExport}
        disabled={exporting || sections.length === 0}
        aria-label="导出 Word 文档"
      >
        {exporting ? '导出中…' : '导出 Word'}
      </button>
    </section>
  );
};

export default ExportPanel;
