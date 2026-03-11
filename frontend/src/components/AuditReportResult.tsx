/**
 * AuditReportResult - 复核报告组件
 * Task 18.1: 统计仪表盘、问题清单按科目分组、Finding状态管理、导出
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  ReportReviewFinding, ReportReviewResult, ReportReviewFindingCategory,
  FINDING_CATEGORY_LABELS, FINDING_CATEGORY_COLORS, RISK_LEVEL_COLORS,
} from '../types/audit';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

interface Props {
  sessionId: string | null;
}

const AuditReportResult: React.FC<Props> = ({ sessionId }) => {
  const [result, setResult] = useState<ReportReviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    fetch(`${API}/api/report-review/result/${sessionId}`)
      .then(r => r.json())
      .then(data => setResult(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sessionId]);

  const handleExport = useCallback(async (format: 'word' | 'pdf') => {
    if (!sessionId) return;
    setExporting(true);
    try {
      const resp = await fetch(`${API}/api/report-review/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, format }),
      });
      if (!resp.ok) throw new Error('导出失败');
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `审计报告复核结果.${format === 'word' ? 'docx' : 'pdf'}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
    setExporting(false);
  }, [sessionId]);

  const updateFindingStatus = async (findingId: string) => {
    await fetch(`${API}/api/report-review/finding/${findingId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'resolved' }),
    });
    // Reload
    if (sessionId) {
      const r = await fetch(`${API}/api/report-review/result/${sessionId}`);
      setResult(await r.json());
    }
  };

  if (loading) return <div style={{ textAlign: 'center', padding: 40 }}>加载中...</div>;
  if (!result) return <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>暂无复核结果</div>;

  const confirmedFindings = result.findings.filter(f => f.confirmation_status === 'confirmed');

  // Group by account_name
  const grouped = confirmedFindings.reduce<Record<string, ReportReviewFinding[]>>((acc, f) => {
    if (!acc[f.account_name]) acc[f.account_name] = [];
    acc[f.account_name].push(f);
    return acc;
  }, {});

  return (
    <div>
      {/* Dashboard */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-4)' }}>
        {/* Risk summary */}
        <div className="gt-card" style={{ padding: 'var(--gt-space-3)', textAlign: 'center' }}>
          <div style={{ fontSize: 13, color: '#888', marginBottom: 8 }}>按风险等级</div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 16 }}>
            {(['high', 'medium', 'low'] as const).map(level => (
              <div key={level}>
                <div style={{ fontSize: 24, fontWeight: 700, color: RISK_LEVEL_COLORS[level] }}>
                  {result.risk_summary[level]}
                </div>
                <div style={{ fontSize: 11 }}>{level === 'high' ? '高' : level === 'medium' ? '中' : '低'}</div>
              </div>
            ))}
          </div>
        </div>
        {/* Category summary */}
        <div className="gt-card" style={{ padding: 'var(--gt-space-3)', textAlign: 'center' }}>
          <div style={{ fontSize: 13, color: '#888', marginBottom: 8 }}>按分类</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 8 }}>
            {Object.entries(result.category_summary).filter(([, v]) => v > 0).map(([k, v]) => (
              <span key={k} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, backgroundColor: FINDING_CATEGORY_COLORS[k as ReportReviewFindingCategory], color: '#fff' }}>
                {FINDING_CATEGORY_LABELS[k as ReportReviewFindingCategory]}: {v}
              </span>
            ))}
          </div>
        </div>
        {/* Confirmation summary */}
        <div className="gt-card" style={{ padding: 'var(--gt-space-3)', textAlign: 'center' }}>
          <div style={{ fontSize: 13, color: '#888', marginBottom: 8 }}>确认状态</div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 16 }}>
            <div><div style={{ fontSize: 24, fontWeight: 700, color: 'var(--gt-success, green)' }}>{result.confirmation_summary.confirmed}</div><div style={{ fontSize: 11 }}>已确认</div></div>
            <div><div style={{ fontSize: 24, fontWeight: 700, color: '#999' }}>{result.confirmation_summary.dismissed}</div><div style={{ fontSize: 11 }}>已忽略</div></div>
            <div><div style={{ fontSize: 24, fontWeight: 700, color: 'var(--gt-warning)' }}>{result.confirmation_summary.pending}</div><div style={{ fontSize: 11 }}>待确认</div></div>
          </div>
        </div>
      </div>

      {/* Conclusion */}
      {result.conclusion && (
        <div className="gt-card" style={{ padding: 'var(--gt-space-3)', marginBottom: 'var(--gt-space-4)' }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>复核结论</div>
          <p style={{ fontSize: 13, color: '#555', whiteSpace: 'pre-wrap' }}>{result.conclusion}</p>
        </div>
      )}

      {/* Findings grouped by account */}
      <h3 style={{ fontSize: 16, marginBottom: 'var(--gt-space-3)' }}>已确认问题清单</h3>
      {Object.entries(grouped).map(([account, findings]) => (
        <div key={account} style={{ marginBottom: 'var(--gt-space-4)' }}>
          <h4 style={{ fontSize: 14, color: 'var(--gt-primary)', marginBottom: 8 }}>{account} ({findings.length})</h4>
          <table className="gt-table" style={{ width: '100%' }}>
            <caption className="sr-only">{account}相关问题</caption>
            <thead>
              <tr>
                <th scope="col">分类</th>
                <th scope="col">风险</th>
                <th scope="col">描述</th>
                <th scope="col">建议</th>
                <th scope="col">状态</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {findings.map(f => (
                <tr key={f.id}>
                  <td><span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3, backgroundColor: FINDING_CATEGORY_COLORS[f.category], color: '#fff' }}>{FINDING_CATEGORY_LABELS[f.category]}</span></td>
                  <td><span style={{ color: RISK_LEVEL_COLORS[f.risk_level], fontWeight: 600 }}>{f.risk_level === 'high' ? '高' : f.risk_level === 'medium' ? '中' : '低'}</span></td>
                  <td style={{ fontSize: 13 }}>{f.description}</td>
                  <td style={{ fontSize: 13 }}>{f.suggestion}</td>
                  <td style={{ fontSize: 12 }}>{f.status}</td>
                  <td>
                    {f.status === 'open' && (
                      <button onClick={() => updateFindingStatus(f.id)} style={{ fontSize: 11, padding: '2px 8px', backgroundColor: 'var(--gt-success, green)', color: '#fff', border: 'none', borderRadius: 3, cursor: 'pointer' }}>
                        标记已解决
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {confirmedFindings.length === 0 && <p style={{ textAlign: 'center', color: '#999' }}>暂无已确认的问题</p>}

      {/* Export buttons */}
      <div style={{ display: 'flex', gap: 'var(--gt-space-3)', marginTop: 'var(--gt-space-4)', justifyContent: 'center' }}>
        <button
          className="gt-button"
          style={{ backgroundColor: 'var(--gt-primary)', color: '#fff', padding: '8px 24px', border: 'none', borderRadius: 8, cursor: 'pointer' }}
          onClick={() => handleExport('word')}
          disabled={exporting}
        >
          导出 Word
        </button>
        <button
          className="gt-button"
          style={{ backgroundColor: 'var(--gt-primary)', color: '#fff', padding: '8px 24px', border: 'none', borderRadius: 8, cursor: 'pointer' }}
          onClick={() => handleExport('pdf')}
          disabled={exporting}
        >
          导出 PDF
        </button>
      </div>
    </div>
  );
};

export default AuditReportResult;
