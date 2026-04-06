/**
 * ChatMessageList - 消息列表组件
 *
 * 渲染用户消息（右对齐）和 AI 消息（左对齐 + Markdown 渲染），
 * 消息变化时自动滚动到底部。
 * 用户消息中的图片以缩略图展示（最大宽度 300px），点击弹出全屏预览。
 * AI 回复中如果用户发送了图片，标注"已识别图片内容"。
 * AI 回复支持 📌 保存到笔记按钮（hover 显示）和"建议保存到笔记"提示标签。
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import type { ChatMessage } from '../types/chat';
import { copyRichText } from '../utils/copyRichText';
import { chatApi } from '../services/api';
import DocumentEditorModal from './DocumentEditorModal';
import '../styles/gt-design-tokens.css';

interface ChatMessageListProps {
  messages: ChatMessage[];
  onSaveNote?: (content: string, title: string) => void;
  onUpdateMessage?: (msgId: string, newContent: string) => void;
  onDeleteMessage?: (msgId: string) => void;
  exportMode?: boolean;
  selectedMsgIds?: Set<string>;
  onToggleSelect?: (msgId: string) => void;
  onSelectMode?: (mode: 'review' | 'generate' | 'analysis' | 'report_review') => void;
}

/** 模块推荐标记正则 */
const MODULE_RECOMMEND_RE = /\[推荐模块:(review|generate|analysis|report_review)\]/g;

/** 模块 key → 显示信息 */
const MODULE_LABEL_MAP: Record<string, { icon: string; label: string }> = {
  review: { icon: '📋', label: '底稿复核' },
  generate: { icon: '📝', label: '文档生成' },
  analysis: { icon: '🔍', label: '文档分析' },
  report_review: { icon: '📊', label: '审计报告复核' },
};

/** 从内容中提取推荐模块并返回清理后的内容 */
function extractModuleRecommendation(content: string): {
  cleanContent: string;
  recommendedMode: 'review' | 'generate' | 'analysis' | 'report_review' | null;
} {
  const match = MODULE_RECOMMEND_RE.exec(content);
  MODULE_RECOMMEND_RE.lastIndex = 0; // reset regex state
  if (!match) return { cleanContent: content, recommendedMode: null };
  const recommendedMode = match[1] as 'review' | 'generate' | 'analysis' | 'report_review';
  const cleanContent = content.replace(MODULE_RECOMMEND_RE, '').trimEnd();
  return { cleanContent, recommendedMode };
}

/** 知识库 ID → 显示名称映射 */
const LIBRARY_DISPLAY_NAMES: Record<string, string> = {
  workpaper_templates: '底稿模板库',
  audit_regulations: '监管规定库',
  accounting_standards: '会计准则库',
  quality_standards: '质控标准库',
  audit_procedures: '审计程序库',
  industry_guidelines: '行业指引库',
  prompt_library: '提示词库',
  report_templates: '报告模板库',
  notes: '笔记库',
};

