/**
 * AuditReportResult - 复核报告组件
 * 统计仪表盘 + 按科目分组的卡片式问题清单 + 导出
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  ReportReviewFinding, ReportReviewResult, ReportReviewFindingCategory,
  FINDING_CATEGORY_LABELS, FINDING_CATEGORY_COLORS, RISK_LEVEL_COLORS,
} from '../types/audit';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

interface Props {
  sessionId: string | null;
  onBack?: () => void;
}

const RISK_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' };

const AuditReportResult: React.FC<Props> = ({ sessionId, onBack }) => {
  const [result, setResult] = useState<ReportReviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

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
      if (!resp.ok) {
        const errText = await resp.text();
        throw new Error(errText || '导出失败');
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `审计报告复核结果.${format === 'word' ? 'docx' : 'pdf'}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e?.message || '导出失败，请重试');
    }
    setExporting(false);
  }, [sessionId]);

  const toggleGroup = (account: string) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev);
      next.has(account) ? next.delete(account) : next.add(account);
      return next;
    });
  };

  if (loading) return <div style={{ textAlign: 'center', padding: 40, color: '#888' }}>加载中...</div>;
  if (!result) return (
    <div style={{ textAlign: 'center', padding: 60 }}>
      <p style={{ color: '#999', marginBottom: 24 }}>暂无复核结果</p>
      {onBack && (
        <button onClick={onBack} style={{ padding: '8px 24px', border: '1px solid #ddd', borderRadius: 8, cursor: 'pointer', background: '#fff', color: '#555' }}>
          ← 上一步
        </button>
      )}
    </div>
  );

  const allFindings = result.findings ?? [];
  const riskSummary = result.risk_summary || { high: 0, medium: 0, low: 0 };
  const categorySummary = result.category_summary || {};
  const confirmationSummary = result.confirmation_summary || { confirmed: allFindings.length, dismissed: 0, pending: 0 };

  // Group by account_name, preserve order
  const groupOrder: string[] = [];
  const grouped: Record<string, ReportReviewFinding[]> = {};
  for (const f of allFindings) {
    if (!grouped[f.account_name]) {
      grouped[f.account_name] = [];
      groupOrder.push(f.account_name);
    }
    grouped[f.account_name].push(f);
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      {/* 顶部统计仪表盘 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 24 }}>
        {/* 风险等级 */}
        <div style={{ background: '#fff', borderRadius: 12, padding: '20px 16px', textAlign: 'center', boxShadow: '0 1px 4px rgba(0,0,0,0.06)', border: '1px solid #f0f0f0' }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 12 }}>风险分布</div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 24 }}>
            {(['high', 'medium', 'low'] as const).map(level => (
              <div key={level}>
                <div style={{ fontSize: 28, fontWeight: 700, color: RISK_LEVEL_COLORS[level], lineHeight: 1.2 }}>{riskSummary[level]}</div>
                <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{RISK_LABELS[level]}风险</div>
              </div>
            ))}
          </div>
        </div>
        {/* 分类统计 */}
        <div style={{ background: '#fff', borderRadius: 12, padding: '20px 16px', textAlign: 'center', boxShadow: '0 1px 4px rgba(0,0,0,0.06)', border: '1px solid #f0f0f0' }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 12 }}>问题分类</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 6 }}>
            {Object.entries(categorySummary).filter(([, v]) => v > 0).map(([k, v]) => (
              <span key={k} style={{ fontSize: 11, padding: '3px 10px', borderRadius: 12, backgroundColor: FINDING_CATEGORY_COLORS[k as ReportReviewFindingCategory] || '#888', color: '#fff' }}>
                {FINDING_CATEGORY_LABELS[k as ReportReviewFindingCategory] || k} {v}
              </span>
            ))}
          </div>
        </div>
        {/* 确认状态 */}
        <div style={{ background: '#fff', borderRadius: 12, padding: '20px 16px', textAlign: 'center', boxShadow: '0 1px 4px rgba(0,0,0,0.06)', border: '1px solid #f0f0f0' }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 12 }}>确认状态</div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 24 }}>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#52c41a', lineHeight: 1.2 }}>{confirmationSummary.confirmed}</div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>已确认</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#bbb', lineHeight: 1.2 }}>{confirmationSummary.dismissed}</div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>已忽略</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#faad14', lineHeight: 1.2 }}>{confirmationSummary.pending}</div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>待确认</div>
            </div>
          </div>
        </div>
      </div>

      {/* 复核结论 */}
      {result.conclusion && (
        <div style={{ background: '#fafafa', borderRadius: 10, padding: '16px 20px', marginBottom: 24, borderLeft: '4px solid var(--gt-primary, #4b2d77)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#333', marginBottom: 4 }}>复核结论</div>
          <p style={{ fontSize: 13, color: '#555', margin: 0, lineHeight: 1.7 }}>{result.conclusion}</p>
        </div>
      )}

      {/* 问题清单标题 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#333' }}>
          问题清单
          <span style={{ fontSize: 12, color: '#999', fontWeight: 400, marginLeft: 8 }}>
            共 {allFindings.length} 个问题，{groupOrder.length} 个科目
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setCollapsedGroups(new Set())} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid #ddd', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#666' }}>全部展开</button>
          <button onClick={() => setCollapsedGroups(new Set(groupOrder))} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid #ddd', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#666' }}>全部折叠</button>
        </div>
      </div>

      {/* 按科目分组的卡片 */}
      {groupOrder.map(account => {
        const findings = grouped[account];
        const isCollapsed = collapsedGroups.has(account);
        const groupRisk = { high: 0, medium: 0, low: 0 };
        findings.forEach(f => { groupRisk[f.risk_level]++; });

        return (
          <div key={account} style={{ marginBottom: 12, borderRadius: 10, border: '1px solid #e8e8e8', overflow: 'hidden', background: '#fff' }}>
            {/* 科目分组头 */}
            <div
              onClick={() => toggleGroup(account)}
              style={{
                display: 'flex', alignItems: 'center', padding: '12px 16px', cursor: 'pointer',
                background: 'linear-gradient(135deg, #f8f6fb 0%, #f5f5f5 100%)',
                borderBottom: isCollapsed ? 'none' : '1px solid #eee',
                userSelect: 'none',
              }}
              role="button" tabIndex={0} aria-expanded={!isCollapsed}
              aria-label={`${account} ${findings.length} 个问题`}
            >
              <span style={{ fontSize: 13, color: '#888', marginRight: 8, transition: 'transform 0.2s', transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)', display: 'inline-block' }}>▼</span>
              <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--gt-primary, #4b2d77)', flex: 1 }}>{account}</span>
              <span style={{ fontSize: 12, color: '#999', marginRight: 12 }}>{findings.length} 个问题</span>
              {groupRisk.high > 0 && <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 10, background: '#fff1f0', color: '#cf1322', marginRight: 4 }}>高 {groupRisk.high}</span>}
              {groupRisk.medium > 0 && <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 10, background: '#fffbe6', color: '#d48806', marginRight: 4 }}>中 {groupRisk.medium}</span>}
              {groupRisk.low > 0 && <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 10, background: '#e6f7ff', color: '#096dd9' }}>低 {groupRisk.low}</span>}
            </div>

            {/* 问题列表 */}
            {!isCollapsed && (
              <div style={{ padding: '0' }}>
                {findings.map((f, idx) => (
                  <FindingRow key={f.id} finding={f} isLast={idx === findings.length - 1} />
                ))}
              </div>
            )}
          </div>
        );
      })}

      {allFindings.length === 0 && <p style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无问题</p>}

      {/* 底部操作栏 */}
      <div style={{
        display: 'flex', gap: 12, marginTop: 32, justifyContent: 'center',
        padding: '20px 0', borderTop: '1px solid #f0f0f0',
      }}>
        {onBack && (
          <button onClick={onBack} style={{ padding: '10px 28px', border: '1px solid #ddd', borderRadius: 8, cursor: 'pointer', background: '#fff', color: '#555', fontSize: 14 }}>
            ← 上一步
          </button>
        )}
        <button
          onClick={() => handleExport('word')}
          disabled={exporting}
          style={{
            padding: '10px 28px', border: 'none', borderRadius: 8, cursor: exporting ? 'not-allowed' : 'pointer',
            background: 'var(--gt-primary, #4b2d77)', color: '#fff', fontSize: 14, opacity: exporting ? 0.6 : 1,
          }}
        >
          {exporting ? '导出中...' : '导出 Word'}
        </button>
      </div>
    </div>
  );
};

