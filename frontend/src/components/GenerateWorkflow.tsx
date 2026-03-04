/**
 * GenerateWorkflow - 文档生成工作流容器
 *
 * 四步骤文档生成工作流：模板上传与配置 → 大纲识别与确认 → 逐章节生成与编辑 → 导出
 * 使用 gt-flow-diagram 步骤指示器展示进度，管理步骤间导航和状态传递。
 *
 * Requirements: 7.1, 10.3
 */
import React, { useState, useCallback } from 'react';
import type {
  TemplateOutlineItem,
  GeneratedSection,
  FontSettings,
  ProjectInfo,
} from '../types/audit';
import TemplateSelector from './TemplateSelector';
import TemplateOutlineEditor from './TemplateOutlineEditor';
import DocumentEditor from './DocumentEditor';
import ExportPanel from './ExportPanel';
import '../styles/gt-design-tokens.css';

/** 工作流步骤定义 */
const STEPS = [
  { label: '模板上传与配置', key: 'template' },
  { label: '大纲识别与确认', key: 'outline' },
  { label: '逐章节生成与编辑', key: 'generate' },
  { label: '导出', key: 'export' },
] as const;

/** 工作流状态 */
interface WorkflowState {
  selectedTemplateId: string;
  projectInfo: ProjectInfo;
  knowledgeLibraryIds: string[];
  outline: TemplateOutlineItem[];
  documentId: string;
  sections: GeneratedSection[];
  fontSettings: FontSettings;
}

const DEFAULT_PROJECT_INFO: ProjectInfo = {
  client_name: '',
  audit_period: '',
  key_matters: '',
};

const DEFAULT_FONT_SETTINGS: FontSettings = {
  chinese_font: '宋体',
  english_font: 'Times New Roman',
};

const GenerateWorkflow: React.FC = () => {
  const [currentStep, setCurrentStep] = useState(0);
  const [state, setState] = useState<WorkflowState>({
    selectedTemplateId: '',
    projectInfo: { ...DEFAULT_PROJECT_INFO },
    knowledgeLibraryIds: [],
    outline: [],
    documentId: '',
    sections: [],
    fontSettings: { ...DEFAULT_FONT_SETTINGS },
  });

  /** Navigate to next step */
  const handleNext = useCallback(() => {
    setCurrentStep((prev) => Math.min(prev + 1, STEPS.length - 1));
  }, []);

  /** Navigate to previous step */
  const handlePrev = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 0));
  }, []);

  /** Update workflow state from child components */
  const updateState = useCallback((patch: Partial<WorkflowState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  /** Determine if "Next" button should be enabled */
  const canProceed = (): boolean => {
    switch (currentStep) {
      case 0:
        return state.selectedTemplateId !== '';
      case 1:
        return state.outline.length > 0;
      case 2:
        return state.sections.length > 0;
      default:
        return false;
    }
  };

  /** Render placeholder content for each step (child components in tasks 21.2-21.7) */
  const renderStepContent = () => {
    switch (currentStep) {
      case 0:
        return (
          <TemplateSelector
            selectedTemplateId={state.selectedTemplateId}
            projectInfo={state.projectInfo}
            knowledgeLibraryIds={state.knowledgeLibraryIds}
            onTemplateSelect={(templateId) => updateState({ selectedTemplateId: templateId })}
            onProjectInfoChange={(info) => updateState({ projectInfo: info })}
            onKnowledgeLibraryIdsChange={(ids) => updateState({ knowledgeLibraryIds: ids })}
          />
        );
      case 1:
        return (
          <TemplateOutlineEditor
            templateId={state.selectedTemplateId}
            outline={state.outline}
            onOutlineChange={(newOutline) => updateState({ outline: newOutline })}
            onConfirm={handleNext}
          />
        );
      case 2:
        return (
          <DocumentEditor
            documentId={state.documentId}
            templateId={state.selectedTemplateId}
            outline={state.outline}
            sections={state.sections}
            projectInfo={state.projectInfo}
            knowledgeLibraryIds={state.knowledgeLibraryIds}
            onSectionsChange={(newSections) => updateState({ sections: newSections })}
            onDocumentIdChange={(id) => updateState({ documentId: id })}
          />
        );
      case 3:
        return (
          <ExportPanel
            sections={state.sections}
            documentId={state.documentId}
            templateId={state.selectedTemplateId}
            fontSettings={state.fontSettings}
            onFontSettingsChange={(settings) => updateState({ fontSettings: settings })}
          />
        );
      default:
        return null;
    }
  };

  return (
    <section className="gt-container gt-section" aria-label="文档生成工作流">
      <h2 className="gt-h2" style={{ marginBottom: 'var(--gt-space-4)' }}>
        文档生成工作流
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

      {/* Step content */}
      <div style={{ marginBottom: 'var(--gt-space-6)' }}>
        {renderStepContent()}
      </div>

      {/* Navigation buttons */}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--gt-space-4)' }}>
        <button
          className="gt-button gt-button--secondary"
          onClick={handlePrev}
          disabled={currentStep === 0}
          aria-label="上一步"
        >
          上一步
        </button>
        {currentStep < STEPS.length - 1 ? (
          <button
            className="gt-button gt-button--primary"
            onClick={handleNext}
            disabled={!canProceed()}
            aria-label="下一步"
          >
            下一步
          </button>
        ) : (
          <button
            className="gt-button gt-button--primary"
            disabled={state.sections.length === 0}
            aria-label="导出文档"
          >
            导出文档
          </button>
        )}
      </div>
    </section>
  );
};

export default GenerateWorkflow;
