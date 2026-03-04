/**
 * SectionEditor - 章节编辑器
 *
 * 全屏模态编辑器，支持：
 * - 手动文本编辑（左侧 textarea 直接修改）
 * - 选中部分文本后仅对选中部分发起 AI 辅助修改
 * - AI 对话式修改（右侧聊天面板，多轮对话历史）
 * - 每个章节独立维护编辑状态（editContent, aiInput, messages, targetWordCount）
 * - 参照现有 ContentEdit.tsx 的 ManualEditState 交互模式
 *
 * Requirements: 12.7, 12.8, 12.16
 */
import React, { useState, useRef, useCallback, useEffect } from 'react';
import type { SectionRevisionRequest } from '../types/audit';
import { generateApi } from '../services/api';
import { processSSEStream } from '../utils/sseParser';
import '../styles/gt-design-tokens.css';

interface SectionEditorProps {
  sectionIndex: number;
  sectionTitle: string;
  content: string;
  documentId: string;
  onContentChange: (content: string) => void;
  onClose: () => void;
}

interface ChatMessage {
  role: string;
  content: string;
}

const SectionEditor: React.FC<SectionEditorProps> = ({
  sectionIndex,
  sectionTitle,
  content,
  documentId,
  onContentChange,
  onClose,
}) => {
  // ─── Edit state (independent per section) ───
  const [editContent, setEditContent] = useState(content);
  const [aiInput, setAiInput] = useState('');
  const [aiProcessing, setAiProcessing] = useState(false);
  const [selectedText, setSelectedText] = useState('');
  const [selectionStart, setSelectionStart] = useState(0);
  const [selectionEnd, setSelectionEnd] = useState(0);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [targetWordCount, setTargetWordCount] = useState<number | undefined>(undefined);

  // ─── Refs ───
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatLogRef = useRef<HTMLDivElement>(null);

  /** Sync content from parent when it changes externally */
  useEffect(() => {
    setEditContent(content);
  }, [content]);

  /** Auto-scroll chat log to bottom when messages change */
  useEffect(() => {
    if (chatLogRef.current) {
      chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
    }
  }, [messages]);

  /** Track text selection in the textarea */
  const handleTextSelect = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = ta.value.substring(start, end);
    setSelectedText(selected);
    setSelectionStart(start);
    setSelectionEnd(end);
  }, []);

  /** Word count helper */
  const getWordCount = (text: string): number => {
    if (!text) return 0;
    // Count Chinese characters + English words
    const chineseChars = (text.match(/[\u4e00-\u9fff]/g) || []).length;
    const englishWords = text
      .replace(/[\u4e00-\u9fff]/g, '')
      .split(/\s+/)
      .filter(Boolean).length;
    return chineseChars + englishWords;
  };

  /** Save content and close */
  const handleSave = useCallback(() => {
    onContentChange(editContent);
    onClose();
  }, [editContent, onContentChange, onClose]);

  /** Submit AI revision request via SSE */
  const handleAiSubmit = useCallback(async () => {
    if (!aiInput.trim() || aiProcessing) return;

    const hasSelection = selectedText.length > 0;
    const instruction = aiInput.trim();

    // Add user message to chat
    const userMessage: ChatMessage = { role: 'user', content: instruction };
    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setAiInput('');
    setAiProcessing(true);

    // Build request
    const requestData: SectionRevisionRequest = {
      document_id: documentId,
      section_index: sectionIndex,
      current_content: editContent,
      user_instruction: instruction + (hasSelection ? '\n\n【注意】只修改上述选中的部分内容，保持格式和风格一致。' : ''),
      selected_text: hasSelection ? selectedText : undefined,
      selection_start: hasSelection ? selectionStart : undefined,
      selection_end: hasSelection ? selectionEnd : undefined,
      messages: updatedMessages.map((m) => ({ role: m.role, content: m.content })),
    };

    let revisedContent = '';

    try {
      const response = await generateApi.reviseSection(requestData);

      if (!response.ok) {
        throw new Error(`AI修改失败: ${response.status}`);
      }

      await processSSEStream(
        response,
        (data) => {
          try {
            const event = JSON.parse(data);
            if (event.status === 'streaming' && event.content) {
              revisedContent += event.content;
            } else if ((event.status === 'completed' || event.status === 'section_complete') && event.content) {
              revisedContent = event.content;
            } else if (event.status === 'error') {
              throw new Error(event.message || 'AI修改失败');
            }
          } catch {
            // ignore parse errors for non-JSON lines
          }
        },
        () => {
          // On done
          if (revisedContent) {
            if (hasSelection) {
              // Replace only the selected portion
              const before = editContent.substring(0, selectionStart);
              const after = editContent.substring(selectionEnd);
              const newContent = before + revisedContent + after;
              setEditContent(newContent);
            } else {
              setEditContent(revisedContent);
            }

            // Add assistant response to chat
            const assistantMsg: ChatMessage = {
              role: 'assistant',
              content: hasSelection ? `已修改选中文本（${selectedText.length}字）` : '已修改全文内容',
            };
            setMessages((prev) => [...prev, assistantMsg]);
          }
          setAiProcessing(false);
          setSelectedText('');
        },
        (err) => {
          const errorMsg: ChatMessage = { role: 'assistant', content: `修改失败: ${err.message}` };
          setMessages((prev) => [...prev, errorMsg]);
          setAiProcessing(false);
        },
      );
    } catch (err: any) {
      const errorMsg: ChatMessage = { role: 'assistant', content: `请求失败: ${err.message}` };
      setMessages((prev) => [...prev, errorMsg]);
      setAiProcessing(false);
    }
  }, [aiInput, aiProcessing, selectedText, selectionStart, selectionEnd, editContent, messages, documentId, sectionIndex]);

  /** Handle Enter key in AI input */
  const handleAiKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && e.ctrlKey) {
        e.preventDefault();
        handleAiSubmit();
      }
    },
    [handleAiSubmit],
  );

  return (
    <div
      className="gt-section"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--gt-space-4)',
      }}
      role="dialog"
      aria-modal="true"
      aria-label={`编辑章节: ${sectionTitle}`}
    >
      <div
        className="gt-card"
        style={{
          width: '100%',
          maxWidth: 1200,
          height: '90vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* ─── Header ─── */}
        <div
          className="gt-card-header"
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 'var(--gt-space-2)',
            flexShrink: 0,
          }}
        >
          <div>
            <h2 className="gt-h4" style={{ margin: 0 }}>
              编辑章节
            </h2>
            <span
              style={{
                fontSize: 'var(--gt-font-sm)',
                color: 'var(--gt-text-secondary)',
              }}
            >
              {sectionTitle}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-3)' }}>
            {/* Target word count */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-1)' }}>
              <label
                htmlFor="section-target-wc"
                style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}
              >
                目标字数:
              </label>
              <input
                id="section-target-wc"
                type="number"
                min={0}
                value={targetWordCount ?? ''}
                onChange={(e) =>
                  setTargetWordCount(e.target.value ? parseInt(e.target.value, 10) : undefined)
                }
                placeholder="自动"
                style={{
                  width: 80,
                  padding: '2px var(--gt-space-2)',
                  border: '1px solid #ddd',
                  borderRadius: 'var(--gt-radius-sm)',
                  fontSize: 'var(--gt-font-sm)',
                }}
                aria-label="目标字数"
              />
            </div>

            {/* Current word count */}
            <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
              当前: {getWordCount(editContent)} 字
            </span>

            {/* Save & Close */}
            <button
              className="gt-button gt-button--primary"
              onClick={handleSave}
              aria-label="保存并关闭"
            >
              保存
            </button>
            <button
              className="gt-button gt-button--secondary"
              onClick={onClose}
              aria-label="关闭编辑器"
            >
              关闭
            </button>
          </div>
        </div>

        {/* ─── Body: two-panel layout ─── */}
        <div
          className="gt-card-content"
          style={{
            flex: 1,
            display: 'flex',
            gap: 'var(--gt-space-4)',
            overflow: 'hidden',
            padding: 'var(--gt-space-4)',
          }}
        >
          {/* ─── Left panel: Text editor ─── */}
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              minWidth: 0,
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 'var(--gt-space-2)',
              }}
            >
              <label
                htmlFor={`section-editor-textarea-${sectionIndex}`}
                style={{
                  fontSize: 'var(--gt-font-sm)',
                  fontWeight: 600,
                  color: 'var(--gt-text-primary)',
                }}
              >
                章节内容
              </label>
              {selectedText && (
                <span
                  style={{
                    fontSize: 'var(--gt-font-xs)',
                    color: 'var(--gt-primary)',
                    backgroundColor: 'rgba(75, 45, 119, 0.08)',
                    padding: '2px var(--gt-space-2)',
                    borderRadius: 'var(--gt-radius-sm)',
                  }}
                >
                  已选中 {selectedText.length} 字
                </span>
              )}
            </div>
            <textarea
              id={`section-editor-textarea-${sectionIndex}`}
              ref={textareaRef}
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              onSelect={handleTextSelect}
              onMouseUp={handleTextSelect}
              onKeyUp={handleTextSelect}
              style={{
                flex: 1,
                width: '100%',
                padding: 'var(--gt-space-3)',
                border: '1px solid #ddd',
                borderRadius: 'var(--gt-radius-md)',
                fontFamily: 'var(--gt-font-cn)',
                fontSize: 'var(--gt-font-base)',
                lineHeight: 1.8,
                resize: 'none',
                color: 'var(--gt-text-primary)',
                outline: 'none',
              }}
              aria-label={`编辑 ${sectionTitle} 内容`}
            />
          </div>

          {/* ─── Right panel: AI chat ─── */}
          <div
            style={{
              width: 380,
              flexShrink: 0,
              display: 'flex',
              flexDirection: 'column',
              borderLeft: '1px solid #eee',
              paddingLeft: 'var(--gt-space-4)',
            }}
          >
            <div
              style={{
                fontSize: 'var(--gt-font-sm)',
                fontWeight: 600,
                color: 'var(--gt-text-primary)',
                marginBottom: 'var(--gt-space-2)',
              }}
            >
              AI 辅助修改
            </div>

            {/* Chat message log */}
            <div
              ref={chatLogRef}
              role="log"
              aria-label="AI对话历史"
              aria-live="polite"
              style={{
                flex: 1,
                overflowY: 'auto',
                marginBottom: 'var(--gt-space-3)',
                padding: 'var(--gt-space-2)',
                backgroundColor: '#f8f9fa',
                borderRadius: 'var(--gt-radius-md)',
                minHeight: 100,
              }}
            >
              {messages.length === 0 && (
                <div
                  style={{
                    color: 'var(--gt-text-secondary)',
                    fontSize: 'var(--gt-font-sm)',
                    textAlign: 'center',
                    padding: 'var(--gt-space-6) var(--gt-space-2)',
                  }}
                >
                  输入修改指令，AI 将帮助您修改章节内容。
                  <br />
                  选中左侧文本后可仅修改选中部分。
                </div>
              )}
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  style={{
                    marginBottom: 'var(--gt-space-2)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  }}
                >
                  <span
                    style={{
                      fontSize: 'var(--gt-font-xs)',
                      color: 'var(--gt-text-secondary)',
                      marginBottom: 2,
                    }}
                  >
                    {msg.role === 'user' ? '您' : 'AI'}
                  </span>
                  <div
                    style={{
                      maxWidth: '90%',
                      padding: 'var(--gt-space-2) var(--gt-space-3)',
                      borderRadius: 'var(--gt-radius-md)',
                      fontSize: 'var(--gt-font-sm)',
                      lineHeight: 1.5,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      backgroundColor: msg.role === 'user' ? 'var(--gt-primary)' : '#fff',
                      color: msg.role === 'user' ? '#fff' : 'var(--gt-text-primary)',
                      border: msg.role === 'user' ? 'none' : '1px solid #e0e0e0',
                    }}
                  >
                    {msg.content}
                  </div>
                </div>
              ))}
              {aiProcessing && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--gt-space-2)',
                    color: 'var(--gt-text-secondary)',
                    fontSize: 'var(--gt-font-sm)',
                    padding: 'var(--gt-space-2)',
                  }}
                  role="status"
                  aria-label="AI正在处理"
                >
                  <div
                    aria-hidden="true"
                    style={{
                      width: 14,
                      height: 14,
                      border: '2px solid var(--gt-primary-light)',
                      borderTopColor: 'var(--gt-primary)',
                      borderRadius: '50%',
                      animation: 'gt-spin 0.8s linear infinite',
                    }}
                  />
                  AI 正在修改...
                </div>
              )}
            </div>

            {/* Selection hint */}
            {selectedText && (
              <div
                style={{
                  marginBottom: 'var(--gt-space-2)',
                  padding: 'var(--gt-space-2) var(--gt-space-3)',
                  backgroundColor: 'rgba(75, 45, 119, 0.06)',
                  borderRadius: 'var(--gt-radius-sm)',
                  fontSize: 'var(--gt-font-xs)',
                  color: 'var(--gt-primary)',
                  border: '1px solid rgba(75, 45, 119, 0.15)',
                }}
              >
                将仅修改选中的 {selectedText.length} 字文本
              </div>
            )}

            {/* AI input */}
            <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
              <div style={{ flex: 1 }}>
                <label
                  htmlFor={`section-ai-input-${sectionIndex}`}
                  style={{
                    display: 'block',
                    fontSize: 'var(--gt-font-xs)',
                    color: 'var(--gt-text-secondary)',
                    marginBottom: 'var(--gt-space-1)',
                  }}
                >
                  {selectedText ? '修改选中文本的指令' : '修改指令'}
                </label>
                <textarea
                  id={`section-ai-input-${sectionIndex}`}
                  value={aiInput}
                  onChange={(e) => setAiInput(e.target.value)}
                  onKeyDown={handleAiKeyDown}
                  placeholder={
                    selectedText
                      ? '输入对选中文本的修改要求...'
                      : '输入修改要求，Ctrl+Enter 提交...'
                  }
                  rows={3}
                  disabled={aiProcessing}
                  style={{
                    width: '100%',
                    padding: 'var(--gt-space-2)',
                    border: '1px solid #ddd',
                    borderRadius: 'var(--gt-radius-sm)',
                    fontFamily: 'var(--gt-font-cn)',
                    fontSize: 'var(--gt-font-sm)',
                    resize: 'none',
                    color: 'var(--gt-text-primary)',
                    outline: 'none',
                  }}
                  aria-label={selectedText ? '修改选中文本的指令' : '修改指令'}
                />
              </div>
              <button
                className="gt-button gt-button--primary"
                onClick={handleAiSubmit}
                disabled={!aiInput.trim() || aiProcessing}
                style={{
                  alignSelf: 'flex-end',
                  whiteSpace: 'nowrap',
                  height: 40,
                }}
                aria-label={selectedText ? '修改选中文本' : '提交AI修改'}
              >
                {aiProcessing ? '处理中...' : selectedText ? '修改选中' : 'AI修改'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Spin animation */}
      <style>{`
        @keyframes gt-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export default SectionEditor;
