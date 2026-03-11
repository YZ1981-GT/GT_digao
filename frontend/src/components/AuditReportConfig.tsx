/**
 * AuditReportConfig - 复核配置组件
 * Task 17.1: 提示词选择、自定义要求、变动阈值、模板类型显示、开始复核
 */
import React, { useState, useCallback } from 'react';
import { REPORT_TEMPLATE_TYPE_LABELS } from '../types/audit';
import { processSSEStream } from '../utils/sseParser';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

interface Props {
  sessionId: string | null;
  templateType: 'soe' | 'listed';
  onStart: () => void;
}

const AuditReportConfig: React.FC<Props> = ({ sessionId, templateType, onStart }) => {
  const [customPrompt, setCustomPrompt] = useState('');
  const [threshold, setThreshold] = useState(30);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);

  const handleStart = useCallback(async () => {
    if (!sessionId) return;
    setStarting(true);
    setError(null);
    setProgress(null);
    try {
      const resp = await fetch(`${API}/api/report-review/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          template_type: templateType,
          custom_prompt: customPrompt || undefined,
          change_threshold: threshold / 100,
        }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      // Consume SSE stream so backend populates findings
      await processSSEStream(
        resp,
        (data) => {
          try {
            const parsed = JSON.parse(data);
            if (parsed.status === 'account_complete') {
              setProgress(`正在复核: ${parsed.account_name || ''}...`);
            }
          } catch { /* non-JSON event, ignore */ }
        },
        () => { onStart(); },
        (err) => { setError(err.message); },
      );
    } catch (e: any) {
      setError(e.message || '启动复核失败');
    } finally {
      setStarting(false);
    }
  }, [sessionId, templateType, customPrompt, threshold, onStart]);

  return (
    <div style={{ maxWidth: 640 }}>
      <h3 style={{ fontSize: 16, marginBottom: 'var(--gt-space-4)' }}>复核配置</h3>

      {/* Template type display */}
      <div className="gt-card" style={{ padding: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-4)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontSize: 13, color: '#888' }}>当前模板类型：</span>
          <span style={{ fontWeight: 600, color: 'var(--gt-primary)' }}>{REPORT_TEMPLATE_TYPE_LABELS[templateType]}</span>
        </div>
        <button
          onClick={() => { /* Template editor is a separate view */ }}
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

      {error && <div className="gt-error" style={{ color: 'var(--gt-danger)', borderLeft: '3px solid var(--gt-danger)', paddingLeft: 8, marginBottom: 'var(--gt-space-3)' }}>{error}</div>}

      {progress && <div style={{ fontSize: 13, color: 'var(--gt-primary)', marginBottom: 'var(--gt-space-3)' }}>{progress}</div>}

      <button
        className="gt-button"
        style={{ backgroundColor: 'var(--gt-primary)', color: '#fff', padding: '10px 32px', border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 15, fontWeight: 600 }}
        onClick={handleStart}
        disabled={starting}
      >
        {starting ? '正在启动复核...' : '开始复核'}
      </button>
    </div>
  );
};

export default AuditReportConfig;
