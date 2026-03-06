/**
 * DocumentEditor - 文档编辑组件
 *
 * 以大纲树形结构展示所有章节，每个叶子章节有独立的生成状态：
 * 待生成 → 生成中 → 已完成。支持三种生成模式：
 * - 逐章节生成：从前到后按顺序逐一生成
 * - 批量生成：3个并发同时生成
 * - 停止：中断所有正在进行的生成
 *
 * Requirements: 12.4, 12.5, 12.6
 */
import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import type {
  TemplateOutlineItem,
  GeneratedSection,
  ProjectInfo,
} from '../types/audit';
import { generateApi } from '../services/api';
import { processSSEStream } from '../utils/sseParser';
import SectionEditor from './SectionEditor';
import '../styles/gt-design-tokens.css';

interface DocumentEditorProps {
  documentId: string;
  templateId: string;
  outline: TemplateOutlineItem[];
  sections: GeneratedSection[];
  projectInfo: ProjectInfo;
  knowledgeLibraryIds: string[];
  onSectionsChange: (sections: GeneratedSection[]) => void;
  onDocumentIdChange: (id: string) => void;
}

type SectionStatus = 'pending' | 'generating' | 'done' | 'error';
type GenerateMode = 'idle' | 'sequential' | 'batch';

/** Per-section UI state */
interface SectionUIState {
  mode: 'view' | 'manual-edit' | 'ai-revise';
  editContent: string;
  aiInstruction: string;
  aiProcessing: boolean;
}

/** Flatten outline to leaf sections */
function flattenOutline(items: TemplateOutlineItem[]): TemplateOutlineItem[] {
  const result: TemplateOutlineItem[] = [];
  const walk = (list: TemplateOutlineItem[]) => {
    for (const item of list) {
      if (item.children && item.children.length > 0) {
        walk(item.children);
      } else {
        result.push(item);
      }
    }
  };
  walk(items);
  return result;
}

/** Find parent path and siblings for a leaf section in the outline tree */
function findSectionContext(
  outline: TemplateOutlineItem[],
  targetId: string,
  targetTitle: string,
): { parents: Record<string, any>[]; siblings: Record<string, any>[] } {
  const parents: Record<string, any>[] = [];
  let siblings: Record<string, any>[] = [];

  const search = (items: TemplateOutlineItem[], parentPath: Record<string, any>[]): boolean => {
    for (const item of items) {
      const isLeaf = !item.children || item.children.length === 0;
      if (isLeaf && item.id === targetId && item.title === targetTitle) {
        parents.push(...parentPath);
        siblings = items
          .filter((s) => !(s.id === targetId && s.title === targetTitle))
          .map((s) => ({ id: s.id, title: s.title, description: s.description }));
        return true;
      }
      if (item.children && item.children.length > 0) {
        const newPath = [...parentPath, { id: item.id, title: item.title, description: item.description }];
        if (search(item.children, newPath)) return true;
      }
    }
    return false;
  };

  search(outline, []);
  return { parents, siblings };
}

/** Status badge colors */
const STATUS_CONFIG: Record<SectionStatus, { label: string; color: string; bg: string }> = {
  pending: { label: '待生成', color: '#6b7280', bg: '#f3f4f6' },
  generating: { label: '生成中', color: '#7c3aed', bg: '#ede9fe' },
  done: { label: '已完成', color: '#059669', bg: '#d1fae5' },
  error: { label: '失败', color: '#dc2626', bg: '#fee2e2' },
};

/** Batch concurrency limit */
const BATCH_CONCURRENCY = 3;