/** 全屏图片预览模态框 */
const ImagePreviewModal: React.FC<{ src: string; onClose: () => void }> = ({ src, onClose }) => (
  <div
    onClick={onClose}
    style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0,0,0,0.8)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 99999,
      cursor: 'pointer',
    }}
  >
    <img
      src={src}
      alt="图片预览"
      onClick={(e) => e.stopPropagation()}
      style={{
        maxWidth: '90vw',
        maxHeight: '90vh',
        objectFit: 'contain',
        borderRadius: 8,
        cursor: 'default',
      }}
    />
    <button
      onClick={onClose}
      aria-label="关闭预览"
      style={{
        position: 'absolute',
        top: 20,
        right: 20,
        width: 36,
        height: 36,
        borderRadius: '50%',
        border: 'none',
        backgroundColor: 'rgba(255,255,255,0.2)',
        color: '#fff',
        fontSize: 20,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      ✕
    </button>
  </div>
);

/** 检查 assistant 消息是否有"已识别图片内容"标记 */
function hasImageOcrTag(msg: ChatMessage): boolean {
  return (
    msg.role === 'assistant' &&
    !!msg.attachments?.some((a) => a.filename === '__image_ocr_tag__')
  );
}

/** 找到当前 assistant 消息之前最近的 user 消息 */
function findPrevUserMessage(messages: ChatMessage[], currentIndex: number): ChatMessage | null {
  for (let i = currentIndex - 1; i >= 0; i--) {
    if (messages[i].role === 'user') return messages[i];
  }
  return null;
}

const ChatMessageList: React.FC<ChatMessageListProps> = ({ messages, onSaveNote, onUpdateMessage, onDeleteMessage, exportMode, selectedMsgIds, onToggleSelect, onSelectMode }) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [hoveredMsgId, setHoveredMsgId] = useState<string | null>(null);
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);
  const [editorBlob, setEditorBlob] = useState<Blob | null>(null);
  const [editorFilename, setEditorFilename] = useState('');
  const [editorMarkdown, setEditorMarkdown] = useState('');
  const [editorMsgId, setEditorMsgId] = useState('');

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const openPreview = useCallback((src: string) => setPreviewSrc(src), []);
  const closePreview = useCallback(() => setPreviewSrc(null), []);

  const handleSaveNote = useCallback((msg: ChatMessage, msgIndex: number) => {
    if (!onSaveNote) return;
    const prevUser = findPrevUserMessage(messages, msgIndex);
    const title = prevUser?.content?.slice(0, 50) || 'AI 回复';
    onSaveNote(msg.content, title);
  }, [messages, onSaveNote]);

  const handleCopy = useCallback(async (msg: ChatMessage) => {
    const ok = await copyRichText(msg.content);
    if (ok) {
      setCopiedMsgId(msg.id);
      setTimeout(() => setCopiedMsgId(null), 1500);
    }
  }, []);

  const handleExportWord = useCallback(async (msg: ChatMessage) => {
    try {
      const now = new Date();
      const fname = `聊天记录_${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
      const res = await chatApi.exportWord(msg.content, fname);
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${fname}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* 静默失败 */
    }
  }, []);

  /** 在线编辑：生成 Word Blob → 打开 DocumentEditorModal */
  const handleOnlineEdit = useCallback(async (msg: ChatMessage) => {
    try {
      const now = new Date();
      const fname = `聊天记录_${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
      const res = await chatApi.exportWord(msg.content, fname);
      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      setEditorBlob(blob);
      setEditorFilename(`${fname}.docx`);
      setEditorMarkdown(msg.content);
      setEditorMsgId(msg.id);
    } catch {
      /* 静默失败 */
    }
  }, []);

  return (
    <div>
      {messages.map((msg, msgIndex) => {
        const imageAttachments =
          msg.role === 'user'
            ? msg.attachments?.filter((a) => a.type === 'image' && a.thumbnailUrl)
            : undefined;

        const isAssistant = msg.role === 'assistant';
        const isHovered = hoveredMsgId === msg.id;

        return (
          <div
            key={msg.id}
            style={{
              marginBottom: 'var(--gt-space-3)',
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
            }}
          >
            {/* 多选模式 checkbox */}
            {exportMode && (
              <input
                type="checkbox"
                checked={selectedMsgIds?.has(msg.id) || false}
                onChange={() => onToggleSelect?.(msg.id)}
                style={{ marginTop: 10, marginRight: 6, flexShrink: 0 }}
              />
            )}
            <div
              onMouseEnter={() => setHoveredMsgId(msg.id)}
              onMouseLeave={() => setHoveredMsgId(null)}
              style={{
                maxWidth: '80%',
              }}
            >
              {/* 消息气泡 */}
              <div
                style={{
                  padding: 'var(--gt-space-3) var(--gt-space-4)',
                  borderRadius: 'var(--gt-radius-md)',
                  backgroundColor: msg.role === 'user' ? '#f3f0f8' : '#ffffff',
                  border: isAssistant ? '1px solid #e8e8e8' : 'none',
                  fontSize: 'var(--gt-font-sm)',
                  lineHeight: msg.role === 'user' ? 1.6 : undefined,
                }}
              >
              {msg.role === 'user' ? (
                <>
                  {imageAttachments && imageAttachments.length > 0 && (
                    <div
                      style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: '8px',
                        marginBottom: msg.content && msg.content !== '（发送了图片）' ? 8 : 0,
                      }}
                    >
                      {imageAttachments.map((att, idx) => (
                        <img
                          key={idx}
                          src={att.thumbnailUrl}
                          alt={att.filename || `图片 ${idx + 1}`}
                          onClick={() => att.thumbnailUrl && openPreview(att.thumbnailUrl)}
                          style={{
                            maxWidth: 300,
                            maxHeight: 200,
                            borderRadius: 'var(--gt-radius-sm)',
                            cursor: 'pointer',
                            objectFit: 'contain',
                            border: '1px solid #e0e0e0',
                          }}
                        />
                      ))}
                    </div>
                  )}
                  {msg.content && msg.content !== '（发送了图片）' && (
                    <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
                  )}
                </>
              ) : (
                <>
                  {(() => {
                    const { cleanContent, recommendedMode } = extractModuleRecommendation(msg.content);
                    return (
                      <>
                        <div className="chat-markdown">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            rehypePlugins={[rehypeHighlight]}
                          >
                            {cleanContent}
                          </ReactMarkdown>
                        </div>

                        {/* 模块推荐按钮 */}
                        {recommendedMode && onSelectMode && MODULE_LABEL_MAP[recommendedMode] && (
                          <button
                            onClick={() => onSelectMode(recommendedMode)}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 6,
                              marginTop: 8,
                              padding: '6px 14px',
                              backgroundColor: 'var(--gt-primary)',
                              color: '#fff',
                              border: 'none',
                              borderRadius: 16,
                              fontSize: 'var(--gt-font-xs)',
                              fontWeight: 500,
                              cursor: 'pointer',
                              transition: 'background 0.2s, box-shadow 0.2s',
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.backgroundColor = 'var(--gt-primary-dark)';
                              e.currentTarget.style.boxShadow = '0 2px 6px rgba(75, 45, 119, 0.3)';
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.backgroundColor = 'var(--gt-primary)';
                              e.currentTarget.style.boxShadow = 'none';
                            }}
                          >
                            <span>{MODULE_LABEL_MAP[recommendedMode].icon}</span>
                            <span>前往{MODULE_LABEL_MAP[recommendedMode].label}</span>
                          </button>
                        )}
                      </>
                    );
                  })()}

                  {/* 操作按钮、标签等移到气泡外 — 先关闭气泡内的 fragment 和 bubble div */}
                </>
              )}
              </div>
              {/* ─── 气泡外：操作按钮区域 — hover 时显示 ─── */}
              {isAssistant && isHovered && !msg.savedToNotes && (
                <div
                  style={{
                    display: 'flex',
                    gap: 4,
                    marginTop: 4,
                    paddingLeft: 2,
                  }}
                >
                      {/* 📋 复制按钮 */}
                      {copiedMsgId === msg.id ? (
                        <span
                          style={{
                            fontSize: 'var(--gt-font-xs)',
                            color: 'var(--gt-success)',
                            fontWeight: 500,
                            padding: '2px 6px',
                          }}
                        >
                          ✓ 已复制
                        </span>
                      ) : (
                        <button
                          onClick={() => handleCopy(msg)}
                          title="复制"
                          aria-label="复制"
                          style={{
                            background: 'rgba(75, 45, 119, 0.08)',
                            border: 'none',
                            borderRadius: 'var(--gt-radius-sm)',
                            cursor: 'pointer',
                            fontSize: 14,
                            padding: '2px 6px',
                            color: 'var(--gt-text-secondary)',
                            transition: 'color 0.2s, background 0.2s',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = 'var(--gt-primary)';
                            e.currentTarget.style.background = 'rgba(75, 45, 119, 0.15)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = 'var(--gt-text-secondary)';
                            e.currentTarget.style.background = 'rgba(75, 45, 119, 0.08)';
                          }}
                        >
                          📋
                        </button>
                      )}
                      {/* 📄 导出 Word 按钮 */}
                      <button
                        onClick={() => handleExportWord(msg)}
                        title="导出 Word"
                        aria-label="导出 Word"
                        style={{
                          background: 'rgba(75, 45, 119, 0.08)',
                          border: 'none',
                          borderRadius: 'var(--gt-radius-sm)',
                          cursor: 'pointer',
                          fontSize: 14,
                          padding: '2px 6px',
                          color: 'var(--gt-text-secondary)',
                          transition: 'color 0.2s, background 0.2s',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.color = 'var(--gt-primary)';
                          e.currentTarget.style.background = 'rgba(75, 45, 119, 0.15)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.color = 'var(--gt-text-secondary)';
                          e.currentTarget.style.background = 'rgba(75, 45, 119, 0.08)';
                        }}
                      >
                        📄
                      </button>
                      {/* ✏️ 在线编辑按钮 */}
                      <button
                        onClick={() => handleOnlineEdit(msg)}
                        title="在线编辑"
                        aria-label="在线编辑"
                        style={{
                          background: 'rgba(75, 45, 119, 0.08)',
                          border: 'none',
                          borderRadius: 'var(--gt-radius-sm)',
                          cursor: 'pointer',
                          fontSize: 14,
                          padding: '2px 6px',
                          color: 'var(--gt-text-secondary)',
                          transition: 'color 0.2s, background 0.2s',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.color = 'var(--gt-primary)';
                          e.currentTarget.style.background = 'rgba(75, 45, 119, 0.15)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.color = 'var(--gt-text-secondary)';
                          e.currentTarget.style.background = 'rgba(75, 45, 119, 0.08)';
                        }}
                      >
                        ✏️
                      </button>
                      {/* 📌 保存到笔记按钮 */}
                      {onSaveNote && (
                        <button
                          onClick={() => handleSaveNote(msg, msgIndex)}
                          title="保存到笔记"
                          aria-label="保存到笔记"
                          style={{
                            background: 'rgba(75, 45, 119, 0.08)',
                            border: 'none',
                            borderRadius: 'var(--gt-radius-sm)',
                            cursor: 'pointer',
                            fontSize: 14,
                            padding: '2px 6px',
                            color: 'var(--gt-text-secondary)',
                            transition: 'color 0.2s, background 0.2s',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = 'var(--gt-primary)';
                            e.currentTarget.style.background = 'rgba(75, 45, 119, 0.15)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = 'var(--gt-text-secondary)';
                            e.currentTarget.style.background = 'rgba(75, 45, 119, 0.08)';
                          }}
                        >
                          📌
                        </button>
                      )}
                      {/* 🗑️ 删除单条消息按钮 */}
                      {onDeleteMessage && (
                        <button
                          onClick={() => onDeleteMessage(msg.id)}
                          title="删除此消息"
                          aria-label="删除此消息"
                          style={{
                            background: 'rgba(75, 45, 119, 0.08)',
                            border: 'none',
                            borderRadius: 'var(--gt-radius-sm)',
                            cursor: 'pointer',
                            fontSize: 14,
                            padding: '2px 6px',
                            color: 'var(--gt-text-secondary)',
                            transition: 'color 0.2s, background 0.2s',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = 'var(--gt-danger, #FF5149)';
                            e.currentTarget.style.background = 'rgba(255, 81, 73, 0.1)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = 'var(--gt-text-secondary)';
                            e.currentTarget.style.background = 'rgba(75, 45, 119, 0.08)';
                          }}
                        >
                          🗑️
                        </button>
                      )}
                </div>
              )}
              {/* 已保存反馈 */}
              {isAssistant && msg.savedToNotes && (
                <div
                  style={{
                    marginTop: 4,
                    paddingLeft: 2,
                    fontSize: 'var(--gt-font-xs)',
                    color: 'var(--gt-success)',
                    fontWeight: 500,
                  }}
                >
                  ✓ 已保存
                </div>
              )}

              {/* "已识别图片内容"标签 */}
              {isAssistant && hasImageOcrTag(msg) && (
                <div
                  style={{
                    marginTop: 6,
                    display: 'inline-block',
                    padding: '2px 8px',
                    backgroundColor: '#f0f7ff',
                    color: 'var(--gt-text-secondary)',
                    borderRadius: 'var(--gt-radius-sm)',
                    fontSize: 'var(--gt-font-xs)',
                  }}
                >
                  🖼️ 已识别图片内容
                </div>
              )}

              {/* "建议保存到笔记"提示标签 */}
              {isAssistant && msg.suggestSaveNote && !msg.savedToNotes && onSaveNote && (
                <div
                  onClick={() => handleSaveNote(msg, msgIndex)}
                  style={{
                    marginTop: 6,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '3px 10px',
                    backgroundColor: 'rgba(75, 45, 119, 0.08)',
                    color: 'var(--gt-primary)',
                    borderRadius: 'var(--gt-radius-sm)',
                    fontSize: 'var(--gt-font-xs)',
                    cursor: 'pointer',
                    transition: 'background 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'rgba(75, 45, 119, 0.15)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'rgba(75, 45, 119, 0.08)';
                  }}
                >
                  💡 建议保存到笔记
                </div>
              )}

              {/* 知识库引用标签 */}
              {isAssistant && msg.knowledgeRefs && msg.knowledgeRefs.length > 0 && (
                <div
                  style={{
                    marginTop: 6,
                    fontSize: 'var(--gt-font-xs)',
                    color: 'var(--gt-text-secondary)',
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <span>已参考：</span>
                  {msg.knowledgeRefs.map((ref) => (
                    <span
                      key={ref}
                      style={{
                        display: 'inline-block',
                        padding: '1px 8px',
                        backgroundColor: 'rgba(75, 45, 119, 0.1)',
                        color: 'var(--gt-primary)',
                        borderRadius: 'var(--gt-radius-sm)',
                        fontSize: 'var(--gt-font-xs)',
                        fontWeight: 500,
                      }}
                    >
                      @{LIBRARY_DISPLAY_NAMES[ref] || ref}
                    </span>
                  ))}
                </div>
              )}
              {/* 用户消息的删除按钮（hover 显示） */}
              {!isAssistant && isHovered && onDeleteMessage && (
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
                  <button
                    onClick={() => onDeleteMessage(msg.id)}
                    title="删除此消息"
                    aria-label="删除此消息"
                    style={{
                      background: 'rgba(75, 45, 119, 0.08)',
                      border: 'none',
                      borderRadius: 'var(--gt-radius-sm)',
                      cursor: 'pointer',
                      fontSize: 14,
                      padding: '2px 6px',
                      color: 'var(--gt-text-secondary)',
                      transition: 'color 0.2s, background 0.2s',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = 'var(--gt-danger, #FF5149)';
                      e.currentTarget.style.background = 'rgba(255, 81, 73, 0.1)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = 'var(--gt-text-secondary)';
                      e.currentTarget.style.background = 'rgba(75, 45, 119, 0.08)';
                    }}
                  >
                    🗑️
                  </button>
                </div>
              )}
            </div>
          </div>
        );
      })}
      <div ref={messagesEndRef} />

      {/* 全屏图片预览模态框 */}
      {previewSrc && <ImagePreviewModal src={previewSrc} onClose={closePreview} />}

      {/* 文档在线编辑模态框 */}
      {editorBlob && (
        <DocumentEditorModal
          fileBlob={editorBlob}
          markdownContent={editorMarkdown}
          filename={editorFilename}
          onClose={() => { setEditorBlob(null); setEditorFilename(''); setEditorMarkdown(''); setEditorMsgId(''); }}
          onSyncToChat={onUpdateMessage ? (newContent) => {
            if (editorMsgId) onUpdateMessage(editorMsgId, newContent);
          } : undefined}
          onSaveToNote={onSaveNote}
        />
      )}
    </div>
  );
};

export default ChatMessageList;
