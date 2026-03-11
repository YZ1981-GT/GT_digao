/**
 * AnalysisWorkflow - 文档分析处理工作流容器
 *
 * 四步骤工作流：文档上传与预览 → 分析配置 → 章节框架确认 → 逐章节内容生成与编辑
 * 支持：
 * - 多文档上传、解析缓存、预览和编辑
 * - 分析模式选择（总结分析/整理汇总/生成汇总台账）
 * - 自动生成带注释的章节框架，用户可编辑确认
 * - 逐章节生成内容，引用原文并标注出处
 * - 鼠标悬停出处标注可查看引用原文
 * - 每个章节支持手动编辑、AI修改、重新生成、重置
 */
import React, { useState, useCallback, useMemo, useRef } from 'react';
import ReactDOM from 'react-dom';
import type { AnalysisDocumentInfo, AnalysisChapter, AnalysisSourceRef, AnalysisMode } from '../types/analysis';
import { analysisApi } from '../services/api';
import { processSSEStream } from '../utils/sseParser';
import '../styles/gt-design-tokens.css';

/** 工作流步骤 */
const STEPS = [
  { label: '文档上传与预览', key: 'upload' },
  { label: '分析配置', key: 'config' },
  { label: '章节框架确认', key: 'outline' },
  { label: '逐章节生成与编辑', key: 'content' },
] as const;

const MODE_OPTIONS: Array<{ value: AnalysisMode; label: string; desc: string; wordCount: number }> = [
  { value: 'summary', label: '总结分析', desc: '对上传文档进行总结提炼，提取核心要点', wordCount: 3000 },
  { value: 'consolidation', label: '整理汇总', desc: '对多个文档进行整理汇总，形成统一报告', wordCount: 5000 },
  { value: 'ledger', label: '生成汇总台账', desc: '基于文档内容生成结构化汇总台账', wordCount: 8000 },
];

/** 工作流状态 */
interface WorkflowState {
  documents: AnalysisDocumentInfo[];
  projectId: string;
  mode: AnalysisMode;
  customInstruction: string;
  targetWordCount: number;
  outline: AnalysisChapter[];
  chapterContents: Record<string, { content: string; sources: AnalysisSourceRef[] }>;
  chapterStatuses: Record<string, 'pending' | 'generating' | 'done' | 'error'>;
}

type ChapterStatus = 'pending' | 'generating' | 'done' | 'error';

/** 扁平化章节列表 */
function flattenChapters(chapters: AnalysisChapter[]): AnalysisChapter[] {
  const result: AnalysisChapter[] = [];
  const walk = (list: AnalysisChapter[]) => {
    for (const ch of list) {
      if (ch.children && ch.children.length > 0) {
        walk(ch.children);
      } else {
        result.push(ch);
      }
    }
  };
  walk(chapters);
  return result;
}