const DocumentEditor: React.FC<DocumentEditorProps> = ({
  documentId,
  templateId,
  outline,
  sections,
  projectInfo,
  knowledgeLibraryIds,
  onSectionsChange,
  onDocumentIdChange,
}) => {
  const [generateMode, setGenerateMode] = useState<GenerateMode>('idle');
  const [sectionStatuses, setSectionStatuses] = useState<Record<number, SectionStatus>>(() => {
    // Initialize from existing sections — mark sections with content as 'done'
    const initial: Record<number, SectionStatus> = {};
    sections.forEach((sec, idx) => {
      if (sec && sec.content && sec.content.trim()) {
        initial[idx] = 'done';
      }
    });
    return initial;
  });
  const [streamingContents, setStreamingContents] = useState<Record<number, string>>({});
  const [progressMessage, setProgressMessage] = useState('');
  const [error, setError] = useState('');
  const [sectionUI, setSectionUI] = useState<Record<number, SectionUIState>>({});
  const [sectionEditorIndex, setSectionEditorIndex] = useState<number | null>(null);
  const [selectedLeaf, setSelectedLeaf] = useState<number | null>(null);
  const [expandedLeaves, setExpandedLeaves] = useState<Set<number>>(() => {
    // Auto-expand sections that already have content
    const expanded = new Set<number>();
    sections.forEach((sec, idx) => {
      if (sec && sec.content && sec.content.trim()) {
        expanded.add(idx);
      }
    });
    return expanded;
  });
  const sectionRefs = useRef<Record<number, HTMLElement | null>>({});

  // AbortController for stopping all in-flight requests
  const abortControllerRef = useRef<AbortController | null>(null);
  // Track whether stop was requested
  const stopRequestedRef = useRef(false);
  // Ref to latest sections for use in async callbacks
  const sectionsRef = useRef(sections);
  sectionsRef.current = sections;

  const leafSections = useMemo(() => flattenOutline(outline), [outline]);
  const totalSections = leafSections.length;
  const completedCount = Object.values(sectionStatuses).filter((s) => s === 'done').length;
  const generating = generateMode !== 'idle';

  // Reconcile sections with outline when outline changes (e.g., user edited outline in step 1)
  const prevLeafTitlesRef = useRef<string[]>([]);
  useEffect(() => {
    const newTitles = leafSections.map((l) => l.title);
    const oldTitles = prevLeafTitlesRef.current;
    prevLeafTitlesRef.current = newTitles;

    // Skip on first mount or if titles haven't changed
    if (oldTitles.length === 0 || JSON.stringify(oldTitles) === JSON.stringify(newTitles)) return;

    // Build a map from old title → section data
    const oldSectionsByTitle = new Map<string, GeneratedSection>();
    const oldStatusByTitle = new Map<string, SectionStatus>();
    oldTitles.forEach((title, idx) => {
      const sec = sectionsRef.current[idx];
      if (sec && sec.content && sec.content.trim()) {
        oldSectionsByTitle.set(title, sec);
        oldStatusByTitle.set(title, 'done');
      }
    });

    if (oldSectionsByTitle.size === 0) return;

    // Remap to new indices
    const newSections: GeneratedSection[] = [];
    const newStatuses: Record<number, SectionStatus> = {};
    const newExpanded = new Set<number>();

    newTitles.forEach((title, idx) => {
      const old = oldSectionsByTitle.get(title);
      if (old) {
        newSections[idx] = { ...old, index: idx };
        newStatuses[idx] = 'done';
        newExpanded.add(idx);
      }
    });

    if (Object.keys(newStatuses).length > 0) {
      onSectionsChange(newSections);
      setSectionStatuses(newStatuses);
      setExpandedLeaves(newExpanded);
    }
  }, [leafSections]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll position tracking for floating button
  const [isAtTop, setIsAtTop] = useState(true);

  useEffect(() => {
    const onScroll = () => setIsAtTop(window.scrollY < 100);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const generatingIndex = useMemo(() => {
    for (let i = 0; i < leafSections.length; i++) {
      if (sectionStatuses[i] === 'generating') return i;
    }
    return null;
  }, [leafSections, sectionStatuses]);

  const handleFloatingClick = useCallback(() => {
    if (!isAtTop) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (generatingIndex !== null) {
      sectionRefs.current[generatingIndex]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [isAtTop, generatingIndex]);

  const getUI = useCallback(
    (index: number): SectionUIState =>
      sectionUI[index] ?? { mode: 'view', editContent: '', aiInstruction: '', aiProcessing: false },
    [sectionUI],
  );

  const updateUI = useCallback((index: number, patch: Partial<SectionUIState>) => {
    setSectionUI((prev) => ({
      ...prev,
      [index]: { ...prev[index] ?? { mode: 'view', editContent: '', aiInstruction: '', aiProcessing: false }, ...patch },
    }));
  }, []);

  const toggleLeafExpand = useCallback((index: number) => {
    setExpandedLeaves((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  /** Generate a single section via SSE, returns the content string */
  const generateOneSection = useCallback(
    async (leafIdx: number, signal: AbortSignal): Promise<string> => {
      const outlineItem = leafSections[leafIdx];
      if (!outlineItem) throw new Error('章节不存在');

      setSectionStatuses((prev) => ({ ...prev, [leafIdx]: 'generating' }));
      setStreamingContents((prev) => ({ ...prev, [leafIdx]: '' }));
      setExpandedLeaves((prev) => new Set(prev).add(leafIdx));

      setTimeout(() => {
        sectionRefs.current[leafIdx]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 100);

      let content = '';

      // Build parent/sibling context from outline tree
      const ctx = findSectionContext(outline, outlineItem.id, outlineItem.title);

      const response = await generateApi.generateSection(
        {
          document_id: documentId || 'pending',
          section: { ...outlineItem },
          parent_sections: ctx.parents.length > 0 ? ctx.parents : undefined,
          sibling_sections: ctx.siblings.length > 0 ? ctx.siblings : undefined,
          project_info: projectInfo,
          knowledge_library_ids: knowledgeLibraryIds,
        },
        signal,
      );

      if (!response.ok) throw new Error(`章节生成失败: ${response.status}`);

      await processSSEStream(
        response,
        (data) => {
          try {
            const event = JSON.parse(data);
            if (event.status === 'streaming') {
              content += event.content || '';
              setStreamingContents((prev) => ({
                ...prev,
                [leafIdx]: (prev[leafIdx] || '') + (event.content || ''),
              }));
            } else if (event.status === 'completed' || event.status === 'section_complete') {
              if (event.content) content = event.content;
              if (event.document_id) onDocumentIdChange(event.document_id);
            } else if (event.status === 'error') {
              throw new Error(event.message || '章节生成失败');
            }
          } catch (e: any) {
            if (e.message && e.message !== '章节生成失败') {
              // JSON parse error, ignore
            } else if (e.message) {
              throw e;
            }
          }
        },
        undefined,
        (err) => { throw err; },
      );

      return content;
    },
    [leafSections, outline, documentId, projectInfo, knowledgeLibraryIds, onDocumentIdChange],
  );

  /** Complete a section: update sections array and status */
  const completeSection = useCallback(
    (leafIdx: number, content: string) => {
      const outlineItem = leafSections[leafIdx];
      const section: GeneratedSection = {
        index: leafIdx,
        title: outlineItem?.title || '',
        content,
        is_placeholder: content.includes('【待补充】'),
      };

      // Use functional update to avoid stale closure
      onSectionsChange((() => {
        const current = [...sectionsRef.current];
        current[leafIdx] = section;
        return current;
      })());

      setSectionStatuses((prev) => ({ ...prev, [leafIdx]: 'done' }));
      setStreamingContents((prev) => { const n = { ...prev }; delete n[leafIdx]; return n; });
    },
    [leafSections, onSectionsChange],
  );

  /** Get list of pending section indices */
  const getPendingIndices = useCallback((): number[] => {
    return leafSections
      .map((_, i) => i)
      .filter((i) => {
        const status = sectionStatuses[i];
        return !status || status === 'pending' || status === 'error';
      });
  }, [leafSections, sectionStatuses]);

  /** Sequential generation: one section at a time */
  const handleSequentialGenerate = useCallback(async () => {
    setGenerateMode('sequential');
    setError('');
    stopRequestedRef.current = false;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    // Initialize pending statuses for unfinished sections
    const pending = getPendingIndices();
    if (pending.length === 0) {
      setGenerateMode('idle');
      return;
    }

    setSectionStatuses((prev) => {
      const next = { ...prev };
      pending.forEach((i) => { next[i] = 'pending'; });
      return next;
    });

    setProgressMessage(`逐章节生成中... (0/${pending.length})`);
    let completed = 0;

    for (const idx of pending) {
      if (stopRequestedRef.current || controller.signal.aborted) break;

      setProgressMessage(`逐章节生成中: ${leafSections[idx]?.title || ''} (${completed}/${pending.length})`);

      try {
        const content = await generateOneSection(idx, controller.signal);
        completeSection(idx, content);
        completed++;
      } catch (err: any) {
        if (err.name === 'AbortError' || stopRequestedRef.current) break;
        setSectionStatuses((prev) => ({ ...prev, [idx]: 'error' }));
        setError(`章节 "${leafSections[idx]?.title}" 生成失败: ${err.message}`);
        // Continue to next section on error
      }
    }

    setProgressMessage(stopRequestedRef.current ? '已停止生成' : `生成完成 (${completed}/${pending.length})`);
    setGenerateMode('idle');
    abortControllerRef.current = null;
  }, [getPendingIndices, leafSections, generateOneSection, completeSection]);

  /** Batch generation: up to BATCH_CONCURRENCY concurrent sections */
  const handleBatchGenerate = useCallback(async () => {
    setGenerateMode('batch');
    setError('');
    stopRequestedRef.current = false;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const pending = getPendingIndices();
    if (pending.length === 0) {
      setGenerateMode('idle');
      return;
    }

    setSectionStatuses((prev) => {
      const next = { ...prev };
      pending.forEach((i) => { next[i] = 'pending'; });
      return next;
    });

    setProgressMessage(`批量生成中... (0/${pending.length})`);
    let completed = 0;
    let cursor = 0;

    // Simple concurrency pool
    const runNext = async (): Promise<void> => {
      while (cursor < pending.length) {
        if (stopRequestedRef.current || controller.signal.aborted) return;
        const idx = pending[cursor++];

        setProgressMessage(`批量生成中... (${completed}/${pending.length})`);

        try {
          const content = await generateOneSection(idx, controller.signal);
          completeSection(idx, content);
          completed++;
        } catch (err: any) {
          if (err.name === 'AbortError' || stopRequestedRef.current) return;
          setSectionStatuses((prev) => ({ ...prev, [idx]: 'error' }));
          // Continue on error
        }
      }
    };

    // Launch BATCH_CONCURRENCY workers
    const workers = Array.from({ length: Math.min(BATCH_CONCURRENCY, pending.length) }, () => runNext());
    await Promise.all(workers);

    setProgressMessage(stopRequestedRef.current ? '已停止生成' : `生成完成 (${completed}/${pending.length})`);
    setGenerateMode('idle');
    abortControllerRef.current = null;
  }, [getPendingIndices, generateOneSection, completeSection]);

  /** Stop all generation */
  const handleStop = useCallback(() => {
    stopRequestedRef.current = true;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;

    // Reset any 'generating' statuses back to 'pending'
    setSectionStatuses((prev) => {
      const next = { ...prev };
      Object.keys(next).forEach((k) => {
        if (next[Number(k)] === 'generating') next[Number(k)] = 'pending';
      });
      return next;
    });
    setStreamingContents({});
    setGenerateMode('idle');
    setProgressMessage('已停止生成');
  }, []);

  /** Clear all generated content, reset to initial state */
  const handleClearAll = useCallback(() => {
    if (!window.confirm('确定要清除所有已生成的章节内容吗？此操作不可撤销。')) return;
    handleStop();
    onSectionsChange([]);
    setSectionStatuses({});
    setStreamingContents({});
    setSectionUI({});
    setExpandedLeaves(new Set());
    setSelectedLeaf(null);
    setProgressMessage('');
    setError('');
  }, [handleStop, onSectionsChange]);

  /** Regenerate a single section */
  const handleRegenerateSection = useCallback(
    async (sectionIndex: number) => {
      const outlineItem = leafSections[sectionIndex];
      if (!outlineItem) return;

      updateUI(sectionIndex, { aiProcessing: true });
      setSectionStatuses((prev) => ({ ...prev, [sectionIndex]: 'generating' }));
      setStreamingContents((prev) => ({ ...prev, [sectionIndex]: '' }));
      setExpandedLeaves((prev) => new Set(prev).add(sectionIndex));
      setError('');

      let content = '';

      try {
        const ctx = findSectionContext(outline, outlineItem.id, outlineItem.title);
        const response = await generateApi.generateSection({
          document_id: documentId || 'pending',
          section: { ...outlineItem },
          parent_sections: ctx.parents.length > 0 ? ctx.parents : undefined,
          sibling_sections: ctx.siblings.length > 0 ? ctx.siblings : undefined,
          project_info: projectInfo,
          knowledge_library_ids: knowledgeLibraryIds,
        });
        if (!response.ok) throw new Error(`章节生成失败: ${response.status}`);

        await processSSEStream(
          response,
          (data) => {
            try {
              const event = JSON.parse(data);
              if (event.status === 'streaming') {
                content += event.content || '';
                setStreamingContents((prev) => ({
                  ...prev,
                  [sectionIndex]: (prev[sectionIndex] || '') + (event.content || ''),
                }));
              } else if (event.status === 'completed' || event.status === 'section_complete') {
                if (event.content) content = event.content;
              } else if (event.status === 'error') {
                setError(event.message || '章节生成失败');
              }
            } catch { /* non-JSON line, ignore */ }
          },
          () => {
            // Stream ended — always finalize
            if (content) {
              completeSection(sectionIndex, content);
            } else {
              setSectionStatuses((prev) => ({ ...prev, [sectionIndex]: 'error' }));
            }
            updateUI(sectionIndex, { aiProcessing: false });
          },
          (err) => {
            setError(err.message);
            setSectionStatuses((prev) => ({ ...prev, [sectionIndex]: 'error' }));
            setStreamingContents((prev) => { const n = { ...prev }; delete n[sectionIndex]; return n; });
            updateUI(sectionIndex, { aiProcessing: false });
          },
        );
      } catch (err: any) {
        setError(err.message || '章节生成失败');
        setSectionStatuses((prev) => ({ ...prev, [sectionIndex]: 'error' }));
        setStreamingContents((prev) => { const n = { ...prev }; delete n[sectionIndex]; return n; });
        updateUI(sectionIndex, { aiProcessing: false });
      }
    },
    [leafSections, outline, documentId, projectInfo, knowledgeLibraryIds, completeSection, updateUI],
  );

  /** Submit AI revision */
  const handleAIRevise = useCallback(
    async (sectionIndex: number) => {
      const ui = getUI(sectionIndex);
      const section = sections[sectionIndex];
      if (!section || !ui.aiInstruction.trim()) return;

      updateUI(sectionIndex, { aiProcessing: true });
      setError('');
      let revisedContent = '';

      try {
        const response = await generateApi.reviseSection({
          document_id: documentId,
          section_index: sectionIndex,
          current_content: section.content,
          user_instruction: ui.aiInstruction,
          messages: [],
        });
        if (!response.ok) throw new Error(`AI修改失败: ${response.status}`);

        await processSSEStream(
          response,
          (data) => {
            try {
              const event = JSON.parse(data);
              if (event.status === 'streaming') revisedContent += event.content || '';
              else if (event.status === 'completed' || event.status === 'section_complete') {
                if (event.content) revisedContent = event.content;
              } else if (event.status === 'error') setError(event.message || 'AI修改失败');
            } catch { /* ignore */ }
          },
          () => {
            if (revisedContent) {
              const updated = [...sections];
              updated[sectionIndex] = { ...updated[sectionIndex], content: revisedContent };
              onSectionsChange(updated);
            }
            updateUI(sectionIndex, { aiProcessing: false, aiInstruction: '', mode: 'view' });
          },
          (err) => {
            setError(err.message);
            updateUI(sectionIndex, { aiProcessing: false });
          },
        );
      } catch (err: any) {
        setError(err.message || 'AI修改失败');
        updateUI(sectionIndex, { aiProcessing: false });
      }
    },
    [sections, documentId, getUI, onSectionsChange, updateUI],
  );

  /** Build a map from leaf title to its flat index */
  const leafIndexMap = useMemo(() => {
    const m = new Map<string, number>();
    leafSections.forEach((leaf, i) => m.set(`${leaf.id}-${leaf.title}`, i));
    return m;
  }, [leafSections]);

  const getLeafIndex = useCallback(
    (item: TemplateOutlineItem): number | null => {
      const key = `${item.id}-${item.title}`;
      return leafIndexMap.get(key) ?? null;
    },
    [leafIndexMap],
  );

  /** Render status badge */
  const renderStatusBadge = (status: SectionStatus) => {
    const cfg = STATUS_CONFIG[status];
    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 8px',
          borderRadius: 'var(--gt-radius-sm)',
          fontSize: 12,
          fontWeight: 500,
          color: cfg.color,
          backgroundColor: cfg.bg,
          whiteSpace: 'nowrap',
        }}
      >
        {status === 'generating' && (
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              border: `2px solid ${cfg.bg}`,
              borderTopColor: cfg.color,
              borderRadius: '50%',
              animation: 'gt-spin 0.8s linear infinite',
            }}
          />
        )}
        {cfg.label}
      </span>
    );
  };

  /** Render a single leaf section row with expandable content */
  const renderLeafSection = useCallback((item: TemplateOutlineItem, leafIdx: number) => {
    const status = sectionStatuses[leafIdx] || 'pending';
    const section = sections[leafIdx];
    const isExpanded = expandedLeaves.has(leafIdx);
    const streaming = streamingContents[leafIdx];
    const ui = getUI(leafIdx);
    const hasContent = section?.content || streaming || status === 'generating';
    const isSelected = selectedLeaf === leafIdx;

    return (
      <div
        key={`leaf-${leafIdx}`}
        ref={(el) => { sectionRefs.current[leafIdx] = el; }}
        onClick={() => setSelectedLeaf(isSelected ? null : leafIdx)}
        style={{
          border: `2px solid ${isSelected ? 'var(--gt-primary, #7c3aed)' : status === 'generating' ? 'var(--gt-primary)' : '#e5e7eb'}`,
          borderRadius: 'var(--gt-radius-sm)',
          marginBottom: 'var(--gt-space-2)',
          overflow: 'hidden',
          transition: 'border-color 0.2s, box-shadow 0.2s',
          boxShadow: isSelected ? '0 0 0 2px rgba(124, 58, 237, 0.15)' : 'none',
        }}
      >
        {/* Row header */}
        <div
          onClick={(e) => { e.stopPropagation(); if (hasContent) toggleLeafExpand(leafIdx); }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--gt-space-2)',
            padding: '10px 14px',
            cursor: hasContent ? 'pointer' : 'default',
            backgroundColor: isSelected ? '#f5f0ff' : status === 'generating' ? '#faf5ff' : '#fff',
            userSelect: 'none',
          }}
        >
          {/* Expand toggle */}
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 18,
              height: 18,
              fontSize: 14,
              fontWeight: 600,
              color: '#6b7280',
              border: '1px solid #d1d5db',
              borderRadius: 3,
              lineHeight: 1,
              visibility: hasContent ? 'visible' : 'hidden',
              flexShrink: 0,
            }}
          >
            {isExpanded ? '−' : '+'}
          </span>

          {/* Title */}
          <span style={{ flex: 1, fontSize: 14, color: 'var(--gt-text-primary)' }}>
            {item.id} {item.title}
          </span>

          {/* Status badge — clickable to generate when pending/error */}
          {(status === 'pending' || status === 'error') ? (
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
              <button
                className="gt-button gt-button--secondary"
                style={{ padding: '2px 10px', fontSize: 12, cursor: 'pointer' }}
                onClick={() => setSectionEditorIndex(leafIdx)}
                title="手动编辑该章节内容"
              >
                编辑
              </button>
              <button
                className="gt-button gt-button--primary"
                style={{ padding: '2px 10px', fontSize: 12, cursor: 'pointer' }}
                onClick={() => handleRegenerateSection(leafIdx)}
                disabled={generating}
                title="调用AI生成该章节"
              >
                {status === 'error' ? '重试' : '生成'}
              </button>
            </div>
          ) : (
            renderStatusBadge(status)
          )}

          {/* Action buttons (only when done) */}
          {status === 'done' && section && (
            <div style={{ display: 'flex', gap: 4, marginLeft: 8 }} onClick={(e) => e.stopPropagation()}>
              <button
                className="gt-button gt-button--secondary"
                style={{ padding: '2px 8px', fontSize: 12 }}
                onClick={() => setSectionEditorIndex(leafIdx)}
                disabled={ui.aiProcessing}
              >
                编辑
              </button>
              <button
                className="gt-button gt-button--secondary"
                style={{ padding: '2px 8px', fontSize: 12 }}
                onClick={() => updateUI(leafIdx, {
                  mode: ui.mode === 'ai-revise' ? 'view' : 'ai-revise',
                  aiInstruction: '',
                })}
                disabled={ui.aiProcessing}
              >
                AI修改
              </button>
              <button
                className="gt-button gt-button--secondary"
                style={{ padding: '2px 8px', fontSize: 12 }}
                onClick={() => handleRegenerateSection(leafIdx)}
                disabled={ui.aiProcessing || generating}
              >
                重新生成
              </button>
              <button
                className="gt-button gt-button--secondary"
                style={{ padding: '2px 8px', fontSize: 12, color: '#dc2626' }}
                onClick={() => {
                  const updated = [...sectionsRef.current];
                  updated[leafIdx] = undefined as any;
                  onSectionsChange(updated);
                  setSectionStatuses((prev) => { const n = { ...prev }; delete n[leafIdx]; return n; });
                  setStreamingContents((prev) => { const n = { ...prev }; delete n[leafIdx]; return n; });
                  setExpandedLeaves((prev) => { const n = new Set(prev); n.delete(leafIdx); return n; });
                  updateUI(leafIdx, { mode: 'view', aiInstruction: '', aiProcessing: false });
                }}
                disabled={ui.aiProcessing}
                title="重置该章节内容"
              >
                重置
              </button>
            </div>
          )}
        </div>

        {/* Expanded content area */}
        {isExpanded && (
          <div style={{ padding: '0 14px 12px 44px', borderTop: '1px solid #f3f4f6' }}>
            {/* Streaming preview */}
            {status === 'generating' && streaming && (
              <div
                style={{
                  marginTop: 'var(--gt-space-2)',
                  padding: 'var(--gt-space-3)',
                  backgroundColor: '#f8f9fa',
                  borderRadius: 'var(--gt-radius-sm)',
                  fontSize: 13,
                  color: 'var(--gt-text-secondary)',
                  maxHeight: 200,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  lineHeight: 1.6,
                }}
              >
                {streaming}
                <span style={{ animation: 'gt-blink 1s infinite' }}>▌</span>
              </div>
            )}

            {/* Completed content */}
            {status === 'done' && section && ui.mode === 'view' && (
              <div
                style={{
                  marginTop: 'var(--gt-space-2)',
                  whiteSpace: 'pre-wrap',
                  lineHeight: 1.7,
                  color: 'var(--gt-text-primary)',
                  fontSize: 14,
                  maxHeight: 300,
                  overflow: 'auto',
                }}
              >
                {section.content || <span style={{ color: '#9ca3af', fontStyle: 'italic' }}>暂无内容</span>}
              </div>
            )}

            {/* AI revise mode */}
            {status === 'done' && ui.mode === 'ai-revise' && (
              <div style={{ marginTop: 'var(--gt-space-2)' }}>
                <div
                  style={{
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.7,
                    fontSize: 13,
                    color: 'var(--gt-text-secondary)',
                    maxHeight: 150,
                    overflow: 'auto',
                    padding: 'var(--gt-space-2)',
                    backgroundColor: '#f8f9fa',
                    borderRadius: 'var(--gt-radius-sm)',
                    marginBottom: 'var(--gt-space-2)',
                  }}
                >
                  {section?.content}
                </div>
                <textarea
                  value={ui.aiInstruction}
                  onChange={(e) => updateUI(leafIdx, { aiInstruction: e.target.value })}
                  placeholder="输入修改指令..."
                  style={{
                    width: '100%',
                    minHeight: 60,
                    padding: 'var(--gt-space-2)',
                    border: '1px solid #ddd',
                    borderRadius: 'var(--gt-radius-sm)',
                    fontSize: 13,
                    resize: 'vertical',
                  }}
                  disabled={ui.aiProcessing}
                />
                <div style={{ display: 'flex', gap: 'var(--gt-space-2)', marginTop: 'var(--gt-space-2)' }}>
                  <button
                    className="gt-button gt-button--primary"
                    style={{ padding: '4px 12px', fontSize: 12 }}
                    onClick={() => handleAIRevise(leafIdx)}
                    disabled={ui.aiProcessing || !ui.aiInstruction.trim()}
                  >
                    {ui.aiProcessing ? '修改中...' : '提交修改'}
                  </button>
                  <button
                    className="gt-button gt-button--secondary"
                    style={{ padding: '4px 12px', fontSize: 12 }}
                    onClick={() => updateUI(leafIdx, { mode: 'view', aiInstruction: '' })}
                    disabled={ui.aiProcessing}
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }, [sectionStatuses, streamingContents, sections, expandedLeaves, generating, selectedLeaf,
      toggleLeafExpand, updateUI, getUI, setSectionEditorIndex, handleRegenerateSection, handleAIRevise]);

  /** Render outline tree recursively */
  const renderOutlineTree = useCallback(
    (items: TemplateOutlineItem[], depth: number = 0): React.ReactNode => {
      return items.map((item) => {
        const isLeaf = !item.children || item.children.length === 0;

        if (isLeaf) {
          const idx = getLeafIndex(item);
          if (idx === null) return null;
          return renderLeafSection(item, idx);
        }

        return (
          <div key={item.id} style={{ marginBottom: depth === 0 ? 'var(--gt-space-3)' : 'var(--gt-space-1)' }}>
            <div
              style={{
                padding: depth === 0 ? '8px 0' : '4px 0',
                fontWeight: depth === 0 ? 600 : 500,
                fontSize: depth === 0 ? 15 : 14,
                color: 'var(--gt-text-primary)',
                borderBottom: depth === 0 ? '1px solid #e5e7eb' : 'none',
                marginBottom: 'var(--gt-space-2)',
              }}
            >
              {item.id} {item.title}
            </div>
            <div style={{ paddingLeft: depth === 0 ? 0 : 16 }}>
              {renderOutlineTree(item.children!, depth + 1)}
            </div>
          </div>
        );
      });
    },
    [getLeafIndex, renderLeafSection],
  );

  const pendingCount = getPendingIndices().length;

  return (
    <section className="gt-section" aria-label="文档编辑">
      {/* Header */}
      <div className="gt-card" style={{ marginBottom: 'var(--gt-space-4)' }}>
        <div className="gt-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-3)' }}>
            <span>文档内容</span>
            {totalSections > 0 && (
              <span style={{ fontSize: 13, color: 'var(--gt-text-secondary)' }}>
                {completedCount} / {totalSections} 章节已完成
              </span>
            )}
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 'var(--gt-space-2)', alignItems: 'center' }}>
            <button
              className="gt-button gt-button--secondary"
              onClick={handleClearAll}
              disabled={generating || completedCount === 0}
              style={{ padding: '6px 16px', fontSize: 13 }}
              title="清除所有已生成的章节内容"
            >
              🗑 重置
            </button>
            {generating && (
              <button
                className="gt-button"
                onClick={handleStop}
                style={{
                  padding: '6px 16px',
                  fontSize: 13,
                  backgroundColor: '#dc2626',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 'var(--gt-radius-sm)',
                  cursor: 'pointer',
                }}
                title="停止所有正在进行的生成"
              >
                ⏹ 停止
              </button>
            )}
            <button
              className="gt-button gt-button--primary"
              onClick={handleBatchGenerate}
              disabled={generating || outline.length === 0 || pendingCount === 0}
              style={{ padding: '6px 16px', fontSize: 13 }}
              title={`${BATCH_CONCURRENCY}个并发同时生成所有待生成章节`}
            >
              {generateMode === 'batch' ? '批量生成中...' : `⚡ 批量生成${pendingCount > 0 ? ` (${pendingCount})` : ''}`}
            </button>
            <button
              className="gt-button gt-button--secondary"
              onClick={handleSequentialGenerate}
              disabled={generating || outline.length === 0 || pendingCount === 0}
              style={{ padding: '6px 16px', fontSize: 13 }}
              title="从前到后逐章节生成"
            >
              {generateMode === 'sequential' ? '逐章节生成中...' : `📝 逐章节生成${pendingCount > 0 ? ` (${pendingCount})` : ''}`}
            </button>
          </div>
        </div>

        {/* Overall progress bar */}
        {(generating || progressMessage) && totalSections > 0 && (
          <div className="gt-card-content" style={{ paddingTop: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)', marginBottom: 6 }}>
              {generating && (
                <div
                  style={{
                    width: 14, height: 14,
                    border: '2px solid var(--gt-primary-light)',
                    borderTopColor: 'var(--gt-primary)',
                    borderRadius: '50%',
                    animation: 'gt-spin 0.8s linear infinite',
                  }}
                />
              )}
              <span style={{ color: 'var(--gt-text-secondary)', fontSize: 13 }}>{progressMessage}</span>
            </div>
            <div
              style={{
                width: '100%', height: 4,
                backgroundColor: '#e9ecef',
                borderRadius: 2,
                overflow: 'hidden',
              }}
              role="progressbar"
              aria-valuenow={completedCount}
              aria-valuemin={0}
              aria-valuemax={totalSections}
            >
              <div
                style={{
                  width: `${(completedCount / totalSections) * 100}%`,
                  height: '100%',
                  backgroundColor: 'var(--gt-primary)',
                  transition: 'width 0.3s ease',
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div
          className="gt-card"
          role="alert"
          style={{ marginBottom: 'var(--gt-space-4)', borderLeft: '4px solid var(--gt-danger)' }}
        >
          <div className="gt-card-content" style={{ color: 'var(--gt-danger)' }}>{error}</div>
        </div>
      )}

      {/* Outline tree with section statuses */}
      {outline.length > 0 ? (
        <div className="gt-card">
          <div className="gt-card-content">
            {renderOutlineTree(outline)}
          </div>
        </div>
      ) : (
        <div className="gt-card">
          <div className="gt-card-content" style={{ textAlign: 'center', color: 'var(--gt-text-secondary)', padding: 'var(--gt-space-8)' }}>
            请先在上一步确认大纲结构。
          </div>
        </div>
      )}

      {/* Animations */}
      <style>{`
        @keyframes gt-spin { to { transform: rotate(360deg); } }
        @keyframes gt-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
      `}</style>

      {/* SectionEditor modal */}
      {sectionEditorIndex !== null && (
        <SectionEditor
          sectionIndex={sectionEditorIndex}
          sectionTitle={sections[sectionEditorIndex]?.title || leafSections[sectionEditorIndex]?.title || ''}
          content={sections[sectionEditorIndex]?.content || ''}
          documentId={documentId || 'pending'}
          onContentChange={(newContent) => {
            const leaf = leafSections[sectionEditorIndex];
            const updated = [...sectionsRef.current];
            updated[sectionEditorIndex] = {
              index: sectionEditorIndex,
              title: leaf?.title || '',
              content: newContent,
              is_placeholder: newContent.includes('【待补充】'),
            };
            onSectionsChange(updated);
            if (newContent.trim()) {
              setSectionStatuses((prev) => ({ ...prev, [sectionEditorIndex]: 'done' }));
              setStreamingContents((prev) => { const n = { ...prev }; delete n[sectionEditorIndex]; return n; });
            }
          }}
          onClose={() => setSectionEditorIndex(null)}
        />
      )}

      {/* Floating scroll button */}
      {(!isAtTop || generatingIndex !== null) && (
        <button
          onClick={handleFloatingClick}
          title={!isAtTop ? '返回顶部' : '跳转到生成中的章节'}
          style={{
            position: 'fixed',
            right: 32,
            bottom: 32,
            width: 44,
            height: 44,
            borderRadius: '50%',
            border: 'none',
            backgroundColor: 'var(--gt-primary, #7c3aed)',
            color: '#fff',
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 8px rgba(0,0,0,0.18)',
            zIndex: 1000,
            transition: 'transform 0.2s, opacity 0.2s',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(1.1)'; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
        >
          {!isAtTop ? '↑' : '↓'}
        </button>
      )}
    </section>
  );
};

export default DocumentEditor;
