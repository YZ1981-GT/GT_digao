/**
 * DocumentEditor - 文档编辑组件
 *
 * 以章节为单位展示生成的文档内容，每个章节提供"手动编辑"和"AI修改"两个操作入口。
 * 支持 SSE 流式生成进度和内容实时展示。
 *
 * Requirements: 12.4, 12.5, 12.6
 */
import React, { useState, useCallback } from 'react';
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

/** Per-section UI state */
interface SectionUIState {
  mode: 'view' | 'manual-edit' | 'ai-revise';
  editContent: string;
  aiInstruction: string;
  aiProcessing: boolean;
}

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
  const [generating, setGenerating] = useState(false);
  const [generatingIndex, setGeneratingIndex] = useState(-1);
  const [streamingContent, setStreamingContent] = useState('');
  const [progressMessage, setProgressMessage] = useState('');
  const [error, setError] = useState('');
  const [sectionUI, setSectionUI] = useState<Record<number, SectionUIState>>({});
  const [sectionEditorIndex, setSectionEditorIndex] = useState<number | null>(null);

  /** Get or create UI state for a section */
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

  /** Flatten outline to leaf sections for generation */
  const flattenOutline = useCallback((items: TemplateOutlineItem[]): TemplateOutlineItem[] => {
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
  }, []);

  /** Start generating all sections via SSE */
  const handleStartGenerate = useCallback(async () => {
    setGenerating(true);
    setError('');
    setProgressMessage('正在准备生成...');
    setStreamingContent('');
    setGeneratingIndex(-1);

    const newSections: GeneratedSection[] = [];

    try {
      const response = await generateApi.startGenerate({
        template_id: templateId,
        outline: outline.map((o) => ({ ...o })),
        knowledge_library_ids: knowledgeLibraryIds,
        project_info: projectInfo,
      });

      if (!response.ok) {
        throw new Error(`生成请求失败: ${response.status}`);
      }

      await processSSEStream(
        response,
        (data) => {
          try {
            const event = JSON.parse(data);
            switch (event.status) {
              case 'started':
                setProgressMessage(event.message || '开始生成文档...');
                break;
              case 'loading_knowledge':
                setProgressMessage(event.message || '正在读取知识库...');
                break;
              case 'section_start':
                setGeneratingIndex(event.section_index ?? event.index ?? newSections.length);
                setStreamingContent('');
                setProgressMessage(`正在生成: ${event.section_title || event.section || ''}`);
                break;
              case 'streaming':
                if (event.section_index !== undefined) {
                  setGeneratingIndex(event.section_index);
                }
                setStreamingContent((prev) => prev + (event.content || ''));
                break;
              case 'section_complete': {
                const completedSection: GeneratedSection = {
                  index: event.section_index ?? newSections.length,
                  title: event.title || event.section || '',
                  content: event.content || '',
                  is_placeholder: (event.content || '').includes('【待补充】'),
                };
                newSections.push(completedSection);
                onSectionsChange([...newSections]);
                setStreamingContent('');
                break;
              }
              case 'completed':
                if (event.document_id) {
                  onDocumentIdChange(event.document_id);
                } else if (event.document?.id) {
                  onDocumentIdChange(event.document.id);
                }
                if (event.sections) {
                  onSectionsChange(event.sections);
                } else if (event.document?.sections) {
                  onSectionsChange(event.document.sections);
                }
                setProgressMessage('文档生成完成');
                break;
              case 'error':
                setError(event.message || '生成过程中发生错误');
                break;
              default:
                break;
            }
          } catch {
            // Non-JSON data, ignore
          }
        },
        () => {
          setGenerating(false);
          setGeneratingIndex(-1);
          if (!error) setProgressMessage('文档生成完成');
        },
        (err) => {
          setError(err.message);
          setGenerating(false);
          setGeneratingIndex(-1);
        },
      );
    } catch (err: any) {
      setError(err.message || '生成请求失败');
      setGenerating(false);
      setGeneratingIndex(-1);
    }
  }, [documentId, outline, knowledgeLibraryIds, projectInfo, onSectionsChange, onDocumentIdChange, error]);

  /** Regenerate a single section via SSE */
  const handleRegenerateSection = useCallback(
    async (sectionIndex: number) => {
      const section = sections[sectionIndex];
      if (!section) return;

      const leafSections = flattenOutline(outline);
      const outlineItem = leafSections[sectionIndex];
      if (!outlineItem) return;

      updateUI(sectionIndex, { aiProcessing: true });
      setError('');

      let content = '';

      try {
        const response = await generateApi.generateSection({
          document_id: documentId,
          section: { ...outlineItem },
          project_info: projectInfo,
          knowledge_library_ids: knowledgeLibraryIds,
        });

        if (!response.ok) {
          throw new Error(`章节重新生成失败: ${response.status}`);
        }

        await processSSEStream(
          response,
          (data) => {
            try {
              const event = JSON.parse(data);
              if (event.status === 'streaming') {
                content += event.content || '';
              } else if (event.status === 'section_complete' || event.status === 'completed') {
                if (event.content) content = event.content;
              } else if (event.status === 'error') {
                setError(event.message || '章节重新生成失败');
              }
            } catch {
              // ignore
            }
          },
          () => {
            if (content) {
              const updated = [...sections];
              updated[sectionIndex] = { ...updated[sectionIndex], content };
              onSectionsChange(updated);
            }
            updateUI(sectionIndex, { aiProcessing: false });
          },
          (err) => {
            setError(err.message);
            updateUI(sectionIndex, { aiProcessing: false });
          },
        );
      } catch (err: any) {
        setError(err.message || '章节重新生成失败');
        updateUI(sectionIndex, { aiProcessing: false });
      }
    },
    [sections, outline, documentId, projectInfo, knowledgeLibraryIds, flattenOutline, onSectionsChange, updateUI],
  );

  /** Save manual edit */
  const handleSaveManualEdit = useCallback(
    (index: number) => {
      const ui = getUI(index);
      const updated = [...sections];
      updated[index] = { ...updated[index], content: ui.editContent };
      onSectionsChange(updated);
      updateUI(index, { mode: 'view' });
    },
    [sections, getUI, onSectionsChange, updateUI],
  );

  /** Submit AI revision for a section */
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

        if (!response.ok) {
          throw new Error(`AI修改失败: ${response.status}`);
        }

        await processSSEStream(
          response,
          (data) => {
            try {
              const event = JSON.parse(data);
              if (event.status === 'streaming') {
                revisedContent += event.content || '';
              } else if (event.status === 'completed' || event.status === 'section_complete') {
                if (event.content) revisedContent = event.content;
              } else if (event.status === 'error') {
                setError(event.message || 'AI修改失败');
              }
            } catch {
              // ignore
            }
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

  /** Total sections expected from outline */
  const totalSections = flattenOutline(outline).length;

  return (
    <section className="gt-section" aria-label="文档编辑">
      {/* Header with generate button */}
      <div className="gt-card" style={{ marginBottom: 'var(--gt-space-4)' }}>
        <div className="gt-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>文档内容</span>
          <button
            className="gt-button gt-button--primary"
            onClick={handleStartGenerate}
            disabled={generating || outline.length === 0}
            aria-label="开始生成文档"
          >
            {generating ? '生成中...' : '开始生成'}
          </button>
        </div>

        {/* Progress indicator */}
        {generating && (
          <div
            className="gt-card-content"
            role="status"
            aria-live="polite"
            aria-label="生成进度"
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)', marginBottom: 'var(--gt-space-2)' }}>
              <div
                className="gt-loading"
                aria-hidden="true"
                style={{
                  width: 16,
                  height: 16,
                  border: '2px solid var(--gt-primary-light)',
                  borderTopColor: 'var(--gt-primary)',
                  borderRadius: '50%',
                  animation: 'gt-spin 0.8s linear infinite',
                }}
              />
              <span style={{ color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
                {progressMessage}
              </span>
              {generatingIndex >= 0 && totalSections > 0 && (
                <span style={{ color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)', marginLeft: 'auto' }}>
                  {`${Math.min(sections.length + 1, totalSections)} / ${totalSections}`}
                </span>
              )}
            </div>

            {/* Progress bar */}
            {totalSections > 0 && (
              <div
                style={{
                  width: '100%',
                  height: 6,
                  backgroundColor: '#e9ecef',
                  borderRadius: 'var(--gt-radius-sm)',
                  overflow: 'hidden',
                }}
                role="progressbar"
                aria-valuenow={sections.length}
                aria-valuemin={0}
                aria-valuemax={totalSections}
                aria-label={`已生成 ${sections.length} / ${totalSections} 个章节`}
              >
                <div
                  style={{
                    width: `${(sections.length / totalSections) * 100}%`,
                    height: '100%',
                    backgroundColor: 'var(--gt-primary)',
                    transition: 'width 0.3s ease',
                  }}
                />
              </div>
            )}

            {/* Streaming preview for current section */}
            {streamingContent && (
              <div
                style={{
                  marginTop: 'var(--gt-space-3)',
                  padding: 'var(--gt-space-3)',
                  backgroundColor: '#f8f9fa',
                  borderRadius: 'var(--gt-radius-sm)',
                  fontSize: 'var(--gt-font-sm)',
                  color: 'var(--gt-text-secondary)',
                  maxHeight: 120,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                }}
                aria-label="当前章节生成预览"
              >
                {streamingContent}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Error display */}
      {error && (
        <div
          className="gt-card gt-error"
          role="alert"
          style={{
            marginBottom: 'var(--gt-space-4)',
            borderLeft: '4px solid var(--gt-danger)',
          }}
        >
          <div className="gt-card-content" style={{ color: 'var(--gt-danger)' }}>
            {error}
          </div>
        </div>
      )}

      {/* Sections list */}
      {sections.length === 0 && !generating && (
        <div className="gt-card">
          <div className="gt-card-content" style={{ textAlign: 'center', color: 'var(--gt-text-secondary)', padding: 'var(--gt-space-8)' }}>
            点击"开始生成"按钮，基于大纲逐章节生成文档内容。
          </div>
        </div>
      )}

      {sections.map((section, index) => {
        const ui = getUI(index);
        const sectionId = `section-heading-${index}`;

        return (
          <article
            key={index}
            className="gt-card"
            style={{ marginBottom: 'var(--gt-space-4)' }}
            aria-labelledby={sectionId}
          >
            {/* Section header */}
            <div
              className="gt-card-header"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--gt-space-2)' }}
            >
              <h3 id={sectionId} className="gt-h4" style={{ margin: 0 }}>
                {section.title}
              </h3>
              <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
                <button
                  className="gt-button gt-button--secondary"
                  onClick={() => {
                    setSectionEditorIndex(index);
                  }}
                  disabled={ui.aiProcessing}
                  aria-label={`手动编辑章节: ${section.title}`}
                >
                  手动编辑
                </button>
                <button
                  className="gt-button gt-button--secondary"
                  onClick={() => {
                    updateUI(index, {
                      mode: ui.mode === 'ai-revise' ? 'view' : 'ai-revise',
                      aiInstruction: '',
                    });
                  }}
                  disabled={ui.aiProcessing}
                  aria-label={`AI修改章节: ${section.title}`}
                >
                  AI修改
                </button>
                <button
                  className="gt-button gt-button--secondary"
                  onClick={() => handleRegenerateSection(index)}
                  disabled={ui.aiProcessing || generating}
                  aria-label={`重新生成章节: ${section.title}`}
                  style={{ fontSize: 'var(--gt-font-sm)' }}
                >
                  重新生成
                </button>
              </div>
            </div>

            {/* Section content */}
            <div className="gt-card-content">
              {/* View mode */}
              {ui.mode === 'view' && (
                <div
                  style={{
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.7,
                    color: 'var(--gt-text-primary)',
                  }}
                >
                  {section.content || (
                    <span style={{ color: 'var(--gt-text-secondary)', fontStyle: 'italic' }}>
                      暂无内容
                    </span>
                  )}
                </div>
              )}

              {/* Manual edit mode */}
              {ui.mode === 'manual-edit' && (
                <div>
                  <label
                    htmlFor={`manual-edit-${index}`}
                    style={{
                      display: 'block',
                      marginBottom: 'var(--gt-space-2)',
                      fontSize: 'var(--gt-font-sm)',
                      color: 'var(--gt-text-secondary)',
                    }}
                  >
                    编辑章节内容
                  </label>
                  <textarea
                    id={`manual-edit-${index}`}
                    value={ui.editContent}
                    onChange={(e) => updateUI(index, { editContent: e.target.value })}
                    style={{
                      width: '100%',
                      minHeight: 200,
                      padding: 'var(--gt-space-3)',
                      border: '1px solid #ddd',
                      borderRadius: 'var(--gt-radius-sm)',
                      fontFamily: 'var(--gt-font-cn)',
                      fontSize: 'var(--gt-font-base)',
                      lineHeight: 1.7,
                      resize: 'vertical',
                      color: 'var(--gt-text-primary)',
                    }}
                    aria-label={`编辑 ${section.title} 内容`}
                  />
                  <div style={{ display: 'flex', gap: 'var(--gt-space-2)', marginTop: 'var(--gt-space-3)' }}>
                    <button
                      className="gt-button gt-button--primary"
                      onClick={() => handleSaveManualEdit(index)}
                      aria-label="保存编辑"
                    >
                      保存
                    </button>
                    <button
                      className="gt-button gt-button--secondary"
                      onClick={() => updateUI(index, { mode: 'view' })}
                      aria-label="取消编辑"
                    >
                      取消
                    </button>
                  </div>
                </div>
              )}

              {/* AI revise mode */}
              {ui.mode === 'ai-revise' && (
                <div>
                  {/* Show current content */}
                  <div
                    style={{
                      whiteSpace: 'pre-wrap',
                      lineHeight: 1.7,
                      color: 'var(--gt-text-primary)',
                      marginBottom: 'var(--gt-space-3)',
                      padding: 'var(--gt-space-3)',
                      backgroundColor: '#f8f9fa',
                      borderRadius: 'var(--gt-radius-sm)',
                      maxHeight: 200,
                      overflow: 'auto',
                    }}
                  >
                    {section.content}
                  </div>
                  <label
                    htmlFor={`ai-instruction-${index}`}
                    style={{
                      display: 'block',
                      marginBottom: 'var(--gt-space-2)',
                      fontSize: 'var(--gt-font-sm)',
                      color: 'var(--gt-text-secondary)',
                    }}
                  >
                    输入修改指令
                  </label>
                  <textarea
                    id={`ai-instruction-${index}`}
                    value={ui.aiInstruction}
                    onChange={(e) => updateUI(index, { aiInstruction: e.target.value })}
                    placeholder="例如：请补充更多关于风险评估的内容..."
                    style={{
                      width: '100%',
                      minHeight: 80,
                      padding: 'var(--gt-space-3)',
                      border: '1px solid #ddd',
                      borderRadius: 'var(--gt-radius-sm)',
                      fontFamily: 'var(--gt-font-cn)',
                      fontSize: 'var(--gt-font-base)',
                      resize: 'vertical',
                      color: 'var(--gt-text-primary)',
                    }}
                    disabled={ui.aiProcessing}
                    aria-label={`AI修改 ${section.title} 的指令`}
                  />
                  <div style={{ display: 'flex', gap: 'var(--gt-space-2)', marginTop: 'var(--gt-space-3)' }}>
                    <button
                      className="gt-button gt-button--primary"
                      onClick={() => handleAIRevise(index)}
                      disabled={ui.aiProcessing || !ui.aiInstruction.trim()}
                      aria-label="提交AI修改"
                    >
                      {ui.aiProcessing ? '修改中...' : '提交修改'}
                    </button>
                    <button
                      className="gt-button gt-button--secondary"
                      onClick={() => updateUI(index, { mode: 'view', aiInstruction: '' })}
                      disabled={ui.aiProcessing}
                      aria-label="取消AI修改"
                    >
                      取消
                    </button>
                  </div>
                </div>
              )}

              {/* Processing indicator */}
              {ui.aiProcessing && (
                <div
                  role="status"
                  aria-live="polite"
                  style={{
                    marginTop: 'var(--gt-space-2)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--gt-space-2)',
                    color: 'var(--gt-text-secondary)',
                    fontSize: 'var(--gt-font-sm)',
                  }}
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
                  处理中...
                </div>
              )}
            </div>
          </article>
        );
      })}

      {/* Spin animation keyframes (injected once) */}
      <style>{`
        @keyframes gt-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>

      {/* SectionEditor modal */}
      {sectionEditorIndex !== null && sections[sectionEditorIndex] && (
        <SectionEditor
          sectionIndex={sectionEditorIndex}
          sectionTitle={sections[sectionEditorIndex].title}
          content={sections[sectionEditorIndex].content}
          documentId={documentId}
          onContentChange={(newContent) => {
            const updated = [...sections];
            updated[sectionEditorIndex] = { ...updated[sectionEditorIndex], content: newContent };
            onSectionsChange(updated);
          }}
          onClose={() => setSectionEditorIndex(null)}
        />
      )}
    </section>
  );
};

export default DocumentEditor;
