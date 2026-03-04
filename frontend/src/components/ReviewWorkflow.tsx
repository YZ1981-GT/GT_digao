/**
 * ReviewWorkflow - 复核工作流容器
 *
 * 四步骤复核工作流：底稿上传  提示词选择与维度配置  补充材料与确认  报告查看导出
 * 使用 gt-flow-diagram 步骤指示器展示进度，管理步骤间导航和状态传递。
 * 集成 SSE 流式通信处理复核事件（dimension_start / dimension_complete /
 * need_supplementary / streaming / completed / error）。
 *
 * Requirements: 2.7, 6.3, 7.4
 */
import React, { useState, useCallback, useEffect, useRef } from 'react';
import type {
  WorkpaperParseResult,
  ReviewDimension,
  SupplementaryMaterial,
  RequiredReference,
  ReviewReport as ReviewReportType,
  ReviewRequest,
  FindingStatus,
  CrossReferenceAnalysis,
} from '../types/audit';
import { processSSEStream } from '../utils/sseParser';
import { reviewApi } from '../services/api';
import { saveAuditState, loadAuditState } from '../utils/auditStorage';
import type { AuditWorkState } from '../utils/auditStorage';
import WorkpaperUpload from './WorkpaperUpload';
import PromptSelector from './PromptSelector';
import ReviewDimensionConfig from './ReviewDimensionConfig';
import SupplementaryUpload from './SupplementaryUpload';
import ReviewConfirmation from './ReviewConfirmation';
import ReviewReportComponent from './ReviewReport';
import CrossReferenceGraph from './CrossReferenceGraph';
import '../styles/gt-design-tokens.css';

const STEPS = [
  { label: '底稿上传', key: 'upload' },
  { label: '提示词选择与维度配置', key: 'config' },
  { label: '补充材料与确认', key: 'confirm' },
  { label: '报告查看导出', key: 'report' },
] as const;

interface WorkflowState {
  workpapers: WorkpaperParseResult[];
  selectedPromptId: string | null;
  customPrompt: string;
  dimensions: ReviewDimension[];
  customDimensions: string[];
  supplementaryMaterials: SupplementaryMaterial[];
  reviewId: string;
  report: ReviewReportType | null;
  isReviewing: boolean;
  reviewProgress: number;
  currentDimension: string;
  needSupplementary: boolean;
  requiredReferences: RequiredReference[];
  crossReferenceAnalysis: CrossReferenceAnalysis | null;
}

