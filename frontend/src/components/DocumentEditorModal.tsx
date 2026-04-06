/**
 * DocumentEditorModal - 文档在线编辑/预览模态框
 *
 * 全屏模态框，支持三种模式：
 * 1. 预览模式：iframe 渲染 Markdown → HTML
 * 2. 手动编辑模式：左侧 Markdown 编辑器 + 右侧实时预览
 * 3. AI 润色模式：调用 /api/chat/polish SSE 流式润色
 *
 * 编辑后可重新生成 Word 下载。
 */
import React, { useEffect, useRef, useCallback, useState } from 'react';
import { markdownToHtml } from '../utils/markdownToHtml';
import { chatApi } from '../services/api';
import { processSSEStream } from '../utils/sseParser';

type EditorMode = 'preview' | 'edit' | 'polishing';

interface DocumentEditorModalProps {
  fileBlob: Blob;
  markdownContent?: string;
  filename: string;
  onClose: () => void;
  /** 保存编辑后的内容回对话（同步到原消息） */
  onSyncToChat?: (newContent: string) => void;
  /** 转存到笔记 */
  onSaveToNote?: (content: string, title: string) => void;
}

/** 构建完整的 HTML 文档字符串 */
function buildPreviewHtml(bodyHtml: string): string {
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body { font-family: -apple-system,'Microsoft YaHei',sans-serif; font-size:14px; line-height:1.8; color:#2c3e50; max-width:800px; margin:0 auto; padding:32px 40px; background:#fff; }
  h1,h2,h3,h4 { font-weight:600; margin:20px 0 10px; color:#1a1a1a; }
  h1 { font-size:22px; border-bottom:2px solid #4b2d77; padding-bottom:8px; }
  h2 { font-size:18px; border-bottom:1px solid #e8e8e8; padding-bottom:6px; }
  h3 { font-size:16px; }
  p { margin:10px 0; }
  ul,ol { margin:10px 0; padding-left:24px; }
  li { margin:6px 0; }
  blockquote { margin:12px 0; padding:10px 16px; border-left:3px solid #a06dff; background:#f9f7fc; color:#555; }
  code { font-family:Consolas,Monaco,monospace; font-size:13px; background:#f5f5f5; padding:1px 5px; border-radius:3px; }
  pre { margin:12px 0; padding:14px; background:#f8f8f8; border:1px solid #e8e8e8; border-radius:6px; overflow-x:auto; }
  pre code { background:none; padding:0; }
  table { border-collapse:collapse; width:100%; margin:12px 0; }
  th,td { border:1px solid #ccc; padding:8px 12px; text-align:left; }
  th { background:#f0f0f0; font-weight:600; }
  tr:nth-child(even) { background:#fafafa; }
  hr { border:none; border-top:1px solid #e0e0e0; margin:16px 0; }
  strong { font-weight:600; }
  a { color:#4b2d77; }
</style></head><body>${bodyHtml}</body></html>`;
}

const DocumentEditorModal: React.FC<DocumentEditorModalProps> = ({
  fileBlob: initialBlob,
  markdownContent: initialMarkdown,
  filename,
  onClose,
  onSyncToChat,
  onSaveToNote,
}) => {
  const [content, setContent] = useState(initialMarkdown || '');
  const [mode, setMode] = useState<EditorMode>('preview');
  const [wordBlob, setWordBlob] = useState<Blob>(initialBlob);
  const [downloading, setDownloading] = useState(false);
  const [syncFeedback, setSyncFeedback] = useState('');
  const [noteFeedback, setNoteFeedback] = useState('');
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const previewIframeRef = useRef<HTMLIFrameElement>(null);
  const polishAbortRef = useRef<AbortController | null>(null);

  /* ─── 预览模式：渲染到 iframe ─── */
  const renderPreview = useCallback((targetRef: React.RefObject<HTMLIFrameElement | null>, md: string) => {
    if (!targetRef.current || !md) return;
    const html = buildPreviewHtml(markdownToHtml(md));
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    targetRef.current.src = url;
    // 延迟释放，等 iframe 加载完
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }, []);

  useEffect(() => {
    if (mode === 'preview') {
      renderPreview(iframeRef, content);
    }
  }, [mode, content, renderPreview]);

  /* ─── 编辑模式：实时预览（防抖） ─── */
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (mode !== 'edit') return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      renderPreview(previewIframeRef, content);
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [content, mode, renderPreview]);

  /* ─── AI 润色 ─── */
  const handlePolish = useCallback(async () => {
    if (!content.trim()) return;
    setMode('polishing');
    const controller = new AbortController();
    polishAbortRef.current = controller;
    let polished = '';
    try {
      const response = await chatApi.polish(content, controller.signal);
      if (!response.ok) throw new Error(`请求失败 (${response.status})`);
      await processSSEStream(
        response,
        (data) => { polished += data; setContent(polished); },
        () => {},
        (err) => { if (err.name !== 'AbortError' && polished) setContent(polished); },
      );
    } catch (err: any) {
      if (err.name !== 'AbortError' && polished) setContent(polished);
    } finally {
      setMode('preview');
      polishAbortRef.current = null;
    }
  }, [content]);

  /* ─── 下载 Word（用编辑后的内容重新生成） ─── */
  const handleDownload = useCallback(async () => {
    setDownloading(true);
    try {
      // 如果内容被编辑过，重新生成 Word
      const res = await chatApi.exportWord(content, filename.replace(/\.docx$/, ''));
      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      setWordBlob(blob);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename.endsWith('.docx') ? filename : `${filename}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // 回退：下载原始 blob
      const url = URL.createObjectURL(wordBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename.endsWith('.docx') ? filename : `${filename}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  }, [content, filename, wordBlob]);

  const isEditing = mode === 'edit';
  const isPolishing = mode === 'polishing';

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 99999, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', flexDirection: 'column' }}>
      {/* ─── 顶部工具栏 ─── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 20px',
        background: 'linear-gradient(135deg, var(--gt-primary) 0%, var(--gt-primary-dark) 100%)',
        flexShrink: 0,
      }}>
        <span style={{ color: '#fff', fontSize: 'var(--gt-font-base)', fontWeight: 600 }}>
          📄 {filename}
        </span>

        {/* 中间：模式切换按钮组 */}
        <div style={{ display: 'flex', gap: 4, background: 'rgba(255,255,255,0.1)', borderRadius: 6, padding: 3 }}>
          {/* 预览 */}
          <button
            onClick={() => setMode('preview')}
            disabled={isPolishing}
            style={{
              background: mode === 'preview' ? 'rgba(255,255,255,0.25)' : 'transparent',
              border: 'none', borderRadius: 4, color: '#fff', fontSize: 13,
              padding: '4px 12px', cursor: isPolishing ? 'not-allowed' : 'pointer', fontWeight: mode === 'preview' ? 600 : 400,
            }}
          >
            👁 预览
          </button>
          {/* 手动编辑 */}
          <button
            onClick={() => setMode('edit')}
            disabled={isPolishing}
            style={{
              background: mode === 'edit' ? 'rgba(255,255,255,0.25)' : 'transparent',
              border: 'none', borderRadius: 4, color: '#fff', fontSize: 13,
              padding: '4px 12px', cursor: isPolishing ? 'not-allowed' : 'pointer', fontWeight: mode === 'edit' ? 600 : 400,
            }}
          >
            ✏️ 编辑
          </button>
          {/* AI 润色 */}
          <button
            onClick={handlePolish}
            disabled={isPolishing || !content.trim()}
            style={{
              background: isPolishing ? 'rgba(255,255,255,0.25)' : 'transparent',
              border: 'none', borderRadius: 4, color: '#fff', fontSize: 13,
              padding: '4px 12px', cursor: (isPolishing || !content.trim()) ? 'not-allowed' : 'pointer',
              fontWeight: isPolishing ? 600 : 400,
            }}
          >
            {isPolishing ? '✨ 润色中...' : '✨ AI 润色'}
          </button>
        </div>

        {/* 右侧：同步 + 笔记 + 下载 + 关闭 */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {/* 同步到对话 */}
          {onSyncToChat && (
            syncFeedback ? (
              <span style={{ color: '#90EE90', fontSize: 13, fontWeight: 500, padding: '0 8px' }}>✓ {syncFeedback}</span>
            ) : (
              <button
                onClick={() => {
                  onSyncToChat(content);
                  setSyncFeedback('已同步');
                  setTimeout(() => setSyncFeedback(''), 2000);
                }}
                disabled={isPolishing}
                style={{
                  background: 'rgba(255,255,255,0.2)', border: 'none', borderRadius: 'var(--gt-radius-sm)',
                  color: '#fff', fontSize: 13, padding: '6px 12px',
                  cursor: isPolishing ? 'not-allowed' : 'pointer', fontWeight: 500,
                }}
              >
                🔄 同步到对话
              </button>
            )
          )}
          {/* 转存笔记 */}
          {onSaveToNote && (
            noteFeedback ? (
              <span style={{ color: '#90EE90', fontSize: 13, fontWeight: 500, padding: '0 8px' }}>✓ {noteFeedback}</span>
            ) : (
              <button
                onClick={() => {
                  const title = filename.replace(/\.docx$/, '') || '编辑文档';
                  onSaveToNote(content, title);
                  setNoteFeedback('已保存');
                  setTimeout(() => setNoteFeedback(''), 2000);
                }}
                disabled={isPolishing}
                style={{
                  background: 'rgba(255,255,255,0.2)', border: 'none', borderRadius: 'var(--gt-radius-sm)',
                  color: '#fff', fontSize: 13, padding: '6px 12px',
                  cursor: isPolishing ? 'not-allowed' : 'pointer', fontWeight: 500,
                }}
              >
                📌 存到笔记
              </button>
            )
          )}
          <button
            onClick={handleDownload}
            disabled={downloading}
            style={{
              background: 'rgba(255,255,255,0.2)', border: 'none', borderRadius: 'var(--gt-radius-sm)',
              color: '#fff', fontSize: 'var(--gt-font-sm)', padding: '6px 16px',
              cursor: downloading ? 'wait' : 'pointer', fontWeight: 500,
            }}
          >
            {downloading ? '⏳ 生成中...' : '⬇ 下载 Word'}
          </button>
          <button
            onClick={onClose}
            aria-label="关闭"
            style={{
              background: 'rgba(255,255,255,0.15)', border: 'none', borderRadius: 'var(--gt-radius-sm)',
              color: '#fff', fontSize: 16, width: 34, height: 34, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* ─── 内容区域 ─── */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', backgroundColor: '#e8e8e8' }}>
        {/* 预览模式 / 润色模式：全屏 iframe */}
        {(mode === 'preview' || mode === 'polishing') && (
          <div style={{ flex: 1, display: 'flex', justifyContent: 'center', padding: 16, overflow: 'hidden' }}>
            {content ? (
              <iframe
                ref={iframeRef}
                title="文档预览"
                style={{
                  width: '100%', maxWidth: 900, height: '100%',
                  border: 'none', borderRadius: 8,
                  boxShadow: '0 2px 12px rgba(0,0,0,0.15)', backgroundColor: '#fff',
                }}
              />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, color: '#666' }}>
                <span style={{ fontSize: 48 }}>📄</span>
                <span>文档已生成，请点击"下载 Word"保存到本地</span>
              </div>
            )}
          </div>
        )}

        {/* 编辑模式：左侧编辑器 + 右侧预览 */}
        {mode === 'edit' && (
          <>
            {/* 左侧 Markdown 编辑器 */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid #d0d0d0' }}>
              <div style={{ padding: '8px 16px', backgroundColor: '#f5f5f5', borderBottom: '1px solid #e0e0e0', fontSize: 12, color: '#888', flexShrink: 0 }}>
                Markdown 编辑器
              </div>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                style={{
                  flex: 1, padding: '16px 20px', border: 'none', outline: 'none', resize: 'none',
                  fontSize: 14, lineHeight: 1.7, fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                  backgroundColor: '#fff', color: '#333',
                }}
                spellCheck={false}
              />
            </div>
            {/* 右侧实时预览 */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
              <div style={{ padding: '8px 16px', backgroundColor: '#f5f5f5', borderBottom: '1px solid #e0e0e0', fontSize: 12, color: '#888', flexShrink: 0 }}>
                实时预览
              </div>
              <div style={{ flex: 1, padding: 16, overflow: 'hidden', display: 'flex', justifyContent: 'center' }}>
                <iframe
                  ref={previewIframeRef}
                  title="实时预览"
                  style={{
                    width: '100%', height: '100%', border: 'none',
                    borderRadius: 6, backgroundColor: '#fff',
                    boxShadow: '0 1px 6px rgba(0,0,0,0.1)',
                  }}
                />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default DocumentEditorModal;
