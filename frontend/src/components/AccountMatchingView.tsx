/**
 * AccountMatchingView - 文档解析视图
 *
 * 一级页签：审计报告正文 | 财务报表 | 财务报表附注
 * - 审计报告正文：单页展示
 * - 财务报表：每个 sheet 一个页签
 * - 财务报表附注：3~4个页签
 *   · 会计政策及其他（报表科目注释前的一级标题，合并一页，可折叠）
 *   · 财务报表主要项目注释
 *   · 母公司财务报表主要项目附注（如有）
 *   · 其他事项（报表科目注释后的一级标题）
 *
 * 致同品牌色系：主色 #4b2d77（致同紫）
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  NoteTable, NoteSection, MatchingMap, StatementItem,
} from '../types/audit';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

// ─── 致同品牌色系 ───
const GT = {
  primary: '#4b2d77',
  primaryLight: '#6b4fa0',
  primaryBg: '#f3f0fa',
  primaryBgDeep: '#ece5f5',
  accent: '#2980b9',
  accentBg: '#eaf2f8',
  success: '#27ae60',
  successBg: '#eafaf1',
  warning: '#e67e22',
  warningBg: '#fef5ec',
  danger: '#e74c3c',
  text: '#2c2c2c',
  textSecondary: '#666',
  textMuted: '#999',
  border: '#e0dce8',
  borderLight: '#f0edf6',
  bgPage: '#faf9fc',
  bgWhite: '#fff',
  shadow: '0 2px 8px rgba(75,45,119,0.08)',
  shadowHover: '0 4px 16px rgba(75,45,119,0.14)',
  radius: 8,
  radiusSm: 6,
  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif',
};

const LEVEL_COLORS: Record<string, Record<number, string>> = {
  title:   { 1: GT.primary, 2: GT.accent, 3: GT.success, 4: GT.warning },
  titleBg: { 1: GT.primaryBgDeep, 2: '#dfedf7', 3: '#e0f5e9', 4: '#fdf2e4' },
  bodyBg:  { 1: '#f9f7fc', 2: '#f4f9fd', 3: '#f4fbf7', 4: '#fefbf6' },
  border:  { 1: GT.primary, 2: GT.accent, 3: GT.success, 4: GT.warning },
};
const lvlColor   = (l: number) => LEVEL_COLORS.title[l]   || GT.textSecondary;
const lvlTitleBg = (l: number) => LEVEL_COLORS.titleBg[l] || '#f0f0f0';
const lvlBodyBg  = (l: number) => LEVEL_COLORS.bodyBg[l]  || '#fafafa';

// ─── 数值格式化：千分符 + 保留2位小数 ───
const fmtNum = (v: any): string => {
  if (v == null) return '';
  const s = String(v).trim();
  if (!s) return '';
  const n = Number(s.replace(/,/g, ''));
  if (isNaN(n)) return s;
  if (n === 0) return '';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
const lvlBorder  = (l: number) => LEVEL_COLORS.border[l]  || '#ccc';

// ─── 判断是否为"财务报表主要项目注释"类标题 ───
// 上市版: "合并财务报表项目附注"  国企版: "财务报表主要项目注释"
const MAIN_NOTE_KW = [
  '财务报表主要项目', '主要项目注释', '报表项目注释',
  '报表主要项目', '合并财务报表项目',
];
// 上市版: "公司财务报表主要项目注释"（无"母"字）
// 国企版: "母公司财务报表的主要项目附注"
const PARENT_NOTE_KW = [
  '母公司财务报表', '母公司报表主要项目',
  '公司财务报表主要项目注释', '公司财务报表主要项目附注',
];

// 合并报表注释的延续章节（位于主项目注释之后、母公司之前，单独页签显示）
const EXTRA_DISCLOSURE_KW = [
  '研发支出', '在其他主体中的权益', '政府补助', '金融工具风险',
  '公允价值', '关联方', '股份支付', '企业合并及合并',
  '补充资料', '非经常性损益', '净资产收益率', '每股收益',
  '承诺及或有', '或有事项', '资产负债表日后', '日后事项',
  '其他重要事项',
];

function isExtraDisclosure(title: string): boolean {
  const c = title.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');
  return EXTRA_DISCLOSURE_KW.some(k => c.includes(k));
}

function isMainNoteSection(title: string): boolean {
  const c = title.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');
  // 先排除母公司标题，避免"公司财务报表主要项目注释"同时命中两个
  if (isParentNoteSection(title)) return false;
  return MAIN_NOTE_KW.some(k => c.includes(k));
}
function isParentNoteSection(title: string): boolean {
  const c = title.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');
  return PARENT_NOTE_KW.some(k => c.includes(k));
}

// ─── Props ───
interface Props {
  sessionId: string | null;
  onConfirm: () => void;
}


const AccountMatchingView: React.FC<Props> = ({ sessionId, onConfirm }) => {
  // ─── State ───
  const [notes, setNotes] = useState<NoteTable[]>([]);
  const [sections, setSections] = useState<NoteSection[]>([]);
  const [sheetData, setSheetData] = useState<Record<string, any[]>>({});
  const [auditReportContent, setAuditReportContent] = useState<Array<{ text: string; level?: number; is_bold?: boolean }>>([]);
  const [matching, setMatching] = useState<MatchingMap | null>(null);
  const [statementItems, setStatementItems] = useState<StatementItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [templateType, setTemplateType] = useState<string>('soe');
  const [parentPresetAccounts, setParentPresetAccounts] = useState<Array<{ name: string; keywords: string[]; order: number }>>([]);

  const [activeTopTab, setActiveTopTab] = useState<string>('notes');
  const [activeSheetTab, setActiveSheetTab] = useState(0);
  const [activeNoteTab, setActiveNoteTab] = useState(0);

  // 折叠状态
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const toggleCollapse = useCallback((id: string) => {
    setCollapsedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // 收集所有 section id（递归）
  const collectAllIds = useCallback((secs: NoteSection[]): string[] => {
    const ids: string[] = [];
    const walk = (s: NoteSection) => { ids.push(s.id); s.children.forEach(walk); };
    secs.forEach(walk);
    return ids;
  }, []);

  const expandAll = useCallback(() => setCollapsedIds(new Set()), []);
  const collapseAll = useCallback((secs: NoteSection[]) => {
    setCollapsedIds(new Set(collectAllIds(secs)));
  }, [collectAllIds]);

  // ─── 数据加载 ───
  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    fetch(`${API}/api/report-review/session/${sessionId}`)
      .then(r => r.json())
      .then(data => {
        setNotes(data.note_tables || []);
        setSections(data.note_sections || []);
        setSheetData(data.sheet_data || {});
        setAuditReportContent(data.audit_report_content || []);
        setMatching(data.matching_map || null);
        setStatementItems(data.statement_items || []);
        if (data.template_type) setTemplateType(data.template_type);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  // ─── hover 样式 ───
  useEffect(() => {
    const STYLE_ID = 'acct-match-table-hover';
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `.amt-table tbody tr:hover>td{background:${GT.primaryBg}!important}`;
    document.head.appendChild(style);
    return () => { document.getElementById(STYLE_ID)?.remove(); };
  }, []);

  // ─── 加载母公司附注预设科目 ───
  useEffect(() => {
    if (!templateType) return;
    fetch(`${API}/api/report-review/parent-accounts/${templateType}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.accounts) setParentPresetAccounts(data.accounts);
      })
      .catch(() => {});
  }, [templateType]);

  const noteMap = useMemo(() => new Map(notes.map(n => [n.id, n])), [notes]);

  // ─── 报表科目映射：noteTableId → StatementItem（反向索引） ───
  const stmtItemMap = useMemo(() => new Map(statementItems.map(s => [s.id, s])), [statementItems]);
  const noteToStmtMap = useMemo(() => {
    const m = new Map<string, StatementItem>();
    if (!matching) return m;
    for (const entry of matching.entries) {
      const item = stmtItemMap.get(entry.statement_item_id);
      if (!item) continue;
      for (const nid of entry.note_table_ids) {
        // 一个 note_table 可能被多个 statement_item 匹配，取第一个
        if (!m.has(nid)) m.set(nid, item);
      }
    }
    return m;
  }, [matching, stmtItemMap]);

  // 通过 section 的 note_table_ids 找到对应的报表科目
  const findStmtForSection = useCallback((sec: NoteSection): StatementItem | null => {
    // 先在自身的 note_table_ids 中查找
    for (const nid of sec.note_table_ids) {
      const item = noteToStmtMap.get(nid);
      if (item) return item;
    }
    // 再在子节点中递归查找
    for (const child of sec.children) {
      const item = findStmtForSection(child);
      if (item) return item;
    }
    // 最后尝试通过科目名称直接匹配
    const secName = sec.title.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');
    for (const si of statementItems) {
      if (si.is_sub_item) continue;
      const siName = si.account_name.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');
      if (secName.includes(siName) || siName.includes(secName)) return si;
    }
    return null;
  }, [noteToStmtMap, statementItems]);

  // ─── 附注分组：前段 / 主项目注释 / 其他专项披露 / 母公司 / 后段 ───
  const noteGroups = useMemo(() => {
    const before: NoteSection[] = [];
    let mainSec: NoteSection | null = null;
    let parentSec: NoteSection | null = null;
    const extra: NoteSection[] = [];
    const after: NoteSection[] = [];
    let foundMain = false;

    for (const sec of sections) {
      if (isMainNoteSection(sec.title)) {
        mainSec = sec;
        foundMain = true;
      } else if (isParentNoteSection(sec.title)) {
        parentSec = sec;
      } else if (!foundMain) {
        before.push(sec);
      } else if (isExtraDisclosure(sec.title)) {
        extra.push(sec);
      } else {
        after.push(sec);
      }
    }

    // 如果母公司节点未在根级找到，检查 mainSec 的子节点中是否有母公司容器
    if (mainSec && !parentSec) {
      const parentIdx = mainSec.children.findIndex(c => isParentNoteSection(c.title));
      if (parentIdx >= 0) {
        parentSec = mainSec.children[parentIdx];
        // 从 mainSec.children 中移除母公司节点（避免重复显示）
        mainSec = {
          ...mainSec,
          children: mainSec.children.filter((_, i) => i !== parentIdx),
        } as NoteSection;
      }
    }

    return { before, mainSec, parentSec, extra, after };
  }, [sections]);

  // 附注页签列表
  const noteTabs = useMemo(() => {
    const tabs: { key: string; label: string }[] = [];
    if (noteGroups.before.length > 0) tabs.push({ key: 'before', label: '会计政策及其他' });
    if (noteGroups.mainSec) tabs.push({ key: 'main', label: '财务报表主要项目注释' });
    if (noteGroups.parentSec) tabs.push({ key: 'parent', label: '母公司报表主要项目附注' });
    if (noteGroups.extra.length > 0) tabs.push({ key: 'extra', label: '其他专项披露' });
    if (noteGroups.after.length > 0) tabs.push({ key: 'after', label: '其他事项' });
    return tabs;
  }, [noteGroups]);

  // 所有 sheets 扁平化（过滤掉辅助性 sheet）
  const SKIP_SHEET_KW = ['校验', 'custom', '辅助', '参数', '配置', 'config', 'setting', 'template'];
  const allSheets = useMemo(() => {
    const result: { fileId: string; sheet: any }[] = [];
    for (const [fileId, sheets] of Object.entries(sheetData)) {
      for (const sheet of sheets) {
        const name = (sheet.sheet_name || '').toLowerCase();
        if (SKIP_SHEET_KW.some(kw => name.includes(kw))) continue;
        result.push({ fileId, sheet });
      }
    }
    return result;
  }, [sheetData]);

  // 确认匹配
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

  // ═══════════════════════════════════════════════════
  // 渲染工具函数
  // ═══════════════════════════════════════════════════

  // ─── 全部展开/折叠按钮 ───
  const renderExpandCollapseBar = (targetSections: NoteSection[]) => (
    <div style={{ display: 'flex', gap: 8, marginBottom: 12, justifyContent: 'flex-end' }}>
      <button onClick={expandAll} style={btnStyle}>全部展开</button>
      <button onClick={() => collapseAll(targetSections)} style={btnStyle}>全部折叠</button>
    </div>
  );

  // ─── 折叠标题行 ───
  const renderCollapseHeader = (
    id: string, title: string, level: number, hasContent: boolean, seqNo?: string,
  ) => {
    const isCollapsed = collapsedIds.has(id);
    const tc = lvlColor(level);
    const bg = lvlTitleBg(level);
    const bc = lvlBorder(level);
    return (
      <div
        onClick={() => hasContent && toggleCollapse(id)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 14px', background: bg,
          borderRadius: GT.radiusSm,
          cursor: hasContent ? 'pointer' : 'default', userSelect: 'none',
          marginBottom: isCollapsed ? 8 : 0,
        }}>
        <span style={{ fontSize: level <= 2 ? 14 : 13, fontWeight: 600, color: tc }}>
          {seqNo && !(/^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽⑾⑿⒀⒁⒂⒃⒄⒅⒆⒇㈠㈡㈢㈣㈤㈥㈦㈧㈨㈩]/.test(title.trim()) || /^\d+[.、)）\s]/.test(title.trim()) || /^[\(（]\d+[\)）]/.test(title.trim())) && <span style={{ marginRight: 8, opacity: 0.7, fontVariantNumeric: 'tabular-nums' }}>{seqNo}</span>}
          {title}
        </span>
        {hasContent && (
          <span style={{
            fontSize: 16, fontWeight: 700, color: tc, width: 22, height: 22,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            borderRadius: 4, background: `${tc}15`, flexShrink: 0,
          }}>{isCollapsed ? '+' : '−'}</span>
        )}
      </div>
    );
  };

  // ─── 附注表格渲染 ───
  const renderNoteTable = (nt: NoteTable, label?: string, level?: number) => {
    const tc = level ? lvlColor(level) : GT.primary;
    const hBg = level ? lvlTitleBg(level) : GT.primaryBgDeep;
    const sBg = level ? lvlBodyBg(level) : GT.bgPage;
    const rawHeaders: string[][] = nt.header_rows && nt.header_rows.length > 1 ? nt.header_rows : [];

    // 数据行的最大列数（用于确定表格总列数）
    const dataCols = nt.rows.length > 0 ? Math.max(...nt.rows.map(r => r.length)) : 0;
    const headerCols = rawHeaders.length > 0 ? Math.max(...rawHeaders.map(r => r.length)) : nt.headers.length;
    const totalCols = Math.max(dataCols, headerCols);

    /**
     * 构建多行表头的合并单元格矩阵。
     * 策略：先将所有 header_rows 填充到 totalCols 列的网格中，
     * 然后通过"相同值合并"检测 colSpan 和 rowSpan。
     */
    const buildHeaderGrid = () => {
      if (rawHeaders.length < 2) return null;
      const tR = rawHeaders.length;
      const tC = totalCols;

      // 1. 构建网格，短行补空
      const grid: string[][] = rawHeaders.map(row => {
        const padded = [...row];
        while (padded.length < tC) padded.push('');
        return padded.slice(0, tC).map(v => (v || '').trim());
      });

      // 2. 占位矩阵
      const occ: boolean[][] = Array.from({ length: tR }, () => Array(tC).fill(false));
      type CellInfo = { text: string; cs: number; rs: number; col: number };
      const cells: CellInfo[][] = Array.from({ length: tR }, () => []);

      for (let ri = 0; ri < tR; ri++) {
        for (let ci = 0; ci < tC; ci++) {
          if (occ[ri][ci]) continue;
          const t = grid[ri][ci];

          if (!t) {
            // 空单元格 — 跳过（会被其他单元格的 colSpan/rowSpan 覆盖）
            continue;
          }

          // 计算 colSpan：向右扫描相同值或空值
          let cs = 1;
          while (ci + cs < tC) {
            const nextVal = grid[ri][ci + cs];
            if (occ[ri][ci + cs]) break;
            // 相同值 → 水平合并
            if (nextVal === t) { cs++; continue; }
            // 空值 → 检查下面是否有子列值
            if (!nextVal) {
              let hasBelow = false;
              for (let b = ri + 1; b < tR; b++) {
                if (grid[b][ci + cs]) { hasBelow = true; break; }
              }
              if (hasBelow) { cs++; continue; }
            }
            break;
          }

          // 计算 rowSpan：向下扫描相同值或空值
          let rs = 1;
          while (ri + rs < tR) {
            const belowVal = grid[ri + rs][ci];
            if (occ[ri + rs][ci]) break;
            // 相同值 → 纵向合并
            if (belowVal === t) { rs++; continue; }
            // 空值且整个 colSpan 范围都为空 → 纵向合并
            if (!belowVal) {
              let allEmpty = true;
              for (let c = ci; c < ci + cs; c++) {
                if (grid[ri + rs][c]) { allEmpty = false; break; }
              }
              if (allEmpty) { rs++; continue; }
            }
            break;
          }

          // 标记占位
          for (let dr = 0; dr < rs; dr++)
            for (let dc = 0; dc < cs; dc++)
              occ[ri + dr][ci + dc] = true;

          cells[ri].push({ text: t, cs, rs, col: ci });
        }
      }
      return { cells, tR };
    };

    const headerGrid = buildHeaderGrid();

    return (
      <div key={nt.id} style={{ marginBottom: 14 }}>
        {label && (
          <div style={{
            fontSize: 13, fontWeight: 600, color: tc, background: hBg,
            padding: '6px 12px',
            borderRadius: GT.radiusSm, marginBottom: 4,
          }}>{label}</div>
        )}
        <div style={{
          overflowX: 'auto', borderRadius: GT.radius,
          border: `1px solid ${tc}30`, boxShadow: GT.shadow,
        }}>
          <table className="amt-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <caption className="sr-only">{nt.account_name}</caption>
            {(nt.headers.length > 0 || headerGrid) && (
              <thead>
                {headerGrid ? (
                  <>{headerGrid.cells.map((rowCells, ri) => (
                    <tr key={ri} style={{ background: hBg }}>
                      {rowCells.map((c, idx) => (
                        <th key={idx}
                          colSpan={c.cs > 1 ? c.cs : undefined}
                          rowSpan={c.rs > 1 ? c.rs : undefined}
                          style={{
                            padding: '8px 12px', fontWeight: 600, color: tc,
                            borderBottom: ri < headerGrid.tR - 1 ? `1px solid #e8e4f0` : `2px solid ${tc}50`,
                            borderRight: `1px solid #e8e4f0`,
                            textAlign: c.col === 0 ? 'left' : 'center',
                            whiteSpace: 'nowrap',
                          }}>{c.text}</th>
                      ))}
                    </tr>
                  ))}</>
                ) : (
                  <tr style={{ background: hBg }}>
                    {nt.headers.map((h, i) => (
                      <th key={i} style={{
                        padding: '8px 12px', fontWeight: 600,
                        borderBottom: `2px solid ${tc}50`, color: tc,
                        textAlign: i === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                      }}>{h}</th>
                    ))}
                  </tr>
                )}
              </thead>
            )}
            <tbody>
              {nt.rows.slice(0, 30).map((row, ri) => (
                <tr key={ri} style={{ background: ri % 2 === 0 ? GT.bgWhite : sBg }}>
                  {row.map((c: any, ci: number) => (
                    <td key={ci} style={{
                      padding: '6px 12px', borderBottom: `1px solid ${GT.borderLight}`,
                      textAlign: ci === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                      fontVariantNumeric: ci > 0 ? 'tabular-nums' : 'normal',
                      color: GT.text, fontSize: 13,
                    }}>{ci > 0 ? fmtNum(c) : (c != null ? String(c) : '')}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };


  // ─── 从附注表格中提取合计行金额 ───
  const extractNoteTotals = useCallback((sec: NoteSection): { closing?: number; opening?: number } => {
    // 取第一个表格的合计行
    if (sec.note_table_ids.length === 0) return {};
    const nt = noteMap.get(sec.note_table_ids[0]);
    if (!nt || nt.rows.length === 0) return {};

    const parse = (v: any): number | undefined => {
      if (v == null) return undefined;
      const s = String(v).replace(/,/g, '').trim();
      if (!s || s === '—' || s === '-' || s === '——') return undefined;
      const n = Number(s);
      return isNaN(n) ? undefined : n;
    };

    // 找合计行（从后往前找）
    let totalRow: any[] | null = null;
    for (let ri = nt.rows.length - 1; ri >= 0; ri--) {
      const first = (String(nt.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
      if (first === '合计') { totalRow = nt.rows[ri]; break; }
    }
    if (!totalRow) return {};

    // 提取合计行中所有数值及其列索引
    const nums: { idx: number; val: number }[] = [];
    for (let ci = 1; ci < totalRow.length; ci++) {
      const v = parse(totalRow[ci]);
      if (v != null) nums.push({ idx: ci, val: v });
    }
    if (nums.length === 0) return {};

    // ── 简单表格（≤2个数值列）：第一个=期末，第二个=期初 ──
    if (nums.length <= 2) {
      return { closing: nums[0]?.val, opening: nums[1]?.val };
    }

    // ── 多列表格：通过 header_rows 分析语义列 ──
    const hRows = nt.header_rows && nt.header_rows.length > 0 ? nt.header_rows : [];
    const totalCols = totalRow.length;

    // 辅助：在 header_rows 中查找某个关键词出现的列索引
    const findColsByKeyword = (kw: string, rowIdx?: number): number[] => {
      const result: number[] = [];
      const rows = rowIdx != null ? [hRows[rowIdx]] : hRows;
      for (const row of rows) {
        for (let ci = 0; ci < row.length; ci++) {
          const h = (row[ci] || '').replace(/\s/g, '');
          if (h.includes(kw)) result.push(ci);
        }
      }
      return result;
    };

    // 辅助：找到某个父列在子行中覆盖的列范围
    // 智能展开后，父行中相同值的连续列表示 colSpan，需要跳过
    const findChildRange = (parentRow: string[], parentCol: number, childRow: string[]): [number, number] => {
      const parentVal = (parentRow[parentCol] || '').trim();
      // 找到父行中下一个不同值的非空列
      let nextParentCol = totalCols;
      for (let ci = parentCol + 1; ci < parentRow.length; ci++) {
        const v = (parentRow[ci] || '').trim();
        if (v && v !== parentVal) { nextParentCol = ci; break; }
      }
      const endCol = Math.min(nextParentCol, childRow.length);
      return [parentCol, endCol];
    };

    if (hRows.length >= 2) {
      // ── 多行表头策略 ──
      const firstRow = hRows[0];
      const lastRow = hRows[hRows.length - 1];

      // 策略A：在最后一行表头中找"账面价值"列
      const valueColsInLast: number[] = [];
      for (let ci = 0; ci < lastRow.length; ci++) {
        const h = (lastRow[ci] || '').replace(/\s/g, '');
        if (h.includes('账面价值')) valueColsInLast.push(ci);
      }
      if (valueColsInLast.length >= 2) {
        // 第一个"账面价值"=期末，第二个=期初
        return {
          closing: parse(totalRow[valueColsInLast[0]]),
          opening: parse(totalRow[valueColsInLast[1]]),
        };
      }
      if (valueColsInLast.length === 1) {
        // 只有一个"账面价值"列，判断它属于期末还是期初
        const vci = valueColsInLast[0];
        // 看第一行中哪个父列覆盖了这个位置
        let parentLabel = '';
        for (let ci = vci; ci >= 0; ci--) {
          const h = (firstRow[ci] || '').replace(/\s/g, '');
          if (h) { parentLabel = h; break; }
        }
        if (parentLabel.includes('期末') || parentLabel.includes('本期')) {
          return { closing: parse(totalRow[vci]) };
        }
        if (parentLabel.includes('期初') || parentLabel.includes('上期') || parentLabel.includes('上年')) {
          return { opening: parse(totalRow[vci]) };
        }
        return { closing: parse(totalRow[vci]) };
      }

      // 策略A2：没有"账面价值"列，但有"账面余额/原值"和"减值准备"列时，用 原值-准备 计算
      if (valueColsInLast.length === 0) {
        const balanceCols: number[] = [];  // 账面余额/原值列
        const provisionCols: number[] = []; // 减值准备/坏账准备列
        for (let ci = 0; ci < lastRow.length; ci++) {
          const h = (lastRow[ci] || '').replace(/\s/g, '');
          if (h.includes('账面余额') || h.includes('原值')) balanceCols.push(ci);
          if (h.includes('减值准备') || h.includes('坏账准备')) provisionCols.push(ci);
        }
        // 需要成对出现：每组一个余额+一个准备
        if (balanceCols.length >= 2 && provisionCols.length >= 2) {
          const closingBal = parse(totalRow[balanceCols[0]]);
          const closingProv = parse(totalRow[provisionCols[0]]) ?? 0;
          const openingBal = parse(totalRow[balanceCols[1]]);
          const openingProv = parse(totalRow[provisionCols[1]]) ?? 0;
          return {
            closing: closingBal != null ? closingBal - closingProv : undefined,
            opening: openingBal != null ? openingBal - openingProv : undefined,
          };
        }
        if (balanceCols.length >= 1 && provisionCols.length >= 1) {
          // 只有一组，判断期末/期初
          const bal = parse(totalRow[balanceCols[0]]);
          const prov = parse(totalRow[provisionCols[0]]) ?? 0;
          const vci = balanceCols[0];
          let parentLabel = '';
          for (let ci = vci; ci >= 0; ci--) {
            const h = (firstRow[ci] || '').replace(/\s/g, '');
            if (h) { parentLabel = h; break; }
          }
          const val = bal != null ? bal - prov : undefined;
          if (parentLabel.includes('期初') || parentLabel.includes('上期') || parentLabel.includes('上年')) {
            return { opening: val };
          }
          return { closing: val };
        }
      }

      // 策略B：在最后一行表头中找"期末余额"/"期初余额"或"期末数"/"期初数"
      const closingColsLast = findColsByKeyword('期末', hRows.length - 1)
        .concat(findColsByKeyword('本期', hRows.length - 1));
      const openingColsLast = findColsByKeyword('期初', hRows.length - 1)
        .concat(findColsByKeyword('上期', hRows.length - 1))
        .concat(findColsByKeyword('上年', hRows.length - 1));
      if (closingColsLast.length > 0 || openingColsLast.length > 0) {
        return {
          closing: closingColsLast.length > 0 ? parse(totalRow[closingColsLast[0]]) : undefined,
          opening: openingColsLast.length > 0 ? parse(totalRow[openingColsLast[0]]) : undefined,
        };
      }

      // 策略C：在第一行表头中找"期末"/"期初"父列，然后在子行中定位金额列
      let closingParentCol = -1, openingParentCol = -1;
      for (let ci = 0; ci < firstRow.length; ci++) {
        const h = (firstRow[ci] || '').replace(/\s/g, '');
        if (!h) continue;
        if (closingParentCol < 0 && (h.includes('期末') || h.includes('本期'))) closingParentCol = ci;
        if (openingParentCol < 0 && (h.includes('期初') || h.includes('上期') || h.includes('上年'))) openingParentCol = ci;
      }

      // 在子列范围内找最佳金额值：
      // 1. 优先找"账面价值"列直接取值
      // 2. 如果有"账面余额/原值"和"减值准备"列，计算 原值-准备
      // 3. 其次找"金额"/"余额"列（排除"比例"/%列）
      // 4. 最后取范围内第一个有数值的非比例列
      const pickAmountValue = (start: number, end: number): number | undefined => {
        const tr = totalRow!;
        // 优先：账面价值
        for (let ci = start; ci < end; ci++) {
          const h = (lastRow[ci] || '').replace(/\s/g, '');
          if (h.includes('账面价值')) return parse(tr[ci]);
        }
        // 其次：原值/账面余额 - 减值准备
        let balCol = -1, provCol = -1;
        for (let ci = start; ci < end; ci++) {
          const h = (lastRow[ci] || '').replace(/\s/g, '');
          if (balCol < 0 && (h.includes('账面余额') || h.includes('原值'))) balCol = ci;
          if (provCol < 0 && (h.includes('减值准备') || h.includes('坏账准备'))) provCol = ci;
        }
        if (balCol >= 0 && provCol >= 0) {
          const bal = parse(tr[balCol]);
          const prov = parse(tr[provCol]) ?? 0;
          if (bal != null) return bal - prov;
        }
        // 其次：金额/余额（排除比例/%）
        for (let ci = start; ci < end; ci++) {
          const h = (lastRow[ci] || '').replace(/\s/g, '');
          if (h && (h.includes('金额') || h.includes('余额') || h.includes('价值'))
            && !h.includes('比例') && !h.includes('比率') && !h.includes('%')) return parse(tr[ci]);
        }
        // fallback：第一个有数值且子表头不含"比例"/%的列
        for (let ci = start; ci < end; ci++) {
          const h = (lastRow[ci] || '').replace(/\s/g, '');
          if (h.includes('比例') || h.includes('比率') || h.includes('%')) continue;
          if (parse(tr[ci]) != null) return parse(tr[ci]);
        }
        // 最终：第一个有数值的列
        for (let ci = start; ci < end; ci++) {
          if (parse(tr[ci]) != null) return parse(tr[ci]);
        }
        return undefined;
      };

      if (closingParentCol >= 0 || openingParentCol >= 0) {
        let closingVal: number | undefined;
        let openingVal: number | undefined;

        if (closingParentCol >= 0) {
          const [start, end] = findChildRange(firstRow, closingParentCol, lastRow);
          closingVal = pickAmountValue(start, end);
        }

        if (openingParentCol >= 0) {
          const [start, end] = findChildRange(firstRow, openingParentCol, lastRow);
          openingVal = pickAmountValue(start, end);
        }

        if (closingVal != null || openingVal != null) {
          return { closing: closingVal, opening: openingVal };
        }
      }
    }

    // ── 单行表头策略 ──
    const headers = (hRows.length === 1 ? hRows[0] : nt.headers).map(h => (h || '').replace(/[\s-]/g, ''));

    // 找"账面价值"列
    const valueColIndices = headers
      .map((h, i) => ({ h, i }))
      .filter(x => x.h.includes('账面价值'));
    if (valueColIndices.length >= 2) {
      return {
        closing: parse(totalRow[valueColIndices[0].i]),
        opening: parse(totalRow[valueColIndices[1].i]),
      };
    }

    // 找"期末"/"期初"关键词
    let closingIdx = -1, openingIdx = -1;
    for (let ci = 0; ci < headers.length; ci++) {
      const h = headers[ci];
      if (closingIdx < 0 && (h.includes('期末') || h.includes('本期') || h.includes('本年'))) closingIdx = ci;
      if (openingIdx < 0 && (h.includes('期初') || h.includes('上期') || h.includes('上年'))) openingIdx = ci;
    }
    if (closingIdx >= 0 || openingIdx >= 0) {
      return {
        closing: closingIdx >= 0 ? parse(totalRow[closingIdx]) : undefined,
        opening: openingIdx >= 0 ? parse(totalRow[openingIdx]) : undefined,
      };
    }

    // 最终 fallback：取第一个和最后一个数值
    return { closing: nums[0]?.val, opening: nums[nums.length - 1]?.val };
  }, [noteMap]);

  // ─── 渲染报表金额提示条 ───
  const renderStmtAmountBar = (item: StatementItem, mode: 'consolidated' | 'parent', sec: NoteSection) => {
    const fmt = (v?: number) => v != null ? v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
    // 根据模式选择金额
    const stmtClosing = mode === 'parent' ? (item.company_closing_balance ?? item.closing_balance) : item.closing_balance;
    const stmtOpening = mode === 'parent' ? (item.company_opening_balance ?? item.opening_balance) : item.opening_balance;
    const label = mode === 'parent' ? '母公司报表' : item.sheet_name;

    // 提取附注合计行金额进行比对
    const noteTotals = extractNoteTotals(sec);
    const TOL = 0.5;
    // closingMatch / openingMatch: true=一致, false=不一致, null=无法比对
    const closingMatch = (stmtClosing != null && noteTotals.closing != null)
      ? Math.abs(stmtClosing - noteTotals.closing) <= TOL : null;
    const openingMatch = (stmtOpening != null && noteTotals.opening != null)
      ? Math.abs(stmtOpening - noteTotals.opening) <= TOL : null;

    return (
      <div style={{
        margin: '4px 0 8px 0', borderRadius: GT.radiusSm,
        border: `1px solid ${GT.primary}40`, overflow: 'hidden',
      }}>
        {/* 报表金额行 */}
        <div style={{
          padding: '7px 14px',
          background: `linear-gradient(135deg, ${GT.primaryBg} 0%, ${GT.primaryBgDeep} 100%)`,
          fontSize: 12, display: 'flex', flexWrap: 'wrap', gap: '4px 20px',
          alignItems: 'center',
        }}>
          <span style={{ fontWeight: 700, color: GT.primary, fontSize: 12 }}>📊 {label}</span>
          <span style={{ color: GT.primary, fontWeight: 600 }}>
            期末/本期：<span style={{ fontVariantNumeric: 'tabular-nums' }}>{fmt(stmtClosing)}</span>
          </span>
          <span style={{ color: GT.primary, fontWeight: 600 }}>
            期初/上期：<span style={{ fontVariantNumeric: 'tabular-nums' }}>{fmt(stmtOpening)}</span>
          </span>
        </div>
        {/* 勾稽校验行 */}
        {(closingMatch !== null || openingMatch !== null) && (
          <div style={{
            padding: '5px 14px',
            background: (closingMatch === false || openingMatch === false) ? '#fdf0ef' : '#eafaf1',
            borderTop: `1px solid ${GT.primary}20`,
            fontSize: 12, display: 'flex', flexWrap: 'wrap', gap: '4px 20px',
            alignItems: 'center',
          }}>
            <span style={{ fontWeight: 600, color: GT.textSecondary, fontSize: 11 }}>勾稽校验</span>
            {closingMatch !== null && (
              <span style={{
                color: closingMatch ? GT.success : GT.danger,
                fontWeight: closingMatch ? 400 : 700,
              }}>
                {closingMatch ? '✓' : '✗'} 期末
                {!closingMatch && noteTotals.closing != null && (
                  <span style={{ fontSize: 11, marginLeft: 4 }}>
                    （附注：{fmt(noteTotals.closing)}）
                  </span>
                )}
              </span>
            )}
            {openingMatch !== null && (
              <span style={{
                color: openingMatch ? GT.success : GT.danger,
                fontWeight: openingMatch ? 400 : 700,
              }}>
                {openingMatch ? '✓' : '✗'} 期初
                {!openingMatch && noteTotals.opening != null && (
                  <span style={{ fontSize: 11, marginLeft: 4 }}>
                    （附注：{fmt(noteTotals.opening)}）
                  </span>
                )}
              </span>
            )}
          </div>
        )}
      </div>
    );
  };

  // ─── 渲染 section 内容（正文段落 + 表格） ───
  const renderSectionContent = (sec: NoteSection, mode: 'consolidated' | 'parent' = 'consolidated', showAmountBar = false, stmtItemOverride?: StatementItem | null) => {
    const tableTitles = new Set(
      sec.note_table_ids.map(id => noteMap.get(id)?.section_title?.trim()).filter(Boolean) as string[]
    );
    tableTitles.add(sec.title.trim());
    const filteredParas = sec.content_paragraphs.filter(p => !tableTitles.has(p.trim()));
    const shownLabels = new Set<string>();

    // 只在 showAmountBar=true 时查找报表科目
    const stmtItem = showAmountBar
      ? (stmtItemOverride !== undefined ? stmtItemOverride : findStmtForSection(sec))
      : null;
    let amountBarInserted = false;

    return (
      <div style={{ padding: '2px 0' }}>
        {filteredParas.length > 0 && (
          <div style={{ marginBottom: 6, lineHeight: 1.8, fontSize: 14, color: GT.text }}>
            {filteredParas.map((p, i) => <p key={i} style={{ margin: '2px 0' }}>{p}</p>)}
          </div>
        )}
        {sec.note_table_ids.map((id, idx) => {
          const nt = noteMap.get(id);
          if (!nt) return null;
          const rawLabel = nt.section_title?.trim() || '';
          let label: string | undefined;
          if (rawLabel && rawLabel !== sec.title.trim() && !shownLabels.has(rawLabel)) {
            label = nt.section_title;
            shownLabels.add(rawLabel);
          }
          const tableEl = renderNoteTable(nt, label, sec.level);
          // 只在顶层科目节点的第一个表格之后插入报表金额条
          if (stmtItem && !amountBarInserted && idx === 0) {
            amountBarInserted = true;
            return <React.Fragment key={id}>{tableEl}{renderStmtAmountBar(stmtItem, mode, sec)}</React.Fragment>;
          }
          return tableEl;
        })}
      </div>
    );
  };

  // ─── 递归渲染 section（可折叠） ───
  const renderSectionTree = (sec: NoteSection, seqNo?: string, mode: 'consolidated' | 'parent' = 'consolidated', isTopLevel = false): React.ReactNode => {
    const isCollapsed = collapsedIds.has(sec.id);
    const hasContent = sec.content_paragraphs.length > 0 || sec.note_table_ids.length > 0 || sec.children.length > 0;
    const cBg = lvlBodyBg(sec.level);

    // 如果是顶层科目节点但自身没有表格，把金额条下传给第一个有表格的子节点
    const selfHasTables = sec.note_table_ids.length > 0;
    const needPassDown = isTopLevel && !selfHasTables;

    // 提前找好报表科目（在父级层面找，避免子节点标题不匹配）
    const parentStmtItem = needPassDown ? findStmtForSection(sec) : null;
    const firstChildWithTable = needPassDown
      ? sec.children.findIndex(c => c.note_table_ids.length > 0)
      : -1;

    return (
      <div key={sec.id} style={{ marginBottom: 8 }}>
        {renderCollapseHeader(sec.id, sec.title, sec.level, hasContent, seqNo)}
        {!isCollapsed && hasContent && (
          <div style={{
            background: cBg, padding: '4px 14px',
            borderRadius: `0 0 ${GT.radiusSm}px ${GT.radiusSm}px`,
          }}>
            {renderSectionContent(sec, mode, isTopLevel && selfHasTables)}
            {sec.children.map((child, ci) => {
              if (needPassDown && ci === firstChildWithTable && parentStmtItem) {
                // 子节点需要显示金额条，传入父级找到的报表科目
                return renderSectionTreeWithStmt(child, seqNo ? `${seqNo}.${ci + 1}` : `${ci + 1}`, mode, parentStmtItem);
              }
              return renderSectionTree(child, seqNo ? `${seqNo}.${ci + 1}` : `${ci + 1}`, mode, false);
            })}
          </div>
        )}
      </div>
    );
  };

  // ─── 渲染子节点（带指定的报表科目，用于父级无表格时下传金额条） ───
  const renderSectionTreeWithStmt = (sec: NoteSection, seqNo: string, mode: 'consolidated' | 'parent', stmtItem: StatementItem): React.ReactNode => {
    const isCollapsed = collapsedIds.has(sec.id);
    const hasContent = sec.content_paragraphs.length > 0 || sec.note_table_ids.length > 0 || sec.children.length > 0;
    const cBg = lvlBodyBg(sec.level);

    return (
      <div key={sec.id} style={{ marginBottom: 8 }}>
        {renderCollapseHeader(sec.id, sec.title, sec.level, hasContent, seqNo)}
        {!isCollapsed && hasContent && (
          <div style={{
            background: cBg, padding: '4px 14px',
            borderRadius: `0 0 ${GT.radiusSm}px ${GT.radiusSm}px`,
          }}>
            {renderSectionContent(sec, mode, true, stmtItem)}
            {sec.children.map((child, ci) => renderSectionTree(child, seqNo ? `${seqNo}.${ci + 1}` : `${ci + 1}`, mode, false))}
          </div>
        )}
      </div>
    );
  };

  // ─── 渲染多个 section 合并页面（带全部展开/折叠） ───
  const renderSectionsPage = (secs: NoteSection[]) => (
    <div>
      {renderExpandCollapseBar(secs)}
      <div style={{ paddingRight: 4 }}>
        {secs.map((sec, i) => renderSectionTree(sec, `${i + 1}`))}
      </div>
    </div>
  );

  // ─── 母公司附注预设科目覆盖率面板 ───
  const renderParentCoveragePanel = (sec: NoteSection) => {
    if (parentPresetAccounts.length === 0) return null;

    // 收集所有子节点标题（递归）
    const allTitles: string[] = [];
    const walk = (s: NoteSection) => {
      allTitles.push(s.title);
      s.children.forEach(walk);
    };
    sec.children.forEach(walk);
    // 也检查 sec 自身
    allTitles.push(sec.title);

    const normalize = (s: string) => s.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');

    const coverage = parentPresetAccounts.map(acct => {
      const found = allTitles.some(t => {
        const nt = normalize(t);
        return (acct.keywords as string[]).some(kw => nt.includes(kw));
      });
      return { ...acct, found };
    });

    const foundCount = coverage.filter(c => c.found).length;
    const total = coverage.length;
    const allFound = foundCount === total;

    return (
      <div style={{
        margin: '0 0 12px 0', padding: '10px 14px',
        background: allFound ? GT.successBg : GT.warningBg,
        borderRadius: GT.radiusSm,
        border: `1px solid ${allFound ? GT.success : GT.warning}`,
        fontSize: 13,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 6, color: allFound ? GT.success : GT.warning }}>
          模板预设科目覆盖：{foundCount}/{total}
          {allFound ? ' ✓ 全部覆盖' : ' — 部分科目缺失'}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 10px' }}>
          {coverage.map((c, i) => (
            <span key={i} style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              color: c.found ? GT.success : GT.danger,
              fontWeight: c.found ? 400 : 600,
            }}>
              <span style={{ fontSize: 11 }}>{c.found ? '✓' : '✗'}</span>
              {c.name}
            </span>
          ))}
        </div>
      </div>
    );
  };

  // ─── 渲染报表科目注释（财务报表主要项目注释 / 母公司） ───
  const renderStatementNotes = (sec: NoteSection, mode: 'consolidated' | 'parent' = 'consolidated') => {
    // 如果 mainSec 的直接子节点是容器（如"(一) 合并财务报表项目注释"），
    // 且该容器自身没有表格、无实质正文、只有子节点，则展开一层直接显示科目列表，
    // 避免货币资金等被嵌套在折叠面板深处
    let displayChildren = sec.children;
    const containerPreambles: NoteSection[] = [];

    // 判断一个节点是否为纯容器（有子节点、自身无表格、自身无实质正文）
    const isContainer = (c: NoteSection) =>
      c.children.length > 0 && c.note_table_ids.length === 0 &&
      c.content_paragraphs.filter(p => p.trim()).length === 0;

    if (sec.children.length >= 1 && sec.children.every(isContainer)) {
      // 所有直接子节点都是纯容器，展开它们的子节点
      displayChildren = [];
      for (const container of sec.children) {
        containerPreambles.push(container);
        displayChildren.push(...container.children);
      }
    }

    const allSecs = displayChildren.length > 0 ? displayChildren : [sec];
    return (
      <div>
        {renderExpandCollapseBar(allSecs)}
        <div style={{ paddingRight: 4 }}>
          {/* section 自身的正文 */}
          {(sec.content_paragraphs.length > 0 || sec.note_table_ids.length > 0) && (
            <div style={{ marginBottom: 12 }}>{renderSectionContent(sec, mode)}</div>
          )}
          {/* 多个容器时显示分组标题 */}
          {containerPreambles.length > 1 && containerPreambles.map((cp, i) => (
            <div key={`cp-title-${i}`} style={{
              fontSize: 13, fontWeight: 600, color: GT.primary, padding: '6px 0',
              marginTop: i > 0 ? 16 : 0, borderBottom: `1px solid ${GT.border}`,
              marginBottom: 8,
            }}>{cp.title}</div>
          ))}
          {displayChildren.map((child, ci) => renderSectionTree(child, `${ci + 1}`, mode, true))}
        </div>
      </div>
    );
  };

  // ─── 渲染财务报表 sheet ───
  // 报表终止行关键词（遇到后截断，含该行本身）
  const SHEET_END_KW = [
    '负债和所有者权益总计', '负债及所有者权益总计',
    '负债和股东权益总计', '负债及股东权益总计',
    '负债与所有者权益总计',
  ];
  // 签章行关键词（包含匹配，该行及以下全部截断）
  const SHEET_CUT_KW = ['企业负责人', '单位负责人', '法定代表人', '主管会计'];
  // 注释行关键词（直接跳过）
  const SHEET_SKIP_KW = ['注：', '注:', '注 ：', '＊', '※'];

  const renderSheetContent = (sheet: any) => {
    const origHeaders: string[] = sheet.headers || [];
    const origData: any[][] = sheet.raw_data || [];
    const headerRowsFromBackend: string[][] = sheet.header_rows || [];
    const isConsolidated: boolean = sheet.is_consolidated || false;

    if (origHeaders.length === 0 && origData.length === 0) {
      return <div style={{ padding: 30, textAlign: 'center', color: GT.textMuted }}>该 Sheet 无数据</div>;
    }

    let headers: string[];
    let displayData: any[][];
    let multiRowHeaders: string[][] = [];

    if (headerRowsFromBackend.length > 0) {
      headers = origHeaders;
      displayData = origData;
      multiRowHeaders = headerRowsFromBackend;
    } else {
      const allRows: any[][] = [origHeaders.map(h => h), ...origData];
      const HEADER_KW = ['项目', '项 目'];
      let headerIdx = -1;
      for (let ri = 0; ri < Math.min(allRows.length, 10); ri++) {
        const firstCell = String(allRows[ri]?.[0] ?? '').replace(/\s+/g, '');
        if (HEADER_KW.some(kw => firstCell === kw.replace(/\s+/g, ''))) { headerIdx = ri; break; }
      }
      if (headerIdx >= 0) {
        headers = allRows[headerIdx].map((v: any) => v != null ? String(v) : '');
        displayData = allRows.slice(headerIdx + 1);
      } else {
        headers = origHeaders;
        displayData = origData;
      }
    }

    // 截断 / 过滤
    for (let ri = 0; ri < displayData.length; ri++) {
      const firstCell = String(displayData[ri]?.[0] ?? '').replace(/\s+/g, '');
      if (SHEET_END_KW.some(kw => firstCell === kw.replace(/\s+/g, ''))) { displayData = displayData.slice(0, ri + 1); break; }
      const rowText = displayData[ri].map((c: any) => String(c ?? '')).join('');
      if (SHEET_CUT_KW.some(kw => rowText.includes(kw))) { displayData = displayData.slice(0, ri); break; }
    }
    displayData = displayData.filter(row => String(row?.[0] ?? '').trim().length > 0);
    let endIdx = displayData.length;
    while (endIdx > 0) {
      const row = displayData[endIdx - 1];
      const fc = String(row?.[0] ?? '').trim();
      if (row.every((c: any) => c == null || String(c).trim() === '') || SHEET_SKIP_KW.some(kw => fc.startsWith(kw))) { endIdx--; } else { break; }
    }
    displayData = displayData.slice(0, endIdx);

    // ── 行类型 ──
    const TOTAL_KW = ['合计', '总计', '资产总计', '负债合计', '所有者权益合计',
      '非流动资产合计', '流动资产合计', '流动负债合计', '非流动负债合计',
      '负债和所有者权益总计', '负债及所有者权益总计', '负债和股东权益总计'];
    const SUBTOTAL_KW = ['小计'];
    const SUB_ITEM_PREFIX = ['其中：', '其中:', '其中'];
    const CATEGORY_KW = ['流动资产：', '流动资产:', '非流动资产：', '非流动资产:',
      '流动负债：', '流动负债:', '非流动负债：', '非流动负债:',
      '所有者权益：', '所有者权益:', '所有者权益（或股东权益）：'];
    const EQUITY_SEC_PREFIX = ['一、', '二、', '三、', '四、', '五、', '六、',
      '加：', '加:', '减：', '减:'];

    type RowType = 'total' | 'subtotal' | 'sub_item' | 'category' | 'section' | 'normal';
    const getRowType = (row: any[]): RowType => {
      const name = String(row?.[0] ?? '').replace(/\s+/g, '');
      const raw = String(row?.[0] ?? '').trim();
      if (TOTAL_KW.some(kw => name === kw.replace(/\s+/g, ''))) return 'total';
      if (SUBTOTAL_KW.some(kw => name.includes(kw))) return 'subtotal';
      if (SUB_ITEM_PREFIX.some(kw => raw.startsWith(kw))) return 'sub_item';
      if (CATEGORY_KW.some(kw => name === kw.replace(/\s+/g, ''))) return 'category';
      if (EQUITY_SEC_PREFIX.some(kw => raw.startsWith(kw))) return 'section';
      return 'normal';
    };

    const colCount = headers.length || (displayData[0]?.length ?? 0);
    const isWide = colCount > 5;

    // 检测"附注"列索引，用于居中对齐
    const noteColSet = new Set<number>();
    headers.forEach((h, i) => { if (h.includes('附注')) noteColSet.add(i); });

    return (
      <div style={{
        overflowX: 'auto',
        overflowY: 'auto',
        maxHeight: 'calc(100vh - 280px)',
        borderRadius: 10,
        border: `1px solid ${GT.border}`,
        boxShadow: '0 4px 24px rgba(75,45,119,0.06)',
        background: GT.bgWhite,
      }}>
        <style>{`
          @keyframes stmtFadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to   { opacity: 1; transform: translateY(0); }
          }
          @keyframes stmtRowIn {
            from { opacity: 0; }
            to   { opacity: 1; }
          }
          .stmt-tbl { animation: stmtFadeIn .32s cubic-bezier(.4,0,.2,1) both; }
          .stmt-tbl tbody tr {
            animation: stmtRowIn .28s ease both;
            transition: background .15s ease, box-shadow .15s ease;
          }
          .stmt-tbl tbody tr:hover {
            background: ${GT.primaryBg} !important;
          }
          .stmt-tbl tbody tr:hover td:first-child { color: ${GT.primary} !important; }
          .stmt-tbl thead th { user-select: none; }
        `}</style>
        <table className="stmt-tbl" style={{
          width: isWide ? undefined : '100%',
          minWidth: isWide ? Math.max(colCount * 100, 1200) : undefined,
          borderCollapse: 'separate', borderSpacing: 0,
          fontSize: 13, tableLayout: isWide ? 'auto' : 'fixed',
        }}>
          <caption className="sr-only">{sheet.sheet_name}</caption>
          {!isWide && (
          <colgroup>
            {Array.from({ length: colCount }, (_, ci) => {
              const firstPct = colCount <= 4 ? 30 : 24;
              const restPct = (100 - firstPct) / Math.max(colCount - 1, 1);
              return <col key={ci} style={{ width: ci === 0 ? `${firstPct}%` : `${restPct}%` }} />;
            })}
          </colgroup>
          )}

          {/* ── 表头 ── */}
          {headers.length > 0 && (
            <thead>
              {multiRowHeaders.length > 1 ? (() => {
                const tR = multiRowHeaders.length, tC = Math.max(...multiRowHeaders.map(r => r.length));
                const occ: boolean[][] = Array.from({ length: tR }, () => Array(tC).fill(false));
                type CI = { text: string; cs: number; rs: number; col: number };
                const rc: CI[][] = Array.from({ length: tR }, () => []);
                for (let ri = 0; ri < tR; ri++) {
                  const row = multiRowHeaders[ri];
                  for (let ci = 0; ci < tC; ci++) {
                    if (occ[ri][ci]) continue;
                    const t = (row[ci] || '').trim();
                    if (!t) continue;
                    let cs = 1;
                    while (ci + cs < tC && !(row[ci + cs] || '').trim() && !occ[ri][ci + cs]) {
                      let bv = false;
                      for (let b = ri + 1; b < tR; b++) { if ((multiRowHeaders[b][ci + cs] || '').trim()) { bv = true; break; } }
                      if (bv) cs++; else break;
                    }
                    let rs = 1;
                    while (ri + rs < tR) {
                      if ((multiRowHeaders[ri + rs][ci] || '').trim() || occ[ri + rs][ci]) break;
                      let ae = true;
                      for (let c = ci; c < ci + cs; c++) { if ((multiRowHeaders[ri + rs][c] || '').trim()) { ae = false; break; } }
                      if (!ae) break; rs++;
                    }
                    for (let dr = 0; dr < rs; dr++) for (let dc = 0; dc < cs; dc++) occ[ri + dr][ci + dc] = true;
                    rc[ri].push({ text: t, cs, rs, col: ci });
                  }
                }
                const hH = 36;
                return <>{rc.map((cells, ri) => (
                  <tr key={ri}>{cells.map((c, idx) => (
                    <th key={idx}
                      colSpan={c.cs > 1 ? c.cs : undefined}
                      rowSpan={c.rs > 1 ? c.rs : undefined}
                      style={{
                        padding: '9px 12px', fontWeight: 600,
                        color: GT.primary,
                        background: ri === 0 ? '#f7f5fb' : '#fbfafd',
                        borderBottom: ri < tR - 1
                          ? `1px solid #e8e4f0`
                          : `2px solid ${GT.primary}`,
                        borderRight: `1px solid #e8e4f0`,
                        textAlign: c.col === 0 ? 'left' : 'center',
                        whiteSpace: 'nowrap',
                        position: 'sticky', top: ri * hH, zIndex: isWide && c.col === 0 ? 12 : 10 - ri,
                        fontSize: 13, letterSpacing: .2,
                        ...(isWide && c.col === 0 ? { left: 0, minWidth: 180 } : {}),
                      }}>{c.text}</th>
                  ))}</tr>
                ))}</>;
              })() : (
                <tr>{headers.map((h, i) => (
                  <th key={i} style={{
                    padding: '10px 14px', fontWeight: 600,
                    color: GT.primary,
                    background: '#f7f5fb',
                    textAlign: i === 0 ? 'left' : noteColSet.has(i) ? 'center' : 'right', whiteSpace: 'nowrap',
                    position: 'sticky', top: 0, zIndex: isWide && i === 0 ? 12 : 10, fontSize: 13, letterSpacing: .2,
                    borderBottom: `2px solid ${GT.primary}`,
                    borderRight: i < headers.length - 1 ? `1px solid #e8e4f0` : undefined,
                    ...(isWide && i === 0 ? { left: 0, minWidth: 180 } : {}),
                  }}>{h}</th>
                ))}</tr>
              )}
            </thead>
          )}

          {/* ── 数据行 ── */}
          <tbody>
            {displayData.slice(0, 300).map((row: any[], ri: number) => {
              const rt = getRowType(row);
              const isTotal = rt === 'total';
              const isSubtotal = rt === 'subtotal';
              const isSub = rt === 'sub_item';
              const isCat = rt === 'category';
              const isSec = rt === 'section';

              const bg = isTotal ? `linear-gradient(90deg, ${GT.primaryBgDeep}, #e8dff2)`
                : isSubtotal ? '#f0edf6'
                : isCat ? '#f6f3fb'
                : isSec ? '#faf8fd'
                : ri % 2 === 0 ? GT.bgWhite : '#faf9fc';

              return (
                <tr key={ri} style={{
                  background: bg,
                  animationDelay: `${Math.min(ri * 10, 350)}ms`,
                }}>
                  {row.map((c: any, ci: number) => {
                    const isFirst = ci === 0;
                    const cellText = isFirst ? (c != null ? String(c) : '') : fmtNum(c);
                    const pl = isFirst ? (isSub ? 36 : isSec ? 12 : isCat ? 8 : 16) : 10;

                    // 负数标红
                    let numColor = GT.text;
                    if (!isFirst && c != null) {
                      const n = Number(String(c).replace(/,/g, ''));
                      if (!isNaN(n) && n < 0) numColor = GT.danger;
                    }

                    return (
                      <td key={ci} style={{
                        padding: `7px 10px 7px ${pl}px`,
                        borderBottom: isTotal ? `2px solid ${GT.primary}25` : `1px solid #e8e4f0`,
                        textAlign: isFirst ? 'left' : noteColSet.has(ci) ? 'center' : 'right',
                        whiteSpace: 'nowrap',
                        overflow: isWide ? undefined : 'hidden',
                        textOverflow: isWide ? undefined : 'ellipsis',
                        fontVariantNumeric: !isFirst ? 'tabular-nums' : 'normal',
                        fontWeight: (isTotal || isSubtotal || isCat || isSec) ? 700 : 400,
                        color: isTotal ? GT.primary : isCat ? GT.primaryLight : isSec ? GT.primary : isFirst ? GT.text : numColor,
                        fontSize: isTotal ? 13.5 : 13,
                        borderTop: isTotal ? `2px solid ${GT.primary}25` : undefined,
                        borderRight: isFirst ? `1px solid #e8e4f0` : undefined,
                        ...(isWide && isFirst ? {
                          position: 'sticky' as const, left: 0, zIndex: 1,
                          background: isTotal ? '#ece5f3' : isCat ? '#f6f3fb' : isSec ? '#faf8fd' : ri % 2 === 0 ? GT.bgWhite : '#faf9fc',
                          minWidth: 180,
                        } : {}),
                      }}>{cellText}</td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  // ─── 页签渲染 ───
  const renderTabBar = (
    tabs: { key: string | number; label: string }[],
    active: string | number,
    setActive: (v: any) => void,
    size: 'lg' | 'sm' = 'sm',
  ) => (
    <div style={{
      display: 'flex', gap: 2, flexWrap: 'wrap',
      borderBottom: `2px solid ${GT.border}`,
      marginBottom: size === 'lg' ? 18 : 14, paddingBottom: 0,
    }}>
      {tabs.map(tab => {
        const isActive = active === tab.key;
        return (
          <button key={tab.key} onClick={() => setActive(tab.key)}
            style={{
              padding: size === 'lg' ? '11px 28px' : '8px 18px',
              border: 'none',
              background: isActive ? GT.primaryBg : 'transparent',
              cursor: 'pointer',
              fontSize: size === 'lg' ? 15 : 13,
              fontWeight: isActive ? 700 : 500,
              borderRadius: '6px 6px 0 0',
              transition: 'all 0.15s',
              borderBottom: isActive
                ? `${size === 'lg' ? 3 : 2}px solid ${GT.primary}`
                : `${size === 'lg' ? 3 : 2}px solid transparent`,
              color: isActive ? GT.primary : GT.textMuted,
              marginBottom: -2,
              maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
            title={tab.label}>
            {tab.label}
          </button>
        );
      })}
    </div>
  );


  // ═══════════════════════════════════════════════════
  // 主渲染
  // ═══════════════════════════════════════════════════

  if (loading) return (
    <div style={{ textAlign: 'center', padding: 60, color: GT.textMuted }}>
      <div style={{ fontSize: 28, marginBottom: 10 }}>⏳</div>
      <div style={{ fontSize: 14 }}>加载中...</div>
    </div>
  );

  const TOP_TABS = [
    { key: 'audit_report', label: '审计报告正文' },
    { key: 'financial_statement', label: '财务报表' },
    { key: 'notes', label: '财务报表附注' },
  ];

  const renderFooter = () => (
    <div style={{ flexShrink: 0 }}>
      {error && (
        <div style={{
          color: GT.danger, padding: '10px 16px', background: '#fdf0ef',
          borderRadius: GT.radiusSm, margin: '16px 0', fontSize: 13,
          border: '1px solid #f5c6cb',
        }}>⚠ {error}</div>
      )}
      <div style={{ textAlign: 'right', marginTop: 12, paddingTop: 12, borderTop: `1px solid ${GT.border}` }}>
        <button onClick={handleConfirm} disabled={loading}
          style={{
            padding: '10px 40px', border: 'none', borderRadius: GT.radius,
            cursor: loading ? 'not-allowed' : 'pointer',
            background: loading ? '#ccc' : `linear-gradient(135deg, ${GT.primary} 0%, ${GT.primaryLight} 100%)`,
            color: '#fff', fontSize: 14, fontWeight: 600,
            boxShadow: loading ? 'none' : `0 2px 10px ${GT.primary}40`,
          }}>确认匹配</button>
      </div>
    </div>
  );

  return (
    <div style={{ fontFamily: GT.font, display: 'flex', flexDirection: 'column', height: 'calc(100vh - 180px)', overflow: 'hidden' }}>
      {/* 一级页签 */}
      {renderTabBar(TOP_TABS, activeTopTab, setActiveTopTab, 'lg')}

      {/* 单一滚动容器 */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', minHeight: 0, paddingRight: 4 }}>

      {/* ─── 审计报告正文 ─── */}
      {activeTopTab === 'audit_report' && (
        <div>
          {auditReportContent.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: GT.textMuted, fontSize: 14 }}>
              暂无审计报告正文数据，请上传审计报告文件
            </div>
          ) : (
            <div>
              <div style={{
                maxWidth: 800, margin: '0 auto', padding: '20px 32px',
                background: GT.bgWhite, borderRadius: GT.radius,
                border: `1px solid ${GT.border}`, boxShadow: GT.shadow,
              }}>
                {(() => {
                  // ── 清理特殊字符（Word 域代码、制表符等产生的方块□） ──
                  const cleanText = (t: string) =>
                    t.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')
                     .replace(/[\uf020-\uf0ff]/g, '')  // Word Symbol 字体私有区
                     .replace(/\u00a0/g, ' ')           // 不间断空格 → 普通空格
                     .replace(/□/g, '')                  // 方块字符
                     .trim();

                  // ── 预处理：分区 + 合并目录碎片 ──
                  type Segment = { type: 'header' | 'toc' | 'body'; paras: typeof auditReportContent };
                  const segments: Segment[] = [];
                  let curPhase: 'header' | 'toc' | 'body' = 'header';
                  let curParas: typeof auditReportContent = [];

                  for (const para of auditReportContent) {
                    const ct = cleanText(para.text || '');
                    const isTocTitle = /^目\s*录$/.test(ct);
                    const isBodyStart = /^[一二三四五六七八九十]+、/.test(ct);

                    if (isTocTitle && curPhase === 'header') {
                      if (curParas.length) segments.push({ type: curPhase, paras: curParas });
                      curPhase = 'toc';
                      curParas = [para]; // 目录标题本身
                    } else if (isBodyStart && curPhase !== 'body') {
                      if (curParas.length) segments.push({ type: curPhase, paras: curParas });
                      curPhase = 'body';
                      curParas = [para];
                    } else {
                      curParas.push(para);
                    }
                  }
                  if (curParas.length) segments.push({ type: curPhase, paras: curParas });

                  // ── 合并目录碎片段落为条目 ──
                  const buildTocEntries = (paras: typeof auditReportContent) => {
                    // 跳过第一个（"目录"标题），把剩余段落合并
                    const raw = paras.slice(1);
                    const entries: { title: string; page: string }[] = [];
                    let buf = '';
                    for (const p of raw) {
                      const ct = cleanText(p.text || '');
                      if (!ct) {
                        // 空行：如果 buf 有内容就结算
                        if (buf.trim()) {
                          entries.push(parseTocLine(buf));
                          buf = '';
                        }
                        continue;
                      }
                      // 纯数字行 → 上一条目的页码
                      if (/^\d+$/.test(ct)) {
                        if (buf.trim()) {
                          entries.push(parseTocLine(buf + ' ' + ct));
                          buf = '';
                        } else if (entries.length > 0 && !entries[entries.length - 1].page) {
                          entries[entries.length - 1].page = ct;
                        }
                        continue;
                      }
                      // 如果当前 buf 已经像一个完整条目（含中文标题），新行也像标题开头，先结算
                      if (buf.trim() && /[\u4e00-\u9fff]/.test(buf) && /[\u4e00-\u9fff]/.test(ct)) {
                        entries.push(parseTocLine(buf));
                        buf = ct;
                      } else {
                        buf += (buf ? ' ' : '') + ct;
                      }
                    }
                    if (buf.trim()) entries.push(parseTocLine(buf));
                    // 过滤掉无意义条目（标题为空或只有符号）
                    return entries.filter(e => e.title && /[\u4e00-\u9fff a-zA-Z]/.test(e.title));
                  };

                  const parseTocLine = (line: string): { title: string; page: string } => {
                    // 清理点线、多余空格，提取末尾页码
                    const cleaned = line.replace(/\.{2,}|…+|·{2,}|-{3,}/g, ' ').replace(/\s{2,}/g, ' ').trim();
                    const m = cleaned.match(/^(.+?)\s+(\d+)\s*$/);
                    if (m) return { title: m[1].trim(), page: m[2] };
                    return { title: cleaned, page: '' };
                  };

                  // ── 渲染各区域 ──
                  const elements: React.ReactNode[] = [];
                  let key = 0;

                  for (const seg of segments) {
                    if (seg.type === 'header') {
                      for (const para of seg.paras) {
                        const ct = cleanText(para.text || '');
                        if (!ct) { elements.push(<div key={key++} style={{ height: 8 }} />); continue; }
                        if (/^审\s*计\s*报\s*告$/.test(ct)) {
                          elements.push(
                            <div key={key++} style={{
                              fontSize: 22, fontWeight: 700, color: GT.primary,
                              textAlign: 'center', margin: '20px 0 16px', letterSpacing: 4,
                            }}>审 计 报 告</div>
                          );
                        } else {
                          elements.push(
                            <div key={key++} style={{
                              textAlign: 'center', fontSize: 14, color: GT.textSecondary,
                              margin: '3px 0', lineHeight: 1.8,
                            }}>{ct}</div>
                          );
                        }
                      }
                    } else if (seg.type === 'toc') {
                      // 目录标题
                      elements.push(
                        <div key={key++} style={{
                          fontSize: 18, fontWeight: 700, color: GT.primary,
                          textAlign: 'center', margin: '28px 0 16px',
                          paddingBottom: 8, borderBottom: `2px solid ${GT.primary}`,
                        }}>目　录</div>
                      );
                      // 合并后的目录条目
                      const tocEntries = buildTocEntries(seg.paras);
                      for (const entry of tocEntries) {
                        elements.push(
                          <div key={key++} style={{
                            display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                            padding: '6px 16px', fontSize: 14, color: GT.text,
                            borderBottom: `1px dotted ${GT.borderLight}`,
                          }}>
                            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {entry.title}
                            </span>
                            {entry.page && (
                              <span style={{ color: GT.textMuted, fontSize: 12, flexShrink: 0, marginLeft: 16 }}>
                                {entry.page}
                              </span>
                            )}
                          </div>
                        );
                      }
                      // 目录区底部间距
                      elements.push(<div key={key++} style={{ height: 20 }} />);
                    } else {
                      // body 区
                      for (const para of seg.paras) {
                        const ct = cleanText(para.text || '');
                        const level = para.level;
                        if (!ct) { elements.push(<div key={key++} style={{ height: 8 }} />); continue; }

                        // 一级/二级标题
                        if (level != null && level <= 2) {
                          elements.push(
                            <div key={key++} style={{
                              fontSize: level === 1 ? 16 : 15, fontWeight: 700,
                              color: GT.primary, margin: `${level === 1 ? 28 : 18}px 0 10px`,
                              padding: '8px 14px',
                              background: level === 1 ? GT.primaryBg : GT.bgPage,
                              borderLeft: `4px solid ${GT.primary}`,
                              borderRadius: GT.radiusSm,
                            }}>{ct}</div>
                          );
                        } else if (/^[（(]\d+[）)]/.test(ct) || /^[①②③④⑤⑥⑦⑧⑨⑩]/.test(ct)) {
                          // 带编号的子段落
                          elements.push(
                            <p key={key++} style={{
                              margin: '6px 0', lineHeight: 1.9, fontSize: 14,
                              color: GT.text, paddingLeft: 28, textIndent: '-1em',
                            }}>{ct}</p>
                          );
                        } else {
                          // 普通正文段落
                          elements.push(
                            <p key={key++} style={{
                              margin: '4px 0', lineHeight: 1.9, fontSize: 14,
                              color: GT.text, textIndent: '2em',
                            }}>{ct}</p>
                          );
                        }
                      }
                    }
                  }
                  return elements;
                })()}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ─── 财务报表 ─── */}
      {activeTopTab === 'financial_statement' && (
        <div>
          {allSheets.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: GT.textMuted, fontSize: 14 }}>
              暂无财务报表数据，请上传 Excel 文件
            </div>
          ) : (
            <>
              {renderTabBar(
                allSheets.map((s, i) => ({ key: i, label: s.sheet.sheet_name || `Sheet ${i + 1}` })),
                activeSheetTab,
                setActiveSheetTab,
              )}
              {allSheets[activeSheetTab] && renderSheetContent(allSheets[activeSheetTab].sheet)}
            </>
          )}
        </div>
      )}

      {/* ─── 财务报表附注 ─── */}
      {activeTopTab === 'notes' && (
        <div>
          {sections.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: GT.textMuted, fontSize: 14 }}>
              暂无附注数据，请上传附注文件
            </div>
          ) : (
            <>
              {renderTabBar(
                noteTabs.map(t => ({ key: t.key, label: t.label })),
                noteTabs[activeNoteTab]?.key || noteTabs[0]?.key,
                (key: string) => {
                  const idx = noteTabs.findIndex(t => t.key === key);
                  if (idx >= 0) setActiveNoteTab(idx);
                },
              )}
              {noteTabs[activeNoteTab]?.key === 'before' && renderSectionsPage(noteGroups.before)}
              {noteTabs[activeNoteTab]?.key === 'main' && noteGroups.mainSec && renderStatementNotes(noteGroups.mainSec, 'consolidated')}
              {noteTabs[activeNoteTab]?.key === 'parent' && noteGroups.parentSec && (
                <div>
                  {renderParentCoveragePanel(noteGroups.parentSec)}
                  {renderStatementNotes(noteGroups.parentSec, 'parent')}
                </div>
              )}
              {noteTabs[activeNoteTab]?.key === 'extra' && renderSectionsPage(noteGroups.extra)}
              {noteTabs[activeNoteTab]?.key === 'after' && renderSectionsPage(noteGroups.after)}
            </>
          )}
        </div>
      )}

      </div>{/* 单一滚动容器结束 */}

      {renderFooter()}
    </div>
  );
};

const btnStyle: React.CSSProperties = {
  padding: '5px 14px', border: `1px solid ${GT.border}`, borderRadius: GT.radiusSm,
  background: GT.bgWhite, cursor: 'pointer', fontSize: 12, color: GT.textSecondary,
  transition: 'all 0.15s',
};

export default AccountMatchingView;