const INITIAL_STATE: WorkflowState = {
  workpapers: [],
  selectedPromptId: null,
  customPrompt: '',
  dimensions: [],
  customDimensions: [],
  supplementaryMaterials: [],
  reviewId: '',
  report: null,
  isReviewing: false,
  reviewProgress: 0,
  currentDimension: '',
  needSupplementary: false,
  requiredReferences: [],
  crossReferenceAnalysis: null,
};
const ReviewWorkflow: React.FC = () => {
  const [currentStep, setCurrentStep] = useState(0);
  const [state, setState] = useState<WorkflowState>({ ...INITIAL_STATE });
  const [error, setError] = useState<string | null>(null);
  const [stateLoaded, setStateLoaded] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const updateState = useCallback(
    (patch: Partial<WorkflowState> | ((prev: WorkflowState) => Partial<WorkflowState>)) => {
      setState((prev) => {
        const updates = typeof patch === 'function' ? patch(prev) : patch;
        return { ...prev, ...updates };
      });
    },
    [],
  );

  //  IndexedDB: load cached workflow state on mount 
  useEffect(() => {
    let cancelled = false;
    loadAuditState().then((cached) => {
      if (cancelled || !cached) {
        setStateLoaded(true);
        return;
      }
      setState((prev) => ({
        ...prev,
        workpapers: cached.uploadedWorkpapers ?? prev.workpapers,
        selectedPromptId: cached.reviewConfig?.promptId ?? prev.selectedPromptId,
        customPrompt: cached.reviewConfig?.customPrompt ?? prev.customPrompt,
        dimensions: cached.reviewConfig?.dimensions ?? prev.dimensions,
        customDimensions: cached.reviewConfig?.customDimensions ?? prev.customDimensions,
        supplementaryMaterials: cached.supplementaryMaterials ?? prev.supplementaryMaterials,
        report: cached.reviewReport ?? prev.report,
      }));
      if (cached.reviewReport) {
        setCurrentStep(3);
      }
      setStateLoaded(true);
    });
    return () => { cancelled = true; };
  }, []);

  //  IndexedDB: save workflow state on change (debounced 500ms) 
  useEffect(() => {
    if (!stateLoaded) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      const auditState: AuditWorkState = {
        uploadedWorkpapers: state.workpapers,
        reviewConfig: {
          dimensions: state.dimensions,
          customDimensions: state.customDimensions,
          promptId: state.selectedPromptId,
          customPrompt: state.customPrompt || null,
        },
        selectedPrompt: null,
        supplementaryMaterials: state.supplementaryMaterials,
        reviewReport: state.report,
      };
      saveAuditState(auditState);
    }, 500);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [
    stateLoaded,
    state.workpapers,
    state.dimensions,
    state.customDimensions,
    state.selectedPromptId,
    state.customPrompt,
    state.supplementaryMaterials,
    state.report,
  ]);

  const handleNext = useCallback(() => {
    setCurrentStep((prev) => Math.min(prev + 1, STEPS.length - 1));
  }, []);

  const handlePrev = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 0));
  }, []);

  const canProceed = (): boolean => {
    switch (currentStep) {
      case 0:
        return state.workpapers.length > 0;
      case 1:
        return state.dimensions.length > 0;
      case 2:
        return !state.isReviewing;
      default:
        return false;
    }
  };

  const handleStartReview = useCallback(async () => {
    updateState({ isReviewing: true, reviewProgress: 0, currentDimension: '', report: null });
    setError(null);

    const reviewRequest: ReviewRequest = {
      workpaper_ids: state.workpapers.map((w) => w.id),
      dimensions: state.dimensions,
      custom_dimensions: state.customDimensions.length > 0 ? state.customDimensions : undefined,
      prompt_id: state.selectedPromptId || undefined,
      custom_prompt: state.customPrompt || undefined,
      supplementary_material_ids: state.supplementaryMaterials.map((m) => m.id),
    };

    try {
      const response = await reviewApi.startReview(reviewRequest);

      if (!response.ok) {
        const text = await response.text().catch(() => '');
        updateState({ isReviewing: false });
        setError(text || `服务器返回错误 (${response.status})`);
        return;
      }

      await processSSEStream(
        response,
        (data) => {
          try {
            const event = JSON.parse(data);
            switch (event.status) {
              case 'dimension_start':
                updateState({ currentDimension: event.dimension || '' });
                break;
              case 'dimension_complete':
                updateState((prev) => ({
                  reviewProgress: prev.reviewProgress + 1,
                }));
                break;
              case 'need_supplementary':
                updateState({
                  needSupplementary: true,
                  requiredReferences: event.required_workpapers || [],
                });
                break;
              case 'streaming':
                break;
              case 'completed':
                updateState({
                  report: event.report || null,
                  reviewId: event.review_id || '',
                  isReviewing: false,
                });
                setCurrentStep(3);
                break;
              case 'error':
                updateState({ isReviewing: false });
                setError(event.message || '复核过程中发生错误');
                break;
            }
          } catch {
            /* ignore JSON parse errors */
          }
        },
        () => {
          updateState({ isReviewing: false });
        },
        (err) => {
          updateState({ isReviewing: false });
          setError(err.message || '复核连接中断');
        },
      );
    } catch (err: any) {
      updateState({ isReviewing: false });
      setError(err.message || '发起复核请求失败');
    }
  }, [
    state.workpapers,
    state.dimensions,
    state.customDimensions,
    state.selectedPromptId,
    state.customPrompt,
    state.supplementaryMaterials,
    updateState,
  ]);
  const handleFindingStatusUpdate = useCallback(
    async (findingId: string, newStatus: FindingStatus) => {
      try {
        await reviewApi.updateFindingStatus(findingId, { status: newStatus });
        updateState((prev) => {
          if (!prev.report) return {};
          const updatedFindings = prev.report.findings.map((f) =>
            f.id === findingId
              ? { ...f, status: newStatus, resolved_at: newStatus === 'resolved' ? new Date().toISOString() : undefined }
              : f,
          );
          return { report: { ...prev.report, findings: updatedFindings } };
        });
      } catch (err: any) {
        setError(err.message || '更新问题状态失败');
      }
    },
    [updateState],
  );

  const handleExport = useCallback(
    async (format: 'word' | 'pdf') => {
      if (!state.reviewId) return;
      try {
        const response = await reviewApi.exportReport(state.reviewId, { format });
        const blob = new Blob([response.data]);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `复核报告.${format === 'word' ? 'docx' : 'pdf'}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err: any) {
        setError(err.message || '导出报告失败');
      }
    },
    [state.reviewId],
  );

  const fetchCrossReferences = useCallback(async () => {
    if (!state.reviewId) return;
    try {
      const response = await reviewApi.getCrossReferences(state.reviewId);
      updateState({ crossReferenceAnalysis: response.data });
    } catch {
      /* non-critical */
    }
  }, [state.reviewId, updateState]);

  const totalDimensions = state.dimensions.length + state.customDimensions.length;
  const reviewProgressProp = state.isReviewing
    ? {
        currentDimension: state.currentDimension,
        completedDimensions: state.reviewProgress,
        totalDimensions,
      }
    : null;
  const progressPct = totalDimensions > 0 ? Math.round((state.reviewProgress / totalDimensions) * 100) : 0;
  const renderStepContent = () => {
    switch (currentStep) {
      case 0:
        return (
          <WorkpaperUpload
            workpapers={state.workpapers}
            onWorkpapersChange={(wps) => updateState({ workpapers: wps })}
          />
        );
      case 1:
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-5)' }}>
            <PromptSelector
              selectedPromptId={state.selectedPromptId}
              customPrompt={state.customPrompt}
              onPromptSelect={(id) => updateState({ selectedPromptId: id })}
              onCustomPromptChange={(text) => updateState({ customPrompt: text })}
            />
            <ReviewDimensionConfig
              selectedDimensions={state.dimensions}
              customDimensions={state.customDimensions}
              onDimensionsChange={(dims) => updateState({ dimensions: dims })}
              onCustomDimensionsChange={(customs) => updateState({ customDimensions: customs })}
            />
          </div>
        );
      case 2:
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-5)' }}>
            <SupplementaryUpload
              requiredReferences={state.requiredReferences}
              supplementaryMaterials={state.supplementaryMaterials}
              onSupplementaryChange={(mats) => updateState({ supplementaryMaterials: mats })}
            />
            <ReviewConfirmation
              workpapers={state.workpapers}
              selectedDimensions={state.dimensions}
              customDimensions={state.customDimensions}
              selectedPromptId={state.selectedPromptId}
              customPrompt={state.customPrompt}
              supplementaryMaterials={state.supplementaryMaterials}
              isReviewing={state.isReviewing}
              onConfirmAndStart={handleStartReview}
            />
            {state.isReviewing && (
              <div className="gt-card" aria-live="polite">
                <div className="gt-card-content">
                  <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', marginBottom: 'var(--gt-space-2)' }}>
                    正在分析：
                    <strong style={{ color: 'var(--gt-primary)' }}>
                      {state.currentDimension || '准备中...'}
                    </strong>
                  </p>
                  <div
                    role="progressbar"
                    aria-valuenow={progressPct}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label="复核进度"
                    style={{ width: '100%', height: 8, backgroundColor: '#e8e8e8', borderRadius: 'var(--gt-radius-sm)', overflow: 'hidden' }}
                  >
                    <div
                      style={{
                        width: `${progressPct}%`,
                        height: '100%',
                        backgroundColor: '#4b2d77',
                        borderRadius: 'var(--gt-radius-sm)',
                        transition: 'width 0.3s ease',
                      }}
                    />
                  </div>
                  <p style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', marginTop: 'var(--gt-space-1)', textAlign: 'right' }}>
                    {state.reviewProgress} / {totalDimensions} 维度已完成
                  </p>
                </div>
              </div>
            )}
          </div>
        );
      case 3:
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-5)' }}>
            <ReviewReportComponent
              report={state.report}
              isReviewing={state.isReviewing}
              reviewProgress={reviewProgressProp}
              onFindingStatusUpdate={handleFindingStatusUpdate}
              onExport={handleExport}
            />
            <CrossReferenceGraph analysis={state.crossReferenceAnalysis} />
          </div>
        );
      default:
        return null;
    }
  };
  // Fetch cross-references when entering step 3
  React.useEffect(() => {
    if (currentStep === 3 && state.reviewId) {
      fetchCrossReferences();
    }
  }, [currentStep, state.reviewId, fetchCrossReferences]);

  return (
    <section className="gt-container gt-section" aria-label="底稿复核工作流">
      <h2 className="gt-h2" style={{ marginBottom: 'var(--gt-space-4)' }}>
        底稿复核工作流
      </h2>

      {/* Step indicator */}
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

      {/* Error alert */}
      {error && (
        <div
          role="alert"
          style={{
            padding: 'var(--gt-space-3) var(--gt-space-4)',
            marginBottom: 'var(--gt-space-4)',
            backgroundColor: 'rgba(220, 53, 69, 0.08)',
            color: 'var(--gt-danger)',
            borderRadius: 'var(--gt-radius-sm)',
            fontSize: 'var(--gt-font-sm)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            aria-label="关闭错误提示"
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--gt-danger)',
              fontWeight: 600,
              fontSize: 'var(--gt-font-base)',
              padding: 'var(--gt-space-1)',
            }}
          >
            
          </button>
        </div>
      )}

      {/* Step content */}
      <div style={{ marginBottom: 'var(--gt-space-6)' }}>
        {renderStepContent()}
      </div>

      {/* Navigation buttons */}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--gt-space-4)' }}>
        <button
          className="gt-button gt-button--secondary"
          onClick={handlePrev}
          disabled={currentStep === 0 || state.isReviewing}
          aria-label="上一步"
        >
          上一步
        </button>
        {currentStep < STEPS.length - 1 && (
          <button
            className="gt-button gt-button--primary"
            onClick={handleNext}
            disabled={!canProceed()}
            aria-label="下一步"
          >
            下一步
          </button>
        )}
      </div>
    </section>
  );
};

export default ReviewWorkflow;