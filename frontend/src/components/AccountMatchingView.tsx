/**
 * AccountMatchingView - 科目-附注对照视图
 * 按附注科目逐项展示：附注表格 → 报表对照 → 金额核对
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  StatementItem, NoteTable, MatchingMap,
} from '../types/audit';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

type TabKey = 'asset' | 'liability_equity' | 'income' | 'cash_flow' | 'related_party';
const TABS: { key: TabKey; label: string }[] = [
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

function itemTab(item: StatementItem): TabKey {
  if (item.statement_type === 'income_statement') return 'income';
  if (item.statement_type === 'cash_flow') return 'cash_flow';
  if (item.statement_type === 'equity_change') return 'liability_equity';
  const n = item.account_name.replace(/\s/g, '');
  for (const kw of ASSET_KW) { if (n.includes(kw)) return 'asset'; }
  return 'liability_equity';
}

/** 按科目名称模糊匹配（仅作为 matching_map 未覆盖时的回退） */
function fuzzyMatch(a: string, b: string): boolean {
  const ca = a.replace(/[\s△☆▲]/g, '');
  const cb = b.replace(/[\s△☆▲]/g, '');
  return ca.includes(cb) || cb.includes(ca);
}

/** 格式化金额 */
function fmtAmt(v?: number | null): string {
  if (v == null) return '-';
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
  const [matching, setMatching] = useState<MatchingMap | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('asset');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    fetch(`${API}/api/report-review/session/${sessionId}`)
      .then(r => r.json())
      .then(data => {
        setItems(data.statement_items || []);
        setNotes(data.note_tables || []);
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

  /** 根据 matching_map 查找科目对应的附注，未命中时回退到模糊匹配 */
  const findMatchedNotes = useCallback((si: StatementItem): NoteTable[] => {
    if (matching) {
      const entry = matching.entries?.find(e => e.statement_item_id === si.id);
      if (entry && entry.note_table_ids.length > 0) {
        const noteMap = new Map(notes.map(n => [n.id, n]));
        return entry.note_table_ids.map(id => noteMap.get(id)).filter(Boolean) as NoteTable[];
      }
    }
    // 回退到模糊匹配
    return notes.filter(n => fuzzyMatch(n.account_name, si.account_name));
  }, [matching, notes]);

  /** 报表期初期末均为0（含null/undefined）且无附注匹配的科目不显示 */
  const isZeroAndNoNotes = (si: StatementItem, matchedNotes: NoteTable[]): boolean => {
    const ob = si.opening_balance ?? 0;
    const cb = si.closing_balance ?? 0;
    return ob === 0 && cb === 0 && matchedNotes.length === 0;
  };

  const buildGroups = (): NoteGroup[] => {
    const mainItems = items.filter(i => !i.is_sub_item && itemTab(i) === activeTab);
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

  // 行列高亮 hover 样式（注入一次）
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

  /** 列高亮：鼠标进入单元格时给同列所有 td/th 加 class */
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

  if (loading) return (
    <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>
      <div style={{ fontSize: 24, marginBottom: 8 }}>⏳</div>
      加载中...
    </div>
  );

  return (
    <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
      {/* 页签 */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '2px solid #e8e5f0', marginBottom: 20, paddingBottom: 0 }}>
        {TABS.map(tab => {
          const cnt = items.filter(i => {
            if (i.is_sub_item) return false;
            if (itemTab(i) !== tab.key) return false;
            const matched = findMatchedNotes(i);
            return !isZeroAndNoNotes(i, matched);
          }).length;
          const isActive = activeTab === tab.key;
          return (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)}
              style={{
                padding: '10px 24px', border: 'none', background: isActive ? '#f3f0fa' : 'transparent',
                cursor: 'pointer', fontSize: 14, borderRadius: '8px 8px 0 0', transition: 'all 0.2s',
                borderBottom: isActive ? '3px solid #4b2d77' : '3px solid transparent',
                fontWeight: isActive ? 700 : 400,
                color: isActive ? '#4b2d77' : '#888',
              }}>
              {tab.label}
              {cnt > 0 && <span style={{
                fontSize: 11, marginLeft: 6, padding: '1px 6px', borderRadius: 10,
                background: isActive ? '#4b2d77' : '#e0e0e0',
                color: isActive ? '#fff' : '#666',
              }}>
                {cnt}
              </span>}
            </button>
          );
        })}
      </div>

      {groups.length === 0 && (
        <div style={{ color: '#aaa', padding: 40, textAlign: 'center', fontSize: 14 }}>
          该分类下暂无科目
        </div>
      )}

      {/* 科目列表 */}
      <div style={{ maxHeight: 'calc(100vh - 260px)', overflowY: 'auto', paddingRight: 4 }}>
        {groups.map((g, gi) => {
          const si = g.statementItem;
          const firstNote = g.notes[0];
          const gKey = si?.id || `g${gi}`;
          const isExpanded = expandedId === gKey;
          const hasNotes = g.notes.length > 0;

          return (
            <div key={gKey} style={{
              marginBottom: 12, borderRadius: 10, overflow: 'hidden', transition: 'all 0.2s',
              border: isExpanded ? '2px solid #4b2d77' : '1px solid #e0dce8',
              boxShadow: isExpanded ? '0 4px 16px rgba(75,45,119,0.12)' : '0 1px 4px rgba(0,0,0,0.04)',
            }}>
              {/* 科目标题栏 */}
              <div
                onClick={() => setExpandedId(isExpanded ? null : gKey)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 20px', cursor: 'pointer', transition: 'background 0.2s',
                  background: isExpanded ? 'linear-gradient(135deg, #f3f0fa 0%, #ece8f5 100%)' : '#faf9fc',
                  borderBottom: isExpanded ? '1px solid #e0dce8' : 'none',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    width: 28, height: 28, borderRadius: '50%', fontSize: 12, fontWeight: 700,
                    background: hasNotes ? '#4b2d77' : '#e67e22', color: '#fff',
                  }}>
                    {gi + 1}
                  </span>
                  <span style={{ fontWeight: 600, fontSize: 15, color: '#2c2c2c' }}>
                    {g.accountName}
                  </span>
                  {!hasNotes && (
                    <span style={{
                      fontSize: 11, color: '#e67e22', background: '#fef5ec',
                      padding: '2px 8px', borderRadius: 4, fontWeight: 500,
                    }}>
                      附注缺失
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 12, color: '#999' }}>
                  <span style={{
                    padding: '2px 8px', borderRadius: 4,
                    background: hasNotes ? '#f0edf6' : '#f5f5f5',
                    color: hasNotes ? '#6b4fa0' : '#999',
                  }}>
                    附注: {g.notes.length}
                  </span>
                  <span style={{
                    transition: 'transform 0.2s',
                    transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                    fontSize: 14, color: '#999',
                  }}>▼</span>
                </div>
              </div>

              {/* 展开内容 */}
              {isExpanded && (
                <div style={{ padding: '16px 20px', background: '#fff' }}>
                  {/* 附注表格 */}
                  {firstNote && (
                    <div style={{ marginBottom: 20 }}>
                      <div style={{
                        fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#4b2d77',
                        display: 'flex', alignItems: 'center', gap: 6,
                      }}>
                        <span style={{ width: 4, height: 16, background: '#4b2d77', borderRadius: 2, display: 'inline-block' }} />
                        附注
                      </div>
                      <div style={{ overflowX: 'auto', borderRadius: 8, border: '1px solid #e8e5f0' }}>
                        <table className="amt-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                          <caption className="sr-only">{g.accountName} 附注表格</caption>
                          {firstNote.headers.length > 0 && (
                            <thead>
                              <tr>
                                {firstNote.headers.map((h, i) => (
                                  <th key={i}
                                    onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                    style={{
                                    padding: '10px 14px', background: '#f8f6fc', fontWeight: 600,
                                    borderBottom: '2px solid #e0dce8', color: '#4b2d77',
                                    textAlign: i === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                                  }}>{h}</th>
                                ))}
                              </tr>
                            </thead>
                          )}
                          <tbody>
                            {firstNote.rows.slice(0, 30).map((row, ri) => (
                              <tr key={ri} style={{ background: ri % 2 === 0 ? '#fff' : '#faf9fc' }}>
                                {row.map((c: any, ci: number) => (
                                  <td key={ci}
                                    onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                    style={{
                                    padding: '8px 14px', borderBottom: '1px solid #f0edf6',
                                    textAlign: ci === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                                    fontVariantNumeric: ci > 0 ? 'tabular-nums' : 'normal',
                                    color: '#444',
                                  }}>{c != null ? String(c) : ''}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* 报表对照区 */}
                  {si && (
                    <div style={{ marginBottom: 20 }}>
                      <div style={{
                        fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#2980b9',
                        display: 'flex', alignItems: 'center', gap: 6,
                      }}>
                        <span style={{ width: 4, height: 16, background: '#2980b9', borderRadius: 2, display: 'inline-block' }} />
                        报表
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
                    const closingMatch = noteClosing != null && si.closing_balance != null
                      ? Math.abs(noteClosing - si.closing_balance) < 0.01 : null;
                    const openingMatch = noteOpening != null && si.opening_balance != null
                      ? Math.abs(noteOpening - si.opening_balance) < 0.01 : null;

                    return (
                      <div style={{
                        display: 'flex', gap: 32, padding: '10px 16px', borderRadius: 8,
                        background: '#f9f9fb', border: '1px solid #eee', fontSize: 13, alignItems: 'center',
                      }}>
                        <span style={{ fontWeight: 600, color: '#555', minWidth: 60 }}>金额核对</span>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ color: '#888' }}>期末：</span>
                          {closingMatch === true
                            ? <span style={{ color: '#27ae60', fontWeight: 700, fontSize: 16 }}>✓</span>
                            : closingMatch === false
                              ? <span style={{ color: '#e74c3c', fontWeight: 600 }}>✗ <span style={{ fontSize: 11 }}>(附注{fmtAmt(noteClosing)} ≠ 报表{fmtAmt(si.closing_balance)})</span></span>
                              : <span style={{ color: '#ccc' }}>—</span>}
                        </span>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ color: '#888' }}>期初：</span>
                          {openingMatch === true
                            ? <span style={{ color: '#27ae60', fontWeight: 700, fontSize: 16 }}>✓</span>
                            : openingMatch === false
                              ? <span style={{ color: '#e74c3c', fontWeight: 600 }}>✗ <span style={{ fontSize: 11 }}>(附注{fmtAmt(noteOpening)} ≠ 报表{fmtAmt(si.opening_balance)})</span></span>
                              : <span style={{ color: '#ccc' }}>—</span>}
                        </span>
                      </div>
                    );
                  })()}

                  {/* 更多附注表格 */}
                  {g.notes.length > 1 && (
                    <details style={{ marginTop: 12 }}>
                      <summary style={{
                        cursor: 'pointer', fontSize: 13, color: '#6b4fa0', fontWeight: 500,
                        padding: '6px 0',
                      }}>
                        查看更多附注表格 ({g.notes.length - 1})
                      </summary>
                      {g.notes.slice(1).map((nt, ni) => (
                        <div key={nt.id} style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 13, color: '#888', marginBottom: 4 }}>{nt.section_title}</div>
                          <div style={{ overflowX: 'auto', borderRadius: 6, border: '1px solid #e8e5f0' }}>
                            <table className="amt-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                              <caption className="sr-only">{nt.account_name} 附注表格 {ni + 2}</caption>
                              {nt.headers.length > 0 && (
                                <thead>
                                  <tr>{nt.headers.map((h, i) => (
                                    <th key={i}
                                      onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                      style={{
                                      padding: '8px 12px', background: '#f8f6fc', fontWeight: 600,
                                      borderBottom: '1px solid #e0dce8', fontSize: 13,
                                      textAlign: i === 0 ? 'left' : 'right',
                                    }}>{h}</th>
                                  ))}</tr>
                                </thead>
                              )}
                              <tbody>
                                {nt.rows.slice(0, 30).map((row, ri) => (
                                  <tr key={ri} style={{ background: ri % 2 === 0 ? '#fff' : '#faf9fc' }}>
                                    {row.map((c: any, ci: number) => (
                                      <td key={ci}
                                        onMouseEnter={handleCellEnter} onMouseLeave={handleCellLeave}
                                        style={{
                                        padding: '6px 12px', borderBottom: '1px solid #f0edf6',
                                        textAlign: ci === 0 ? 'left' : 'right',
                                      }}>{c != null ? String(c) : ''}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      ))}
                    </details>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          color: '#c0392b', padding: '10px 16px', background: '#fdf0ef',
          borderRadius: 8, margin: '16px 0', fontSize: 13, border: '1px solid #f5c6cb',
        }}>
          ⚠ {error}
        </div>
      )}

      {/* 确认按钮 */}
      <div style={{ textAlign: 'right', marginTop: 20, paddingTop: 16, borderTop: '1px solid #eee' }}>
        <button
          onClick={handleConfirm}
          disabled={loading}
          style={{
            padding: '10px 36px', border: 'none', borderRadius: 8, cursor: loading ? 'not-allowed' : 'pointer',
            background: loading ? '#ccc' : 'linear-gradient(135deg, #4b2d77 0%, #6b4fa0 100%)',
            color: '#fff', fontSize: 14, fontWeight: 600, transition: 'all 0.2s',
            boxShadow: loading ? 'none' : '0 2px 8px rgba(75,45,119,0.3)',
          }}
        >
          确认匹配
        </button>
      </div>
    </div>
  );
};

export default AccountMatchingView;
