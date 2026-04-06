/**
 * FindingConfirmationView - 问题确认视图
 * 按附注表格(account_name) + 问题类别(category) 两级折叠分组
 * 组头 checkbox 支持批量全选，方便批量确认/忽略
 */
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
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

/** 二级分组结构：account_name → category → findings[] */
interface CategoryGroup {
  category: ReportReviewFindingCategory;
  label: string;
  findings: ReportReviewFinding[];
}
interface AccountGroup {
  accountName: string;
  categories: CategoryGroup[];
  totalCount: number;
}

/** 构建两级分组 */
function buildGroups(findings: ReportReviewFinding[]): AccountGroup[] {
  // 按 account_name 分组
  const accountMap: Record<string, ReportReviewFinding[]> = {};
  for (const f of findings) {
    const key = f.account_name || '未分类';
    if (!accountMap[key]) accountMap[key] = [];
    accountMap[key].push(f);
  }

  const groups: AccountGroup[] = [];
  const accountKeys = Object.keys(accountMap);
  for (const accountName of accountKeys) {
    const items = accountMap[accountName];
    // 按 category 分组
    const catMap: Record<string, ReportReviewFinding[]> = {};
    for (const f of items) {
      const catKey = f.category;
      if (!catMap[catKey]) catMap[catKey] = [];
      catMap[catKey].push(f);
    }
    const categories: CategoryGroup[] = [];
    for (const cat of Object.keys(catMap)) {
      categories.push({
        category: cat as ReportReviewFindingCategory,
        label: FINDING_CATEGORY_LABELS[cat as ReportReviewFindingCategory] || cat,
        findings: catMap[cat],
      });
    }
    groups.push({ accountName, categories, totalCount: items.length });
  }
  return groups;
}

