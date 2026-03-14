/**
 * AuditReportWorkflow - 审计报告复核五步工作流容器
 * Task 14.1: 文件上传 → 科目对照 → 复核配置 → 问题确认 → 复核报告
 */
import React, { useState, useCallback } from 'react';
import AuditReportUpload from './AuditReportUpload';
import AccountMatchingView from './AccountMatchingView';
import AuditReportConfig from './AuditReportConfig';
import FindingConfirmationView from './FindingConfirmationView';
import AuditReportResult from './AuditReportResult';

const STEPS = [
  { label: '文件上传', key: 'upload' },
  { label: '科目对照', key: 'matching' },
  { label: '复核配置', key: 'config' },
  { label: '问题确认', key: 'confirmation' },
  { label: '复核报告', key: 'result' },
] as const;

type StepKey = typeof STEPS[number]['key'];  // eslint-disable-line @typescript-eslint/no-unused-vars

interface WorkflowState {
  sessionId: string | null;
  templateType: 'soe' | 'listed';
}

const AuditReportWorkflow: React.FC = () => {
  const [currentStep, setCurrentStep] = useState<number>(0);
  const [state, setState] = useState<WorkflowState>({
    sessionId: null,
    templateType: 'soe',
  });

  const goNext = useCallback(() => {
    setCurrentStep(prev => Math.min(prev + 1, STEPS.length - 1));
  }, []);

  const goPrev = useCallback(() => {
    setCurrentStep(prev => Math.max(prev - 1, 0));
  }, []);

  const handleUploadComplete = useCallback((sessionId: string, templateType: 'soe' | 'listed') => {
    setState(prev => ({ ...prev, sessionId, templateType }));
    goNext();
  }, [goNext]);

  const renderStep = () => {
    switch (STEPS[currentStep].key) {
      case 'upload':
        return <AuditReportUpload onComplete={handleUploadComplete} />;
      case 'matching':
        return <AccountMatchingView sessionId={state.sessionId} onConfirm={goNext} />;
      case 'config':
        return <AuditReportConfig sessionId={state.sessionId} templateType={state.templateType} onStart={goNext} />;
      case 'confirmation':
        return <FindingConfirmationView sessionId={state.sessionId} onComplete={goNext} />;
      case 'result':
        return <AuditReportResult sessionId={state.sessionId} onBack={goPrev} />;
      default:
        return null;
    }
  };

  return (
    <div className="gt-card" style={{ margin: 'var(--gt-space-4)', minHeight: '80vh' }}>
      {/* 步骤指示器 */}
      <div className="gt-flow-diagram" style={{ display: 'flex', justifyContent: 'center', padding: 'var(--gt-space-4)', gap: 'var(--gt-space-2)' }}>
        {STEPS.map((step, idx) => (
          <div
            key={step.key}
            className={`gt-flow-step ${idx === currentStep ? 'gt-active' : ''} ${idx < currentStep ? 'gt-completed' : ''}`}
            style={{
              display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)',
              cursor: idx <= currentStep ? 'pointer' : 'default',
              opacity: idx <= currentStep ? 1 : 0.5,
            }}
            onClick={() => idx <= currentStep && setCurrentStep(idx)}
            role="button"
            tabIndex={0}
            aria-label={`步骤 ${idx + 1}: ${step.label}`}
            aria-current={idx === currentStep ? 'step' : undefined}
          >
            <span
              className="gt-step-number"
              style={{
                width: 28, height: 28, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                backgroundColor: idx <= currentStep ? 'var(--gt-primary, #4b2d77)' : 'var(--gt-light-gray, #ccc)',
                color: '#fff', fontSize: 14, fontWeight: 600,
              }}
            >
              {idx < currentStep ? '✓' : idx + 1}
            </span>
            <span style={{ fontSize: 14, fontWeight: idx === currentStep ? 600 : 400 }}>{step.label}</span>
            {idx < STEPS.length - 1 && <span style={{ margin: '0 var(--gt-space-1)', color: '#ccc' }}>→</span>}
          </div>
        ))}
      </div>

      {/* 步骤内容 */}
      <div className="gt-card-content" style={{ padding: 'var(--gt-space-4)' }}>
        {renderStep()}
      </div>

      {/* 导航按钮 */}
      {currentStep > 0 && currentStep < STEPS.length - 1 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: 'var(--gt-space-4)' }}>
          <button className="gt-button" onClick={goPrev}>上一步</button>
        </div>
      )}
    </div>
  );
};

export default AuditReportWorkflow;
