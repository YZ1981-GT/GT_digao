/**
 * AuditReportResult - 复核报告组件
 * 统计仪表盘 + 按科目分组的卡片式问题清单 + 单条确认/忽略/编辑 + 批量操作 + 导出
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  ReportReviewFinding, ReportReviewResult, ReportReviewFindingCategory,
  FindingConfirmationStatus,
  FINDING_CATEGORY_LABELS, FINDING_CATEGORY_COLORS, RISK_LEVEL_COLORS,
  CONFIRMATION_STATUS_LABELS,
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
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDesc, setEditDesc] = useState('');

  const loadResult = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/report-review/result/${sessionId}`);
      const data = await r.json();
      setResult(data);
    } catch { /* ignore */ }
    setLoading(false);
  }, [sessionId]);

  useEffect(() => { loadResult(); }, [loadResult]);

  const handleExport = useCallback(async (format: 'word' | 'pdf') => {
    if (!sessionId) return;
    setExporting(true);
    try {
      const resp = await fetch(`${API}/api/report-review/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, format }),
      });
      if (!resp.ok) throw new Error(await resp.text() || '导出失败');
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

  const toggleCheck = (id: string) => {
    setCheckedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  /* 单条确认/忽略/恢复 */
  const updateStatus = async (id: string, action: 'confirm' | 'dismiss' | 'restore') => {
    try {
      await fetch(`${API}/api/report-review/finding/${id}/${action}`, { method: 'PATCH' });
    } catch { /* ignore */ }
    loadResult();
  };

  /* 批量操作 */
  const batchAction = async (action: 'confirm' | 'dismiss') => {
    if (checkedIds.size === 0) return;
    try {
      await fetch(`${API}/api/report-review/findings/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ finding_ids: Array.from(checkedIds), action }),
      });
    } catch { /* ignore */ }
    setCheckedIds(new Set());
    loadResult();
  };

  /* 编辑描述 */
  const startEdit = (f: ReportReviewFinding) => {
    setEditingId(f.id);
    setEditDesc(f.description || '');
  };
  const saveEdit = async () => {
    if (!editingId) return;
    try {
      await fetch(`${API}/api/report-review/finding/${editingId}/edit`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: editDesc }),
      });
    } catch { /* ignore */ }
    setEditingId(null);
    loadResult();
  };
  const cancelEdit = () => { setEditingId(null); };

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
  const confirmed = allFindings.filter(f => f.confirmation_status === 'confirmed').length;
  const dismissed = allFindings.filter(f => f.confirmation_status === 'dismissed').length;
  const pending = allFindings.filter(f => f.confirmation_status === 'pending_confirmation').length;

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

  /* 状态标签颜色 */
  const statusStyle = (s: FindingConfirmationStatus) => {
    if (s === 'confirmed') return { bg: '#f6ffed', color: '#52c41a', label: '已确认' };
    if (s === 'dismissed') return { bg: '#f5f5f5', color: '#999', label: '已忽略' };
    return { bg: '#fffbe6', color: '#faad14', label: '待确认' };
  };

  /* 按钮通用样式 */
  const btnSm = (bg: string, color: string): React.CSSProperties => ({
    fontSize: 11, padding: '3px 10px', border: bg === '#fff' ? '1px solid #ddd' : 'none', borderRadius: 4,
    cursor: 'pointer', background: bg, color, whiteSpace: 'nowrap',
  });

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
              <div style={{ fontSize: 28, fontWeight: 700, color: '#52c41a', lineHeight: 1.2 }}>{confirmed}</div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>已确认</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#bbb', lineHeight: 1.2 }}>{dismissed}</div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>已忽略</div>
            </div>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#faad14', lineHeight: 1.2 }}>{pending}</div>
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

      {/* 问题清单标题 + 批量操作 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#333' }}>
          问题清单
          <span style={{ fontSize: 12, color: '#999', fontWeight: 400, marginLeft: 8 }}>
            共 {allFindings.length} 个问题，{groupOrder.length} 个科目
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {checkedIds.size > 0 && (
            <>
              <span style={{ fontSize: 12, color: '#666' }}>已选 {checkedIds.size} 项</span>
              <button onClick={() => batchAction('confirm')} style={btnSm('#52c41a', '#fff')}>批量确认</button>
              <button onClick={() => batchAction('dismiss')} style={btnSm('#999', '#fff')}>批量忽略</button>
              <button onClick={() => setCheckedIds(new Set())} style={btnSm('#fff', '#666')}>取消选择</button>
            </>
          )}
          <button onClick={() => setCheckedIds(new Set(allFindings.map(f => f.id)))} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid #ddd', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#666' }}>全选</button>
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
              <div>
                {findings.map((f, idx) => {
                  const riskColor = f.risk_level === 'high' ? '#cf1322' : f.risk_level === 'medium' ? '#d48806' : '#096dd9';
                  const riskBg = f.risk_level === 'high' ? '#fff1f0' : f.risk_level === 'medium' ? '#fffbe6' : '#e6f7ff';
                  const st = statusStyle(f.confirmation_status);
                  const isDismissed = f.confirmation_status === 'dismissed';
                  const isEditing = editingId === f.id;

                  return (
                    <div key={f.id} style={{
                      padding: '14px 16px',
                      borderBottom: idx === findings.length - 1 ? 'none' : '1px solid #f5f5f5',
                      opacity: isDismissed ? 0.5 : 1,
                      display: 'flex', gap: 10, alignItems: 'flex-start',
                    }}>
                      {/* 勾选框 */}
                      <input
                        type="checkbox"
                        checked={checkedIds.has(f.id)}
                        onChange={() => toggleCheck(f.id)}
                        style={{ marginTop: 4, flexShrink: 0 }}
                        aria-label={`选择 ${f.account_name}`}
                      />
                      {/* 标签列 */}
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
                        <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 10, textAlign: 'center', backgroundColor: st.bg, color: st.color, whiteSpace: 'nowrap' }}>
                          {st.label}
                        </span>
                      </div>
                      {/* 内容 */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        {isEditing ? (
                          <div>
                            <textarea
                              value={editDesc}
                              onChange={e => setEditDesc(e.target.value)}
                              style={{ width: '100%', minHeight: 60, fontSize: 13, padding: 8, border: '1px solid #d9d9d9', borderRadius: 6, resize: 'vertical' }}
                            />
                            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                              <button onClick={saveEdit} style={btnSm('var(--gt-primary, #4b2d77)', '#fff')}>保存</button>
                              <button onClick={cancelEdit} style={btnSm('#fff', '#666')}>取消</button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div style={{ fontSize: 13, color: '#333', lineHeight: 1.6 }}>{f.description}</div>
                            {f.location && <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>📍 {f.location}</div>}
                            {f.suggestion && (
                              <div style={{ fontSize: 12, color: '#52c41a', marginTop: 4, background: '#f6ffed', padding: '4px 10px', borderRadius: 6, display: 'inline-block' }}>
                                💡 {f.suggestion}
                              </div>
                            )}
                          </>
                        )}
                      </div>
                      {/* 操作按钮 */}
                      {!isEditing && (
                        <div style={{ display: 'flex', gap: 4, flexShrink: 0, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                          {f.confirmation_status !== 'confirmed' && (
                            <button onClick={() => updateStatus(f.id, 'confirm')} style={btnSm('#52c41a', '#fff')}>确认</button>
                          )}
                          {f.confirmation_status !== 'dismissed' && (
                            <button onClick={() => updateStatus(f.id, 'dismiss')} style={btnSm('#999', '#fff')}>忽略</button>
                          )}
                          {isDismissed && (
                            <button onClick={() => updateStatus(f.id, 'restore')} style={btnSm('#fff', '#4b2d77')}>恢复</button>
                          )}
                          <button onClick={() => startEdit(f)} style={btnSm('#fff', '#666')}>编辑</button>
                        </div>
                      )}
                    </div>
                  );
                })}
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

export default AuditReportResult;
