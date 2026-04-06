/**
 * ChatPanel - 首页聊天面板主组件
 *
 * 可折叠面板形式嵌入 WorkModeSelector 首页右下角，
 * 提供 AI 对话、知识库 RAG 检索、快捷指令联动等功能。
 * 遵循 GT Design System 设计规范。
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import type { ChatMessage, ChatSession } from '../types/chat';
import type { KnowledgeLibrary } from './KnowledgePopup';
import { configApi, chatApi } from '../services/api';
import { processSSEStream } from '../utils/sseParser';
import { saveChatSession, loadChatSession, archiveChatSession } from '../utils/chatStorage';
import ChatMessageList from './ChatMessageList';
import ChatInput from './ChatInput';
import type { PendingImage } from './ChatInput';
import ChatWelcome from './ChatWelcome';
import NotesSidebar from './NotesSidebar';
import ChatExportPanel from './ChatExportPanel';
import '../styles/gt-design-tokens.css';

interface ChatPanelProps {
  onSelectMode: (mode: 'review' | 'generate' | 'analysis' | 'report_review') => void;
}

const ChatPanel: React.FC<ChatPanelProps> = ({ onSelectMode }) => {
  /* ─── 状态管理 ─── */
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortController = useRef<AbortController | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const [inputText, setInputText] = useState('');

  /* ─── 面板位置与尺寸（拖动 + 缩放） ─── */
  const [panelPos, setPanelPos] = useState({ x: -1, y: -1 }); // -1 表示使用默认位置
  const [panelSize, setPanelSize] = useState({ w: 0, h: 0 }); // 0 表示使用默认尺寸
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null);

  // 默认尺寸：页面宽度的 1/4，高度 4/5，最小 380x450
  const defaultW = Math.max(380, Math.floor(window.innerWidth / 4));
  const defaultH = Math.max(450, Math.floor(window.innerHeight * 0.8));
  const panelW = panelSize.w || defaultW;
  const panelH = panelSize.h || defaultH;
  const panelX = panelPos.x >= 0 ? panelPos.x : Math.max(0, window.innerWidth - panelW - 24);
  const panelY = panelPos.y >= 0 ? panelPos.y : Math.max(0, window.innerHeight - panelH - 24);

  const [currentModel, setCurrentModel] = useState('');
  const [exportMode, setExportMode] = useState(false);
  const [selectedMsgIds, setSelectedMsgIds] = useState<Set<string>>(new Set());
  const [selectedLibraries, setSelectedLibraries] = useState<KnowledgeLibrary[]>([]);
  const sessionId = useRef<string>(crypto.randomUUID?.() || Date.now().toString());

  /* ─── 文档上传状态 ─── */
  const [uploadedFile, setUploadedFile] = useState<{ filename: string; size: number } | null>(null);
  const [documentContext, setDocumentContext] = useState('');

  /* ─── 图片上传状态 ─── */
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);

  /* ─── 笔记侧边栏状态 ─── */
  const [notesSidebarVisible, setNotesSidebarVisible] = useState(false);

  /* ─── 导出面板状态 ─── */
  const [showExportPanel, setShowExportPanel] = useState(false);
  const [exportContent, setExportContent] = useState('');

  /* ─── 笔记清理状态 (10.2, 10.3) ─── */
  const [cleanupBanner, setCleanupBanner] = useState<{ count: number; sizeMB: number } | null>(null);
  const [cleanupSuggestions, setCleanupSuggestions] = useState<Array<{
    doc_id: string; title: string; created_at: string; reason: string; last_rag_reference?: string | null;
  }>>([]);
  const [cleanupSelected, setCleanupSelected] = useState<Set<string>>(new Set());
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupVisible, setCleanupVisible] = useState(false);
  const [cleanupDeleting, setCleanupDeleting] = useState(false);

  /* ─── IndexedDB 持久化：组件初始化时恢复会话 ─── */
  useEffect(() => {
    loadChatSession().then((session) => {
      if (session) {
        setMessages(session.messages);
        sessionId.current = session.id;
      }
    });
  }, []);

  /* ─── IndexedDB 持久化：消息变化时保存会话 ─── */
  useEffect(() => {
    if (messages.length === 0) return;
    const session: ChatSession = {
      id: sessionId.current,
      messages,
      createdAt: messages[0]?.timestamp || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    saveChatSession(session);
  }, [messages]);

  /* ─── 获取当前模型名称 ─── */
  useEffect(() => {
    if (!chatOpen) return;
    configApi.loadConfig().then((res) => {
      const data = res.data;
      if (!data) return;
      // 优先使用 model_name（如 "deepseek-chat"），回退到激活供应商名称
      if (data.model_name) {
        setCurrentModel(data.model_name);
      } else {
        const providers = data.providers || [];
        const active = Array.isArray(providers)
          ? providers.find((p: Record<string, unknown>) => p.is_active)
          : null;
        if (active) {
          setCurrentModel((active as Record<string, string>).name || '');
        }
      }
    }).catch(() => { /* 静默失败 */ });
  }, [chatOpen]);

  /* ─── 笔记库大小检查：chatOpen 时检查是否超阈值 (10.2) ─── */
  useEffect(() => {
    if (!chatOpen) return;
    chatApi.getNotes().then((res) => {
      const data = res.data;
      if (!data) return;
      const totalCount = data.total_count || 0;
      const totalSize = data.total_size || 0;
      const sizeMB = parseFloat((totalSize / 1024 / 1024).toFixed(1));
      if (totalCount > 50 || sizeMB > 5) {
        setCleanupBanner({ count: totalCount, sizeMB });
      } else {
        setCleanupBanner(null);
      }
    }).catch(() => { /* 静默失败 */ });
  }, [chatOpen]);

  /* ─── 查看清理建议 (10.3) ─── */
  const handleShowCleanupSuggestions = useCallback(async () => {
    setCleanupLoading(true);
    setCleanupVisible(true);
    try {
      const res = await chatApi.cleanupSuggest();
      const suggestions = res.data?.suggestions || [];
      setCleanupSuggestions(suggestions);
      setCleanupSelected(new Set());
    } catch {
      setCleanupSuggestions([]);
    } finally {
      setCleanupLoading(false);
    }
  }, []);

  /* ─── 删除选中的清理建议笔记 (10.3) ─── */
  const handleCleanupDelete = useCallback(async () => {
    if (cleanupSelected.size === 0) return;
    setCleanupDeleting(true);
    try {
      for (const docId of Array.from(cleanupSelected)) {
        await chatApi.deleteNote(docId);
      }
      // 从建议列表中移除已删除的
      setCleanupSuggestions((prev) => prev.filter((s) => !cleanupSelected.has(s.doc_id)));
      setCleanupSelected(new Set());
      // 刷新 banner 状态
      chatApi.getNotes().then((res) => {
        const data = res.data;
        if (!data) return;
        const totalCount = data.total_count || 0;
        const totalSize = data.total_size || 0;
        const sizeMB = parseFloat((totalSize / 1024 / 1024).toFixed(1));
        if (totalCount > 50 || sizeMB > 5) {
          setCleanupBanner({ count: totalCount, sizeMB });
        } else {
          setCleanupBanner(null);
        }
      }).catch(() => {});
    } catch {
      /* 静默失败 */
    } finally {
      setCleanupDeleting(false);
    }
  }, [cleanupSelected]);

  /* ─── 新建对话 ─── */
  const handleNewChat = useCallback(async () => {
    // 归档当前会话（如果有消息）
    if (messages.length > 0) {
      const session: ChatSession = {
        id: sessionId.current,
        messages,
        createdAt: messages[0]?.timestamp || new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      await archiveChatSession(session);
    }
    // 重置状态
    setMessages([]);
    sessionId.current = crypto.randomUUID?.() || Date.now().toString();
    setExportMode(false);
    setSelectedMsgIds(new Set());
    setSelectedLibraries([]);
    setUploadedFile(null);
    setDocumentContext('');
    setPendingImages([]);
  }, [messages]);

  /* ─── 清除对话（不归档，直接删除） ─── */
  const [clearConfirm, setClearConfirm] = useState(false);
  const handleClearChat = useCallback(() => {
    if (!clearConfirm) {
      setClearConfirm(true);
      setTimeout(() => setClearConfirm(false), 3000);
      return;
    }
    setMessages([]);
    sessionId.current = crypto.randomUUID?.() || Date.now().toString();
    setExportMode(false);
    setSelectedMsgIds(new Set());
    setSelectedLibraries([]);
    setUploadedFile(null);
    setDocumentContext('');
    setPendingImages([]);
    setClearConfirm(false);
  }, [clearConfirm]);

  /* ─── 停止生成 ─── */
  const handleStop = useCallback(() => {
    abortController.current?.abort();
    abortController.current = null;
  }, []);

  /* ─── 面板拖动 ─── */
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if (isMaximized) return;
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: panelX, origY: panelY };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const dx = ev.clientX - dragRef.current.startX;
      const dy = ev.clientY - dragRef.current.startY;
      setPanelPos({
        x: Math.max(0, Math.min(window.innerWidth - 100, dragRef.current.origX + dx)),
        y: Math.max(0, Math.min(window.innerHeight - 50, dragRef.current.origY + dy)),
      });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [isMaximized, panelX, panelY]);

  /* ─── 面板缩放（右下角拖拽） ─── */
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    if (isMaximized) return;
    e.preventDefault();
    e.stopPropagation();
    resizeRef.current = { startX: e.clientX, startY: e.clientY, origW: panelW, origH: panelH };
    const onMove = (ev: MouseEvent) => {
      if (!resizeRef.current) return;
      const dw = ev.clientX - resizeRef.current.startX;
      const dh = ev.clientY - resizeRef.current.startY;
      setPanelSize({
        w: Math.max(380, resizeRef.current.origW + dw),
        h: Math.max(450, resizeRef.current.origH + dh),
      });
    };
    const onUp = () => {
      resizeRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [isMaximized, panelW, panelH]);

  /* ─── 文件上传处理 ─── */
  const handleFileUpload = useCallback(async (file: File) => {
    try {
      const res = await chatApi.upload(file);
      const data = res.data;
      if (data?.success) {
        setUploadedFile({ filename: data.filename, size: data.size });
        setDocumentContext(data.content || '');
      } else {
        // 上传失败：在对话中显示临时错误消息
        const errMsg: ChatMessage = {
          id: crypto.randomUUID?.() || Date.now().toString(),
          role: 'assistant',
          content: `⚠️ 文件上传失败：${data?.error || '未知错误'}`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errMsg]);
      }
    } catch (err: any) {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID?.() || Date.now().toString(),
        role: 'assistant',
        content: `⚠️ 文件上传失败：${err.message || '网络错误'}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errMsg]);
    }
  }, []);

  /* ─── 移除已上传文件 ─── */
  const handleRemoveFile = useCallback(() => {
    setUploadedFile(null);
    setDocumentContext('');
  }, []);

  /* ─── 同步编辑后的内容回对话消息 ─── */
  const handleUpdateMessage = useCallback((msgId: string, newContent: string) => {
    setMessages((prev) =>
      prev.map((m) => m.id === msgId ? { ...m, content: newContent } : m),
    );
  }, []);

  /* ─── 删除单条消息 ─── */
  const handleDeleteMessage = useCallback((msgId: string) => {
    setMessages((prev) => prev.filter((m) => m.id !== msgId));
  }, []);

  /* ─── 批量删除选中消息 ─── */
  const handleDeleteSelected = useCallback(() => {
    if (selectedMsgIds.size === 0) return;
    setMessages((prev) => prev.filter((m) => !selectedMsgIds.has(m.id)));
    setSelectedMsgIds(new Set());
  }, [selectedMsgIds]);

  /* ─── 保存单条 AI 回复到笔记 (9.6) ─── */
  const handleSaveNote = useCallback(async (content: string, title: string) => {
    try {
      await chatApi.saveNote({ title, content });
      // 标记该消息已保存，显示"已保存"反馈
      setMessages((prev) =>
        prev.map((m) =>
          m.role === 'assistant' && m.content === content
            ? { ...m, savedToNotes: true }
            : m,
        ),
      );
      // 2 秒后清除 savedToNotes 标记（保留视觉反馈一段时间）
      setTimeout(() => {
        setMessages((prev) =>
          prev.map((m) =>
            m.role === 'assistant' && m.content === content && m.savedToNotes
              ? { ...m, savedToNotes: false }
              : m,
          ),
        );
      }, 2000);
    } catch {
      /* 静默失败 */
    }
  }, []);

  /* ─── 保存整段对话到笔记 (9.7) ─── */
  const [conversationSaved, setConversationSaved] = useState(false);
  const handleSaveConversation = useCallback(async () => {
    if (messages.length === 0) return;
    const now = new Date();
    const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    const title = `对话摘要 - ${dateStr} ${timeStr}`;
    const content = messages
      .map((m) => (m.role === 'user' ? `**提问：** ${m.content}` : `**回复：** ${m.content}`))
      .join('\n\n---\n\n');
    try {
      await chatApi.saveNote({ title, content, date: dateStr });
      setConversationSaved(true);
      setTimeout(() => setConversationSaved(false), 2000);
    } catch {
      /* 静默失败 */
    }
  }, [messages]);

  /* ─── 多选导出处理 ─── */
  const handleToggleExportMode = useCallback(() => {
    setExportMode((prev) => {
      if (prev) {
        setSelectedMsgIds(new Set());
      }
      return !prev;
    });
  }, []);

  const handleToggleSelect = useCallback((msgId: string) => {
    setSelectedMsgIds((prev) => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    setSelectedMsgIds(new Set(messages.map((m) => m.id)));
  }, [messages]);

  const handleSelectAIOnly = useCallback(() => {
    setSelectedMsgIds(new Set(messages.filter((m) => m.role === 'assistant').map((m) => m.id)));
  }, [messages]);

  const handleConfirmExport = useCallback(() => {
    const selected = messages.filter((m) => selectedMsgIds.has(m.id));
    const md = selected
      .map((m) => (m.role === 'user' ? `**提问：** ${m.content}` : m.content))
      .join('\n\n---\n\n');
    setExportContent(md);
    setShowExportPanel(true);
    setExportMode(false);
  }, [messages, selectedMsgIds]);

  /* ─── 发送消息（SSE 流式对话） ─── */
  const handleSend = useCallback(async () => {
    const text = inputText.trim();
    if ((!text && pendingImages.length === 0) || isStreaming) return;

    // 1. 上传待发送的图片，收集 OCR 结果和缩略图附件
    let imageOcrContext: string | undefined;
    const imageAttachments: Array<{ filename: string; size: number; type: 'image'; content?: string; thumbnailUrl?: string }> = [];

    if (pendingImages.length > 0) {
      const ocrParts: string[] = [];
      for (const img of pendingImages) {
        try {
          const file = new File([img.blob], `image_${Date.now()}.png`, { type: img.blob.type || 'image/png' });
          const res = await chatApi.upload(file);
          const data = res.data;
          if (data?.success && data.content) {
            ocrParts.push(data.content);
          }
          imageAttachments.push({
            filename: file.name,
            size: img.blob.size,
            type: 'image',
            content: data?.content || '',
            thumbnailUrl: img.thumbnailUrl,
          });
        } catch {
          imageAttachments.push({
            filename: 'image.png',
            size: img.blob.size,
            type: 'image',
            thumbnailUrl: img.thumbnailUrl,
          });
        }
      }
      if (ocrParts.length > 0) {
        imageOcrContext = ocrParts.join('\n---\n');
      }
      // 清空待上传图片（不 revoke URL，因为消息中还要展示）
      setPendingImages([]);
    }

    // 2. 创建用户消息
    const userMsg: ChatMessage = {
      id: crypto.randomUUID?.() || Date.now().toString(),
      role: 'user',
      content: text || '（发送了图片）',
      timestamp: new Date().toISOString(),
      attachments: imageAttachments.length > 0 ? imageAttachments : undefined,
    };

    // 3. 创建空的 assistant 消息占位
    const assistantMsg: ChatMessage = {
      id: crypto.randomUUID?.() || (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    };

    // 4. 更新状态
    const updatedMessages = [...messages, userMsg, assistantMsg];
    setMessages(updatedMessages);
    setInputText('');
    setIsStreaming(true);

    // 5. 创建 AbortController
    const controller = new AbortController();
    abortController.current = controller;

    // 6. 构建发送给后端的 messages（仅 role + content）
    const historyForApi = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // 7. 提取知识库 ID 列表（如果有选中的知识库标签）
    const knowledgeLibraryIds = selectedLibraries.length > 0
      ? selectedLibraries.map((lib) => lib.id)
      : undefined;

    // 发送后清空知识库标签
    setSelectedLibraries([]);

    // 8. 提取文档上下文（如果有上传文件）
    const docCtx = documentContext || undefined;

    // 发送后清空上传文件状态
    setUploadedFile(null);
    setDocumentContext('');

    let accumulatedContent = '';
    let isDone = false;
    // 记录用户消息是否有图片附件，用于标注 AI 回复
    const userHadImages = imageAttachments.length > 0;

    try {
      const response = await chatApi.stream(
        {
          messages: historyForApi,
          knowledge_library_ids: knowledgeLibraryIds,
          document_context: docCtx,
          image_ocr_context: imageOcrContext,
        },
        controller.signal,
      );

      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        throw new Error(errText || `请求失败 (${response.status})`);
      }

      await processSSEStream(
        response,
        (data) => {
          if (isDone) {
            // [DONE] 之后的 data 行是 meta JSON
            try {
              const parsed = JSON.parse(data);
              if (parsed.meta) {
                const meta = parsed.meta;
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === 'assistant') {
                    updated[updated.length - 1] = {
                      ...last,
                      knowledgeRefs: meta.knowledge_refs || last.knowledgeRefs,
                      suggestSaveNote: !!meta.suggest_save_note,
                    };
                  }
                  return updated;
                });
              }
            } catch {
              // 非 JSON meta 行，忽略
            }
            return;
          }

          // 普通文本 chunk — 累加到 assistant 消息
          accumulatedContent += data;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: accumulatedContent,
              };
            }
            return updated;
          });
        },
        () => {
          // onDone: [DONE] 标记到达 — 如果用户发了图片，标注 AI 回复
          isDone = true;
          if (userHadImages) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  // 复用 attachments 字段标记"已识别图片内容"
                  attachments: [{ filename: '__image_ocr_tag__', size: 0, type: 'image' }],
                };
              }
              return updated;
            });
          }
        },
        (error) => {
          // onError
          if (error.name === 'AbortError') return; // 用户主动中断，不处理
          // 在 assistant 消息中显示错误
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: accumulatedContent || `⚠️ 请求出错：${error.message}`,
              };
            }
            return updated;
          });
        },
      );
    } catch (error: any) {
      if (error.name === 'AbortError') {
        // 用户主动中断 — 保留已接收的部分内容
        return;
      }
      // 网络错误等
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.role === 'assistant') {
          updated[updated.length - 1] = {
            ...last,
            content: accumulatedContent || `⚠️ 请求出错：${error.message || '未知错误'}`,
          };
        }
        return updated;
      });
    } finally {
      setIsStreaming(false);
      abortController.current = null;
    }
  }, [inputText, isStreaming, messages, selectedLibraries, documentContext, pendingImages]);

  return (
    <>
      {/* ─── 折叠入口按钮（右下角） ─── */}
      {!chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          aria-label="打开聊天"
          style={{
            position: 'fixed',
            right: 28,
            bottom: 28,
            width: 52,
            height: 52,
            borderRadius: '50%',
            border: 'none',
            backgroundColor: 'var(--gt-primary)',
            color: '#fff',
            fontSize: 24,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: 'var(--gt-shadow-lg)',
            zIndex: 10000,
            transition: 'transform 0.2s, box-shadow 0.2s',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.transform = 'scale(1.08)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.transform = 'scale(1)';
          }}
        >
          💬
        </button>
      )}

      {/* ─── 聊天面板 ─── */}
      {chatOpen && (
        <div
          style={{
            position: 'fixed',
            ...(isMaximized
              ? { top: 0, left: 0, right: 0, bottom: 0, width: '100%', height: '100%', borderRadius: 0 }
              : { left: panelX, top: panelY, width: panelW, height: panelH, borderRadius: 'var(--gt-radius-lg)' }
            ),
            backgroundColor: '#fff',
            boxShadow: 'var(--gt-shadow-lg)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            zIndex: 10000,
            border: '1px solid #e8e8e8',
          }}
        >
          {/* ─── 面板头部（可拖动） ─── */}
          <div
            onMouseDown={handleDragStart}
            style={{
              background: 'linear-gradient(135deg, var(--gt-primary) 0%, var(--gt-primary-dark) 100%)',
              padding: 'var(--gt-space-3) var(--gt-space-4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexShrink: 0,
              cursor: isMaximized ? 'default' : 'move',
              userSelect: 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)' }}>
              <span style={{ color: '#fff', fontSize: 'var(--gt-font-base)', fontWeight: 600 }}>
                AI 助手
              </span>
              {currentModel && (
                <span
                  style={{
                    color: 'rgba(255,255,255,0.7)',
                    fontSize: 'var(--gt-font-xs)',
                  }}
                >
                  · {currentModel}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-1)' }}>
              {/* 导出按钮 (11.4) */}
              <button
                onClick={handleToggleExportMode}
                title={exportMode ? '取消导出' : '导出'}
                aria-label={exportMode ? '取消导出' : '导出'}
                disabled={messages.length === 0}
                style={{
                  background: exportMode ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.15)',
                  border: 'none',
                  borderRadius: 'var(--gt-radius-sm)',
                  color: '#fff',
                  fontSize: 16,
                  width: 30,
                  height: 30,
                  cursor: messages.length === 0 ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'background 0.2s',
                  opacity: messages.length === 0 ? 0.5 : 1,
                }}
                onMouseEnter={(e) => {
                  if (messages.length > 0) e.currentTarget.style.background = 'rgba(255,255,255,0.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = exportMode ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.15)';
                }}
              >
                📤
              </button>
              {/* 保存对话按钮 (9.7) */}
              <button
                onClick={handleSaveConversation}
                title={conversationSaved ? '已保存' : '保存对话'}
                aria-label="保存对话"
                disabled={messages.length === 0}
                style={{
                  background: 'rgba(255,255,255,0.15)',
                  border: 'none',
                  borderRadius: 'var(--gt-radius-sm)',
                  color: conversationSaved ? '#90EE90' : '#fff',
                  fontSize: 16,
                  width: 30,
                  height: 30,
                  cursor: messages.length === 0 ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'background 0.2s',
                  opacity: messages.length === 0 ? 0.5 : 1,
                }}
                onMouseEnter={(e) => {
                  if (messages.length > 0) e.currentTarget.style.background = 'rgba(255,255,255,0.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.15)';
                }}
              >
                {conversationSaved ? '✓' : '💾'}
              </button>
              {/* 笔记侧边栏按钮 (9.8) */}
              <button
                onClick={() => setNotesSidebarVisible((v) => !v)}
                title="笔记库"
                aria-label="笔记库"
                style={{
                  background: notesSidebarVisible ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.15)',
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
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = notesSidebarVisible ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.15)';
                }}
              >
                📒
              </button>
              {/* 新建对话按钮 */}
              <button
                onClick={handleNewChat}
                title="新建对话"
                aria-label="新建对话"
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
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.15)';
                }}
              >
                ✏️
              </button>
              {/* 清除对话按钮（双击确认） */}
              <button
                onClick={handleClearChat}
                title={clearConfirm ? '再次点击确认清除' : '清除对话'}
                aria-label="清除对话"
                disabled={messages.length === 0}
                style={{
                  background: clearConfirm ? 'rgba(255,81,73,0.4)' : 'rgba(255,255,255,0.15)',
                  border: 'none',
                  borderRadius: 'var(--gt-radius-sm)',
                  color: clearConfirm ? '#ffcccc' : '#fff',
                  fontSize: 16,
                  width: 30,
                  height: 30,
                  cursor: messages.length === 0 ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'background 0.2s',
                  opacity: messages.length === 0 ? 0.5 : 1,
                }}
                onMouseEnter={(e) => {
                  if (messages.length > 0) e.currentTarget.style.background = clearConfirm ? 'rgba(255,81,73,0.6)' : 'rgba(255,255,255,0.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = clearConfirm ? 'rgba(255,81,73,0.4)' : 'rgba(255,255,255,0.15)';
                }}
              >
                🗑️
              </button>
              {/* 最大化/还原按钮 */}
              <button
                onClick={() => setIsMaximized((v) => !v)}
                title={isMaximized ? '还原窗口' : '最大化'}
                aria-label={isMaximized ? '还原窗口' : '最大化'}
                style={{
                  background: 'rgba(255,255,255,0.15)',
                  border: 'none',
                  borderRadius: 'var(--gt-radius-sm)',
                  color: '#fff',
                  fontSize: 14,
                  width: 30,
                  height: 30,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.15)';
                }}
              >
                {isMaximized ? '⊡' : '⊞'}
              </button>
              {/* 折叠按钮 */}
              <button
                onClick={() => setChatOpen(false)}
                title="收起聊天"
                aria-label="收起聊天"
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
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.15)';
                }}
              >
                ✕
              </button>
            </div>
          </div>

          {/* ─── 消息列表区域 ─── */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: 'var(--gt-space-4)',
              backgroundColor: '#fafafa',
              position: 'relative',
            }}
          >
            {/* ─── 笔记清理提示 Banner (10.2) ─── */}
            {cleanupBanner && !cleanupVisible && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '8px 12px',
                  marginBottom: 'var(--gt-space-3)',
                  backgroundColor: '#fff7e6',
                  border: '1px solid #ffd591',
                  borderRadius: 'var(--gt-radius-md)',
                  fontSize: 'var(--gt-font-xs)',
                  color: '#ad6800',
                }}
              >
                <span>
                  📦 笔记库内容较多（{cleanupBanner.count}条/{cleanupBanner.sizeMB}MB），建议清理
                </span>
                <button
                  onClick={handleShowCleanupSuggestions}
                  style={{
                    background: 'none',
                    border: '1px solid #ad6800',
                    borderRadius: 'var(--gt-radius-sm)',
                    color: '#ad6800',
                    fontSize: 'var(--gt-font-xs)',
                    padding: '2px 8px',
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    marginLeft: 8,
                  }}
                >
                  查看建议
                </button>
              </div>
            )}

            {/* ─── 清理建议列表 Overlay (10.3) ─── */}
            {cleanupVisible && (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  backgroundColor: '#fff',
                  zIndex: 10,
                  display: 'flex',
                  flexDirection: 'column',
                  overflow: 'hidden',
                }}
              >
                {/* 标题栏 */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 16px',
                    borderBottom: '1px solid #e8e8e8',
                    flexShrink: 0,
                  }}
                >
                  <span style={{ fontWeight: 600, fontSize: 'var(--gt-font-sm)' }}>
                    🧹 AI 清理建议
                  </span>
                  <button
                    onClick={() => setCleanupVisible(false)}
                    style={{
                      background: 'none',
                      border: 'none',
                      fontSize: 16,
                      cursor: 'pointer',
                      color: 'var(--gt-text-secondary)',
                    }}
                    aria-label="关闭清理建议"
                  >
                    ✕
                  </button>
                </div>

                {/* 列表内容 */}
                <div style={{ flex: 1, overflowY: 'auto', padding: '8px 16px' }}>
                  {cleanupLoading ? (
                    <div style={{ textAlign: 'center', padding: 32, color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
                      ⏳ AI 正在分析笔记库...
                    </div>
                  ) : cleanupSuggestions.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: 32, color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
                      ✅ 笔记库状态良好，暂无清理建议
                    </div>
                  ) : (
                    cleanupSuggestions.map((s) => (
                      <label
                        key={s.doc_id}
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: 8,
                          padding: '10px 0',
                          borderBottom: '1px solid #f0f0f0',
                          cursor: 'pointer',
                          fontSize: 'var(--gt-font-xs)',
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={cleanupSelected.has(s.doc_id)}
                          onChange={() => {
                            setCleanupSelected((prev) => {
                              const next = new Set(prev);
                              if (next.has(s.doc_id)) next.delete(s.doc_id);
                              else next.add(s.doc_id);
                              return next;
                            });
                          }}
                          style={{ marginTop: 2, flexShrink: 0 }}
                        />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 500, marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {s.title}
                          </div>
                          <div style={{ color: 'var(--gt-text-secondary)', marginBottom: 2 }}>
                            创建: {s.created_at}
                            {s.last_rag_reference && <> · 最后引用: {s.last_rag_reference}</>}
                          </div>
                          <div style={{ color: '#ad6800' }}>
                            💡 {s.reason}
                          </div>
                        </div>
                      </label>
                    ))
                  )}
                </div>

                {/* 底部操作栏 */}
                {cleanupSuggestions.length > 0 && !cleanupLoading && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 16px',
                      borderTop: '1px solid #e8e8e8',
                      flexShrink: 0,
                    }}
                  >
                    <label style={{ fontSize: 'var(--gt-font-xs)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input
                        type="checkbox"
                        checked={cleanupSelected.size === cleanupSuggestions.length && cleanupSuggestions.length > 0}
                        onChange={() => {
                          if (cleanupSelected.size === cleanupSuggestions.length) {
                            setCleanupSelected(new Set());
                          } else {
                            setCleanupSelected(new Set(cleanupSuggestions.map((s) => s.doc_id)));
                          }
                        }}
                      />
                      全选
                    </label>
                    <button
                      onClick={handleCleanupDelete}
                      disabled={cleanupSelected.size === 0 || cleanupDeleting}
                      style={{
                        background: cleanupSelected.size === 0 ? '#d9d9d9' : 'var(--gt-danger, #FF5149)',
                        border: 'none',
                        borderRadius: 'var(--gt-radius-sm)',
                        color: '#fff',
                        fontSize: 'var(--gt-font-xs)',
                        padding: '4px 12px',
                        cursor: cleanupSelected.size === 0 ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {cleanupDeleting ? '删除中...' : `删除选中 (${cleanupSelected.size})`}
                    </button>
                  </div>
                )}
              </div>
            )}
            {messages.length === 0 ? (
              <ChatWelcome onSelectMode={onSelectMode} />
            ) : (
              <>
                {/* 多选导出工具栏 */}
                {exportMode && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      marginBottom: 'var(--gt-space-2)',
                      padding: '6px 10px',
                      backgroundColor: 'rgba(75, 45, 119, 0.06)',
                      borderRadius: 'var(--gt-radius-md)',
                      fontSize: 'var(--gt-font-xs)',
                    }}
                  >
                    <button
                      onClick={handleSelectAll}
                      style={{
                        background: 'none',
                        border: '1px solid var(--gt-primary)',
                        borderRadius: 'var(--gt-radius-sm)',
                        color: 'var(--gt-primary)',
                        fontSize: 'var(--gt-font-xs)',
                        padding: '2px 8px',
                        cursor: 'pointer',
                      }}
                    >
                      全选
                    </button>
                    <button
                      onClick={handleSelectAIOnly}
                      style={{
                        background: 'none',
                        border: '1px solid var(--gt-primary)',
                        borderRadius: 'var(--gt-radius-sm)',
                        color: 'var(--gt-primary)',
                        fontSize: 'var(--gt-font-xs)',
                        padding: '2px 8px',
                        cursor: 'pointer',
                      }}
                    >
                      仅选 AI
                    </button>
                    <span style={{ flex: 1, color: 'var(--gt-text-secondary)' }}>
                      已选 {selectedMsgIds.size} 条
                    </span>
                    <button
                      onClick={handleDeleteSelected}
                      disabled={selectedMsgIds.size === 0}
                      style={{
                        background: selectedMsgIds.size === 0 ? '#d9d9d9' : 'var(--gt-danger, #FF5149)',
                        border: 'none',
                        borderRadius: 'var(--gt-radius-sm)',
                        color: '#fff',
                        fontSize: 'var(--gt-font-xs)',
                        padding: '3px 10px',
                        cursor: selectedMsgIds.size === 0 ? 'not-allowed' : 'pointer',
                      }}
                    >
                      删除选中
                    </button>
                    <button
                      onClick={handleConfirmExport}
                      disabled={selectedMsgIds.size === 0}
                      style={{
                        background: selectedMsgIds.size === 0 ? '#d9d9d9' : 'var(--gt-primary)',
                        border: 'none',
                        borderRadius: 'var(--gt-radius-sm)',
                        color: '#fff',
                        fontSize: 'var(--gt-font-xs)',
                        padding: '3px 10px',
                        cursor: selectedMsgIds.size === 0 ? 'not-allowed' : 'pointer',
                      }}
                    >
                      确认导出
                    </button>
                  </div>
                )}
                <ChatMessageList
                  messages={messages}
                  onSaveNote={handleSaveNote}
                  onUpdateMessage={handleUpdateMessage}
                  onDeleteMessage={handleDeleteMessage}
                  exportMode={exportMode}
                  selectedMsgIds={selectedMsgIds}
                  onToggleSelect={handleToggleSelect}
                  onSelectMode={onSelectMode}
                />
              </>
            )}
          </div>

          {/* ─── 输入区域（ChatInput 组件） ─── */}
          <ChatInput
            inputText={inputText}
            onInputChange={setInputText}
            onSend={handleSend}
            onStop={handleStop}
            isStreaming={isStreaming}
            onSelectMode={onSelectMode}
            selectedLibraries={selectedLibraries}
            onLibrariesChange={setSelectedLibraries}
            onFileUpload={handleFileUpload}
            uploadedFile={uploadedFile}
            onRemoveFile={handleRemoveFile}
            pendingImages={pendingImages}
            onImagesChange={setPendingImages}
          />
          {/* ─── 右下角缩放手柄 ─── */}
          {!isMaximized && (
            <div
              onMouseDown={handleResizeStart}
              style={{
                position: 'absolute',
                right: 0,
                bottom: 0,
                width: 16,
                height: 16,
                cursor: 'nwse-resize',
                zIndex: 10,
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" style={{ opacity: 0.3 }}>
                <path d="M14 16L16 14M10 16L16 10M6 16L16 6" stroke="#666" strokeWidth="1.5" fill="none" />
              </svg>
            </div>
          )}
        </div>
      )}
      {/* ─── 笔记侧边栏 (9.8) ─── */}
      <NotesSidebar
        visible={notesSidebarVisible}
        onClose={() => setNotesSidebarVisible(false)}
      />
      {/* ─── 导出预览面板 (11.5) ─── */}
      {showExportPanel && (
        <ChatExportPanel
          content={exportContent}
          onClose={() => setShowExportPanel(false)}
          onContentChange={setExportContent}
        />
      )}
    </>
  );
};

export default ChatPanel;
