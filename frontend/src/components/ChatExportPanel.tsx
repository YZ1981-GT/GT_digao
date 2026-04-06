/**
 * ChatExportPanel - 聊天导出预览编辑面板
 *
 * 合并选中消息为 Markdown，支持手动编辑、AI 润色、导出 Word。
 */
import React, { useState, useCallback, useRef } from 'react';
import { chatApi } from '../services/api';
import { processSSEStream } from '../utils/sseParser';
import DocumentEditorModal from './DocumentEditorModal';

interface ChatExportPanelProps {
  content: string;
  onClose: () => void;
  onContentChange: (content: string) => void;
}

const ChatExportPanel: React.FC<ChatExportPanelProps> = ({ content, onClose, onContentChange }) => {
  const [isPolishing, setIsPolishing] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [editorBlob, setEditorBlob] = useState<Blob | null>(null);
  const [editorFilename, setEditorFilename] = useState('');

  /* ─── AI 润色 (11.7) ─── */
  const handlePolish = useCallback(async () => {
    setIsPolishing(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let polished = '';
    try {
      const response = await chatApi.polish(content, controller.signal);
      if (!response.ok) throw new Error(`请求失败 (${response.status})`);
      await processSSEStream(
        response,
        (data) => { polished += data; onContentChange(polished); },
        () => { /* done */ },
        (err) => { if (err.name !== 'AbortError') onContentChange(polished || content); },
      );
    } catch (err: any) {
      if (err.name !== 'AbortError') onContentChange(polished || content);
    } finally {
      setIsPolishing(false);
      abortRef.current = null;
    }
  }, [content, onContentChange]);

  /* ─── 导出 Word (11.8) ─── */
  const handleExportWord = useCallback(async () => {
    try {
      const now = new Date();
      const fname = `聊天记录_${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
      const res = await chatApi.exportWord(content, fname);
      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${fname}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* 静默失败 */
    }
  }, [content]);

  /* ─── 在线编辑 (11b.4) ─── */
  const handleOnlineEdit = useCallback(async () => {
    try {
      const now = new Date();
      const fname = `聊天记录_${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
      const res = await chatApi.exportWord(content, fname);
      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      setEditorBlob(blob);
      setEditorFilename(`${fname}.docx`);
    } catch {
      /* 静默失败 */
    }
  }, [content]);

  return (
    <div
      style={{
        position: 'fixed',
        right: 24,
        bottom: 24,
        width: 520,
        height: 720,
        borderRadius: 'var(--gt-radius-lg)',
        backgroundColor: '#fff',
        boxShadow: 'var(--gt-shadow-lg)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        zIndex: 10001,
        border: '1px solid #e8e8e8',
      }}
    >
      {/* 标题栏 */}
      <div
        style={{
          background: 'linear-gradient(135deg, var(--gt-primary) 0%, var(--gt-primary-dark) 100%)',
          padding: 'var(--gt-space-3) var(--gt-space-4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <span style={{ color: '#fff', fontSize: 'var(--gt-font-base)', fontWeight: 600 }}>
          导出预览
        </span>
        <button
          onClick={onClose}
          aria-label="关闭"
          style={{
            background: 'rgba(255,255,255,0.15)',
            border: 'none',
            borderRadius: 'var(--gt-radius-sm)',
            color: '#fff',
            fontSize: 16,
            width: 30,
            height: 30,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          ✕
        </button>
      </div>

      {/* 编辑区 */}
      <textarea
        value={content}
        onChange={(e) => onContentChange(e.target.value)}
        disabled={isPolishing}
        style={{
          flex: 1,
          padding: 'var(--gt-space-3)',
          border: 'none',
          outline: 'none',
          resize: 'none',
          fontSize: 'var(--gt-font-sm)',
          lineHeight: 1.6,
          fontFamily: 'inherit',
          backgroundColor: isPolishing ? '#fafafa' : '#fff',
        }}
      />

      {/* 底部操作栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 8,
          padding: '10px 16px',
          borderTop: '1px solid #e8e8e8',
          flexShrink: 0,
        }}
      >
        <button
          onClick={handlePolish}
          disabled={isPolishing || !content.trim()}
          style={{
            background: isPolishing ? '#d9d9d9' : 'rgba(75, 45, 119, 0.1)',
            border: 'none',
            borderRadius: 'var(--gt-radius-sm)',
            color: isPolishing ? '#999' : 'var(--gt-primary)',
            fontSize: 'var(--gt-font-xs)',
            padding: '6px 14px',
            cursor: isPolishing ? 'not-allowed' : 'pointer',
            fontWeight: 500,
          }}
        >
          {isPolishing ? '润色中...' : '✨ AI 润色'}
        </button>
        <button
          onClick={handleOnlineEdit}
          disabled={!content.trim()}
          style={{
            background: !content.trim() ? '#d9d9d9' : 'rgba(75, 45, 119, 0.1)',
            border: 'none',
            borderRadius: 'var(--gt-radius-sm)',
            color: !content.trim() ? '#999' : 'var(--gt-primary)',
            fontSize: 'var(--gt-font-xs)',
            padding: '6px 14px',
            cursor: !content.trim() ? 'not-allowed' : 'pointer',
            fontWeight: 500,
          }}
        >
          ✏️ 在线编辑
        </button>
        <button
          onClick={handleExportWord}
          disabled={!content.trim()}
          style={{
            background: !content.trim() ? '#d9d9d9' : 'var(--gt-primary)',
            border: 'none',
            borderRadius: 'var(--gt-radius-sm)',
            color: '#fff',
            fontSize: 'var(--gt-font-xs)',
            padding: '6px 14px',
            cursor: !content.trim() ? 'not-allowed' : 'pointer',
            fontWeight: 500,
          }}
        >
          📄 导出 Word
        </button>
      </div>

      {/* 文档在线编辑模态框 (11b.4) */}
      {editorBlob && (
        <DocumentEditorModal
          fileBlob={editorBlob}
          markdownContent={content}
          filename={editorFilename}
          onClose={() => { setEditorBlob(null); setEditorFilename(''); }}
          onSyncToChat={(newContent) => onContentChange(newContent)}
          onSaveToNote={(noteContent, title) => {
            chatApi.saveNote({ title, content: noteContent }).catch(() => {});
          }}
        />
      )}
    </div>
  );
};

export default ChatExportPanel;
