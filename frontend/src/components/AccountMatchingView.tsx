/**
 * AccountMatchingView - 科目-附注对照视图（层级化版本）
 *
 * 按附注文档的一级标题作为顶层页签，"财务报表主要项目注释"下展示报表科目对照，
 * "重要会计政策和会计估计"等内容多的章节按2/3/4级层级多页签展开。
 *
 * 致同品牌色系：主色 #4b2d77（致同紫）
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  StatementItem, NoteTable, NoteSection, MatchingMap,
} from '../types/audit';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

// ─── 致同品牌色系 ───
const GT = {
  primary: '#4b2d77',       // 致同紫 - 主色
  primaryLight: '#6b4fa0',  // 浅紫
  primaryBg: '#f3f0fa',     // 紫底
  primaryBgDeep: '#ece5f5', // 深紫底
  accent: '#2980b9',        // 蓝色强调
  accentBg: '#eaf2f8',
  success: '#27ae60',       // 绿色
  successBg: '#eafaf1',
  warning: '#e67e22',       // 橙色
  warningBg: '#fef5ec',
  danger: '#e74c3c',        // 红色
  text: '#2c2c2c',          // 主文字
  textSecondary: '#666',    // 次要文字
  textMuted: '#999',        // 弱化文字
  border: '#e0dce8',        // 边框
  borderLight: '#f0edf6',   // 浅边框
  bgPage: '#faf9fc',        // 页面底色
  bgWhite: '#fff',
  shadow: '0 2px 8px rgba(75,45,119,0.08)',
  shadowHover: '0 4px 16px rgba(75,45,119,0.14)',
  radius: 8,
  radiusSm: 6,
  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif',
};

// ─── 层级色系（1级最深，逐级变浅） ───
const LEVEL_COLORS = {
  title:   { 1: GT.primary, 2: GT.accent, 3: GT.success, 4: GT.warning },
  titleBg: { 1: GT.primaryBgDeep, 2: '#dfedf7', 3: '#e0f5e9', 4: '#fdf2e4' },
  bodyBg:  { 1: '#f9f7fc', 2: '#f4f9fd', 3: '#f4fbf7', 4: '#fefbf6' },
  border:  { 1: GT.primary, 2: GT.accent, 3: GT.success, 4: GT.warning },
} as const;

const lvlColor  = (l: number) => (LEVEL_COLORS.title as any)[l]   || GT.textSecondary;
const lvlTitleBg= (l: number) => (LEVEL_COLORS.titleBg as any)[l] || '#f0f0f0';
const lvlBodyBg = (l: number) => (LEVEL_COLORS.bodyBg as any)[l]  || '#fafafa';
const lvlBorder = (l: number) => (LEVEL_COLORS.border as any)[l]  || '#ccc';

// ─── 报表科目分类 ───
type SubTabKey = 'asset' | 'liability_equity' | 'income' | 'cash_flow' | 'related_party';
const SUB_TABS: { key: SubTabKey; label: string }[] = [
  { key: 'asset', label: '资产' },
  { key: 'liability_equity', label: '负债和权益' },
  { key: 'income', label: '损益' },
  { key: 'cash_flow', label: '现金流' },
  { key: 'related_party', label: '关联方及交易' },
];

const ASSET_KW = [
  '货币资金','结算备付金','拆出资金','交易性金融资产','衍生金融资产',
  '应收票据','应收账款','应收款项融资','预付款项','应收保费',
  '应收利息','应收股利','其他应收款','买入返售','存货','合同资产',
  '持有待售','一年内到期','其他流动资产',
  '债权投资','其他债权投资','长期应收款','长期股权投资','其他权益工具投资',
  '其他非流动金融资产','投资性房地产','固定资产','在建工程','生产性生物资产',
  '油气资产','使用权资产','无形资产','开发支出','商誉','长期待摊费用',
  '递延所得税资产','其他非流动资产','以公允价值计量','金融资产',
];

function itemTab(item: StatementItem): SubTabKey {
  if (item.statement_type === 'income_statement') return 'income';
  if (item.statement_type === 'cash_flow') return 'cash_flow';
  if (item.statement_type === 'equity_change') return 'liability_equity';
  const n = item.account_name.replace(/\s/g, '');
  for (const kw of ASSET_KW) { if (n.includes(kw)) return 'asset'; }
  return 'liability_equity';
}

function fuzzyMatch(a: string, b: string): boolean {
  const ca = a.replace(/[\s△☆▲]/g, '');
  const cb = b.replace(/[\s△☆▲]/g, '');
  return ca.includes(cb) || cb.includes(ca);
}

function fmtAmt(v?: number | null): string {
  if (v == null) return '-';
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function isMainNoteSection(title: string): boolean {
  const kw = ['财务报表主要项目', '主要项目注释', '报表项目注释', '报表主要项目'];
  const clean = title.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');
  return kw.some(k => clean.includes(k));
}

interface NoteGroup {
  accountName: string;
  notes: NoteTable[];
  statementItem?: StatementItem;
  subItems: StatementItem[];
}

interface Props {
  sessionId: string | null;
  onConfirm: () => void;
}

const AccountMatchingView: React.FC<Props> = ({ sessionId, onConfirm }) => {
  const [items, setItems] = useState<StatementItem[]>([]);
  const [notes, setNotes] = useState<NoteTable[]>([]);
  const [sections, setSections] = useState<NoteSection[]>([]);
  const [matching, setMatching] = useState<MatchingMap | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [activeL1, setActiveL1] = useState(0);
  const [activeL2, setActiveL2] = useState(0);
  const [activeL3, setActiveL3] = useState(0);
  const [activeL4, setActiveL4] = useState(0);
  const [activeSubTab, setActiveSubTab] = useState<SubTabKey>('asset');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // 折叠状态：记录被折叠的 section id
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const toggleCollapse = useCallback((id: string) => {
    setCollapsedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    fetch(`${API}/api/report-review/session/${sessionId}`)
      .then(r => r.json())
      .then(data => {
        setItems(data.statement_items || []);
        setNotes(data.note_tables || []);
        setSections(data.note_sections || []);
        setMatching(data.matching_map || null);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  const handleConfirm = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const resp = await fetch(`${API}/api/report-review/confirm-matching`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          matching_map: matching || { entries: [], unmatched_items: [], unmatched_notes: [] },
        }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      onConfirm();
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, [sessionId, matching, onConfirm]);

  const noteMap = useMemo(() => new Map(notes.map(n => [n.id, n])), [notes]);

  const findMatchedNotes = useCallback((si: StatementItem): NoteTable[] => {
    if (matching) {
      const entry = matching.entries?.find(e => e.statement_item_id === si.id);
      if (entry && entry.note_table_ids.length > 0) {
        return entry.note_table_ids.map(id => noteMap.get(id)).filter(Boolean) as NoteTable[];
      }
    }
    return notes.filter(n => fuzzyMatch(n.account_name, si.account_name));
  }, [matching, notes, noteMap]);

  const isZeroAndNoNotes = (si: StatementItem, matchedNotes: NoteTable[]): boolean => {
    const ob = si.opening_balance ?? 0;
    const cb = si.closing_balance ?? 0;
    return ob === 0 && cb === 0 && matchedNotes.length === 0;
  };

  // ─── hover 样式 ───
  useEffect(() => {
    const STYLE_ID = 'acct-match-table-hover';
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .amt-table tbody tr:hover > td { background: ${GT.primaryBg} !important; }
      .amt-table td.amt-col-hover, .amt-table th.amt-col-hover { background: ${GT.primaryBg} !important; }
    `;
    document.head.appendChild(style);
    return () => { document.getElementById(STYLE_ID)?.remove(); };
  }, []);

  const handleCellEnter = useCallback((e: React.MouseEvent<HTMLTableCellElement>) => {
    const cell = e.currentTarget;
    const table = cell.closest('table');
    if (!table) return;
    const colIdx = cell.cellIndex;
    table.querySelectorAll('tr').forEach(row => {
      const c = row.children[colIdx] as HTMLElement | undefined;
      c?.classList.add('amt-col-hover');
    });
  }, []);
  const handleCellLeave = useCallback((e: React.MouseEvent<HTMLTableCellElement>) => {
    const cell = e.currentTarget;
    const table = cell.closest('table');
    if (!table) return;
    const colIdx = cell.cellIndex;
    table.querySelectorAll('tr').forEach(row => {
      const c = row.children[colIdx] as HTMLElement | undefined;
      c?.classList.remove('amt-col-hover');
    });
  }, []);

  const hasSections = sections.length > 0;

  useEffect(() => { setActiveL2(0); setActiveL3(0); setActiveL4(0); }, [activeL1]);
  useEffect(() => { setActiveL3(0); setActiveL4(0); }, [activeL2]);
  useEffect(() => { setActiveL4(0); }, [activeL3]);

  // ─── 渲染附注表格（带层级主题色） ───
  const renderNoteTable = (nt: NoteTable, label?: string, level?: number) => {
    const tc = level ? lvlColor(level) : GT.primary;
    const hBg = level ? lvlTitleBg(level) : GT.primaryBgDeep;
    const sBg = level ? lvlBodyBg(level) : GT.bgPage;

    return (
      <div key={nt.id} style={{ marginBottom: 18 }}>
        {label && (
          <div style={{
            fontSize: 13, fontWeight: 600, color: tc,
            background: hBg, padding: '7px 14px',
            borderLeft: `3px solid ${tc}`, borderRadius: GT.radiusSm,
            marginBottom: 6, letterSpacing: 0.3,
          }}>{label}</div>
        )}
        <div style={{
          overflowX: 'auto', borderRadius: GT.radius,
          border: `1px solid ${tc}30`, boxShadow: GT.shadow,
        }}>
          <table className="amt-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <caption className="sr-only">{nt.account_name}</caption>
            {nt.headers.length > 0 && (
              <thead>
                <tr style={{ background: hBg }}>
                  {nt.headers.map((h, i) => (
                    <th key={i} onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                      style={{
                        padding: '9px 14px', fontWeight: 600,
                        borderBottom: `2px solid ${tc}50`, color: tc,
                        textAlign: i === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                      }}>{h}</th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {nt.rows.slice(0, 30).map((row, ri) => (
                <tr key={ri} style={{ background: ri % 2 === 0 ? GT.bgWhite : sBg }}>
                  {row.map((c: any, ci: number) => (
                    <td key={ci} onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                      style={{
                        padding: '7px 14px', borderBottom: `1px solid ${GT.borderLight}`,
                        textAlign: ci === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                        fontVariantNumeric: ci > 0 ? 'tabular-nums' : 'normal',
                        color: GT.text, fontSize: 13,
                      }}>{c != null ? String(c) : ''}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  // ─── 渲染报表科目对照（"财务报表主要项目注释"） ───
  const renderStatementMatching = (_sectionNoteIds: string[]) => {
    const buildGroups = (): NoteGroup[] => {
      const mainItems = items.filter(i => !i.is_sub_item && itemTab(i) === activeSubTab);
      const groups: NoteGroup[] = [];
      for (const si of mainItems) {
        const matched = findMatchedNotes(si);
        if (isZeroAndNoNotes(si, matched)) continue;
        const subs = items.filter(i => i.is_sub_item && i.parent_id === si.id);
        groups.push({ accountName: si.account_name, notes: matched, statementItem: si, subItems: subs });
      }
      return groups;
    };

    const groups = buildGroups();

    return (
      <div>
        {/* 报表科目子页签 */}
        <div style={{
          display: 'flex', gap: 2, borderBottom: `2px solid ${GT.border}`,
          marginBottom: 18, paddingBottom: 0, flexWrap: 'wrap',
        }}>
          {SUB_TABS.map(tab => {
            const cnt = items.filter(i => {
              if (i.is_sub_item) return false;
              if (itemTab(i) !== tab.key) return false;
              const matched = findMatchedNotes(i);
              return !isZeroAndNoNotes(i, matched);
            }).length;
            const isActive = activeSubTab === tab.key;
            return (
              <button key={tab.key} onClick={() => setActiveSubTab(tab.key)}
                style={{
                  padding: '9px 20px', border: 'none',
                  background: isActive ? GT.primaryBg : 'transparent',
                  cursor: 'pointer', fontSize: 13, borderRadius: '6px 6px 0 0',
                  transition: 'all 0.2s',
                  borderBottom: isActive ? `2px solid ${GT.primary}` : '2px solid transparent',
                  fontWeight: isActive ? 700 : 400,
                  color: isActive ? GT.primary : GT.textMuted,
                  marginBottom: -2,
                }}>
                {tab.label}
                {cnt > 0 && <span style={{
                  fontSize: 10, marginLeft: 5, padding: '1px 6px', borderRadius: 10,
                  background: isActive ? GT.primary : '#e0e0e0',
                  color: isActive ? '#fff' : GT.textSecondary,
                }}>{cnt}</span>}
              </button>
            );
          })}
        </div>

        {groups.length === 0 && (
          <div style={{ color: GT.textMuted, padding: 40, textAlign: 'center', fontSize: 14 }}>
            该分类下暂无科目
          </div>
        )}

        {/* 科目列表 */}
        <div style={{ maxHeight: 'calc(100vh - 340px)', overflowY: 'auto', paddingRight: 4 }}>
          {groups.map((g, gi) => {
            const si = g.statementItem;
            const firstNote = g.notes[0];
            const gKey = si?.id || `g${gi}`;
            const isExpanded = expandedId === gKey;
            const hasNotes = g.notes.length > 0;

            return (
              <div key={gKey} style={{
                marginBottom: 10, borderRadius: GT.radius, overflow: 'hidden',
                transition: 'all 0.2s',
                border: isExpanded ? `2px solid ${GT.primary}` : `1px solid ${GT.border}`,
                boxShadow: isExpanded ? GT.shadowHover : GT.shadow,
              }}>
                {/* 科目标题行 */}
                <div onClick={() => setExpandedId(isExpanded ? null : gKey)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '11px 16px', cursor: 'pointer', transition: 'background 0.2s',
                    background: isExpanded
                      ? `linear-gradient(135deg, ${GT.primaryBg} 0%, ${GT.primaryBgDeep} 100%)`
                      : GT.bgPage,
                    borderBottom: isExpanded ? `1px solid ${GT.border}` : 'none',
                  }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      width: 28, height: 28, borderRadius: '50%', fontSize: 12, fontWeight: 700,
                      background: hasNotes ? GT.primary : GT.warning, color: '#fff',
                      boxShadow: `0 1px 4px ${hasNotes ? GT.primary : GT.warning}40`,
                    }}>{gi + 1}</span>
                    <span style={{ fontWeight: 600, fontSize: 14, color: GT.text }}>{g.accountName}</span>
                    {!hasNotes && (
                      <span style={{
                        fontSize: 11, color: GT.warning, background: GT.warningBg,
                        padding: '2px 10px', borderRadius: 4, fontWeight: 500,
                        border: `1px solid ${GT.warning}30`,
                      }}>附注缺失</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 12 }}>
                    <span style={{
                      padding: '3px 10px', borderRadius: 4,
                      background: hasNotes ? `${GT.primary}12` : '#f5f5f5',
                      color: hasNotes ? GT.primaryLight : GT.textMuted,
                      fontWeight: 500,
                    }}>附注 {g.notes.length}</span>
                    <span style={{
                      transition: 'transform 0.2s',
                      transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                      fontSize: 12, color: GT.textMuted,
                    }}>▼</span>
                  </div>
                </div>

                {/* 展开内容 */}
                {isExpanded && (
                  <div style={{ padding: '16px 18px', background: GT.bgWhite }}>
                    {/* 附注表格 */}
                    {firstNote && (
                      <div style={{ marginBottom: 18 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 600, marginBottom: 8, color: GT.primary,
                          display: 'flex', alignItems: 'center', gap: 8,
                        }}>
                          <span style={{
                            width: 4, height: 16, background: GT.primary,
                            borderRadius: 2, display: 'inline-block',
                          }} />附注数据
                        </div>
                        {renderNoteTable(firstNote)}
                      </div>
                    )}
                    {/* 报表数据 */}
                    {si && (
                      <div style={{ marginBottom: 18 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 600, marginBottom: 8, color: GT.accent,
                          display: 'flex', alignItems: 'center', gap: 8,
                        }}>
                          <span style={{
                            width: 4, height: 16, background: GT.accent,
                            borderRadius: 2, display: 'inline-block',
                          }} />报表数据
                        </div>
                        <div style={{
                          borderRadius: GT.radius, border: `1px solid ${GT.accent}30`,
                          overflow: 'hidden', maxWidth: 600, boxShadow: GT.shadow,
                        }}>
                          <table className="amt-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                            <caption className="sr-only">{g.accountName} 报表数据</caption>
                            <thead>
                              <tr style={{ background: GT.accentBg }}>
                                <th onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                  style={{ padding: '9px 14px', fontWeight: 600, color: GT.accent, textAlign: 'left' }}>项　目</th>
                                <th onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                  style={{ padding: '9px 14px', fontWeight: 600, color: GT.accent, textAlign: 'right' }}>期末余额</th>
                                <th onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                  style={{ padding: '9px 14px', fontWeight: 600, color: GT.accent, textAlign: 'right' }}>期初余额</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr style={{ background: GT.bgWhite }}>
                                <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                  style={{ padding: '9px 14px', fontWeight: 600, color: GT.text, borderBottom: `1px solid ${GT.accentBg}` }}>{si.account_name}</td>
                                <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                  style={{ padding: '9px 14px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 600, color: GT.text, borderBottom: `1px solid ${GT.accentBg}` }}>{fmtAmt(si.closing_balance)}</td>
                                <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                  style={{ padding: '9px 14px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 600, color: GT.text, borderBottom: `1px solid ${GT.accentBg}` }}>{fmtAmt(si.opening_balance)}</td>
                              </tr>
                              {g.subItems.map(sub => (
                                <tr key={sub.id} style={{ background: '#fafcfe' }}>
                                  <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                    style={{ padding: '7px 14px 7px 30px', color: GT.textSecondary, borderBottom: `1px solid #f0f5fa` }}>
                                    <span style={{ color: '#ccc', marginRight: 6 }}>└</span>{sub.account_name}
                                  </td>
                                  <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                    style={{ padding: '7px 14px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: GT.textSecondary, borderBottom: '1px solid #f0f5fa' }}>{fmtAmt(sub.closing_balance)}</td>
                                  <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                    style={{ padding: '7px 14px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: GT.textSecondary, borderBottom: '1px solid #f0f5fa' }}>{fmtAmt(sub.opening_balance)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* 金额核对 */}
                    {si && firstNote && (() => {
                      const lastRow = firstNote.rows.length > 0 ? firstNote.rows[firstNote.rows.length - 1] : [];
                      const parseNum = (v: any): number | null => {
                        if (v == null) return null;
                        const s = String(v).replace(/,/g, '').trim();
                        const n = parseFloat(s);
                        return isNaN(n) ? null : n;
                      };
                      const noteClosing = lastRow.length >= 2 ? parseNum(lastRow[lastRow.length - 2]) : null;
                      const noteOpening = lastRow.length >= 1 ? parseNum(lastRow[lastRow.length - 1]) : null;
                      const closingMatch = noteClosing != null && si.closing_balance != null ? Math.abs(noteClosing - si.closing_balance) < 0.01 : null;
                      const openingMatch = noteOpening != null && si.opening_balance != null ? Math.abs(noteOpening - si.opening_balance) < 0.01 : null;
                      return (
                        <div style={{
                          display: 'flex', gap: 32, padding: '10px 16px', borderRadius: GT.radiusSm,
                          background: GT.bgPage, border: `1px solid ${GT.border}`,
                          fontSize: 13, alignItems: 'center',
                        }}>
                          <span style={{ fontWeight: 600, color: GT.textSecondary, minWidth: 60 }}>金额核对</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ color: GT.textMuted }}>期末：</span>
                            {closingMatch === true ? <span style={{ color: GT.success, fontWeight: 700, fontSize: 16 }}>✓</span>
                              : closingMatch === false ? <span style={{ color: GT.danger, fontWeight: 600 }}>✗ <span style={{ fontSize: 11 }}>(附注{fmtAmt(noteClosing)} ≠ 报表{fmtAmt(si.closing_balance)})</span></span>
                              : <span style={{ color: '#ccc' }}>—</span>}
                          </span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ color: GT.textMuted }}>期初：</span>
                            {openingMatch === true ? <span style={{ color: GT.success, fontWeight: 700, fontSize: 16 }}>✓</span>
                              : openingMatch === false ? <span style={{ color: GT.danger, fontWeight: 600 }}>✗ <span style={{ fontSize: 11 }}>(附注{fmtAmt(noteOpening)} ≠ 报表{fmtAmt(si.opening_balance)})</span></span>
                              : <span style={{ color: '#ccc' }}>—</span>}
                          </span>
                        </div>
                      );
                    })()}
                    {g.notes.length > 1 && (
                      <details style={{ marginTop: 14 }}>
                        <summary style={{
                          cursor: 'pointer', fontSize: 13, color: GT.primaryLight,
                          fontWeight: 500, padding: '8px 0',
                        }}>
                          查看更多附注表格 ({g.notes.length - 1})
                        </summary>
                        <div style={{ marginTop: 8 }}>
                          {g.notes.slice(1).map(nt => renderNoteTable(nt, nt.section_title))}
                        </div>
                      </details>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // ─── 收集 section 及其所有子节点的 note_table_ids ───
  const collectNoteIds = (sec: NoteSection): string[] => {
    const ids = [...sec.note_table_ids];
    for (const child of sec.children) { ids.push(...collectNoteIds(child)); }
    return ids;
  };

  // ─── 渲染通用章节内容（正文段落 + 附注表格） ───
  const renderSectionContent = (sec: NoteSection) => {
    // 收集所有表格标题，用于从正文段落中去重
    const tableTitles = new Set(
      sec.note_table_ids
        .map(id => noteMap.get(id)?.section_title?.trim())
        .filter(Boolean) as string[]
    );
    // 也把 section 自身标题加入去重集合
    tableTitles.add(sec.title.trim());

    // 过滤掉跟表格标题或节点标题重复的正文段落
    const filteredParas = sec.content_paragraphs.filter(p => !tableTitles.has(p.trim()));

    // 用于跟踪已显示过的表格标题，避免连续重复
    const shownLabels = new Set<string>();

    return (
      <div style={{ padding: '10px 0' }}>
        {filteredParas.length > 0 && (
          <div style={{ marginBottom: 14, lineHeight: 1.9, fontSize: 14, color: GT.text }}>
            {filteredParas.map((p, i) => (
              <p key={i} style={{ margin: '5px 0' }}>{p}</p>
            ))}
          </div>
        )}
        {sec.note_table_ids.map(id => {
          const nt = noteMap.get(id);
          if (!nt) return null;
          // 不显示跟 section 标题相同的表格标题，也不重复显示相同的表格标题
          const rawLabel = nt.section_title?.trim() || '';
          let label: string | undefined;
          if (rawLabel && rawLabel !== sec.title.trim() && !shownLabels.has(rawLabel)) {
            label = nt.section_title;
            shownLabels.add(rawLabel);
          }
          return renderNoteTable(nt, label, sec.level);
        })}
      </div>
    );
  };

  // ─── 渲染页签条 ───
  const renderTabBar = (
    tabs: { key: number; label: string }[],
    active: number,
    setActive: (v: number) => void,
    level: number,
  ) => {
    const c = lvlColor(level);
    const bg = lvlTitleBg(level);
    const isL1 = level === 1;

    return (
      <div style={{
        display: 'flex', gap: 2, flexWrap: 'wrap',
        borderBottom: `2px solid ${isL1 ? GT.border : '#eee'}`,
        marginBottom: isL1 ? 18 : 12, paddingBottom: 0,
      }}>
        {tabs.map(tab => {
          const isActive = active === tab.key;
          return (
            <button key={tab.key} onClick={() => setActive(tab.key)}
              style={{
                padding: isL1 ? '10px 22px' : '7px 16px',
                border: 'none', background: isActive ? bg : 'transparent',
                cursor: 'pointer', fontSize: isL1 ? 14 : 13,
                borderRadius: '6px 6px 0 0', transition: 'all 0.15s',
                borderBottom: isActive ? `2px solid ${c}` : '2px solid transparent',
                fontWeight: isActive ? 700 : 400,
                color: isActive ? c : GT.textMuted,
                maxWidth: isL1 ? 220 : 180,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                marginBottom: -2,
              }}
              title={tab.label}>
              {tab.label}
            </button>
          );
        })}
      </div>
    );
  };

  // ─── 递归渲染章节（连续展示，不分页签） ───
  const renderSectionFlat = (sec: NoteSection): React.ReactNode => {
    const tc = lvlColor(sec.level);
    const tBg = lvlTitleBg(sec.level);
    const cBg = lvlBodyBg(sec.level);
    const bc = lvlBorder(sec.level);
    const isCollapsed = collapsedIds.has(sec.id);
    const hasContent = sec.content_paragraphs.length > 0 || sec.note_table_ids.length > 0 || sec.children.length > 0;

    return (
      <div key={sec.id} style={{
        marginBottom: 12, borderLeft: `3px solid ${bc}`,
        borderRadius: GT.radiusSm, overflow: 'hidden',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      }}>
        <div
          onClick={() => hasContent && toggleCollapse(sec.id)}
          style={{
            fontSize: sec.level <= 3 ? 14 : 13, fontWeight: 600,
            color: tc, background: tBg, padding: '8px 14px',
            letterSpacing: 0.3, display: 'flex', alignItems: 'center',
            justifyContent: 'space-between',
            cursor: hasContent ? 'pointer' : 'default',
            userSelect: 'none',
          }}>
          <span>{sec.title}</span>
          {hasContent && (
            <span style={{
              fontSize: 14, fontWeight: 700, color: tc,
              width: 20, height: 20, display: 'inline-flex',
              alignItems: 'center', justifyContent: 'center',
              borderRadius: 4, background: `${tc}15`,
              flexShrink: 0, marginLeft: 8,
            }}>{isCollapsed ? '+' : '−'}</span>
          )}
        </div>
        {!isCollapsed && (
          <div style={{ background: cBg, padding: '6px 14px' }}>
            {renderSectionContent(sec)}
            {sec.children.map(child => renderSectionFlat(child))}
          </div>
        )}
      </div>
    );
  };

  // ─── 渲染有子层级的章节（递归页签） ───
  const renderSectionWithChildren = (
    sec: NoteSection, levelState: number,
    setLevelState: (v: number) => void, nextLevel: number,
  ) => {
    if (sec.children.length === 0) return renderSectionContent(sec);

    const tabs = sec.children.map((child, i) => ({ key: i, label: child.title }));
    const activeChild = sec.children[Math.min(levelState, sec.children.length - 1)];

    const getNextState = (): [number, (v: number) => void, number] => {
      if (nextLevel === 3) return [activeL3, setActiveL3, 4];
      if (nextLevel === 4) return [activeL4, setActiveL4, 5];
      return [0, () => {}, 5];
    };
    const [nextState, setNextState, nextNextLevel] = getNextState();

    const cBg = lvlBodyBg(sec.level);
    const bc = lvlBorder(sec.level);

    return (
      <div style={{
        background: cBg,
        borderLeft: sec.level >= 2 ? `3px solid ${bc}` : 'none',
        borderRadius: sec.level >= 2 ? GT.radiusSm : 0,
        padding: sec.level >= 2 ? '12px 16px' : 0,
        marginTop: sec.level >= 2 ? 6 : 0,
      }}>
        {(sec.content_paragraphs.length > 0 || sec.note_table_ids.length > 0) && renderSectionContent(sec)}
        {renderTabBar(tabs, levelState, setLevelState, sec.level + 1)}
        {activeChild && (
          activeChild.children.length > 0 && nextLevel <= 3
            ? renderSectionWithChildren(activeChild, nextState, setNextState, nextNextLevel)
            : activeChild.children.length > 0
              ? (() => {
                  const acCollapsed = collapsedIds.has(activeChild.id);
                  const acTc = lvlColor(activeChild.level);
                  return (
                    <div style={{
                      borderLeft: `3px solid ${lvlBorder(activeChild.level)}`,
                      borderRadius: GT.radiusSm, overflow: 'hidden', marginTop: 6,
                      boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                    }}>
                      <div
                        onClick={() => toggleCollapse(activeChild.id)}
                        style={{
                          fontSize: 14, fontWeight: 600,
                          color: acTc,
                          background: lvlTitleBg(activeChild.level),
                          padding: '8px 14px', letterSpacing: 0.3,
                          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                          cursor: 'pointer', userSelect: 'none',
                        }}>
                        <span>{activeChild.title}</span>
                        <span style={{
                          fontSize: 14, fontWeight: 700, color: acTc,
                          width: 20, height: 20, display: 'inline-flex',
                          alignItems: 'center', justifyContent: 'center',
                          borderRadius: 4, background: `${acTc}15`,
                          flexShrink: 0, marginLeft: 8,
                        }}>{acCollapsed ? '+' : '−'}</span>
                      </div>
                      {!acCollapsed && (
                        <div style={{
                          background: lvlBodyBg(activeChild.level), padding: '6px 14px',
                        }}>
                          {renderSectionContent(activeChild)}
                          {activeChild.children.map(child => renderSectionFlat(child))}
                        </div>
                      )}
                    </div>
                  );
                })()
              : renderSectionContent(activeChild)
        )}
      </div>
    );
  };

  // ─── Loading ───
  if (loading) return (
    <div style={{ textAlign: 'center', padding: 60, color: GT.textMuted }}>
      <div style={{ fontSize: 28, marginBottom: 10 }}>⏳</div>
      <div style={{ fontSize: 14 }}>加载中...</div>
    </div>
  );

  // ─── 无层级结构回退 ───
  if (!hasSections) {
    const allNoteIds = notes.map(n => n.id);
    return (
      <div style={{ fontFamily: GT.font }}>
        {renderStatementMatching(allNoteIds)}
        {error && (
          <div style={{
            color: GT.danger, padding: '10px 16px', background: '#fdf0ef',
            borderRadius: GT.radiusSm, margin: '16px 0', fontSize: 13,
            border: '1px solid #f5c6cb',
          }}>⚠ {error}</div>
        )}
        <div style={{ textAlign: 'right', marginTop: 24, paddingTop: 16, borderTop: `1px solid ${GT.border}` }}>
          <button onClick={handleConfirm} disabled={loading}
            style={{
              padding: '10px 40px', border: 'none', borderRadius: GT.radius,
              cursor: loading ? 'not-allowed' : 'pointer',
              background: loading ? '#ccc' : `linear-gradient(135deg, ${GT.primary} 0%, ${GT.primaryLight} 100%)`,
              color: '#fff', fontSize: 14, fontWeight: 600, transition: 'all 0.2s',
              boxShadow: loading ? 'none' : `0 2px 10px ${GT.primary}40`,
            }}>确认匹配</button>
        </div>
      </div>
    );
  }

  // ─── 层级化视图 ───
  const l1Tabs = sections.map((sec, i) => ({ key: i, label: sec.title }));
  const activeSection = sections[Math.min(activeL1, sections.length - 1)];

  return (
    <div style={{ fontFamily: GT.font }}>
      {renderTabBar(l1Tabs, activeL1, setActiveL1, 1)}

      <div style={{ maxHeight: 'calc(100vh - 260px)', overflowY: 'auto', paddingRight: 4 }}>
        {activeSection && (
          isMainNoteSection(activeSection.title)
            ? renderStatementMatching(collectNoteIds(activeSection))
            : activeSection.children.length > 0
              ? renderSectionWithChildren(activeSection, activeL2, setActiveL2, 3)
              : renderSectionContent(activeSection)
        )}
      </div>

      {error && (
        <div style={{
          color: GT.danger, padding: '10px 16px', background: '#fdf0ef',
          borderRadius: GT.radiusSm, margin: '16px 0', fontSize: 13,
          border: '1px solid #f5c6cb',
        }}>⚠ {error}</div>
      )}

      <div style={{ textAlign: 'right', marginTop: 24, paddingTop: 16, borderTop: `1px solid ${GT.border}` }}>
        <button onClick={handleConfirm} disabled={loading}
          style={{
            padding: '10px 40px', border: 'none', borderRadius: GT.radius,
            cursor: loading ? 'not-allowed' : 'pointer',
            background: loading ? '#ccc' : `linear-gradient(135deg, ${GT.primary} 0%, ${GT.primaryLight} 100%)`,
            color: '#fff', fontSize: 14, fontWeight: 600, transition: 'all 0.2s',
            boxShadow: loading ? 'none' : `0 2px 10px ${GT.primary}40`,
          }}>确认匹配</button>
      </div>
    </div>
  );
};

export default AccountMatchingView;