const AnalysisWorkflow: React.FC = () => {
  const [currentStep, setCurrentStep] = useState(0);
  const [state, setState] = useState<WorkflowState>({
    documents: [],
    projectId: '',
    mode: 'summary',
    customInstruction: '',
    targetWordCount: 3000,
    outline: [],
    chapterContents: {},
    chapterStatuses: {},
  });
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [uploadMessages, setUploadMessages] = useState<Record<string, string>>({});

  /** 上传进度弹窗状态 */
  interface UploadFileProgress {
    name: string;
    size: number;
    status: 'waiting' | 'uploading' | 'parsing' | 'done' | 'error';
    message?: string;
  }
  const [uploadProgress, setUploadProgress] = useState<UploadFileProgress[]>([]);
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [outlineGenerating, setOutlineGenerating] = useState(false);
  const [outlineRaw, setOutlineRaw] = useState('');
  const [previewDocId, setPreviewDocId] = useState<string | null>(null);
  const [editingDocContent, setEditingDocContent] = useState('');
  const [streamingContents, setStreamingContents] = useState<Record<string, string>>({});
  const [editingChapterId, setEditingChapterId] = useState<string | null>(null);
  const [formatting, setFormatting] = useState(false);
  const [formatStreamContent, setFormatStreamContent] = useState('');
  const [aiReviseChapterId, setAiReviseChapterId] = useState<string | null>(null);
  const [aiInstruction, setAiInstruction] = useState('');
  const [aiProcessing, setAiProcessing] = useState(false);
  const [generateMode, setGenerateMode] = useState<'idle' | 'sequential'>('idle');
  const [progressMessage, setProgressMessage] = useState('');
  const [expandedChapters, setExpandedChapters] = useState<Set<string>>(new Set());
  /** 原始解析文本（上传时的文本，用于源文档预览对照） */
  const [originalParsedText, setOriginalParsedText] = useState<Record<string, string>>({});
  /** 双向高亮：当前选中的段落索引和来源面板 */
  const [highlightState, setHighlightState] = useState<{ index: number; side: 'left' | 'right' } | null>(null);
  /** 预览模式：'dual'=双栏对照, 'pdf'=PDF原件+文本 */
  const [previewMode, setPreviewMode] = useState<'dual' | 'pdf'>('dual');
  /** 右侧段落内联编辑 */
  const [editingParaIndex, setEditingParaIndex] = useState<number | null>(null);
  const [editingParaText, setEditingParaText] = useState('');
  const leftPanelRef = useRef<HTMLDivElement>(null);
  const rightPanelRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const stopRequestedRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  /** PDF 页面图片模式状态 */
  const [pdfPageCount, setPdfPageCount] = useState(0);
  const [activePageNum, setActivePageNum] = useState<number | null>(null);
  const pdfLeftRef = useRef<HTMLDivElement>(null);
  const pdfRightRef = useRef<HTMLDivElement>(null);

  const leafChapters = useMemo(() => flattenChapters(state.outline), [state.outline]);

  // ─── Step 1: 文档上传 ───
  const handleFileUpload = useCallback(async (files: FileList | File[]) => {
    if (!files || files.length === 0) return;
    const fileArray = Array.from(files);

    // 初始化进度列表并弹出对话框
    const initialProgress = fileArray.map(f => ({
      name: f.name,
      size: f.size,
      status: 'waiting' as const,
    }));
    setUploadProgress(initialProgress);
    setShowUploadDialog(true);
    setUploading(true);
    setError('');

    for (let i = 0; i < fileArray.length; i++) {
      // 标记当前文件为上传中
      setUploadProgress(prev => prev.map((p, idx) =>
        idx === i ? { ...p, status: 'uploading' } : p
      ));

      try {
        // 上传完成后进入解析阶段
        setUploadProgress(prev => prev.map((p, idx) =>
          idx === i ? { ...p, status: 'parsing', message: '解析中（含OCR识别）...' } : p
        ));

        const res = await analysisApi.upload(fileArray[i]);
        const doc = res.data?.document;
        const msg = res.data?.message || '';

        if (doc) {
          setState(prev => ({ ...prev, documents: [...prev.documents, doc] }));
          if (msg) setUploadMessages(prev => ({ ...prev, [doc.id]: msg }));
          setUploadProgress(prev => prev.map((p, idx) =>
            idx === i ? { ...p, status: 'done', message: msg || `${doc.content_text.length} 字` } : p
          ));
        } else {
          setUploadProgress(prev => prev.map((p, idx) =>
            idx === i ? { ...p, status: 'error', message: '解析返回为空' } : p
          ));
        }
      } catch (err: any) {
        setUploadProgress(prev => prev.map((p, idx) =>
          idx === i ? { ...p, status: 'error', message: err.message || '上传失败' } : p
        ));
      }
    }
    setUploading(false);
  }, []);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files);
    }
    e.target.value = '';
  }, [handleFileUpload]);

  const handleDeleteDoc = useCallback(async (docId: string) => {
    try {
      await analysisApi.deleteDocument(docId);
      setState(prev => ({
        ...prev,
        documents: prev.documents.filter(d => d.id !== docId),
      }));
      if (previewDocId === docId) setPreviewDocId(null);
    } catch (err: any) {
      setError(err.message);
    }
  }, [previewDocId]);

  const handlePreviewDoc = useCallback((docId: string) => {
    const doc = state.documents.find(d => d.id === docId);
    if (doc) {
      setPreviewDocId(docId);
      setEditingDocContent(doc.content_text);
      setHighlightState(null);
      setEditingParaIndex(null);
      // PDF 文件默认使用 PDF 原件预览模式
      setPreviewMode(doc.file_format === '.pdf' ? 'pdf' : 'dual');
      // 保存原始解析文本（首次打开时记录，后续编辑不影响）
      setOriginalParsedText(prev => prev[docId] ? prev : { ...prev, [docId]: doc.content_text });
      // PDF 文件加载页数
      setActivePageNum(null);
      setPdfPageCount(0);
      if (doc.file_format === '.pdf') {
        const API_BASE = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');
        fetch(`${API_BASE}/api/analysis/document/${docId}/pages`)
          .then(r => r.json())
          .then(data => { if (data.success) setPdfPageCount(data.page_count); })
          .catch(() => {});
      }
    }
  }, [state.documents]);

  const handleSaveDocContent = useCallback(async () => {
    if (!previewDocId) return;
    try {
      await analysisApi.updateDocument(previewDocId, editingDocContent);
      setState(prev => ({
        ...prev,
        documents: prev.documents.map(d =>
          d.id === previewDocId ? { ...d, content_text: editingDocContent } : d
        ),
      }));
      setPreviewDocId(null);
    } catch (err: any) {
      setError(err.message);
    }
  }, [previewDocId, editingDocContent]);

  // ─── 排版处理：调用后端 本地脚本+LLM 将文本整理为 Markdown ───
  const [formatPhase, setFormatPhase] = useState('');
  const handleFormatDocument = useCallback(async () => {
    if (!previewDocId) return;
    setFormatting(true);
    setFormatStreamContent('');
    setFormatPhase('正在进行本地排版处理...');
    setError('');

    try {
      const API_BASE_URL =
        process.env.REACT_APP_API_URL ||
        (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

      const response = await fetch(`${API_BASE_URL}/api/analysis/format-document/${previewDocId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `排版处理失败: ${response.status}`);
      }

      let finalContent = '';

      await processSSEStream(
        response,
        (data) => {
          try {
            const event = JSON.parse(data);
            if (event.status === 'phase') {
              setFormatPhase(event.message || '');
            } else if (event.status === 'streaming') {
              finalContent += event.content || '';
              setFormatStreamContent(prev => prev + (event.content || ''));
              if (formatPhase.includes('本地')) {
                setFormatPhase('AI 精细化整理中...');
              }
            } else if (event.status === 'completed' && event.content) {
              finalContent = event.content;
            } else if (event.status === 'error') {
              setError(event.message || '排版处理失败');
            }
          } catch { /* ignore */ }
        },
        () => {
          if (finalContent) {
            setEditingDocContent(finalContent);
            setFormatStreamContent('');
          }
          setFormatting(false);
          setFormatPhase('');
        },
        (err) => {
          setError(err.message);
          setFormatting(false);
          setFormatStreamContent('');
          setFormatPhase('');
        },
      );
    } catch (err: any) {
      setError(err.message);
      setFormatting(false);
      setFormatStreamContent('');
      setFormatPhase('');
    }
  }, [previewDocId, formatPhase]);

  // ─── Step 2→3: 创建项目并生成框架 ───
  const handleGenerateOutline = useCallback(async () => {
    setError('');
    setOutlineGenerating(true);
    setOutlineRaw('');

    try {
      // 创建项目（如果还没有）
      let projectId = state.projectId;
      if (!projectId) {
        const res = await analysisApi.createProject(state.documents.map(d => d.id));
        projectId = res.data?.project_id;
        if (!projectId) throw new Error('创建项目失败');
        setState(prev => ({ ...prev, projectId }));
      }

      // SSE 流式生成框架
      const response = await analysisApi.generateOutline({
        project_id: projectId,
        mode: state.mode,
        custom_instruction: state.customInstruction || undefined,
        target_word_count: state.targetWordCount,
      });

      if (!response.ok) throw new Error(`生成失败: ${response.status}`);

      let outlineData: AnalysisChapter[] = [];

      await processSSEStream(
        response,
        (data) => {
          try {
            const event = JSON.parse(data);
            if (event.status === 'streaming') {
              setOutlineRaw(prev => prev + (event.content || ''));
            } else if (event.status === 'completed' && event.outline) {
              outlineData = event.outline;
            } else if (event.status === 'error') {
              setError(event.message || '生成失败');
            }
          } catch { /* ignore */ }
        },
        () => {
          if (outlineData.length > 0) {
            setState(prev => ({ ...prev, outline: outlineData }));
            setCurrentStep(2);
          }
          setOutlineGenerating(false);
        },
        (err) => {
          setError(err.message);
          setOutlineGenerating(false);
        },
      );
    } catch (err: any) {
      setError(err.message);
      setOutlineGenerating(false);
    }
  }, [state.projectId, state.documents, state.mode, state.customInstruction, state.targetWordCount]);

  // ─── Step 3: 确认框架 ───
  const handleConfirmOutline = useCallback(async () => {
    if (!state.projectId || state.outline.length === 0) return;
    setError('');
    try {
      const toDict = (chapters: AnalysisChapter[]): any[] =>
        chapters.map(ch => ({
          id: ch.id,
          title: ch.title,
          annotation: ch.annotation,
          target_word_count: ch.target_word_count,
          children: ch.children ? toDict(ch.children) : [],
        }));

      await analysisApi.confirmOutline({
        project_id: state.projectId,
        outline: toDict(state.outline),
      });
      setCurrentStep(3);
    } catch (err: any) {
      setError(err.message);
    }
  }, [state.projectId, state.outline]);

  // ─── Step 4: 生成单章节内容（支持 AbortSignal） ───
  const generateOneChapter = useCallback(async (chapterId: string, signal?: AbortSignal): Promise<string> => {
    if (!state.projectId) throw new Error('项目未创建');

    setState(prev => ({
      ...prev,
      chapterStatuses: { ...prev.chapterStatuses, [chapterId]: 'generating' as ChapterStatus },
    }));
    setStreamingContents(prev => ({ ...prev, [chapterId]: '' }));
    setExpandedChapters(prev => new Set(prev).add(chapterId));

    let finalContent = '';
    let sources: AnalysisSourceRef[] = [];

    const response = await analysisApi.generateChapter({
      project_id: state.projectId,
      chapter_id: chapterId,
    }, signal);

    if (!response.ok) throw new Error(`生成失败: ${response.status}`);

    await processSSEStream(
      response,
      (data) => {
        try {
          const event = JSON.parse(data);
          if (event.status === 'streaming') {
            finalContent += event.content || '';
            setStreamingContents(prev => ({
              ...prev,
              [chapterId]: (prev[chapterId] || '') + (event.content || ''),
            }));
          } else if (event.status === 'completed') {
            if (event.content) finalContent = event.content;
            if (event.sources) sources = event.sources;
          } else if (event.status === 'error') {
            throw new Error(event.message || '生成失败');
          }
        } catch (e: any) {
          if (e.message && e.message !== '生成失败') { /* JSON parse error */ } else if (e.message) throw e;
        }
      },
      undefined,
      (err) => { throw err; },
    );

    if (finalContent) {
      setState(prev => ({
        ...prev,
        chapterContents: {
          ...prev.chapterContents,
          [chapterId]: { content: finalContent, sources },
        },
        chapterStatuses: { ...prev.chapterStatuses, [chapterId]: 'done' as ChapterStatus },
      }));
      setStreamingContents(prev => { const n = { ...prev }; delete n[chapterId]; return n; });
    } else {
      throw new Error('未获取到内容');
    }

    return finalContent;
  }, [state.projectId]);

  const handleGenerateChapter = useCallback(async (chapterId: string) => {
    setError('');
    try {
      await generateOneChapter(chapterId);
    } catch (err: any) {
      setError(err.message);
      setState(prev => ({
        ...prev,
        chapterStatuses: { ...prev.chapterStatuses, [chapterId]: 'error' as ChapterStatus },
      }));
      setStreamingContents(prev => { const n = { ...prev }; delete n[chapterId]; return n; });
    }
  }, [generateOneChapter]);

  const handleResetChapter = useCallback((chapterId: string) => {
    setState(prev => {
      const newContents = { ...prev.chapterContents };
      delete newContents[chapterId];
      const newStatuses = { ...prev.chapterStatuses };
      delete newStatuses[chapterId];
      return { ...prev, chapterContents: newContents, chapterStatuses: newStatuses };
    });
  }, []);

  const handleUpdateChapterContent = useCallback((chapterId: string, content: string) => {
    setState(prev => ({
      ...prev,
      chapterContents: {
        ...prev.chapterContents,
        [chapterId]: { ...prev.chapterContents[chapterId], content, sources: prev.chapterContents[chapterId]?.sources || [] },
      },
    }));
  }, []);

  // ─── 章节框架编辑辅助 ───
  const updateOutlineItem = useCallback((chapterId: string, patch: Partial<AnalysisChapter>) => {
    const update = (items: AnalysisChapter[]): AnalysisChapter[] =>
      items.map(ch => {
        if (ch.id === chapterId) return { ...ch, ...patch };
        if (ch.children) return { ...ch, children: update(ch.children) };
        return ch;
      });
    setState(prev => ({ ...prev, outline: update(prev.outline) }));
  }, []);

  const deleteOutlineItem = useCallback((chapterId: string) => {
    const remove = (items: AnalysisChapter[]): AnalysisChapter[] =>
      items.filter(ch => ch.id !== chapterId).map(ch => ({
        ...ch,
        children: ch.children ? remove(ch.children) : ch.children,
      }));
    setState(prev => ({ ...prev, outline: remove(prev.outline) }));
  }, []);

  // ─── Navigation ───
  const handleNext = useCallback(() => {
    if (currentStep === 1) {
      handleGenerateOutline();
      return;
    }
    if (currentStep === 2) {
      handleConfirmOutline();
      return;
    }
    setCurrentStep(prev => Math.min(prev + 1, STEPS.length - 1));
  }, [currentStep, handleGenerateOutline, handleConfirmOutline]);

  const handlePrev = useCallback(() => {
    setCurrentStep(prev => Math.max(prev - 1, 0));
  }, []);

  const canProceed = (): boolean => {
    switch (currentStep) {
      case 0: return state.documents.length > 0;
      case 1: return state.documents.length > 0 && !outlineGenerating;
      case 2: return state.outline.length > 0;
      default: return false;
    }
  };

  // ─── 引用来源悬浮提示组件（上标样式 + Portal 顶层渲染） ───
  const SourceBadge: React.FC<{ docNames: string[]; sources: AnalysisSourceRef[] }> = ({ docNames, sources }) => {
    const [show, setShow] = useState(false);
    const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
    const badgeRef = useRef<HTMLSpanElement>(null);
    const uniqueNames = docNames.filter((v, i, a) => a.indexOf(v) === i);

    const handleEnter = () => {
      if (badgeRef.current) {
        const rect = badgeRef.current.getBoundingClientRect();
        setPos({
          top: rect.top + window.scrollY - 8,
          left: Math.min(rect.right + window.scrollX, window.innerWidth - 420),
        });
      }
      setShow(true);
    };

    const tooltip = show ? ReactDOM.createPortal(
      <div
        style={{
          position: 'absolute',
          top: pos.top,
          left: pos.left,
          transform: 'translateY(-100%)',
          zIndex: 99999,
          width: 400,
          maxHeight: 280,
          overflow: 'auto',
          padding: '12px',
          backgroundColor: '#fff',
          border: '1px solid #ddd',
          borderRadius: '8px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
          fontSize: '13px',
          lineHeight: 1.6,
          color: '#333',
        }}
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
      >
        {sources.length > 0 ? sources.map((source, idx) => (
          <div key={idx} style={{ marginBottom: idx < sources.length - 1 ? 10 : 0 }}>
            <div style={{ fontWeight: 600, color: 'var(--gt-primary)', marginBottom: 3 }}>
              📄 {source.doc_name}
            </div>
            <div style={{
              color: '#555',
              whiteSpace: 'pre-wrap',
              fontSize: '12px',
              backgroundColor: '#f8f6ff',
              padding: '6px 8px',
              borderRadius: '4px',
              borderLeft: '3px solid var(--gt-primary)',
            }}>
              {source.excerpt || '（无具体引用片段）'}
            </div>
          </div>
        )) : (
          <div style={{ color: '#888' }}>来源：{uniqueNames.join('、')}</div>
        )}
      </div>,
      document.body
    ) : null;

    return (
      <span
        ref={badgeRef}
        style={{ position: 'relative', display: 'inline-block', verticalAlign: 'super' }}
        onMouseEnter={handleEnter}
        onMouseLeave={() => setShow(false)}
      >
        <span
          style={{
            color: 'var(--gt-primary)',
            cursor: 'pointer',
            fontSize: '11px',
            fontWeight: 500,
            backgroundColor: 'var(--gt-primary-light, #f0e6ff)',
            borderRadius: '3px',
            padding: '1px 4px',
            marginLeft: '2px',
            lineHeight: 1,
          }}
        >
          📎{uniqueNames.length > 1 ? `${uniqueNames.length}源` : uniqueNames[0]?.replace(/\.pdf$/i, '').slice(-8)}
        </span>
        {tooltip}
      </span>
    );
  };

  /** 渲染内容：每段末尾右上角统一标注来源 */
  const renderContentWithSources = (content: string, sources: AnalysisSourceRef[]) => {
    if (!content) return null;

    // 按段落分割
    const paragraphs = content.split(/\n{1,}/).map(p => p.trim()).filter(p => p.length > 0);

    // 后端按标注出现顺序生成 sources 数组，这里用全局计数器按序消费
    let sourceIdx = 0;

    return (
      <div style={{ lineHeight: 1.8, fontSize: 'var(--gt-font-base)' }}>
        {paragraphs.map((para, i) => {
          // 统计该段中 [来源：xxx] 标记的数量（每个标记对应一个 source 条目）
          const tagMatches: RegExpExecArray[] = [];
          const tagRe = /\[来源[：:]\s*([^\]]+)\]/g;
          let _tm: RegExpExecArray | null;
          while ((_tm = tagRe.exec(para)) !== null) { tagMatches.push(_tm); }
          // 收集该段对应的 sources
          const paraSourceList: AnalysisSourceRef[] = [];
          const docNames: string[] = [];
          for (const tm of tagMatches) {
            const names = tm[1].split(/[、,，]/).map((n: string) => n.trim()).filter(Boolean);
            for (const name of names) {
              docNames.push(name);
              if (sourceIdx < sources.length) {
                paraSourceList.push(sources[sourceIdx]);
                sourceIdx++;
              }
            }
          }

          const cleanText = para.replace(/\s*\[来源[：:][^\]]+\]/g, '').trim();
          if (!cleanText) return null;

          return (
            <p key={i} style={{ margin: '0 0 8px 0', position: 'relative' }}>
              {cleanText}
              {paraSourceList.length > 0 && (
                <SourceBadge docNames={docNames} sources={paraSourceList} />
              )}
            </p>
          );
        })}
      </div>
    );
  };

  // ─── 段落分割与双向匹配工具 ───
  /** 将文本按段落分割（以空行或页码标记为分隔） */
  const splitParagraphs = useCallback((text: string): string[] => {
    if (!text) return [];
    // 按连续空行或 "--- 第 N 页 ---" 分割
    const raw = text.split(/\n{2,}|(?=\n--- 第 \d+ 页 ---)/);
    return raw.map(p => p.trim()).filter(p => p.length > 0);
  }, []);

  /** 简单文本相似度（基于共同字符比例） */
  const textSimilarity = useCallback((a: string, b: string): number => {
    if (!a || !b) return 0;
    const sa = a.replace(/\s+/g, '').slice(0, 200);
    const sb = b.replace(/\s+/g, '').slice(0, 200);
    if (sa === sb) return 1;
    if (sa.length === 0 || sb.length === 0) return 0;
    // 计算共同子串字符数
    let common = 0;
    const shorter = sa.length <= sb.length ? sa : sb;
    const longer = sa.length > sb.length ? sa : sb;
    for (let i = 0; i < shorter.length; i++) {
      if (longer.includes(shorter[i])) common++;
    }
    return common / Math.max(sa.length, sb.length);
  }, []);

  /** 在目标段落列表中找到与 sourceParagraph 最匹配的索引 */
  const findBestMatch = useCallback((sourceParagraph: string, targetParagraphs: string[]): number => {
    if (targetParagraphs.length === 0) return -1;
    let bestIdx = 0;
    let bestScore = 0;
    for (let i = 0; i < targetParagraphs.length; i++) {
      const score = textSimilarity(sourceParagraph, targetParagraphs[i]);
      if (score > bestScore) {
        bestScore = score;
        bestIdx = i;
      }
    }
    return bestScore > 0.3 ? bestIdx : -1;
  }, [textSimilarity]);

  /** 提交段落内联编辑 */
  const commitParaEdit = useCallback(() => {
    if (editingParaIndex === null) return;
    const rightParas = splitParagraphs(editingDocContent);
    if (editingParaIndex < rightParas.length) {
      rightParas[editingParaIndex] = editingParaText;
      setEditingDocContent(rightParas.join('\n\n'));
    }
    setEditingParaIndex(null);
    setEditingParaText('');
  }, [editingParaIndex, editingParaText, editingDocContent, splitParagraphs]);

  /** 点击段落时的双向高亮处理 */
  const handleParagraphClick = useCallback((index: number, side: 'left' | 'right') => {
    if (!previewDocId) return;
    // 如果正在内联编辑，先保存
    if (editingParaIndex !== null) {
      commitParaEdit();
    }
    const origText = originalParsedText[previewDocId] || '';
    const leftParas = splitParagraphs(origText);
    const rightParas = splitParagraphs(editingDocContent);

    setHighlightState({ index, side });

    if (side === 'left') {
      const matchIdx = findBestMatch(leftParas[index], rightParas);
      if (matchIdx >= 0 && rightPanelRef.current) {
        const el = rightPanelRef.current.querySelector(`[data-para-idx="${matchIdx}"]`);
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    } else {
      const matchIdx = findBestMatch(rightParas[index], leftParas);
      if (matchIdx >= 0 && leftPanelRef.current) {
        const el = leftPanelRef.current.querySelector(`[data-para-idx="${matchIdx}"]`);
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [previewDocId, originalParsedText, editingDocContent, splitParagraphs, findBestMatch, editingParaIndex, commitParaEdit]);

  /** 双击右侧段落进入内联编辑 */
  const handleParaDoubleClick = useCallback((index: number, text: string) => {
    setEditingParaIndex(index);
    setEditingParaText(text);
  }, []);

  /** 将文本按页分组（根据 "--- 第 N 页 ---" 标记） */
  const splitByPages = useCallback((text: string): { pageNum: number; content: string }[] => {
    if (!text) return [];
    const pagePattern = /--- 第 (\d+) 页 ---/g;
    const pages: { pageNum: number; content: string }[] = [];
    let lastIdx = 0;
    let lastPage = 0;
    let match;

    while ((match = pagePattern.exec(text)) !== null) {
      // 保存上一段（如果有内容）
      if (lastIdx > 0 || match.index > 0) {
        const content = text.slice(lastIdx, match.index).trim();
        if (content && lastPage > 0) {
          pages.push({ pageNum: lastPage, content });
        }
      }
      lastPage = parseInt(match[1], 10);
      lastIdx = match.index + match[0].length;
    }
    // 最后一页
    if (lastPage > 0) {
      const content = text.slice(lastIdx).trim();
      if (content) {
        pages.push({ pageNum: lastPage, content });
      }
    }
    // 如果没有页码标记，整体作为第1页
    if (pages.length === 0 && text.trim()) {
      pages.push({ pageNum: 1, content: text.trim() });
    }
    return pages;
  }, []);

  /** PDF 模式：点击左侧页面图片，右侧滚动到对应页文本 */
  const handlePdfPageClick = useCallback((pageNum: number) => {
    setActivePageNum(pageNum);
    // 滚动右侧到对应页
    if (pdfRightRef.current) {
      const el = pdfRightRef.current.querySelector(`[data-page-num="${pageNum}"]`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, []);

  /** PDF 模式：点击右侧页文本，左侧滚动到对应页图片 */
  const handlePdfTextPageClick = useCallback((pageNum: number) => {
    setActivePageNum(pageNum);
    // 滚动左侧到对应页
    if (pdfLeftRef.current) {
      const el = pdfLeftRef.current.querySelector(`[data-page-num="${pageNum}"]`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, []);

  // ─── Step 1 渲染：文档上传与预览 ───
  const renderUploadStep = () => (
    <div>
      {/* 隐藏的文件输入 - 放在上传区域外面 */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.doc,.docx,.xlsx,.xls,.txt,.md,.jpg,.jpeg,.png,.tiff,.tif,.bmp,.webp"
        onChange={handleInputChange}
        style={{ display: 'none' }}
        aria-hidden="true"
      />

      <div
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          const files = e.dataTransfer.files;
          if (files.length > 0) {
            handleFileUpload(files);
          }
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') fileInputRef.current?.click(); }}
        style={{
          border: '2px dashed #d0d0d0',
          borderRadius: 'var(--gt-radius-md)',
          padding: 'var(--gt-space-6)',
          textAlign: 'center',
          cursor: 'pointer',
          backgroundColor: '#fafafa',
          marginBottom: 'var(--gt-space-4)',
          transition: 'border-color 0.2s',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--gt-primary)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#d0d0d0'; }}
      >
        <div style={{ fontSize: 36, marginBottom: 8 }}>📁</div>
        <div style={{ fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-primary)', fontWeight: 600 }}>
          {uploading ? '上传中...' : '点击或拖拽上传文档'}
        </div>
        <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginTop: 4 }}>
          支持 PDF、Word、Excel、TXT、Markdown、图片（JPG/PNG/TIFF/BMP），可上传多个文档
        </div>
      </div>

      {/* 已上传文档列表 */}
      {state.documents.length > 0 && (
        <div>
          <div style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, marginBottom: 'var(--gt-space-2)' }}>
            已上传文档 ({state.documents.length})
          </div>
          {state.documents.map(doc => (
            <div
              key={doc.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--gt-space-3)',
                padding: 'var(--gt-space-3)',
                border: '1px solid #e8e8e8',
                borderRadius: 'var(--gt-radius-sm)',
                marginBottom: 'var(--gt-space-2)',
                backgroundColor: '#fff',
              }}
            >
              <span style={{ fontSize: 20 }}>
                {doc.file_format === '.pdf' ? '📕' : doc.file_format.includes('xls') ? '📊' : '📄'}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {doc.filename}
                </div>
                <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
                  {(doc.file_size / 1024).toFixed(1)} KB · {doc.content_text.length} 字
                  {doc.parse_status !== 'success' && <span style={{ color: '#dc2626' }}> · 解析异常</span>}
                  {uploadMessages[doc.id] && uploadMessages[doc.id].includes('OCR') && (
                    <span style={{ color: 'var(--gt-primary)' }}> · {uploadMessages[doc.id].match(/OCR: ([^）]+)/)?.[1] || 'OCR'}</span>
                  )}
                </div>
              </div>
              <button
                className="gt-button gt-button--secondary"
                style={{ padding: '2px 10px', fontSize: 12 }}
                onClick={() => handlePreviewDoc(doc.id)}
              >
                预览编辑
              </button>
              <button
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#999', fontSize: 16, padding: 4 }}
                onClick={() => handleDeleteDoc(doc.id)}
                aria-label={`删除 ${doc.filename}`}
                title="删除"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 文档预览编辑弹窗 */}
      {previewDocId && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 100,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 'var(--gt-space-4)',
          }}
          role="dialog"
          aria-modal="true"
        >
          <div className="gt-card" style={{ width: '95%', maxWidth: 1400, height: '90vh', display: 'flex', flexDirection: 'column' }}>
            <div className="gt-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-3)' }}>
                <h3 className="gt-h4" style={{ margin: 0 }}>
                  文档预览与编辑 - {state.documents.find(d => d.id === previewDocId)?.filename}
                </h3>
                {/* 预览模式切换 */}
                {(() => {
                  const doc = state.documents.find(d => d.id === previewDocId);
                  const isPdf = doc?.file_format === '.pdf';
                  const isImage = ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'].includes(doc?.file_format || '');
                  if (!isPdf && !isImage) return null;
                  return (
                    <div style={{ display: 'flex', gap: 2, backgroundColor: '#f3f4f6', borderRadius: 'var(--gt-radius-sm)', padding: 2 }}>
                      <button
                        onClick={() => setPreviewMode('dual')}
                        style={{
                          padding: '3px 10px', fontSize: 12, border: 'none', borderRadius: 'var(--gt-radius-sm)', cursor: 'pointer',
                          backgroundColor: previewMode === 'dual' ? '#fff' : 'transparent',
                          color: previewMode === 'dual' ? 'var(--gt-primary)' : 'var(--gt-text-secondary)',
                          fontWeight: previewMode === 'dual' ? 600 : 400,
                          boxShadow: previewMode === 'dual' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                        }}
                      >文本对照</button>
                      <button
                        onClick={() => setPreviewMode('pdf')}
                        style={{
                          padding: '3px 10px', fontSize: 12, border: 'none', borderRadius: 'var(--gt-radius-sm)', cursor: 'pointer',
                          backgroundColor: previewMode === 'pdf' ? '#fff' : 'transparent',
                          color: previewMode === 'pdf' ? 'var(--gt-primary)' : 'var(--gt-text-secondary)',
                          fontWeight: previewMode === 'pdf' ? 600 : 400,
                          boxShadow: previewMode === 'pdf' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                        }}
                      >{isPdf ? '📄 PDF原件' : '🖼️ 原图'}</button>
                    </div>
                  );
                })()}
              </div>
              <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
                <button
                  className="gt-button"
                  style={{
                    padding: '4px 14px', fontSize: 13,
                    backgroundColor: formatting ? '#e8e8e8' : '#f0eaff',
                    color: formatting ? '#999' : 'var(--gt-primary)',
                    border: `1px solid ${formatting ? '#ddd' : 'var(--gt-primary)'}`,
                    borderRadius: 'var(--gt-radius-sm)',
                    cursor: formatting ? 'not-allowed' : 'pointer',
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                  }}
                  onClick={handleFormatDocument}
                  disabled={formatting}
                  title="使用AI将文本整理为标准Markdown格式"
                >
                  {formatting && (
                    <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid #ccc', borderTopColor: 'var(--gt-primary)', borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite' }} />
                  )}
                  {formatting ? '排版中...' : '📝 排版处理'}
                </button>
                <button className="gt-button gt-button--primary" onClick={handleSaveDocContent} disabled={formatting}>保存</button>
                <button className="gt-button gt-button--secondary" onClick={() => { setPreviewDocId(null); setFormatStreamContent(''); setFormatting(false); setFormatPhase(''); setHighlightState(null); }}>关闭</button>
              </div>
            </div>
            <div className="gt-card-content" style={{ flex: 1, overflow: 'hidden', padding: 'var(--gt-space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-3)' }}>
              {/* 排版处理流式预览 */}
              {formatting && (formatStreamContent || formatPhase) && (
                <div style={{
                  padding: 'var(--gt-space-3)',
                  backgroundColor: '#f9f7fc',
                  border: '1px solid #e8dff5',
                  borderRadius: 'var(--gt-radius-sm)',
                  maxHeight: 120,
                  overflow: 'auto',
                  flexShrink: 0,
                }}>
                  <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-primary)', fontWeight: 600, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ display: 'inline-block', width: 10, height: 10, border: '2px solid #e0e0e0', borderTopColor: 'var(--gt-primary)', borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite' }} />
                    {formatPhase || 'AI 排版处理中...'}
                  </div>
                  <pre style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)', whiteSpace: 'pre-wrap', lineHeight: 1.6, margin: 0, fontFamily: 'var(--gt-font-cn)' }}>
                    {formatStreamContent}
                  </pre>
                </div>
              )}

              {/* ─── 双栏对照区域 ─── */}
              <div style={{ flex: 1, display: 'flex', gap: 'var(--gt-space-3)', overflow: 'hidden', minHeight: 0 }}>
                {/* 左侧：源文档预览 */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, border: '1px solid #e5e7eb', borderRadius: 'var(--gt-radius-sm)', overflow: 'hidden' }}>
                  <div style={{ padding: '8px 12px', backgroundColor: '#f8f9fa', borderBottom: '1px solid #e5e7eb', fontSize: 'var(--gt-font-xs)', fontWeight: 600, color: 'var(--gt-text-secondary)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
                    📄 源文档内容
                    <span style={{ fontWeight: 400, color: '#9ca3af' }}>（点击段落可定位右侧对应内容）</span>
                  </div>
                  {previewMode === 'pdf' && (() => {
                    const doc = state.documents.find(d => d.id === previewDocId);
                    const isPdf = doc?.file_format === '.pdf';
                    const isImage = ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'].includes(doc?.file_format || '');
                    return isPdf || isImage;
                  })() ? (
                    /* PDF 按页图片预览（支持与右侧文本的页级映射） */
                    <div ref={pdfLeftRef} style={{ flex: 1, overflow: 'auto', padding: 'var(--gt-space-2)' }}>
                      {(() => {
                        const doc = state.documents.find(d => d.id === previewDocId);
                        const isImage = ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'].includes(doc?.file_format || '');
                        const API_BASE = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

                        if (isImage) {
                          return (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 'var(--gt-space-3)', backgroundColor: '#f8f9fa' }}>
                              <img
                                src={`${API_BASE}/api/analysis/document/${previewDocId}/original`}
                                alt="原始图片"
                                style={{ maxWidth: '100%', objectFit: 'contain' }}
                              />
                            </div>
                          );
                        }

                        // PDF：按页渲染图片
                        if (pdfPageCount === 0) {
                          return (
                            <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)' }}>
                              <div style={{ display: 'inline-block', width: 16, height: 16, border: '2px solid #ccc', borderTopColor: 'var(--gt-primary)', borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite' }} />
                              <div style={{ marginTop: 8, fontSize: 'var(--gt-font-sm)' }}>正在加载 PDF 页面...</div>
                            </div>
                          );
                        }

                        return Array.from({ length: pdfPageCount }, (_, i) => i + 1).map(pageNum => (
                          <div
                            key={pageNum}
                            data-page-num={pageNum}
                            onClick={() => handlePdfPageClick(pageNum)}
                            style={{
                              marginBottom: 'var(--gt-space-3)',
                              cursor: 'pointer',
                              border: activePageNum === pageNum ? '2px solid var(--gt-primary)' : '1px solid #e5e7eb',
                              borderRadius: 'var(--gt-radius-sm)',
                              overflow: 'hidden',
                              transition: 'border-color 0.2s, box-shadow 0.2s',
                              boxShadow: activePageNum === pageNum ? '0 0 8px rgba(124,58,237,0.2)' : 'none',
                            }}
                          >
                            <div style={{
                              padding: '4px 8px',
                              backgroundColor: activePageNum === pageNum ? '#ede9fe' : '#f8f9fa',
                              borderBottom: '1px solid #e5e7eb',
                              fontSize: 11,
                              color: activePageNum === pageNum ? 'var(--gt-primary)' : '#9ca3af',
                              fontWeight: activePageNum === pageNum ? 600 : 400,
                            }}>
                              第 {pageNum} 页
                            </div>
                            <img
                              src={`${API_BASE}/api/analysis/document/${previewDocId}/page-image/${pageNum}`}
                              alt={`第 ${pageNum} 页`}
                              style={{ width: '100%', display: 'block' }}
                              loading="lazy"
                            />
                          </div>
                        ));
                      })()}
                      <div style={{ padding: '6px 12px', fontSize: 'var(--gt-font-xs)', color: '#9ca3af', textAlign: 'center', borderTop: '1px solid #f3f4f6' }}>
                        点击页面可定位右侧对应文本 · 如无法加载，请切换到「文本对照」模式
                      </div>
                    </div>
                  ) : (
                    /* 文本段落对照预览 */
                    <div
                      ref={leftPanelRef}
                      style={{ flex: 1, overflow: 'auto', padding: 'var(--gt-space-3)' }}
                    >
                      {(() => {
                        const origText = originalParsedText[previewDocId!] || '';
                        if (!origText.trim()) {
                          return (
                            <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
                              <div style={{ fontSize: 24, marginBottom: 8 }}>📄</div>
                              <div>暂无源文档文本内容</div>
                              <div style={{ fontSize: 'var(--gt-font-xs)', marginTop: 4 }}>
                                {state.documents.find(d => d.id === previewDocId)?.file_format === '.pdf'
                                  ? '请切换到「PDF原件」模式查看原始文档'
                                  : '文档解析内容为空'}
                              </div>
                            </div>
                          );
                        }
                        const leftParas = splitParagraphs(origText);
                        const rightParas = splitParagraphs(editingDocContent);
                        return leftParas.map((para, idx) => {
                          // 判断高亮：直接点击左侧该段落，或点击右侧后匹配到该段落
                          let isHighlighted = false;
                          if (highlightState) {
                            if (highlightState.side === 'left' && highlightState.index === idx) {
                              isHighlighted = true;
                            } else if (highlightState.side === 'right') {
                              const matchIdx = findBestMatch(rightParas[highlightState.index] || '', leftParas);
                              if (matchIdx === idx) isHighlighted = true;
                            }
                          }

                          return (
                            <div
                              key={idx}
                              data-para-idx={idx}
                              onClick={() => handleParagraphClick(idx, 'left')}
                              style={{
                                padding: '6px 10px',
                                marginBottom: 4,
                                borderRadius: 'var(--gt-radius-sm)',
                                cursor: 'pointer',
                                fontSize: 'var(--gt-font-sm)',
                                lineHeight: 1.7,
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                backgroundColor: isHighlighted ? '#ede9fe' : 'transparent',
                                borderLeft: isHighlighted ? '3px solid var(--gt-primary)' : '3px solid transparent',
                                transition: 'background-color 0.2s, border-color 0.2s',
                              }}
                              onMouseEnter={(e) => { if (!isHighlighted) e.currentTarget.style.backgroundColor = '#f5f3ff'; }}
                              onMouseLeave={(e) => { if (!isHighlighted) e.currentTarget.style.backgroundColor = 'transparent'; }}
                            >
                              {para}
                            </div>
                          );
                        });
                      })()}
                    </div>
                  )}
                </div>

                {/* 右侧：识别后文档编辑 */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, border: '1px solid #e5e7eb', borderRadius: 'var(--gt-radius-sm)', overflow: 'hidden' }}>
                  <div style={{ padding: '8px 12px', backgroundColor: '#f0fdf4', borderBottom: '1px solid #e5e7eb', fontSize: 'var(--gt-font-xs)', fontWeight: 600, color: 'var(--gt-text-secondary)', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      ✏️ 识别结果（可编辑）
                      <span style={{ fontWeight: 400, color: '#9ca3af' }}>
                        {previewMode === 'pdf' ? '（点击页面标题可定位左侧PDF原件）' : '（点击定位源文档，双击编辑段落）'}
                      </span>
                    </div>
                    <span style={{ fontSize: 11, color: '#9ca3af' }}>{editingDocContent.length} 字</span>
                  </div>
                  <div
                    ref={previewMode === 'pdf' ? pdfRightRef : rightPanelRef}
                    style={{ flex: 1, overflow: 'auto', padding: 'var(--gt-space-3)' }}
                  >
                    {previewMode === 'pdf' ? (
                      /* PDF 模式：按页分组显示文本 */
                      (() => {
                        const pages = splitByPages(editingDocContent);
                        if (pages.length === 0) {
                          return (
                            <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
                              <div style={{ fontSize: 24, marginBottom: 8 }}>📄</div>
                              <div>暂无识别文本内容</div>
                            </div>
                          );
                        }
                        return pages.map(({ pageNum, content }) => (
                          <div key={pageNum} data-page-num={pageNum} style={{ marginBottom: 'var(--gt-space-4)' }}>
                            <div
                              onClick={() => handlePdfTextPageClick(pageNum)}
                              style={{
                                padding: '6px 12px',
                                backgroundColor: activePageNum === pageNum ? '#dcfce7' : '#f0fdf4',
                                border: activePageNum === pageNum ? '1px solid #059669' : '1px solid #e5e7eb',
                                borderRadius: 'var(--gt-radius-sm)',
                                cursor: 'pointer',
                                fontSize: 12,
                                fontWeight: 600,
                                color: activePageNum === pageNum ? '#059669' : 'var(--gt-text-secondary)',
                                marginBottom: 6,
                                transition: 'all 0.2s',
                                display: 'flex',
                                alignItems: 'center',
                                gap: 6,
                              }}
                            >
                              📄 第 {pageNum} 页
                              <span style={{ fontWeight: 400, fontSize: 11, color: '#9ca3af' }}>
                                （点击定位左侧PDF）
                              </span>
                            </div>
                            <div style={{
                              padding: '8px 12px',
                              fontSize: 'var(--gt-font-sm)',
                              lineHeight: 1.7,
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              borderLeft: activePageNum === pageNum ? '3px solid #059669' : '3px solid transparent',
                              backgroundColor: activePageNum === pageNum ? '#f0fdf4' : 'transparent',
                              transition: 'all 0.2s',
                            }}>
                              {content}
                            </div>
                          </div>
                        ));
                      })()
                    ) : (
                      (() => {
                      const origText = originalParsedText[previewDocId!] || '';
                      const leftParas = splitParagraphs(origText);
                      const rightParas = splitParagraphs(editingDocContent);
                      return rightParas.map((para, idx) => {
                        let isHighlighted = false;
                        if (highlightState) {
                          if (highlightState.side === 'right' && highlightState.index === idx) {
                            isHighlighted = true;
                          } else if (highlightState.side === 'left') {
                            const matchIdx = findBestMatch(leftParas[highlightState.index] || '', rightParas);
                            if (matchIdx === idx) isHighlighted = true;
                          }
                        }

                        return (
                          <div
                            key={idx}
                            data-para-idx={idx}
                            onClick={() => handleParagraphClick(idx, 'right')}
                            onDoubleClick={() => { if (!formatting) handleParaDoubleClick(idx, para); }}
                            style={{
                              padding: '6px 10px',
                              marginBottom: 4,
                              borderRadius: 'var(--gt-radius-sm)',
                              cursor: 'pointer',
                              fontSize: 'var(--gt-font-sm)',
                              lineHeight: 1.7,
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              backgroundColor: isHighlighted ? '#dcfce7' : (editingParaIndex === idx ? '#fffbeb' : 'transparent'),
                              borderLeft: isHighlighted ? '3px solid #059669' : (editingParaIndex === idx ? '3px solid #f59e0b' : '3px solid transparent'),
                              transition: 'background-color 0.2s, border-color 0.2s',
                            }}
                            onMouseEnter={(e) => { if (!isHighlighted && editingParaIndex !== idx) e.currentTarget.style.backgroundColor = '#f0fdf4'; }}
                            onMouseLeave={(e) => { if (!isHighlighted && editingParaIndex !== idx) e.currentTarget.style.backgroundColor = 'transparent'; }}
                          >
                            {editingParaIndex === idx ? (
                              <textarea
                                value={editingParaText}
                                onChange={(e) => setEditingParaText(e.target.value)}
                                onBlur={commitParaEdit}
                                onKeyDown={(e) => { if (e.key === 'Escape') { setEditingParaIndex(null); setEditingParaText(''); } }}
                                autoFocus
                                style={{
                                  width: '100%', minHeight: 60, padding: 4,
                                  border: '1px solid #f59e0b', borderRadius: 'var(--gt-radius-sm)',
                                  fontFamily: 'var(--gt-font-cn)', fontSize: 'var(--gt-font-sm)',
                                  lineHeight: 1.7, resize: 'vertical', outline: 'none',
                                  backgroundColor: '#fffef5',
                                }}
                                onClick={(e) => e.stopPropagation()}
                              />
                            ) : para}
                          </div>
                        );
                      });
                    })()
                    )}
                  </div>
                  {/* 底部编辑区（可切换到全文编辑模式） */}
                  <div style={{ borderTop: '1px solid #e5e7eb', padding: 'var(--gt-space-2) var(--gt-space-3)', flexShrink: 0, backgroundColor: '#fafafa' }}>
                    <details>
                      <summary style={{ cursor: 'pointer', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', userSelect: 'none' }}>
                        📝 展开全文编辑器
                      </summary>
                      <textarea
                        value={editingDocContent}
                        onChange={(e) => setEditingDocContent(e.target.value)}
                        readOnly={formatting}
                        style={{
                          width: '100%', height: 200, marginTop: 8, padding: 'var(--gt-space-2)',
                          border: '1px solid #ddd', borderRadius: 'var(--gt-radius-sm)',
                          fontFamily: 'var(--gt-font-cn)', fontSize: 'var(--gt-font-sm)',
                          lineHeight: 1.7, resize: 'vertical', outline: 'none',
                          backgroundColor: formatting ? '#fafafa' : '#fff',
                        }}
                        aria-label="全文编辑"
                      />
                    </details>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── 上传进度弹窗 ─── */}
      {showUploadDialog && uploadProgress.length > 0 && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 100,
            backgroundColor: 'rgba(0,0,0,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 'var(--gt-space-4)',
          }}
          role="dialog"
          aria-modal="true"
          aria-label="文档上传进度"
        >
          <div className="gt-card" style={{ width: '90%', maxWidth: 600, maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
            <div className="gt-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
              <h3 className="gt-h4" style={{ margin: 0 }}>
                📤 文档上传
                <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', fontWeight: 400, marginLeft: 8 }}>
                  {uploadProgress.filter(p => p.status === 'done').length} / {uploadProgress.length} 完成
                  {' · '}
                  共 {(uploadProgress.reduce((s, p) => s + p.size, 0) / 1024 / 1024).toFixed(1)} MB
                </span>
              </h3>
              {!uploading && (
                <button
                  className="gt-button gt-button--secondary"
                  style={{ padding: '4px 14px', fontSize: 13 }}
                  onClick={() => setShowUploadDialog(false)}
                >
                  关闭
                </button>
              )}
            </div>

            {/* 总进度条 */}
            <div style={{ padding: '0 var(--gt-space-4)', paddingTop: 'var(--gt-space-2)' }}>
              <div style={{ width: '100%', height: 6, backgroundColor: '#e9ecef', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  width: `${uploadProgress.length > 0 ? (uploadProgress.filter(p => p.status === 'done' || p.status === 'error').length / uploadProgress.length) * 100 : 0}%`,
                  height: '100%',
                  backgroundColor: uploadProgress.some(p => p.status === 'error') ? '#f59e0b' : 'var(--gt-primary)',
                  borderRadius: 3,
                  transition: 'width 0.3s',
                }} />
              </div>
            </div>

            {/* 文件列表 */}
            <div className="gt-card-content" style={{ flex: 1, overflow: 'auto', padding: 'var(--gt-space-3) var(--gt-space-4)' }}>
              {uploadProgress.map((fp, idx) => {
                const statusMap: Record<string, { icon: string; label: string; color: string }> = {
                  waiting: { icon: '⏳', label: '等待中', color: '#9ca3af' },
                  uploading: { icon: '📤', label: '上传中', color: '#3b82f6' },
                  parsing: { icon: '🔍', label: '解析中', color: 'var(--gt-primary)' },
                  done: { icon: '✅', label: '完成', color: '#059669' },
                  error: { icon: '❌', label: '失败', color: '#dc2626' },
                };
                const st = statusMap[fp.status] || statusMap.waiting;

                return (
                  <div
                    key={idx}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)',
                      padding: '8px 0',
                      borderBottom: idx < uploadProgress.length - 1 ? '1px solid #f3f4f6' : 'none',
                    }}
                  >
                    <span style={{ fontSize: 16, flexShrink: 0 }}>{st.icon}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {fp.name}
                      </div>
                      <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', display: 'flex', gap: 8 }}>
                        <span>{(fp.size / 1024).toFixed(0)} KB</span>
                        {fp.message && <span style={{ color: st.color }}>{fp.message}</span>}
                      </div>
                    </div>
                    <span style={{ fontSize: 'var(--gt-font-xs)', color: st.color, fontWeight: 500, flexShrink: 0 }}>
                      {st.label}
                    </span>
                    {(fp.status === 'uploading' || fp.status === 'parsing') && (
                      <span style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid #e0e0e0', borderTopColor: st.color, borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite', flexShrink: 0 }} />
                    )}
                  </div>
                );
              })}
            </div>

            {/* 底部提示 */}
            {uploading && (
              <div style={{ padding: 'var(--gt-space-2) var(--gt-space-4) var(--gt-space-3)', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', textAlign: 'center' }}>
                文档解析中，大文件或含图片的文档需要 OCR 识别，请耐心等待...
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  // ─── Step 2 渲染：分析配置 ───
  const renderConfigStep = () => (
    <div>
      <div style={{ marginBottom: 'var(--gt-space-4)' }}>
        <div style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, marginBottom: 'var(--gt-space-2)' }}>
          选择分析模式
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 'var(--gt-space-3)' }}>
          {MODE_OPTIONS.map(opt => (
            <div
              key={opt.value}
              onClick={() => setState(prev => ({ ...prev, mode: opt.value, targetWordCount: opt.wordCount }))}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter') setState(prev => ({ ...prev, mode: opt.value, targetWordCount: opt.wordCount })); }}
              style={{
                border: `2px solid ${state.mode === opt.value ? 'var(--gt-primary)' : '#e8e8e8'}`,
                borderRadius: 'var(--gt-radius-md)',
                padding: 'var(--gt-space-4)',
                cursor: 'pointer',
                backgroundColor: state.mode === opt.value ? '#f5f0ff' : '#fff',
                transition: 'all 0.2s',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 'var(--gt-font-base)', color: state.mode === opt.value ? 'var(--gt-primary)' : 'var(--gt-text-primary)' }}>
                {opt.label}
              </div>
              <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginTop: 4, lineHeight: 1.5 }}>
                {opt.desc}
              </div>
              <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginTop: 8 }}>
                建议字数：约 {opt.wordCount} 字
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginBottom: 'var(--gt-space-4)' }}>
        <label htmlFor="analysis-word-count" style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, display: 'block', marginBottom: 'var(--gt-space-1)' }}>
          目标总字数
        </label>
        <input
          id="analysis-word-count"
          type="number"
          min={500}
          max={50000}
          value={state.targetWordCount}
          onChange={(e) => setState(prev => ({ ...prev, targetWordCount: parseInt(e.target.value) || 3000 }))}
          style={{
            width: 200, padding: 'var(--gt-space-2)',
            border: '1px solid #ddd', borderRadius: 'var(--gt-radius-sm)',
            fontSize: 'var(--gt-font-base)',
          }}
          aria-label="目标总字数"
        />
      </div>

      <div style={{ marginBottom: 'var(--gt-space-4)' }}>
        <label htmlFor="analysis-custom" style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, display: 'block', marginBottom: 'var(--gt-space-1)' }}>
          自定义要求（可选）
        </label>
        <textarea
          id="analysis-custom"
          value={state.customInstruction}
          onChange={(e) => setState(prev => ({ ...prev, customInstruction: e.target.value }))}
          placeholder="输入您对分析结果的特殊要求，如关注重点、输出格式偏好等..."
          rows={3}
          style={{
            width: '100%', padding: 'var(--gt-space-3)',
            border: '1px solid #ddd', borderRadius: 'var(--gt-radius-sm)',
            fontFamily: 'var(--gt-font-cn)', fontSize: 'var(--gt-font-sm)',
            resize: 'vertical', outline: 'none',
          }}
          aria-label="自定义分析要求"
        />
      </div>

      <div style={{ padding: 'var(--gt-space-3)', backgroundColor: '#f9f7fc', borderRadius: 'var(--gt-radius-sm)', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
        已上传 {state.documents.length} 个文档，共 {state.documents.reduce((sum, d) => sum + d.content_text.length, 0)} 字
      </div>

      {outlineGenerating && (
        <div style={{ marginTop: 'var(--gt-space-4)', padding: 'var(--gt-space-3)', backgroundColor: '#f8f9fa', borderRadius: 'var(--gt-radius-sm)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)', marginBottom: 'var(--gt-space-2)' }}>
            <div style={{ width: 14, height: 14, border: '2px solid #e0e0e0', borderTopColor: 'var(--gt-primary)', borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite' }} />
            <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>正在分析文档并生成章节框架...</span>
          </div>
          {outlineRaw && (
            <pre style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
              {outlineRaw}
            </pre>
          )}
        </div>
      )}
    </div>
  );

  // ─── Step 3 渲染：章节框架确认 ───
  const renderOutlineItem = (ch: AnalysisChapter, depth: number = 0) => (
    <div
      key={ch.id}
      style={{
        marginLeft: depth * 24,
        marginBottom: 'var(--gt-space-2)',
        border: '1px solid #e8e8e8',
        borderRadius: 'var(--gt-radius-sm)',
        padding: 'var(--gt-space-3)',
        backgroundColor: '#fff',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)' }}>
        <span style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', fontWeight: 600, minWidth: 30 }}>
          {ch.id}
        </span>
        <input
          type="text"
          value={ch.title}
          onChange={(e) => updateOutlineItem(ch.id, { title: e.target.value })}
          style={{
            flex: 1, padding: '4px 8px', border: '1px solid #ddd',
            borderRadius: 'var(--gt-radius-sm)', fontSize: 'var(--gt-font-sm)',
            fontWeight: 600, outline: 'none',
          }}
          aria-label={`章节 ${ch.id} 标题`}
        />
        <input
          type="number"
          value={ch.target_word_count}
          onChange={(e) => updateOutlineItem(ch.id, { target_word_count: parseInt(e.target.value) || 500 })}
          style={{ width: 80, padding: '4px 8px', border: '1px solid #ddd', borderRadius: 'var(--gt-radius-sm)', fontSize: 'var(--gt-font-xs)', textAlign: 'center' }}
          title="目标字数"
          aria-label={`章节 ${ch.id} 目标字数`}
        />
        <span style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>字</span>
        <button
          onClick={() => deleteOutlineItem(ch.id)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#dc2626', fontSize: 14, padding: 4 }}
          aria-label={`删除章节 ${ch.id}`}
          title="删除章节"
        >
          ✕
        </button>
      </div>
      <div style={{ marginTop: 'var(--gt-space-1)', marginLeft: 38 }}>
        <input
          type="text"
          value={ch.annotation}
          onChange={(e) => updateOutlineItem(ch.id, { annotation: e.target.value })}
          placeholder="章节注释说明..."
          style={{
            width: '100%', padding: '3px 8px', border: '1px solid #eee',
            borderRadius: 'var(--gt-radius-sm)', fontSize: 'var(--gt-font-xs)',
            color: 'var(--gt-text-secondary)', outline: 'none',
          }}
          aria-label={`章节 ${ch.id} 注释`}
        />
      </div>
      {ch.children && ch.children.map(child => renderOutlineItem(child, depth + 1))}
    </div>
  );

  const renderOutlineStep = () => (
    <div>
      <div style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, marginBottom: 'var(--gt-space-3)' }}>
        章节框架（可编辑标题、注释和目标字数）
      </div>
      {state.outline.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 'var(--gt-space-6)', color: 'var(--gt-text-secondary)' }}>
          暂无章节框架，请返回上一步生成
        </div>
      ) : (
        <div>
          {state.outline.map(ch => renderOutlineItem(ch))}
        </div>
      )}
    </div>
  );

  // ─── Step 4: 逐章节生成 / 停止 ───
  const getPendingChapterIds = useCallback((): string[] => {
    return leafChapters
      .map(ch => ch.id)
      .filter(id => {
        const s = state.chapterStatuses[id];
        return !s || s === 'pending' || s === 'error';
      });
  }, [leafChapters, state.chapterStatuses]);

  const handleSequentialGenerate = useCallback(async () => {
    setGenerateMode('sequential');
    setError('');
    stopRequestedRef.current = false;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const pending = getPendingChapterIds();
    if (pending.length === 0) { setGenerateMode('idle'); return; }

    setProgressMessage(`逐章节生成中... (0/${pending.length})`);
    let completed = 0;

    for (const chId of pending) {
      if (stopRequestedRef.current || controller.signal.aborted) break;
      setProgressMessage(`逐章节生成中: ${leafChapters.find(c => c.id === chId)?.title || ''} (${completed}/${pending.length})`);
      try {
        await generateOneChapter(chId, controller.signal);
        completed++;
      } catch (err: any) {
        if (err.name === 'AbortError' || stopRequestedRef.current) break;
        setState(prev => ({ ...prev, chapterStatuses: { ...prev.chapterStatuses, [chId]: 'error' as ChapterStatus } }));
        setError(`章节 "${leafChapters.find(c => c.id === chId)?.title}" 生成失败: ${err.message}`);
      }
    }

    setProgressMessage(stopRequestedRef.current ? '已停止生成' : `生成完成 (${completed}/${pending.length})`);
    setGenerateMode('idle');
    abortControllerRef.current = null;
  }, [getPendingChapterIds, leafChapters, generateOneChapter]);

  const handleBatchGenerate = useCallback(async () => {
    setGenerateMode('sequential');
    setError('');
    stopRequestedRef.current = false;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const pending = getPendingChapterIds();
    if (pending.length === 0) { setGenerateMode('idle'); return; }

    setProgressMessage(`批量生成中... (0/${pending.length})`);
    let completed = 0;
    let cursor = 0;

    const runNext = async (): Promise<void> => {
      while (cursor < pending.length) {
        if (stopRequestedRef.current || controller.signal.aborted) return;
        const chId = pending[cursor++];
        setProgressMessage(`批量生成中... (${completed}/${pending.length})`);
        try {
          await generateOneChapter(chId, controller.signal);
          completed++;
        } catch (err: any) {
          if (err.name === 'AbortError' || stopRequestedRef.current) return;
          setState(prev => ({ ...prev, chapterStatuses: { ...prev.chapterStatuses, [chId]: 'error' as ChapterStatus } }));
        }
      }
    };

    const workers = Array.from({ length: Math.min(3, pending.length) }, () => runNext());
    await Promise.all(workers);

    setProgressMessage(stopRequestedRef.current ? '已停止生成' : `生成完成 (${completed}/${pending.length})`);
    setGenerateMode('idle');
    abortControllerRef.current = null;
  }, [getPendingChapterIds, generateOneChapter]);

  const handleStop = useCallback(() => {
    stopRequestedRef.current = true;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setState(prev => {
      const next = { ...prev.chapterStatuses };
      Object.keys(next).forEach(k => { if (next[k] === 'generating') next[k] = 'pending'; });
      return { ...prev, chapterStatuses: next };
    });
    setStreamingContents({});
    setGenerateMode('idle');
    setProgressMessage('已停止生成');
  }, []);

  // ─── Step 4: AI 修改章节 ───
  const handleAIRevise = useCallback(async (chapterId: string) => {
    if (!state.projectId || !aiInstruction.trim()) return;
    const chapterData = state.chapterContents[chapterId];
    if (!chapterData) return;

    setAiProcessing(true);
    setError('');
    let revisedContent = '';

    try {
      const response = await analysisApi.reviseChapter({
        project_id: state.projectId,
        chapter_id: chapterId,
        current_content: chapterData.content,
        user_instruction: aiInstruction,
      });
      if (!response.ok) throw new Error(`AI修改失败: ${response.status}`);

      await processSSEStream(
        response,
        (data) => {
          try {
            const event = JSON.parse(data);
            if (event.status === 'streaming') revisedContent += event.content || '';
            else if (event.status === 'completed' && event.content) revisedContent = event.content;
            else if (event.status === 'error') setError(event.message || 'AI修改失败');
          } catch { /* ignore */ }
        },
        () => {
          if (revisedContent) {
            setState(prev => ({
              ...prev,
              chapterContents: {
                ...prev.chapterContents,
                [chapterId]: { ...prev.chapterContents[chapterId], content: revisedContent },
              },
            }));
          }
          setAiProcessing(false);
          setAiInstruction('');
          setAiReviseChapterId(null);
        },
        (err) => { setError(err.message); setAiProcessing(false); },
      );
    } catch (err: any) {
      setError(err.message);
      setAiProcessing(false);
    }
  }, [state.projectId, state.chapterContents, aiInstruction]);

  const toggleChapterExpand = useCallback((chId: string) => {
    setExpandedChapters(prev => {
      const next = new Set(prev);
      if (next.has(chId)) next.delete(chId); else next.add(chId);
      return next;
    });
  }, []);

  // ─── Step 4 渲染：逐章节生成与编辑 ───
  const STATUS_CONFIG: Record<ChapterStatus, { label: string; color: string; bg: string }> = {
    pending: { label: '待生成', color: '#6b7280', bg: '#f3f4f6' },
    generating: { label: '生成中', color: '#7c3aed', bg: '#ede9fe' },
    done: { label: '已完成', color: '#059669', bg: '#d1fae5' },
    error: { label: '失败', color: '#dc2626', bg: '#fee2e2' },
  };

  const renderContentStep = () => {
    const completedCount = Object.values(state.chapterStatuses).filter(s => s === 'done').length;
    const generating = generateMode !== 'idle';
    const pendingCount = getPendingChapterIds().length;

    return (
      <div>
        {/* ─── 顶部操作栏 ─── */}
        <div className="gt-card" style={{ marginBottom: 'var(--gt-space-4)' }}>
          <div className="gt-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-3)' }}>
              <span>章节内容</span>
              {leafChapters.length > 0 && (
                <span style={{ fontSize: 13, color: 'var(--gt-text-secondary)' }}>
                  {completedCount} / {leafChapters.length} 章节已完成
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 'var(--gt-space-2)', alignItems: 'center' }}>
              {generating && (
                <button
                  className="gt-button"
                  onClick={handleStop}
                  style={{ padding: '6px 16px', fontSize: 13, backgroundColor: '#dc2626', color: '#fff', border: 'none', borderRadius: 'var(--gt-radius-sm)', cursor: 'pointer' }}
                  title="停止所有正在进行的生成"
                >
                  ⏹ 停止
                </button>
              )}
              <button
                className="gt-button gt-button--primary"
                onClick={handleBatchGenerate}
                disabled={generating || pendingCount === 0}
                style={{ padding: '6px 16px', fontSize: 13 }}
                title="3个并发同时生成"
              >
                {generating ? '批量生成中...' : `⚡ 批量生成${pendingCount > 0 ? ` (${pendingCount})` : ''}`}
              </button>
              <button
                className="gt-button gt-button--secondary"
                onClick={handleSequentialGenerate}
                disabled={generating || pendingCount === 0}
                style={{ padding: '6px 16px', fontSize: 13 }}
                title="从前到后逐章节生成"
              >
                {generating ? '逐章节生成中...' : `📝 逐章节生成${pendingCount > 0 ? ` (${pendingCount})` : ''}`}
              </button>
            </div>
          </div>

          {/* 进度条 */}
          {(generating || progressMessage) && leafChapters.length > 0 && (
            <div className="gt-card-content" style={{ paddingTop: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)', marginBottom: 6 }}>
                {generating && (
                  <div style={{ width: 14, height: 14, border: '2px solid #e0e0e0', borderTopColor: 'var(--gt-primary)', borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite' }} />
                )}
                <span style={{ color: 'var(--gt-text-secondary)', fontSize: 13 }}>{progressMessage}</span>
              </div>
              <div style={{ width: '100%', height: 4, backgroundColor: '#e9ecef', borderRadius: 2, overflow: 'hidden' }} role="progressbar" aria-valuenow={completedCount} aria-valuemin={0} aria-valuemax={leafChapters.length}>
                <div style={{ width: `${leafChapters.length > 0 ? (completedCount / leafChapters.length) * 100 : 0}%`, height: '100%', backgroundColor: 'var(--gt-primary)', transition: 'width 0.3s ease' }} />
              </div>
            </div>
          )}
        </div>

        {/* ─── 章节列表 ─── */}
        {leafChapters.map(ch => {
          const status = (state.chapterStatuses[ch.id] || 'pending') as ChapterStatus;
          const chapterData = state.chapterContents[ch.id];
          const streaming = streamingContents[ch.id];
          const cfg = STATUS_CONFIG[status];
          const isExpanded = expandedChapters.has(ch.id);
          const hasContent = !!chapterData?.content || !!streaming || status === 'generating';
          const isAiRevising = aiReviseChapterId === ch.id;

          return (
            <div
              key={ch.id}
              style={{
                border: `1px solid ${status === 'generating' ? 'var(--gt-primary)' : '#e5e7eb'}`,
                borderRadius: 'var(--gt-radius-sm)',
                marginBottom: 'var(--gt-space-2)',
                overflow: 'hidden',
              }}
            >
              {/* 章节头 */}
              <div
                onClick={() => { if (hasContent) toggleChapterExpand(ch.id); }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)',
                  padding: '10px 14px',
                  cursor: hasContent ? 'pointer' : 'default',
                  backgroundColor: status === 'generating' ? '#faf5ff' : '#fff',
                  userSelect: 'none',
                }}
              >
                {/* 展开/折叠 */}
                <span style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: 18, height: 18, fontSize: 14, fontWeight: 600, color: '#6b7280',
                  border: '1px solid #d1d5db', borderRadius: 3, lineHeight: 1,
                  visibility: hasContent ? 'visible' : 'hidden', flexShrink: 0,
                }}>
                  {isExpanded ? '−' : '+'}
                </span>

                <span style={{ flex: 1, fontSize: 14, fontWeight: 500 }}>
                  {ch.id} {ch.title}
                  <span style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginLeft: 8 }}>
                    ({ch.annotation})
                  </span>
                </span>

                {/* 状态标签 / 操作按钮 */}
                {(status === 'pending' || status === 'error') ? (
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center' }} onClick={e => e.stopPropagation()}>
                    <button className="gt-button gt-button--secondary" style={{ padding: '2px 10px', fontSize: 12 }}
                      onClick={() => setEditingChapterId(ch.id)} title="手动编辑">
                      编辑
                    </button>
                    <button className="gt-button gt-button--primary" style={{ padding: '2px 10px', fontSize: 12 }}
                      onClick={() => handleGenerateChapter(ch.id)} disabled={generating}>
                      {status === 'error' ? '重试' : '生成'}
                    </button>
                  </div>
                ) : (
                  <span style={{
                    padding: '2px 8px', borderRadius: 'var(--gt-radius-sm)',
                    fontSize: 12, fontWeight: 500, color: cfg.color, backgroundColor: cfg.bg,
                    display: 'inline-flex', alignItems: 'center', gap: 4,
                  }}>
                    {status === 'generating' && (
                      <span style={{ display: 'inline-block', width: 10, height: 10, border: `2px solid ${cfg.bg}`, borderTopColor: cfg.color, borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite' }} />
                    )}
                    {cfg.label}
                  </span>
                )}

                {/* done 状态操作按钮 */}
                {status === 'done' && (
                  <div style={{ display: 'flex', gap: 4, marginLeft: 8 }} onClick={e => e.stopPropagation()}>
                    <button className="gt-button gt-button--secondary" style={{ padding: '2px 8px', fontSize: 12 }}
                      onClick={() => setEditingChapterId(ch.id)} disabled={aiProcessing}>
                      编辑
                    </button>
                    <button className="gt-button gt-button--secondary" style={{ padding: '2px 8px', fontSize: 12 }}
                      onClick={() => { setAiReviseChapterId(isAiRevising ? null : ch.id); setAiInstruction(''); }}
                      disabled={aiProcessing}>
                      AI修改
                    </button>
                    <button className="gt-button gt-button--secondary" style={{ padding: '2px 8px', fontSize: 12 }}
                      onClick={() => handleGenerateChapter(ch.id)} disabled={aiProcessing || generating}>
                      重新生成
                    </button>
                    <button className="gt-button gt-button--secondary" style={{ padding: '2px 8px', fontSize: 12, color: '#dc2626' }}
                      onClick={() => handleResetChapter(ch.id)} disabled={aiProcessing}>
                      重置
                    </button>
                  </div>
                )}
              </div>

              {/* 展开内容区域 */}
              {isExpanded && (
                <div style={{ padding: '0 14px 12px 44px', borderTop: '1px solid #f3f4f6' }}>
                  {/* 流式预览 */}
                  {status === 'generating' && streaming && (
                    <div style={{ marginTop: 'var(--gt-space-2)', padding: 'var(--gt-space-3)', backgroundColor: '#f8f9fa', borderRadius: 'var(--gt-radius-sm)', fontSize: 13, color: 'var(--gt-text-secondary)', maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                      {streaming}
                      <span style={{ animation: 'gt-blink 1s infinite' }}>▌</span>
                    </div>
                  )}

                  {/* 已完成内容 */}
                  {status === 'done' && chapterData && !isAiRevising && (
                    <div style={{ marginTop: 'var(--gt-space-2)' }}>
                      <div style={{ padding: 'var(--gt-space-3)', backgroundColor: '#fafafa', borderRadius: 'var(--gt-radius-sm)', maxHeight: 300, overflow: 'auto' }}>
                        {renderContentWithSources(chapterData.content, chapterData.sources)}
                      </div>
                      {chapterData.sources.length > 0 && (
                        <div style={{ marginTop: 8, fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
                          引用来源：{chapterData.sources.map(s => s.doc_name).filter((v, i, a) => a.indexOf(v) === i).join('、')}
                        </div>
                      )}
                    </div>
                  )}

                  {/* AI 修改模式 */}
                  {status === 'done' && isAiRevising && (
                    <div style={{ marginTop: 'var(--gt-space-2)' }}>
                      <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, fontSize: 13, color: 'var(--gt-text-secondary)', maxHeight: 150, overflow: 'auto', padding: 'var(--gt-space-2)', backgroundColor: '#f8f9fa', borderRadius: 'var(--gt-radius-sm)', marginBottom: 'var(--gt-space-2)' }}>
                        {chapterData?.content}
                      </div>
                      <textarea
                        value={aiInstruction}
                        onChange={e => setAiInstruction(e.target.value)}
                        placeholder="输入修改指令，如：精简内容、补充数据引用、调整语气..."
                        style={{ width: '100%', minHeight: 60, padding: 'var(--gt-space-2)', border: '1px solid #ddd', borderRadius: 'var(--gt-radius-sm)', fontSize: 13, resize: 'vertical', fontFamily: 'var(--gt-font-cn)' }}
                        disabled={aiProcessing}
                      />
                      <div style={{ display: 'flex', gap: 'var(--gt-space-2)', marginTop: 'var(--gt-space-2)' }}>
                        <button className="gt-button gt-button--primary" style={{ padding: '4px 12px', fontSize: 12 }}
                          onClick={() => handleAIRevise(ch.id)} disabled={aiProcessing || !aiInstruction.trim()}>
                          {aiProcessing ? '修改中...' : '提交修改'}
                        </button>
                        <button className="gt-button gt-button--secondary" style={{ padding: '4px 12px', fontSize: 12 }}
                          onClick={() => { setAiReviseChapterId(null); setAiInstruction(''); }} disabled={aiProcessing}>
                          取消
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* ─── 章节编辑器弹窗（两栏布局：左侧编辑 + 右侧AI对话） ─── */}
        {editingChapterId && (state.chapterContents[editingChapterId] || true) && (() => {
          const chTitle = leafChapters.find(c => c.id === editingChapterId)?.title || '';
          return (
            <AnalysisChapterEditor
              chapterId={editingChapterId}
              chapterTitle={chTitle}
              content={state.chapterContents[editingChapterId]?.content || ''}
              projectId={state.projectId}
              onContentChange={(newContent) => handleUpdateChapterContent(editingChapterId, newContent)}
              onClose={() => setEditingChapterId(null)}
            />
          );
        })()}
      </div>
    );
  };

  // ─── 主渲染 ───
  const renderStepContent = () => {
    switch (currentStep) {
      case 0: return renderUploadStep();
      case 1: return renderConfigStep();
      case 2: return renderOutlineStep();
      case 3: return renderContentStep();
      default: return null;
    }
  };

  return (
    <section className="gt-container gt-section" aria-label="文档分析处理工作流">
      <h2 className="gt-h2" style={{ marginBottom: 'var(--gt-space-4)' }}>
        文档分析处理
      </h2>

      {/* 步骤指示器 */}
      <nav aria-label="工作流步骤" className="gt-flow-diagram" style={{ marginBottom: 'var(--gt-space-6)' }}>
        {STEPS.map((step, index) => (
          <React.Fragment key={step.key}>
            {index > 0 && (
              <div
                className={`gt-flow-diagram__connector${index <= currentStep ? ' gt-completed' : ''}`}
                aria-hidden="true"
              />
            )}
            <div
              className={`gt-flow-diagram__step${
                index === currentStep ? ' gt-active' : ''
              }${index < currentStep ? ' gt-completed' : ''}`}
              aria-current={index === currentStep ? 'step' : undefined}
            >
              <span aria-hidden="true">{index + 1}.</span>
              {step.label}
            </div>
          </React.Fragment>
        ))}
      </nav>

      {/* 错误提示 */}
      {error && (
        <div style={{
          padding: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-4)',
          backgroundColor: '#fee2e2', borderRadius: 'var(--gt-radius-sm)',
          color: '#dc2626', fontSize: 'var(--gt-font-sm)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span>⚠️ {error}</span>
          <button onClick={() => setError('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#dc2626', fontSize: 14 }}>✕</button>
        </div>
      )}

      {/* 步骤内容 */}
      <div style={{ marginBottom: 'var(--gt-space-6)' }}>
        {renderStepContent()}
      </div>

      {/* 导航按钮 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--gt-space-4)' }}>
        <button
          className="gt-button gt-button--secondary"
          onClick={handlePrev}
          disabled={currentStep === 0}
          aria-label="上一步"
        >
          上一步
        </button>
        {currentStep < STEPS.length - 1 && (
          <button
            className="gt-button gt-button--primary"
            onClick={handleNext}
            disabled={!canProceed()}
            aria-label={currentStep === 1 ? '生成章节框架' : currentStep === 2 ? '确认并开始生成' : '下一步'}
          >
            {currentStep === 1
              ? (outlineGenerating ? '生成中...' : '生成章节框架')
              : currentStep === 2
              ? '确认框架并开始生成'
              : '下一步'}
          </button>
        )}
      </div>

      {/* Animations */}
      <style>{`
        @keyframes gt-spin { to { transform: rotate(360deg); } }
        @keyframes gt-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
      `}</style>
    </section>
  );
};

/** 章节编辑器弹窗（两栏布局：左侧文本编辑 + 右侧AI对话） */
const AnalysisChapterEditor: React.FC<{
  chapterId: string;
  chapterTitle: string;
  content: string;
  projectId: string;
  onContentChange: (content: string) => void;
  onClose: () => void;
}> = ({ chapterId, chapterTitle, content, projectId, onContentChange, onClose }) => {
  const [editContent, setEditContent] = useState(content);
  const [aiInput, setAiInput] = useState('');
  const [aiProcessing, setAiProcessing] = useState(false);
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([]);
  const chatLogRef = useRef<HTMLDivElement>(null);

  React.useEffect(() => { setEditContent(content); }, [content]);
  React.useEffect(() => {
    if (chatLogRef.current) chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
  }, [messages]);

  const handleSave = useCallback(() => { onContentChange(editContent); onClose(); }, [editContent, onContentChange, onClose]);

  const handleAiSubmit = useCallback(async () => {
    if (!aiInput.trim() || aiProcessing) return;
    const instruction = aiInput.trim();
    const userMsg = { role: 'user', content: instruction };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setAiInput('');
    setAiProcessing(true);

    let revisedContent = '';
    try {
      const response = await analysisApi.reviseChapter({
        project_id: projectId,
        chapter_id: chapterId,
        current_content: editContent,
        user_instruction: instruction,
        messages: updatedMessages,
      });
      if (!response.ok) throw new Error(`AI修改失败: ${response.status}`);

      await processSSEStream(
        response,
        (data) => {
          try {
            const event = JSON.parse(data);
            if (event.status === 'streaming') revisedContent += event.content || '';
            else if (event.status === 'completed' && event.content) revisedContent = event.content;
          } catch { /* ignore */ }
        },
        () => {
          if (revisedContent) {
            setEditContent(revisedContent);
            setMessages(prev => [...prev, { role: 'assistant', content: '已修改全文内容' }]);
          }
          setAiProcessing(false);
        },
        (err) => {
          setMessages(prev => [...prev, { role: 'assistant', content: `修改失败: ${err.message}` }]);
          setAiProcessing(false);
        },
      );
    } catch (err: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `请求失败: ${err.message}` }]);
      setAiProcessing(false);
    }
  }, [aiInput, aiProcessing, editContent, messages, projectId, chapterId]);

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 'var(--gt-space-4)' }} role="dialog" aria-modal="true">
      <div className="gt-card" style={{ width: '100%', maxWidth: 1200, height: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Header */}
        <div className="gt-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
          <div>
            <h2 className="gt-h4" style={{ margin: 0 }}>编辑章节</h2>
            <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>{chapterTitle}</span>
          </div>
          <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
            <button className="gt-button gt-button--primary" onClick={handleSave}>保存</button>
            <button className="gt-button gt-button--secondary" onClick={onClose}>关闭</button>
          </div>
        </div>
        {/* Body: two-panel */}
        <div className="gt-card-content" style={{ flex: 1, display: 'flex', gap: 'var(--gt-space-4)', overflow: 'hidden', padding: 'var(--gt-space-4)' }}>
          {/* Left: textarea */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <label style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, marginBottom: 'var(--gt-space-2)' }}>章节内容</label>
            <textarea
              value={editContent}
              onChange={e => setEditContent(e.target.value)}
              style={{ flex: 1, width: '100%', padding: 'var(--gt-space-3)', border: '1px solid #ddd', borderRadius: 'var(--gt-radius-md)', fontFamily: 'var(--gt-font-cn)', fontSize: 'var(--gt-font-base)', lineHeight: 1.8, resize: 'none', outline: 'none' }}
              aria-label={`编辑 ${chapterTitle} 内容`}
            />
          </div>
          {/* Right: AI chat */}
          <div style={{ width: 380, flexShrink: 0, display: 'flex', flexDirection: 'column', borderLeft: '1px solid #eee', paddingLeft: 'var(--gt-space-4)' }}>
            <div style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, marginBottom: 'var(--gt-space-2)' }}>AI 辅助修改</div>
            <div ref={chatLogRef} role="log" style={{ flex: 1, overflowY: 'auto', marginBottom: 'var(--gt-space-3)', padding: 'var(--gt-space-2)', backgroundColor: '#f8f9fa', borderRadius: 'var(--gt-radius-md)', minHeight: 100 }}>
              {messages.length === 0 && (
                <div style={{ color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)', textAlign: 'center', padding: 'var(--gt-space-6) var(--gt-space-2)' }}>
                  输入修改指令，AI 将帮助您修改章节内容。
                </div>
              )}
              {messages.map((msg, idx) => (
                <div key={idx} style={{ marginBottom: 'var(--gt-space-2)', display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                  <span style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginBottom: 2 }}>{msg.role === 'user' ? '您' : 'AI'}</span>
                  <div style={{ maxWidth: '90%', padding: 'var(--gt-space-2) var(--gt-space-3)', borderRadius: 'var(--gt-radius-md)', fontSize: 'var(--gt-font-sm)', lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', backgroundColor: msg.role === 'user' ? 'var(--gt-primary)' : '#fff', color: msg.role === 'user' ? '#fff' : 'var(--gt-text-primary)', border: msg.role === 'user' ? 'none' : '1px solid #e0e0e0' }}>
                    {msg.content}
                  </div>
                </div>
              ))}
              {aiProcessing && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)', color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)', padding: 'var(--gt-space-2)' }}>
                  <div style={{ width: 14, height: 14, border: '2px solid #e0e0e0', borderTopColor: 'var(--gt-primary)', borderRadius: '50%', animation: 'gt-spin 0.8s linear infinite' }} />
                  AI 正在修改...
                </div>
              )}
            </div>
            <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
              <textarea
                value={aiInput}
                onChange={e => setAiInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); handleAiSubmit(); } }}
                placeholder="输入修改要求，Ctrl+Enter 提交..."
                rows={3}
                disabled={aiProcessing}
                style={{ flex: 1, padding: 'var(--gt-space-2)', border: '1px solid #ddd', borderRadius: 'var(--gt-radius-sm)', fontFamily: 'var(--gt-font-cn)', fontSize: 'var(--gt-font-sm)', resize: 'none', outline: 'none' }}
              />
              <button className="gt-button gt-button--primary" onClick={handleAiSubmit} disabled={!aiInput.trim() || aiProcessing} style={{ alignSelf: 'flex-end', whiteSpace: 'nowrap', height: 40 }}>
                {aiProcessing ? '处理中...' : 'AI修改'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AnalysisWorkflow;
