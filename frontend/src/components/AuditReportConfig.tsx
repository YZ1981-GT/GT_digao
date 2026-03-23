/**
 * AuditReportConfig - 复核配置组件
 * Task 17.1: 提示词选择、自定义要求、变动阈值、模板类型显示、开始复核
 */
import React, { useState, useCallback } from 'react';
import { REPORT_TEMPLATE_TYPE_LABELS } from '../types/audit';
import { processSSEStream } from '../utils/sseParser';
import TemplateEditorView from './TemplateEditorView';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

interface Props {
  sessionId: string | null;
  templateType: 'soe' | 'listed';
  onStart: () => void;
}

/** 复核阶段定义 */
const REVIEW_PHASES = [
  { key: 'structure_analysis', label: '结构识别' },
  { key: 'reconciliation', label: '数值校验' },
  { key: 'body_review', label: '正文复核' },
  { key: 'note_review', label: '附注复核' },
  { key: 'text_quality', label: '文本质量' },
] as const;

type PhaseKey = typeof REVIEW_PHASES[number]['key'];

const AuditReportConfig: React.FC<Props> = ({ sessionId, templateType, onStart }) => {
  const [customPrompt, setCustomPrompt] = useState('');
  const [threshold, setThreshold] = useState(30);
  const [amountThreshold, setAmountThreshold] = useState(0);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [showTemplateEditor, setShowTemplateEditor] = useState(false);
  const [currentPhase, setCurrentPhase] = useState<PhaseKey | null>(null);
  const [completedPhases, setCompletedPhases] = useState<Set<PhaseKey>>(new Set());
  const [accountProgress, setAccountProgress] = useState<string | null>(null);
  const [localReviewDone, setLocalReviewDone] = useState(false);
  const [showLlmWarning, setShowLlmWarning] = useState(false);
  const [currentReviewMode, setCurrentReviewMode] = useState<'local' | 'llm' | 'full' | null>(null);

  /** 每个阶段的完成信息 */
  interface PhaseResult {
    message: string;
    findingsCount: number;
    changeFindingsCount?: number;
    details: string[];
    breakdown?: Record<string, number>;
  }

  const [phaseResults, setPhaseResults] = useState<Record<string, PhaseResult>>({});
  const [reviewDone, setReviewDone] = useState(false);
  const [totalFindings, setTotalFindings] = useState(0);

  const handleStart = useCallback(async (reviewMode: 'local' | 'llm' | 'full' = 'full') => {
    if (!sessionId) return;
    setStarting(true);
    setError(null);
    setProgress(null);
    setCurrentPhase(null);
    setCompletedPhases(new Set());
    setAccountProgress(null);
    setPhaseResults({});
    setReviewDone(false);
    setTotalFindings(0);
    setCurrentReviewMode(reviewMode);
    try {
      const resp = await fetch(`${API}/api/report-review/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          template_type: templateType,
          custom_prompt: customPrompt || undefined,
          change_threshold: threshold / 100,
          change_amount_threshold: amountThreshold * 10000,
          review_mode: reviewMode,
        }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      let prevPhase: PhaseKey | null = null;
      await processSSEStream(
        resp,
        (data) => {
          try {
            const parsed = JSON.parse(data);
            if (parsed.status === 'phase') {
              // Mark previous phase as completed
              if (prevPhase) {
                setCompletedPhases(prev => new Set(prev).add(prevPhase!));
              }
              prevPhase = parsed.phase as PhaseKey;
              setCurrentPhase(parsed.phase as PhaseKey);
              setProgress(parsed.message || '');
              setAccountProgress(null);
            } else if (parsed.status === 'phase_progress') {
              setProgress(parsed.message || '');
            } else if (parsed.status === 'phase_complete') {
              const phase = parsed.phase as PhaseKey;
              setCompletedPhases(prev => new Set(prev).add(phase));
              setPhaseResults(prev => ({
                ...prev,
                [phase]: {
                  message: parsed.message || '',
                  findingsCount: parsed.findings_count ?? 0,
                  changeFindingsCount: parsed.change_findings_count,
                  details: parsed.details || [],
                  breakdown: parsed.breakdown,
                },
              }));
            } else if (parsed.status === 'account_complete') {
              setAccountProgress(`${parsed.account_name || ''} (发现 ${parsed.findings_count ?? 0} 个问题)`);
            } else if (parsed.status === 'completed') {
              // Mark last phase as completed
              if (prevPhase) {
                setCompletedPhases(prev => new Set(prev).add(prevPhase!));
              }
              setCurrentPhase(null);
              setProgress('复核完成');
              setReviewDone(true);
              // 本地复核完成后标记
              if (reviewMode === 'local' || reviewMode === 'full') {
                setLocalReviewDone(true);
              }
              // Count total findings
              const result = parsed.result;
              if (result?.findings) {
                setTotalFindings(result.findings.length);
              }
            }
          } catch { /* non-JSON event, ignore */ }
        },
        () => { /* stream ended, user clicks to proceed */ },
        (err) => { setError(err.message); },
      );
    } catch (e: any) {
      setError(e.message || '启动复核失败');
    } finally {
      setStarting(false);
    }
  }, [sessionId, templateType, customPrompt, threshold, amountThreshold, onStart]);

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
      {/* 左侧：配置面板 */}
      <div style={{ flex: '0 0 420px', maxWidth: 420 }}>
      <h3 style={{ fontSize: 16, marginBottom: 'var(--gt-space-4)' }}>复核配置</h3>

      {/* Template type display */}
      <div className="gt-card" style={{ padding: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-4)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontSize: 13, color: '#888' }}>当前模板类型：</span>
          <span style={{ fontWeight: 600, color: 'var(--gt-primary)' }}>{REPORT_TEMPLATE_TYPE_LABELS[templateType]}</span>
        </div>
        <button
          onClick={() => setShowTemplateEditor(true)}
          style={{ fontSize: 12, color: 'var(--gt-primary)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}
        >
          查看/编辑模板
        </button>
      </div>

      {/* Custom prompt */}
      <div style={{ marginBottom: 'var(--gt-space-4)' }}>
        <label style={{ fontSize: 14, fontWeight: 600, display: 'block', marginBottom: 8 }}>自定义复核要求</label>
        <textarea
          value={customPrompt}
          onChange={e => setCustomPrompt(e.target.value)}
          placeholder="输入额外的复核要求，将与预设提示词合并..."
          rows={4}
          style={{ width: '100%', padding: 8, border: '1px solid #ddd', borderRadius: 'var(--gt-radius-md, 6px)', fontSize: 13, resize: 'vertical' }}
          aria-label="自定义复核要求"
        />
      </div>

      {/* Threshold */}
      <div style={{ marginBottom: 'var(--gt-space-4)' }}>
        <label style={{ fontSize: 14, fontWeight: 600, display: 'block', marginBottom: 8 }}>
          变动阈值：{threshold}%
        </label>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-3)' }}>
          <input
            type="range"
            min={5} max={100} value={threshold}
            onChange={e => setThreshold(Number(e.target.value))}
            style={{ flex: 1 }}
            aria-label="变动阈值滑块"
          />
          <input
            type="number"
            min={5} max={100} value={threshold}
            onChange={e => setThreshold(Math.min(100, Math.max(5, Number(e.target.value))))}
            style={{ width: 60, padding: 4, border: '1px solid #ddd', borderRadius: 4, textAlign: 'center' }}
            aria-label="变动阈值数值"
          />
        </div>
        <p style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
          超过此阈值的科目变动将触发异常分析（默认30%）
        </p>
      </div>

      {/* Amount Threshold */}
      <div style={{ marginBottom: 'var(--gt-space-4)' }}>
        <label style={{ fontSize: 14, fontWeight: 600, display: 'block', marginBottom: 8 }}>
          金额阈值：{amountThreshold > 0 ? `${amountThreshold}万元` : '不限'}
        </label>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-3)' }}>
          <input
            type="range"
            min={0} max={100000} step={100} value={amountThreshold}
            onChange={e => setAmountThreshold(Number(e.target.value))}
            style={{ flex: 1 }}
            aria-label="金额阈值滑块"
          />
          <input
            type="number"
            min={0} max={1000000} step={100} value={amountThreshold}
            onChange={e => setAmountThreshold(Math.max(0, Number(e.target.value)))}
            style={{ width: 80, padding: 4, border: '1px solid #ddd', borderRadius: 4, textAlign: 'center' }}
            aria-label="金额阈值数值"
          />
          <span style={{ fontSize: 13, color: '#666' }}>万元</span>
        </div>
        <p style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
          变动金额低于此值的科目不报异常，用于过滤基数小但变动比率大的情况（0=不限）
        </p>
      </div>

      {error && <div className="gt-error" style={{ color: 'var(--gt-danger)', borderLeft: '3px solid var(--gt-danger)', paddingLeft: 8, marginBottom: 'var(--gt-space-3)' }}>{error}</div>}

      {/* 复核进度面板 */}
      {starting && (
        <div style={{ marginBottom: 'var(--gt-space-4)', padding: 12, border: '1px solid #e0d8ec', borderRadius: 8, backgroundColor: '#faf8fd' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: 'var(--gt-primary)' }}>复核进度</div>
          <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
            {REVIEW_PHASES.map((phase) => {
              const isCompleted = completedPhases.has(phase.key);
              const isCurrent = currentPhase === phase.key;
              return (
                <div key={phase.key} style={{ flex: 1, textAlign: 'center' }}>
                  <div style={{
                    height: 6, borderRadius: 3, marginBottom: 4,
                    backgroundColor: isCompleted ? 'var(--gt-primary, #4b2d77)' : isCurrent ? '#b39ddb' : '#e0e0e0',
                    transition: 'background-color 0.3s',
                    animation: isCurrent ? 'pulse 1.5s ease-in-out infinite' : 'none',
                  }} />
                  <span style={{
                    fontSize: 11,
                    color: isCompleted ? 'var(--gt-primary, #4b2d77)' : isCurrent ? '#7c4dff' : '#999',
                    fontWeight: isCurrent ? 600 : 400,
                  }}>
                    {isCompleted ? '✓ ' : ''}{phase.label}
                  </span>
                </div>
              );
            })}
          </div>
          {progress && <div style={{ fontSize: 12, color: '#555' }}>{progress}</div>}
          {accountProgress && <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>  └ {accountProgress}</div>}
          <style>{`@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }`}</style>
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <button
          className="gt-button"
          style={{
            backgroundColor: 'var(--gt-primary)', color: '#fff', padding: '10px 28px',
            border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 14, fontWeight: 600,
            opacity: starting ? 0.6 : 1,
          }}
          onClick={() => handleStart('local')}
          disabled={starting}
          title="仅执行本地规则校验，不调用 LLM，速度快"
        >
          {starting && currentReviewMode === 'local' ? '本地复核中...' : '📋 本地复核'}
        </button>
        <button
          className="gt-button"
          style={{
            backgroundColor: localReviewDone ? '#7c4dff' : '#ccc',
            color: '#fff', padding: '10px 28px',
            border: 'none', borderRadius: 8,
            cursor: localReviewDone && !starting ? 'pointer' : 'not-allowed',
            fontSize: 14, fontWeight: 600,
            opacity: starting ? 0.6 : 1,
          }}
          onClick={() => {
            if (!localReviewDone) {
              setShowLlmWarning(true);
              return;
            }
            handleStart('llm');
          }}
          disabled={starting}
          title="在本地复核基础上，调用 LLM 进行智能增强复核"
        >
          {starting && currentReviewMode === 'llm' ? 'LLM复核中...' : '🤖 LLM复核'}
        </button>
      </div>
      </div>{/* 左侧配置面板结束 */}

      {/* 右侧：复核详情面板 */}
      <div style={{
        flex: 1, minWidth: 0,
        border: '1px solid #e0d8ec', borderRadius: 10,
        backgroundColor: '#faf8fd', padding: 16,
        minHeight: 400, maxHeight: 'calc(100vh - 240px)', overflowY: 'auto',
      }}>
        {!starting && !reviewDone && (
          <div style={{ textAlign: 'center', color: '#bbb', padding: 60, fontSize: 14 }}>
            点击"本地复核"开始基础校验，完成后可选择"LLM复核"进行智能增强分析
          </div>
        )}

        {(starting || reviewDone) && (
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--gt-primary)', marginBottom: 12 }}>
              复核详情
            </div>

            {REVIEW_PHASES.map((phase) => {
              const isCompleted = completedPhases.has(phase.key);
              const isCurrent = currentPhase === phase.key;
              const result = phaseResults[phase.key];

              return (
                <div key={phase.key} style={{
                  marginBottom: 10, padding: '10px 14px',
                  borderRadius: 8,
                  border: isCurrent ? '1px solid var(--gt-primary, #4b2d77)' : '1px solid #e8e4f0',
                  backgroundColor: isCompleted ? '#f0edf6' : isCurrent ? '#fff' : '#faf8fd',
                  transition: 'all 0.3s',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: '50%', display: 'inline-flex',
                      alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 600,
                      backgroundColor: isCompleted ? 'var(--gt-primary, #4b2d77)' : isCurrent ? '#b39ddb' : '#e0e0e0',
                      color: '#fff', flexShrink: 0,
                    }}>
                      {isCompleted ? '✓' : isCurrent ? '…' : ''}
                    </span>
                    <span style={{
                      fontSize: 13, fontWeight: 600,
                      color: isCompleted ? 'var(--gt-primary, #4b2d77)' : isCurrent ? '#7c4dff' : '#999',
                    }}>
                      {phase.label}
                    </span>
                    {isCompleted && result && (
                      <span style={{
                        marginLeft: 'auto', fontSize: 12,
                        color: result.findingsCount > 0 ? 'var(--gt-danger, #e53935)' : 'var(--gt-success, green)',
                        fontWeight: 600,
                      }}>
                        {result.findingsCount > 0
                          ? `发现 ${result.findingsCount} 个问题` + (result.changeFindingsCount ? `，变动提示 ${result.changeFindingsCount} 个` : '')
                          : (result.changeFindingsCount ? `变动提示 ${result.changeFindingsCount} 个` : '未发现问题')}
                      </span>
                    )}
                    {isCurrent && (
                      <span style={{ marginLeft: 'auto', fontSize: 12, color: '#7c4dff' }}>
                        进行中...
                      </span>
                    )}
                  </div>
                  {isCompleted && result && result.message && (
                    <div style={{ fontSize: 12, color: '#666', marginTop: 6, paddingLeft: 30 }}>
                      {result.details && result.details.length > 0 ? (
                        <ul style={{ margin: 0, paddingLeft: 16, listStyle: 'none' }}>
                          {result.details.map((d, idx) => (
                            <li key={idx} style={{ marginBottom: 2, lineHeight: 1.6 }}>
                              <span style={{ color: '#999', marginRight: 4 }}>•</span>{d}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        result.message
                      )}
                      {result.breakdown && Object.keys(result.breakdown).length > 0 && (
                        <div style={{
                          marginTop: 6, padding: '6px 12px', background: '#fdf0ef',
                          borderRadius: 6, border: '1px solid #f5c6cb', fontSize: 12,
                        }}>
                          <span style={{ fontWeight: 600, color: '#c62828' }}>
                            问题构成（{result.findingsCount} 个）：
                          </span>
                          {(() => {
                            const labels: Record<string, string> = {
                              amount_inconsistency: '报表与附注金额不符',
                              reconciliation_error: '勾稽错误',
                              note_missing: '有余额科目缺失附注',
                            };
                            return Object.entries(result.breakdown).map(([k, v]) => (
                              <span key={k} style={{ marginLeft: 8 }}>
                                {labels[k] || k} {v} 个
                              </span>
                            ));
                          })()}
                        </div>
                      )}
                    </div>
                  )}
                  {isCurrent && progress && (
                    <div style={{ fontSize: 12, color: '#888', marginTop: 6, paddingLeft: 30 }}>
                      {progress}
                      {accountProgress && <div style={{ marginTop: 2 }}>└ {accountProgress}</div>}
                    </div>
                  )}
                </div>
              );
            })}

            {/* 复核完成汇总 */}
            {reviewDone && (
              <div style={{
                marginTop: 16, padding: '14px 16px',
                borderRadius: 8, border: '2px solid var(--gt-primary, #4b2d77)',
                backgroundColor: '#f7f5fb',
              }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--gt-primary)', marginBottom: 8 }}>
                  ✅ {currentReviewMode === 'local' ? '本地复核完成' : currentReviewMode === 'llm' ? 'LLM复核完成' : '复核完成'}
                </div>
                <div style={{ fontSize: 13, color: '#555', marginBottom: 12 }}>
                  共发现 <span style={{ fontWeight: 700, color: 'var(--gt-danger, #e53935)' }}>{totalFindings}</span> 个问题
                  {currentReviewMode === 'local' && '。可继续点击"LLM复核"进行智能增强分析。'}
                  {currentReviewMode !== 'local' && '，请确认后进入下一步进行问题审核。'}
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                  {currentReviewMode === 'local' && (
                    <button
                      onClick={() => handleStart('llm')}
                      disabled={starting}
                      style={{
                        padding: '8px 28px', border: 'none', borderRadius: 8, cursor: 'pointer',
                        background: 'linear-gradient(135deg, #7c4dff 0%, #b388ff 100%)',
                        color: '#fff', fontSize: 14, fontWeight: 600,
                        boxShadow: '0 2px 10px rgba(124,77,255,0.3)',
                      }}
                    >
                      🤖 继续LLM复核
                    </button>
                  )}
                  <button
                    onClick={onStart}
                    style={{
                      padding: '8px 28px', border: 'none', borderRadius: 8, cursor: 'pointer',
                      background: 'linear-gradient(135deg, var(--gt-primary, #4b2d77) 0%, #7c4dff 100%)',
                      color: '#fff', fontSize: 14, fontWeight: 600,
                      boxShadow: '0 2px 10px rgba(75,45,119,0.3)',
                    }}
                  >
                    确认并继续 →
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* LLM复核提示弹窗 */}
      {showLlmWarning && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.4)', zIndex: 10000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowLlmWarning(false); }}
          role="dialog"
          aria-label="LLM复核提示"
          aria-modal="true"
        >
          <div style={{
            backgroundColor: '#fff', borderRadius: 12, padding: '28px 32px',
            maxWidth: 420, width: '90%', boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: '#333', marginBottom: 12 }}>
              请先完成本地复核
            </div>
            <div style={{ fontSize: 14, color: '#666', marginBottom: 20, lineHeight: 1.6 }}>
              LLM复核需要在本地复核完成后运行。请先点击"本地复核"完成基础校验，再运行LLM增强复核。
            </div>
            <button
              onClick={() => setShowLlmWarning(false)}
              style={{
                padding: '8px 32px', border: 'none', borderRadius: 8,
                backgroundColor: 'var(--gt-primary, #4b2d77)', color: '#fff',
                fontSize: 14, fontWeight: 600, cursor: 'pointer',
              }}
            >
              知道了
            </button>
          </div>
        </div>
      )}

      {/* 模板编辑器弹窗 */}
      {showTemplateEditor && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 10000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowTemplateEditor(false); }}
          role="dialog"
          aria-label="模板编辑器"
          aria-modal="true"
        >
          <div style={{
            backgroundColor: '#fff', borderRadius: 12, width: '90vw', maxWidth: 1100,
            height: '80vh', display: 'flex', flexDirection: 'column',
            boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '12px 20px', borderBottom: '1px solid #eee',
            }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--gt-primary)' }}>模板编辑器</span>
              <button
                onClick={() => setShowTemplateEditor(false)}
                style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#999', padding: '4px 8px' }}
                aria-label="关闭模板编辑器"
              >
                ✕
              </button>
            </div>
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <TemplateEditorView />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AuditReportConfig;
