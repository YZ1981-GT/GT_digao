/**
 * AccountMatchingView - 科目-附注对照视图（层级化版本）
 *
 * 按附注文档的一级标题作为顶层页签，"财务报表主要项目注释"下展示报表科目对照，
 * "重要会计政策和会计估计"等内容多的章节按2/3/4级层级多页签展开。
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  StatementItem, NoteTable, NoteSection, MatchingMap,
} from '../types/audit';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

// ─── 报表科目分类（用于"财务报表主要项目注释"下的子页签） ───
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

/** 判断一级标题是否为"财务报表主要项目注释" */
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

  // 一级页签：附注一级标题索引
  const [activeL1, setActiveL1] = useState(0);
  // 二级页签（用于有子层级的章节）
  const [activeL2, setActiveL2] = useState(0);
  // 三级页签
  const [activeL3, setActiveL3] = useState(0);
  // 四级页签
  const [activeL4, setActiveL4] = useState(0);
  // 报表科目子页签（仅在"财务报表主要项目注释"下使用）
  const [activeSubTab, setActiveSubTab] = useState<SubTabKey>('asset');
  // 展开的科目ID
  const [expandedId, setExpandedId] = useState<string | null>(null);

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
      .amt-table tbody tr:hover > td { background: #f3f0fa !important; }
      .amt-table td.amt-col-hover, .amt-table th.amt-col-hover { background: #f3f0fa !important; }
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

  // ─── 如果没有 note_sections，回退到旧的扁平模式 ───
  const hasSections = sections.length > 0;

  // 当一级页签切换时重置子页签
  useEffect(() => { setActiveL2(0); setActiveL3(0); setActiveL4(0); }, [activeL1]);
  useEffect(() => { setActiveL3(0); setActiveL4(0); }, [activeL2]);
  useEffect(() => { setActiveL4(0); }, [activeL3]);

  // ─── 渲染附注表格 ───
  const renderNoteTable = (nt: NoteTable, label?: string) => (
    <div key={nt.id} style={{ marginBottom: 16 }}>
      {label && <div style={{ fontSize: 13, color: '#888', marginBottom: 4 }}>{label}</div>}
      <div style={{ overflowX: 'auto', borderRadius: 8, border: '1px solid #e8e5f0' }}>
        <table className="amt-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <caption className="sr-only">{nt.account_name}</caption>
          {nt.headers.length > 0 && (
            <thead>
              <tr>{nt.headers.map((h, i) => (
                <th key={i} onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                  style={{
                    padding: '10px 14px', background: '#f8f6fc', fontWeight: 600,
                    borderBottom: '2px solid #e0dce8', color: '#4b2d77',
                    textAlign: i === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                  }}>{h}</th>
              ))}</tr>
            </thead>
          )}
          <tbody>
            {nt.rows.slice(0, 30).map((row, ri) => (
              <tr key={ri} style={{ background: ri % 2 === 0 ? '#fff' : '#faf9fc' }}>
                {row.map((c: any, ci: number) => (
                  <td key={ci} onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                    style={{
                      padding: '8px 14px', borderBottom: '1px solid #f0edf6',
                      textAlign: ci === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                      fontVariantNumeric: ci > 0 ? 'tabular-nums' : 'normal', color: '#444',
                    }}>{c != null ? String(c) : ''}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  // ─── 渲染报表科目对照（用于"财务报表主要项目注释"） ───
  const renderStatementMatching = (_sectionNoteIds: string[]) => {
    // 收集该 section 及其子节点下所有的 note_table_ids
    const sectionNotes = _sectionNoteIds.map(id => noteMap.get(id)).filter(Boolean) as NoteTable[];

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
        <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e8e5f0', marginBottom: 16, paddingBottom: 0 }}>
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
                  padding: '8px 18px', border: 'none', background: isActive ? '#f3f0fa' : 'transparent',
                  cursor: 'pointer', fontSize: 13, borderRadius: '6px 6px 0 0', transition: 'all 0.2s',
                  borderBottom: isActive ? '2px solid #4b2d77' : '2px solid transparent',
                  fontWeight: isActive ? 700 : 400, color: isActive ? '#4b2d77' : '#888',
                }}>
                {tab.label}
                {cnt > 0 && <span style={{
                  fontSize: 10, marginLeft: 4, padding: '1px 5px', borderRadius: 8,
                  background: isActive ? '#4b2d77' : '#e0e0e0', color: isActive ? '#fff' : '#666',
                }}>{cnt}</span>}
              </button>
            );
          })}
        </div>

        {groups.length === 0 && (
          <div style={{ color: '#aaa', padding: 30, textAlign: 'center', fontSize: 14 }}>该分类下暂无科目</div>
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
                marginBottom: 10, borderRadius: 8, overflow: 'hidden', transition: 'all 0.2s',
                border: isExpanded ? '2px solid #4b2d77' : '1px solid #e0dce8',
                boxShadow: isExpanded ? '0 4px 16px rgba(75,45,119,0.12)' : '0 1px 4px rgba(0,0,0,0.04)',
              }}>
                <div onClick={() => setExpandedId(isExpanded ? null : gKey)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 16px', cursor: 'pointer', transition: 'background 0.2s',
                    background: isExpanded ? 'linear-gradient(135deg, #f3f0fa 0%, #ece8f5 100%)' : '#faf9fc',
                    borderBottom: isExpanded ? '1px solid #e0dce8' : 'none',
                  }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      width: 26, height: 26, borderRadius: '50%', fontSize: 11, fontWeight: 700,
                      background: hasNotes ? '#4b2d77' : '#e67e22', color: '#fff',
                    }}>{gi + 1}</span>
                    <span style={{ fontWeight: 600, fontSize: 14, color: '#2c2c2c' }}>{g.accountName}</span>
                    {!hasNotes && (
                      <span style={{ fontSize: 11, color: '#e67e22', background: '#fef5ec', padding: '2px 8px', borderRadius: 4, fontWeight: 500 }}>
                        附注缺失
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 12, color: '#999' }}>
                    <span style={{
                      padding: '2px 8px', borderRadius: 4,
                      background: hasNotes ? '#f0edf6' : '#f5f5f5', color: hasNotes ? '#6b4fa0' : '#999',
                    }}>附注: {g.notes.length}</span>
                    <span style={{ transition: 'transform 0.2s', transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)', fontSize: 14, color: '#999' }}>▼</span>
                  </div>
                </div>

                {isExpanded && (
                  <div style={{ padding: '14px 16px', background: '#fff' }}>
                    {firstNote && (
                      <div style={{ marginBottom: 16 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#4b2d77', display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 4, height: 14, background: '#4b2d77', borderRadius: 2, display: 'inline-block' }} />附注
                        </div>
                        {renderNoteTable(firstNote)}
                      </div>
                    )}
                    {si && (
                      <div style={{ marginBottom: 16 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#2980b9', display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 4, height: 14, background: '#2980b9', borderRadius: 2, display: 'inline-block' }} />报表
                        </div>
                        <div style={{ borderRadius: 8, border: '1px solid #d6eaf8', overflow: 'hidden', maxWidth: 560 }}>
                          <table className="amt-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                            <caption className="sr-only">{g.accountName} 报表数据</caption>
                            <thead>
                              <tr style={{ background: '#eaf2f8' }}>
                                <th onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '10px 14px', fontWeight: 600, color: '#2980b9', textAlign: 'left' }}>项　目</th>
                                <th onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '10px 14px', fontWeight: 600, color: '#2980b9', textAlign: 'right' }}>期末余额</th>
                                <th onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '10px 14px', fontWeight: 600, color: '#2980b9', textAlign: 'right' }}>期初余额</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr style={{ background: '#fff' }}>
                                <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '10px 14px', fontWeight: 600, color: '#333', borderBottom: '1px solid #eaf2f8' }}>{si.account_name}</td>
                                <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '10px 14px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 600, color: '#333', borderBottom: '1px solid #eaf2f8' }}>{fmtAmt(si.closing_balance)}</td>
                                <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '10px 14px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 600, color: '#333', borderBottom: '1px solid #eaf2f8' }}>{fmtAmt(si.opening_balance)}</td>
                              </tr>
                              {g.subItems.map(sub => (
                                <tr key={sub.id} style={{ background: '#fafcfe' }}>
                                  <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '8px 14px 8px 28px', color: '#666', borderBottom: '1px solid #f0f5fa' }}>
                                    <span style={{ color: '#ccc', marginRight: 4 }}>└</span>{sub.account_name}
                                  </td>
                                  <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '8px 14px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: '#666', borderBottom: '1px solid #f0f5fa' }}>{fmtAmt(sub.closing_balance)}</td>
                                  <td onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave} style={{ padding: '8px 14px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: '#666', borderBottom: '1px solid #f0f5fa' }}>{fmtAmt(sub.opening_balance)}</td>
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
                        <div style={{ display: 'flex', gap: 32, padding: '10px 16px', borderRadius: 8, background: '#f9f9fb', border: '1px solid #eee', fontSize: 13, alignItems: 'center' }}>
                          <span style={{ fontWeight: 600, color: '#555', minWidth: 60 }}>金额核对</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ color: '#888' }}>期末：</span>
                            {closingMatch === true ? <span style={{ color: '#27ae60', fontWeight: 700, fontSize: 16 }}>✓</span>
                              : closingMatch === false ? <span style={{ color: '#e74c3c', fontWeight: 600 }}>✗ <span style={{ fontSize: 11 }}>(附注{fmtAmt(noteClosing)} ≠ 报表{fmtAmt(si.closing_balance)})</span></span>
                              : <span style={{ color: '#ccc' }}>—</span>}
                          </span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ color: '#888' }}>期初：</span>
                            {openingMatch === true ? <span style={{ color: '#27ae60', fontWeight: 700, fontSize: 16 }}>✓</span>
                              : openingMatch === false ? <span style={{ color: '#e74c3c', fontWeight: 600 }}>✗ <span style={{ fontSize: 11 }}>(附注{fmtAmt(noteOpening)} ≠ 报表{fmtAmt(si.opening_balance)})</span></span>
                              : <span style={{ color: '#ccc' }}>—</span>}
                          </span>
                        </div>
                      );
                    })()}
                    {g.notes.length > 1 && (
                      <details style={{ marginTop: 12 }}>
                        <summary style={{ cursor: 'pointer', fontSize: 13, color: '#6b4fa0', fontWeight: 500, padding: '6px 0' }}>
                          查看更多附注表格 ({g.notes.length - 1})
                        </summary>
                        {g.notes.slice(1).map(nt => renderNoteTable(nt, nt.section_title))}
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
    for (const child of sec.children) {
      ids.push(...collectNoteIds(child));
    }
    return ids;
  };

  // ─── 渲染通用章节内容（正文段落 + 附注表格） ───
  const renderSectionContent = (sec: NoteSection) => (
    <div style={{ padding: '12px 0' }}>
      {sec.content_paragraphs.length > 0 && (
        <div style={{ marginBottom: 16, lineHeight: 1.8, fontSize: 14, color: '#333' }}>
          {sec.content_paragraphs.map((p, i) => (
            <p key={i} style={{ margin: '6px 0' }}>{p}</p>
          ))}
        </div>
      )}
      {sec.note_table_ids.map(id => {
        const nt = noteMap.get(id);
        return nt ? renderNoteTable(nt, nt.section_title) : null;
      })}
    </div>
  );

  // ─── 渲染页签条 ───
  const renderTabBar = (
    tabs: { key: number; label: string }[],
    active: number,
    setActive: (v: number) => void,
    level: number,
  ) => {
    const colors = ['#4b2d77', '#2980b9', '#27ae60', '#e67e22'];
    const bgColors = ['#f3f0fa', '#eaf2f8', '#eafaf1', '#fef5ec'];
    const c = colors[Math.min(level - 1, colors.length - 1)];
    const bg = bgColors[Math.min(level - 1, bgColors.length - 1)];

    return (
      <div style={{
        display: 'flex', gap: 2, flexWrap: 'wrap',
        borderBottom: `1px solid ${level === 1 ? '#e8e5f0' : '#eee'}`,
        marginBottom: level === 1 ? 16 : 12, paddingBottom: 0,
      }}>
        {tabs.map(tab => {
          const isActive = active === tab.key;
          return (
            <button key={tab.key} onClick={() => setActive(tab.key)}
              style={{
                padding: level === 1 ? '10px 20px' : '7px 14px',
                border: 'none', background: isActive ? bg : 'transparent',
                cursor: 'pointer', fontSize: level === 1 ? 14 : 13,
                borderRadius: '6px 6px 0 0', transition: 'all 0.2s',
                borderBottom: isActive ? `2px solid ${c}` : '2px solid transparent',
                fontWeight: isActive ? 700 : 400,
                color: isActive ? c : '#888',
                maxWidth: level === 1 ? 220 : 180,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}
              title={tab.label}>
              {tab.label}
            </button>
          );
        })}
      </div>
    );
  };

  // ─── 渲染有子层级的章节（递归展开为页签） ───
  const renderSectionWithChildren = (sec: NoteSection, levelState: number, setLevelState: (v: number) => void, nextLevel: number) => {
    if (sec.children.length === 0) {
      return renderSectionContent(sec);
    }

    const tabs = sec.children.map((child, i) => ({ key: i, label: child.title }));
    const activeChild = sec.children[Math.min(levelState, sec.children.length - 1)];

    // 获取下一层的 state/setter
    const getNextState = (): [number, (v: number) => void, number] => {
      if (nextLevel === 3) return [activeL3, setActiveL3, 4];
      if (nextLevel === 4) return [activeL4, setActiveL4, 5];
      return [0, () => {}, 5]; // 最多4级
    };

    const [nextState, setNextState, nextNextLevel] = getNextState();

    return (
      <div>
        {/* 当前节点自身的内容 */}
        {(sec.content_paragraphs.length > 0 || sec.note_table_ids.length > 0) && renderSectionContent(sec)}
        {/* 子节点页签 */}
        {renderTabBar(tabs, levelState, setLevelState, sec.level + 1)}
        {activeChild && (
          activeChild.children.length > 0
            ? renderSectionWithChildren(activeChild, nextState, setNextState, nextNextLevel)
            : renderSectionContent(activeChild)
        )}
      </div>
    );
  };

  if (loading) return (
    <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>
      <div style={{ fontSize: 24, marginBottom: 8 }}>⏳</div>
      加载中...
    </div>
  );

  // ─── 无层级结构时回退到旧的扁平模式 ───
  if (!hasSections) {
    // 回退：使用旧的扁平科目列表
    const allNoteIds = notes.map(n => n.id);
    return (
      <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
        {renderStatementMatching(allNoteIds)}
        {error && (
          <div style={{ color: '#c0392b', padding: '10px 16px', background: '#fdf0ef', borderRadius: 8, margin: '16px 0', fontSize: 13, border: '1px solid #f5c6cb' }}>
            ⚠ {error}
          </div>
        )}
        <div style={{ textAlign: 'right', marginTop: 20, paddingTop: 16, borderTop: '1px solid #eee' }}>
          <button onClick={handleConfirm} disabled={loading}
            style={{
              padding: '10px 36px', border: 'none', borderRadius: 8, cursor: loading ? 'not-allowed' : 'pointer',
              background: loading ? '#ccc' : 'linear-gradient(135deg, #4b2d77 0%, #6b4fa0 100%)',
              color: '#fff', fontSize: 14, fontWeight: 600, transition: 'all 0.2s',
              boxShadow: loading ? 'none' : '0 2px 8px rgba(75,45,119,0.3)',
            }}>确认匹配</button>
        </div>
      </div>
    );
  }

  // ─── 层级化视图 ───
  const l1Tabs = sections.map((sec, i) => ({ key: i, label: sec.title }));
  const activeSection = sections[Math.min(activeL1, sections.length - 1)];

  return (
    <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
      {/* 一级页签：附注一级标题 */}
      {renderTabBar(l1Tabs, activeL1, setActiveL1, 1)}

      {/* 一级内容区 */}
      <div style={{ maxHeight: 'calc(100vh - 260px)', overflowY: 'auto', paddingRight: 4 }}>
        {activeSection && (
          isMainNoteSection(activeSection.title)
            ? /* 财务报表主要项目注释 → 展示报表科目对照 */
              renderStatementMatching(collectNoteIds(activeSection))
            : activeSection.children.length > 0
              ? /* 有子层级的章节 → 递归页签 */
                renderSectionWithChildren(activeSection, activeL2, setActiveL2, 3)
              : /* 无子层级 → 直接展示内容 */
                renderSectionContent(activeSection)
        )}
      </div>

      {error && (
        <div style={{ color: '#c0392b', padding: '10px 16px', background: '#fdf0ef', borderRadius: 8, margin: '16px 0', fontSize: 13, border: '1px solid #f5c6cb' }}>
          ⚠ {error}
        </div>
      )}

      <div style={{ textAlign: 'right', marginTop: 20, paddingTop: 16, borderTop: '1px solid #eee' }}>
        <button onClick={handleConfirm} disabled={loading}
          style={{
            padding: '10px 36px', border: 'none', borderRadius: 8, cursor: loading ? 'not-allowed' : 'pointer',
            background: loading ? '#ccc' : 'linear-gradient(135deg, #4b2d77 0%, #6b4fa0 100%)',
            color: '#fff', fontSize: 14, fontWeight: 600, transition: 'all 0.2s',
            boxShadow: loading ? 'none' : '0 2px 8px rgba(75,45,119,0.3)',
          }}>确认匹配</button>
      </div>
    </div>
  );
};

export default AccountMatchingView;
