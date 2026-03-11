/**
 * FindingConfirmationView - 问题确认视图
 * Task 16.1: 顶部统计栏 + 筛选栏 + 问题列表，批量操作，已忽略灰显+恢复
 */
import React, { useState, useEffect, useCallback } from 'react';
import FindingDetailPanel from './FindingDetailPanel';
import {
  ReportReviewFinding, ReportReviewFindingCategory, FindingConfirmationStatus, RiskLevel,
  FINDING_CATEGORY_LABELS, FINDING_CATEGORY_COLORS, CONFIRMATION_STATUS_LABELS,
} from '../types/audit';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

interface Props {
  sessionId: string | null;
  onComplete: () => void;
}

const FindingConfirmationView: React.FC<Props> = ({ sessionId, onComplete }) => {
  const [findings, setFindings] = useState<ReportReviewFinding[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<ReportReviewFindingCategory | 'all'>('all');
  const [filterRisk, setFilterRisk] = useState<RiskLevel | 'all'>('all');
  const [filterStatus, setFilterStatus] = useState<FindingConfirmationStatus | 'all'>('all');
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);

  const loadFindings = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/report-review/findings/${sessionId}`);
      const data = await r.json();
      setFindings(data.findings || data || []);
    } catch { /* ignore */ }
    setLoading(false);
  }, [sessionId]);

  useEffect(() => { loadFindings(); }, [loadFindings]);

  const filtered = findings.filter(f => {
    if (filterCategory !== 'all' && f.category !== filterCategory) return false;
    if (filterRisk !== 'all' && f.risk_level !== filterRisk) return false;
    if (filterStatus !== 'all' && f.confirmation_status !== filterStatus) return false;
    return true;
  });

  const stats = {
    total: findings.length,
    pending: findings.filter(f => f.confirmation_status === 'pending_confirmation').length,
    confirmed: findings.filter(f => f.confirmation_status === 'confirmed').length,
    dismissed: findings.filter(f => f.confirmation_status === 'dismissed').length,
  };

  const updateStatus = async (id: string, status: FindingConfirmationStatus) => {
    await fetch(`${API}/api/report-review/finding/${id}/${status === 'confirmed' ? 'confirm' : status === 'dismissed' ? 'dismiss' : 'restore'}`, { method: 'PATCH' });
    loadFindings();
  };

  const batchAction = async (action: 'confirm' | 'dismiss') => {
    if (checkedIds.size === 0) return;
    await fetch(`${API}/api/report-review/findings/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ finding_ids: Array.from(checkedIds), action }),
    });
    setCheckedIds(new Set());
    loadFindings();
  };

  const toggleCheck = (id: string) => {
    setCheckedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <div style={{ display: 'flex', gap: 'var(--gt-space-4)', minHeight: '60vh' }}>
      {/* Left: list */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Stats bar */}
        <div style={{ display: 'flex', gap: 'var(--gt-space-4)', marginBottom: 'var(--gt-space-3)', flexWrap: 'wrap' }}>
          <span>总计: {stats.total}</span>
          <span style={{ color: 'var(--gt-warning)' }}>待确认: {stats.pending}</span>
          <span style={{ color: 'var(--gt-success, green)' }}>已确认: {stats.confirmed}</span>
          <span style={{ color: '#999' }}>已忽略: {stats.dismissed}</span>
        </div>

        {/* Filters */}
        <div style={{ display: 'flex', gap: 'var(--gt-space-2)', marginBottom: 'var(--gt-space-3)', flexWrap: 'wrap', fontSize: 13 }}>
          <select value={filterCategory} onChange={e => setFilterCategory(e.target.value as any)} aria-label="按分类筛选">
            <option value="all">全部分类</option>
            {Object.entries(FINDING_CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={filterRisk} onChange={e => setFilterRisk(e.target.value as any)} aria-label="按风险等级筛选">
            <option value="all">全部风险</option>
            <option value="high">高</option><option value="medium">中</option><option value="low">低</option>
          </select>
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value as any)} aria-label="按状态筛选">
            <option value="all">全部状态</option>
            {Object.entries(CONFIRMATION_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>

        {/* Batch actions */}
        {checkedIds.size > 0 && (
          <div style={{ marginBottom: 'var(--gt-space-2)', display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 13 }}>已选 {checkedIds.size} 项</span>
            <button onClick={() => batchAction('confirm')} style={{ fontSize: 12, padding: '2px 10px', cursor: 'pointer', backgroundColor: 'var(--gt-success, green)', color: '#fff', border: 'none', borderRadius: 4 }}>批量确认</button>
            <button onClick={() => batchAction('dismiss')} style={{ fontSize: 12, padding: '2px 10px', cursor: 'pointer', backgroundColor: '#999', color: '#fff', border: 'none', borderRadius: 4 }}>批量忽略</button>
          </div>
        )}

        {/* Finding list */}
        {loading ? <p style={{ textAlign: 'center', color: '#999' }}>加载中...</p> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-2)' }}>
            {filtered.map(f => (
              <div
                key={f.id}
                className="gt-card"
                style={{
                  padding: 'var(--gt-space-3)', cursor: 'pointer',
                  opacity: f.confirmation_status === 'dismissed' ? 0.5 : 1,
                  border: selected === f.id ? '2px solid var(--gt-primary)' : '1px solid #eee',
                }}
                onClick={() => setSelected(f.id)}
                role="button"
                tabIndex={0}
                aria-label={`问题: ${f.description}`}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={checkedIds.has(f.id)}
                    onChange={() => toggleCheck(f.id)}
                    onClick={e => e.stopPropagation()}
                    aria-label={`选择问题 ${f.account_name}`}
                  />
                  <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3, backgroundColor: FINDING_CATEGORY_COLORS[f.category], color: '#fff' }}>
                    {FINDING_CATEGORY_LABELS[f.category]}
                  </span>
                  <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 3, backgroundColor: f.risk_level === 'high' ? '#DC3545' : f.risk_level === 'medium' ? '#FFC107' : '#17A2B8', color: '#fff' }}>
                    {f.risk_level === 'high' ? '高' : f.risk_level === 'medium' ? '中' : '低'}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>{f.account_name}</span>
                  <span style={{ fontSize: 11, color: '#888' }}>{CONFIRMATION_STATUS_LABELS[f.confirmation_status]}</span>
                </div>
                <p style={{ fontSize: 13, color: '#555', margin: '4px 0 0 28px' }}>{f.description}</p>
                {f.confirmation_status === 'dismissed' && (
                  <button
                    onClick={e => { e.stopPropagation(); updateStatus(f.id, 'pending_confirmation'); }}
                    style={{ fontSize: 11, marginLeft: 28, marginTop: 4, color: 'var(--gt-primary)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}
                  >
                    恢复
                  </button>
                )}
              </div>
            ))}
            {filtered.length === 0 && <p style={{ textAlign: 'center', color: '#999' }}>暂无匹配的问题</p>}
          </div>
        )}

        {/* Complete button */}
        <div style={{ marginTop: 'var(--gt-space-4)', textAlign: 'right' }}>
          <button
            className="gt-button"
            style={{ backgroundColor: 'var(--gt-primary)', color: '#fff', padding: '8px 24px', border: 'none', borderRadius: 8, cursor: 'pointer' }}
            onClick={onComplete}
          >
            完成确认，查看报告
          </button>
        </div>
      </div>

      {/* Right: detail panel */}
      <div style={{ width: 480, flexShrink: 0 }}>
        {selected ? (
          <FindingDetailPanel
            findingId={selected}
            finding={findings.find(f => f.id === selected) || null}
            onStatusChange={(id, status) => { updateStatus(id, status); }}
            onUpdate={loadFindings}
          />
        ) : (
          <div style={{ textAlign: 'center', color: '#999', paddingTop: 80 }}>选择左侧问题查看详情</div>
        )}
      </div>
    </div>
  );
};

export default FindingConfirmationView;