/* 单条问题行组件 */
const FindingRow: React.FC<{ finding: ReportReviewFinding; isLast: boolean }> = ({ finding: f, isLast }) => {
  const riskColor = f.risk_level === 'high' ? '#cf1322' : f.risk_level === 'medium' ? '#d48806' : '#096dd9';
  const riskBg = f.risk_level === 'high' ? '#fff1f0' : f.risk_level === 'medium' ? '#fffbe6' : '#e6f7ff';

  return (
    <div style={{ padding: '14px 16px', borderBottom: isLast ? 'none' : '1px solid #f5f5f5', display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      {/* 左侧标签列 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flexShrink: 0, paddingTop: 2 }}>
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 10, textAlign: 'center',
          backgroundColor: FINDING_CATEGORY_COLORS[f.category] || '#888', color: '#fff', whiteSpace: 'nowrap',
        }}>
          {FINDING_CATEGORY_LABELS[f.category] || '未分类'}
        </span>
        <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 10, textAlign: 'center', backgroundColor: riskBg, color: riskColor, whiteSpace: 'nowrap' }}>
          {RISK_LABELS[f.risk_level]}风险
        </span>
      </div>
      {/* 右侧内容 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: '#333', lineHeight: 1.6 }}>{f.description}</div>
        {f.location && (
          <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>📍 {f.location}</div>
        )}
        {f.suggestion && (
          <div style={{ fontSize: 12, color: '#52c41a', marginTop: 4, background: '#f6ffed', padding: '4px 10px', borderRadius: 6, display: 'inline-block' }}>
            💡 {f.suggestion}
          </div>
        )}
      </div>
    </div>
  );
};

export default AuditReportResult;