const FindingConfirmationView: React.FC<Props> = ({ sessionId, onComplete }) => {
  const [findings, setFindings] = useState<ReportReviewFinding[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<ReportReviewFindingCategory | 'all'>('all');
  const [filterRisk, setFilterRisk] = useState<RiskLevel | 'all'>('all');
  const [filterStatus, setFilterStatus] = useState<FindingConfirmationStatus | 'all'>('all');
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [panelWidth, setPanelWidth] = useState(480);
  const [collapsedAccounts, setCollapsedAccounts] = useState<Set<string>>(new Set());
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());
  const dragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  // 拖拽调整右侧面板宽度
  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const newWidth = rect.right - ev.clientX;
      setPanelWidth(Math.max(280, Math.min(newWidth, rect.width - 300)));
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, []);

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

  useEffect(() => {
    if (selected && detailRef.current) detailRef.current.scrollTop = 0;
  }, [selected]);

  const filtered = useMemo(() => findings.filter(f => {
    if (filterCategory !== 'all' && f.category !== filterCategory) return false;
    if (filterRisk !== 'all' && f.risk_level !== filterRisk) return false;
    if (filterStatus !== 'all' && f.confirmation_status !== filterStatus) return false;
    if (filterStatus !== 'dismissed' && f.confirmation_status === 'dismissed') return false;
    return true;
  }), [findings, filterCategory, filterRisk, filterStatus]);

  const groups = useMemo(() => buildGroups(filtered), [filtered]);

  const stats = useMemo(() => ({
    total: findings.length,
    pending: findings.filter(f => f.confirmation_status === 'pending_confirmation').length,
    confirmed: findings.filter(f => f.confirmation_status === 'confirmed').length,
    dismissed: findings.filter(f => f.confirmation_status === 'dismissed').length,
  }), [findings]);

  const updateStatus = async (id: string, status: FindingConfirmationStatus) => {
    try {
      const endpoint = status === 'confirmed' ? 'confirm' : status === 'dismissed' ? 'dismiss' : 'restore';
      await fetch(`${API}/api/report-review/finding/${id}/${endpoint}`, { method: 'PATCH' });
    } catch (e) { console.warn('更新状态失败:', e); }
    if (status === 'dismissed' && selected === id) setSelected(null);
    loadFindings();
  };

  const batchAction = async (action: 'confirm' | 'dismiss') => {
    if (checkedIds.size === 0) return;
    try {
      await fetch(`${API}/api/report-review/findings/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ finding_ids: Array.from(checkedIds), action }),
      });
    } catch (e) { console.warn('批量操作失败:', e); }
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

  /** 组头 checkbox：全选/取消该组下所有 finding */
  const toggleGroupCheck = (ids: string[]) => {
    setCheckedIds(prev => {
      const next = new Set(prev);
      const allChecked = ids.every(id => next.has(id));
      if (allChecked) {
        ids.forEach(id => next.delete(id));
      } else {
        ids.forEach(id => next.add(id));
      }
      return next;
    });
  };

  const toggleAccountCollapse = (key: string) => {
    setCollapsedAccounts(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const toggleCategoryCollapse = (key: string) => {
    setCollapsedCategories(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  /** 风险统计小标签 */
  const riskBadges = (items: ReportReviewFinding[]) => {
    const h = items.filter(f => f.risk_level === 'high').length;
    const m = items.filter(f => f.risk_level === 'medium').length;
    const l = items.filter(f => f.risk_level === 'low').length;
    return (
      <span style={{ display: 'inline-flex', gap: 4, marginLeft: 8 }}>
        {h > 0 && <span style={{ fontSize: 10, padding: '0 4px', borderRadius: 3, background: '#DC3545', color: '#fff' }}>高{h}</span>}
        {m > 0 && <span style={{ fontSize: 10, padding: '0 4px', borderRadius: 3, background: '#FFC107', color: '#333' }}>中{m}</span>}
        {l > 0 && <span style={{ fontSize: 10, padding: '0 4px', borderRadius: 3, background: '#17A2B8', color: '#fff' }}>低{l}</span>}
      </span>
    );
  };

  return (
    <div ref={containerRef} style={{ display: 'flex', minHeight: '60vh', maxHeight: 'calc(100vh - 160px)', alignItems: 'flex-start' }}>
      {/* Left: grouped list */}
      <div style={{ flex: 1, minWidth: 0, paddingRight: 'var(--gt-space-3)', overflowY: 'auto', maxHeight: 'calc(100vh - 160px)' }}>
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
        <div style={{ marginBottom: 'var(--gt-space-2)', display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => setCheckedIds(new Set(filtered.map(f => f.id)))} style={{ fontSize: 12, padding: '2px 10px', cursor: 'pointer', border: '1px solid #ccc', borderRadius: 4, background: '#fff' }}>全选</button>
          <button onClick={() => setCheckedIds(new Set())} style={{ fontSize: 12, padding: '2px 10px', cursor: 'pointer', border: '1px solid #ccc', borderRadius: 4, background: '#fff' }}>全清</button>
          <span style={{ width: 1, height: 16, background: '#ddd', margin: '0 2px' }} />
          <button onClick={() => { setCollapsedAccounts(new Set()); setCollapsedCategories(new Set()); }} style={{ fontSize: 12, padding: '2px 10px', cursor: 'pointer', border: '1px solid #ccc', borderRadius: 4, background: '#fff' }}>全部展开</button>
          <button onClick={() => { setCollapsedAccounts(new Set(groups.map(g => g.accountName))); setCollapsedCategories(new Set(groups.flatMap(g => g.categories.map(c => `${g.accountName}::${c.category}`)))); }} style={{ fontSize: 12, padding: '2px 10px', cursor: 'pointer', border: '1px solid #ccc', borderRadius: 4, background: '#fff' }}>全部折叠</button>
          {checkedIds.size > 0 && (
            <>
              <span style={{ fontSize: 13, marginLeft: 4 }}>已选 {checkedIds.size} 项</span>
              <button onClick={() => batchAction('confirm')} style={{ fontSize: 12, padding: '2px 10px', cursor: 'pointer', backgroundColor: 'var(--gt-success, green)', color: '#fff', border: 'none', borderRadius: 4 }}>批量确认</button>
              <button onClick={() => batchAction('dismiss')} style={{ fontSize: 12, padding: '2px 10px', cursor: 'pointer', backgroundColor: '#999', color: '#fff', border: 'none', borderRadius: 4 }}>批量忽略</button>
            </>
          )}
        </div>

        {/* Grouped finding list */}
        {loading ? <p style={{ textAlign: 'center', color: '#999' }}>加载中...</p> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {groups.map(accountGroup => {
              const accountKey = accountGroup.accountName;
              const isAccountCollapsed = collapsedAccounts.has(accountKey);
              const allAccountIds = accountGroup.categories.flatMap(c => c.findings.map(f => f.id));
              const allAccountChecked = allAccountIds.length > 0 && allAccountIds.every(id => checkedIds.has(id));
              const someAccountChecked = allAccountIds.some(id => checkedIds.has(id));

              return (
                <div key={accountKey} style={{ border: '1px solid #e8e8e8', borderRadius: 8, overflow: 'hidden', marginBottom: 4 }}>
                  {/* Account-level header */}
                  <div
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
                      background: '#f7f5ff', cursor: 'pointer', userSelect: 'none',
                      borderBottom: isAccountCollapsed ? 'none' : '1px solid #e8e8e8',
                    }}
                    onClick={() => toggleAccountCollapse(accountKey)}
                  >
                    <input
                      type="checkbox"
                      checked={allAccountChecked}
                      ref={el => { if (el) el.indeterminate = someAccountChecked && !allAccountChecked; }}
                      onChange={e => { e.stopPropagation(); toggleGroupCheck(allAccountIds); }}
                      onClick={e => e.stopPropagation()}
                      aria-label={`全选 ${accountKey}`}
                    />
                    <span style={{ fontSize: 14, fontWeight: 700, color: '#888', fontFamily: 'monospace', width: 16, textAlign: 'center', display: 'inline-block' }}>{isAccountCollapsed ? '+' : '−'}</span>
                    <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--gt-primary, #4b2d77)' }} title={accountKey.length > 30 ? accountKey : undefined}>
                      {accountKey.length > 30 ? accountKey.slice(0, 28) + '…' : accountKey}
                    </span>
                    <span style={{ fontSize: 12, color: '#888' }}>({accountGroup.totalCount}条)</span>
                    {riskBadges(accountGroup.categories.flatMap(c => c.findings))}
                  </div>

                  {/* Category sub-groups */}
                  {!isAccountCollapsed && accountGroup.categories.map(catGroup => {
                    const catKey = `${accountKey}::${catGroup.category}`;
                    const isCatCollapsed = collapsedCategories.has(catKey);
                    const catIds = catGroup.findings.map(f => f.id);
                    const allCatChecked = catIds.length > 0 && catIds.every(id => checkedIds.has(id));
                    const someCatChecked = catIds.some(id => checkedIds.has(id));

                    return (
                      <div key={catKey}>
                        {/* Category-level header */}
                        <div
                          style={{
                            display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px 6px 28px',
                            background: '#fafafa', cursor: 'pointer', userSelect: 'none',
                            borderBottom: '1px solid #f0f0f0',
                          }}
                          onClick={() => toggleCategoryCollapse(catKey)}
                        >
                          <input
                            type="checkbox"
                            checked={allCatChecked}
                            ref={el => { if (el) el.indeterminate = someCatChecked && !allCatChecked; }}
                            onChange={e => { e.stopPropagation(); toggleGroupCheck(catIds); }}
                            onClick={e => e.stopPropagation()}
                            aria-label={`全选 ${accountKey} - ${catGroup.label}`}
                          />
                          <span style={{ fontSize: 13, fontWeight: 700, color: '#888', fontFamily: 'monospace', width: 14, textAlign: 'center', display: 'inline-block' }}>{isCatCollapsed ? '+' : '−'}</span>
                          <span style={{
                            fontSize: 11, padding: '1px 6px', borderRadius: 3,
                            backgroundColor: FINDING_CATEGORY_COLORS[catGroup.category] || '#888', color: '#fff',
                          }}>
                            {catGroup.label}
                          </span>
                          <span style={{ fontSize: 12, color: '#666' }}>({catGroup.findings.length}条)</span>
                          {riskBadges(catGroup.findings)}
                        </div>

                        {/* Finding items */}
                        {!isCatCollapsed && catGroup.findings.map(f => (
                          <div
                            key={f.id}
                            style={{
                              display: 'flex', flexDirection: 'column', padding: '8px 12px 8px 48px',
                              cursor: 'pointer',
                              opacity: f.confirmation_status === 'dismissed' ? 0.5 : 1,
                              background: selected === f.id ? '#f0ebff' : '#fff',
                              borderBottom: '1px solid #f5f5f5',
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
                                aria-label={`选择问题`}
                              />
                              <span style={{
                                fontSize: 11, padding: '1px 6px', borderRadius: 3,
                                backgroundColor: f.risk_level === 'high' ? '#DC3545' : f.risk_level === 'medium' ? '#FFC107' : '#17A2B8',
                                color: f.risk_level === 'medium' ? '#333' : '#fff',
                              }}>
                                {f.risk_level === 'high' ? '高' : f.risk_level === 'medium' ? '中' : '低'}
                              </span>
                              <span style={{ fontSize: 12, color: '#888' }}>{CONFIRMATION_STATUS_LABELS[f.confirmation_status]}</span>
                              {f.confirmation_status === 'dismissed' && (
                                <button
                                  onClick={e => { e.stopPropagation(); updateStatus(f.id, 'pending_confirmation'); }}
                                  style={{ fontSize: 11, color: 'var(--gt-primary)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}
                                >恢复</button>
                              )}
                            </div>
                            <p style={{ fontSize: 13, color: '#555', margin: '4px 0 0 28px', lineHeight: 1.4 }}>{f.description}</p>
                            {f.location && (
                              <p style={{ fontSize: 11, color: '#999', margin: '2px 0 0 28px' }}>📍 {f.location}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              );
            })}
            {groups.length === 0 && <p style={{ textAlign: 'center', color: '#999' }}>暂无匹配的问题</p>}
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

      {/* Drag handle */}
      <div
        onMouseDown={onDragStart}
        style={{
          width: 6, cursor: 'col-resize', flexShrink: 0, alignSelf: 'stretch',
          background: '#e5e5e5', borderRadius: 3, transition: 'background 0.15s',
          minHeight: 100,
        }}
        onMouseEnter={e => (e.currentTarget.style.background = 'var(--gt-primary, #7c3aed)')}
        onMouseLeave={e => (e.currentTarget.style.background = '#e5e5e5')}
        role="separator"
        aria-orientation="vertical"
        aria-label="拖拽调整面板宽度"
        tabIndex={0}
      />

      {/* Right: detail panel */}
      <div ref={detailRef} style={{
        width: panelWidth, flexShrink: 0, paddingLeft: 'var(--gt-space-3)',
        position: 'sticky', top: 0, alignSelf: 'flex-start',
        maxHeight: 'calc(100vh - 160px)', overflowY: 'auto',
      }}>
        {selected ? (
          <FindingDetailPanel
            findingId={selected}
            finding={findings.find(f => f.id === selected) || null}
            sessionId={sessionId}
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
