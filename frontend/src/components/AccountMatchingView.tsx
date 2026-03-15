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
  const [consolidatedPresetAccounts, setConsolidatedPresetAccounts] = useState<Array<{ name: string; keywords: string[]; order: number }>>([]);

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

  // ─── 加载合并附注预设科目 ───
  useEffect(() => {
    if (!templateType) return;
    fetch(`${API}/api/report-review/consolidated-accounts/${templateType}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.accounts) setConsolidatedPresetAccounts(data.accounts);
      })
      .catch(() => {});
  }, [templateType]);

  const noteMap = useMemo(() => new Map(notes.map(n => [n.id, n])), [notes]);

  // ─── 报表科目映射：noteTableId → StatementItem（反向索引） ───
  const stmtItemMap = useMemo(() => new Map(statementItems.map(s => [s.id, s])), [statementItems]);
  const noteToStmtMap = useMemo(() => {
    const m = new Map<string, StatementItem>();
    if (!matching) return m;
    // 报表类型优先级：利润表 > 现金流量表 > 资产负债表
    // 附注中的科目（如投资收益、资产减值损失）应优先匹配利润表而非资产负债表
    const stmtTypePriority = (t: string) =>
      t === 'income_statement' ? 2 : t === 'cash_flow' ? 1 : 0;
    // 正式报表 Sheet 名称关键词（优先匹配来自正式报表的科目）
    const FORMAL_KW = ['资产负债', '利润', '损益', '现金流量', '权益变动'];
    const isFormal = (name: string) => FORMAL_KW.some(kw => name.includes(kw));
    for (const entry of matching.entries) {
      const item = stmtItemMap.get(entry.statement_item_id);
      if (!item) continue;
      for (const nid of entry.note_table_ids) {
        const note = noteMap.get(nid);
        const noteAcct = note?.account_name?.replace(/[\s（()）]/g, '') ?? '';
        const itemAcct = item.account_name.replace(/[\s（()）]/g, '');
        const existing = m.get(nid);
        if (!existing) {
          m.set(nid, item);
        } else {
          const existAcct = existing.account_name.replace(/[\s（()）]/g, '');
          // 正式报表优先：来自正式报表 Sheet 的科目优先于辅助 Sheet
          const newFormal = isFormal(item.sheet_name);
          const oldFormal = isFormal(existing.sheet_name);
          if (newFormal && !oldFormal) {
            m.set(nid, item);
            continue;
          }
          if (!newFormal && oldFormal) continue;
          // 精确匹配优先：如果新 item 名称与附注科目完全一致，替换
          const newExact = noteAcct === itemAcct;
          const oldExact = noteAcct === existAcct;
          if (newExact && !oldExact) {
            m.set(nid, item);
          } else if (newExact && oldExact) {
            // 都精确匹配时，优先利润表科目
            if (stmtTypePriority(item.statement_type) > stmtTypePriority(existing.statement_type)) {
              m.set(nid, item);
            }
          } else if (!newExact && !oldExact) {
            // 都不精确时，优先利润表科目，其次选择有余额的科目
            if (stmtTypePriority(item.statement_type) > stmtTypePriority(existing.statement_type)) {
              m.set(nid, item);
            } else if (stmtTypePriority(item.statement_type) === stmtTypePriority(existing.statement_type)) {
              if (
                (existing.closing_balance == null && existing.opening_balance == null)
                && (item.closing_balance != null || item.opening_balance != null)
              ) {
                m.set(nid, item);
              }
            }
          }
        }
      }
    }
    return m;
  }, [matching, stmtItemMap, noteMap]);

  // 通过 section 的 note_table_ids 找到对应的报表科目
  const findStmtForSection = useCallback((sec: NoteSection): StatementItem | null => {
    // 清洗科目名：去除编号、标点、括号及其内容
    const cleanAcctName = (s: string) => {
      // 先去除括号及其内容（中英文括号）
      let r = s.replace(/[（(][^）)]*[）)]/g, '');
      // 再去除编号、空白、标点
      r = r.replace(/[\s一二三四五六七八九十、.\d]/g, '');
      return r;
    };
    const secName = cleanAcctName(sec.title);
    const stmtPri = (t: string) => t === 'income_statement' ? 2 : t === 'cash_flow' ? 1 : 0;
    // 正式报表 Sheet 名称关键词（优先匹配来自正式报表的科目）
    const FORMAL_SHEET_KW = ['资产负债', '利润', '损益', '现金流量', '权益变动'];
    const isFormalSheet = (name: string) => FORMAL_SHEET_KW.some(kw => name.includes(kw));

    // ① 最高优先：section 名称与报表科目精确匹配（如"投资收益"→利润表投资收益）
    // 国企版利润表中"营业收入"/"营业成本"是"其中："子项，需要也能匹配到
    let exactMatch: StatementItem | null = null;
    let exactMatchSub: StatementItem | null = null;  // 子项的精确匹配（优先级低于非子项）
    for (const si of statementItems) {
      const siName = cleanAcctName(si.account_name);
      if (secName !== siName) continue;
      const target = si.is_sub_item ? 'sub' : 'main';
      const cur = target === 'sub' ? exactMatchSub : exactMatch;
      if (!cur) {
        if (target === 'sub') exactMatchSub = si; else exactMatch = si;
      } else {
        // 优先选择来自正式报表 Sheet 的科目
        const curFormal = isFormalSheet(cur.sheet_name);
        const newFormal = isFormalSheet(si.sheet_name);
        if (newFormal && !curFormal) {
          if (target === 'sub') exactMatchSub = si; else exactMatch = si;
        } else if (newFormal === curFormal) {
          if (stmtPri(si.statement_type) > stmtPri(cur.statement_type)) {
            if (target === 'sub') exactMatchSub = si; else exactMatch = si;
          } else if (stmtPri(si.statement_type) === stmtPri(cur.statement_type)) {
            const curHasVal = (cur.closing_balance != null || cur.opening_balance != null);
            const newHasVal = (si.closing_balance != null || si.opening_balance != null);
            if (newHasVal && !curHasVal) {
              if (target === 'sub') exactMatchSub = si; else exactMatch = si;
            }
          }
        }
      }
    }
    if (exactMatch) return exactMatch;
    if (exactMatchSub) return exactMatchSub;

    // ② 通过 noteToStmtMap 查找（自身表格 → 子节点表格）
    for (const nid of sec.note_table_ids) {
      const item = noteToStmtMap.get(nid);
      if (item) return item;
    }
    for (const child of sec.children) {
      for (const nid of child.note_table_ids) {
        const item = noteToStmtMap.get(nid);
        if (item) return item;
      }
      for (const gc of child.children) {
        for (const nid of gc.note_table_ids) {
          const item = noteToStmtMap.get(nid);
          if (item) return item;
        }
      }
    }

    // ③ 包含匹配回退
    // ③ 包含匹配回退（先找非子项，找不到再找子项）
    let bestMatch: StatementItem | null = null;
    let bestMatchLen = 0;
    let bestMatchSub: StatementItem | null = null;
    let bestMatchSubLen = 0;
    for (const si of statementItems) {
      const siName = cleanAcctName(si.account_name);
      if (secName.includes(siName) || siName.includes(secName)) {
        const matchLen = siName.length;
        const ref = si.is_sub_item ? bestMatchSub : bestMatch;
        const refLen = si.is_sub_item ? bestMatchSubLen : bestMatchLen;
        const newFml = isFormalSheet(si.sheet_name);
        const curFml = ref ? isFormalSheet(ref.sheet_name) : false;
        let better = false;
        if (matchLen > refLen) {
          better = true;
        } else if (matchLen === refLen && ref) {
          if (newFml && !curFml) {
            better = true;
          } else if (newFml === curFml) {
            if (stmtPri(si.statement_type) > stmtPri(ref.statement_type)) {
              better = true;
            } else if (stmtPri(si.statement_type) === stmtPri(ref.statement_type)) {
              if (ref.closing_balance == null && ref.opening_balance == null
                && (si.closing_balance != null || si.opening_balance != null)) {
                better = true;
              }
            }
          }
        }
        if (better) {
          if (si.is_sub_item) { bestMatchSub = si; bestMatchSubLen = matchLen; }
          else { bestMatch = si; bestMatchLen = matchLen; }
        }
      }
    }
    return bestMatch || bestMatchSub;
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
  const SKIP_SHEET_KW = ['校验', 'custom', '辅助', '参数', '配置', 'config', 'setting', 'template', '横纵加', '勾稽', '目录', '封面', '说明', '备注', '增加额', '调整'];
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
    id: string, title: string, level: number, hasContent: boolean, seqNo?: string, warn?: boolean,
  ) => {
    const isCollapsed = collapsedIds.has(id);
    const tc = warn ? GT.danger : lvlColor(level);
    const bg = warn ? '#fdf0ef' : lvlTitleBg(level);
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
  // subColumnHint: 可选，用于多子列表格（如"收入"/"成本"）中定位正确的子列
  const extractNoteTotals = useCallback((sec: NoteSection, subColumnHint?: string): { closing?: number; opening?: number } => {
    // 尝试从 section 下所有表格中提取合计金额
    if (sec.note_table_ids.length === 0) return {};

    const parse = (v: any): number | undefined => {
      if (v == null) return undefined;
      const s = String(v).replace(/,/g, '').trim();
      if (!s || s === '—' || s === '-' || s === '——') return undefined;
      const n = Number(s);
      return isNaN(n) ? undefined : n;
    };

    // ── 辅助：根据表头判断列索引属于期末还是期初 ──
    // 检查 header_rows 和 headers 中该列及其父列的关键词
    const CLOSING_KW_DETECT = ['期末', '年末', '本期', '本年'];
    const OPENING_KW_DETECT = ['期初', '年初', '上期', '上年'];
    const MOVE_KW_DETECT = ['增加', '减少', '增减', '转入', '转出', '摊销', '折旧', '计提', '处置', '变动', '转换', '发生'];
    const isMovementHeader = (h: string) => MOVE_KW_DETECT.some(kw => h.includes(kw));
    const detectColSemantic = (colIdx: number, headerRows: string[][], headers: string[]): 'closing' | 'opening' | null => {
      // 检查所有表头行中该列的文本
      for (const row of headerRows) {
        const h = (row[colIdx] || '').replace(/\s/g, '');
        if (!h) continue;
        // 跳过变动列（"本期增加"/"本期减少"等含期末/期初关键词但不是余额列）
        if (isMovementHeader(h)) continue;
        // 先检查 opening（"上年年末" 含"年末"但应归为 opening）
        if (OPENING_KW_DETECT.some(kw => h.includes(kw))) return 'opening';
        if (CLOSING_KW_DETECT.some(kw => h.includes(kw))) return 'closing';
      }
      // 检查 headers（单行表头）
      const h = (headers[colIdx] || '').replace(/\s/g, '');
      if (h && !isMovementHeader(h)) {
        if (OPENING_KW_DETECT.some(kw => h.includes(kw))) return 'opening';
        if (CLOSING_KW_DETECT.some(kw => h.includes(kw))) return 'closing';
      }
      // 检查父列：在 header_rows 第一行中，向左找最近的非空单元格
      if (headerRows.length > 0) {
        const firstRow = headerRows[0];
        for (let ci = colIdx; ci >= 0; ci--) {
          const ph = (firstRow[ci] || '').replace(/\s/g, '');
          if (!ph) continue;
          // 跳过变动列父标题
          if (isMovementHeader(ph)) continue;
          if (OPENING_KW_DETECT.some(kw => ph.includes(kw))) return 'opening';
          if (CLOSING_KW_DETECT.some(kw => ph.includes(kw))) return 'closing';
          break; // 只检查最近的非变动列非空父列
        }
      }
      return null;
    };

    // 辅助：对两个列索引，根据表头语义分配 closing/opening
    // 返回 { closing, opening }，如果表头无法判断则回退到位置假设（first=closing）
    const assignByHeaderSemantic = (
      colIdx1: number, val1: number | undefined,
      colIdx2: number, val2: number | undefined,
      nt: NoteTable
    ): { closing?: number; opening?: number } => {
      const hRows = nt.header_rows && nt.header_rows.length > 0 ? nt.header_rows : [];
      const hdrs = nt.headers || [];
      const sem1 = detectColSemantic(colIdx1, hRows, hdrs);
      const sem2 = detectColSemantic(colIdx2, hRows, hdrs);
      // 只有当两个列都能明确判断语义，且语义不同时，才使用语义分配
      if (sem1 && sem2 && sem1 !== sem2) {
        if (sem1 === 'closing' && sem2 === 'opening') return { closing: val1, opening: val2 };
        if (sem1 === 'opening' && sem2 === 'closing') return { closing: val2, opening: val1 };
      }
      // 其他情况（无法判断、只有一个能判断、两个相同）：回退到位置假设（第一个=closing）
      return { closing: val1, opening: val2 };
    };

    // 辅助：从单个表格中提取合计行
    // 对于含"减：一年内到期"等扣减行的表格，优先取"小计"行（对应资产负债表金额）
    const extractFromTable = (nt: NoteTable): { totalRow: any[] | null; nt: NoteTable } => {
      if (!nt || nt.rows.length === 0) return { totalRow: null, nt };

      // 找"合计"/"总计"行
      let totalIdx = -1;
      for (let ri = 0; ri < nt.rows.length; ri++) {
        const first = (String(nt.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
        if (first === '合计' || first === '总计') {
          totalIdx = ri;
        }
      }

      // 默认：找"合计"行
      if (totalIdx >= 0) {
        return { totalRow: nt.rows[totalIdx], nt };
      }
      for (let ri = nt.rows.length - 1; ri >= 0; ri--) {
        const first = (String(nt.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
        if (first === '合计' || first === '总计') {
          return { totalRow: nt.rows[ri], nt };
        }
      }
      return { totalRow: null, nt };
    };

    // 遍历所有表格，找到第一个有合计行的
    let totalRow: any[] | null = null;
    let nt: NoteTable | null = null;

    // ── 特殊表格：未分配利润 ──
    // 该表格没有合计行，而是通过特定行名标识期末/期初：
    // "期末未分配利润" → 本期发生额列 = 期末数
    // "调整后 期初未分配利润" → 本期发生额列 = 期初数
    for (const nid of sec.note_table_ids) {
      const table = noteMap.get(nid);
      if (!table || table.rows.length === 0) continue;
      let closingVal: number | undefined;
      let openingVal: number | undefined;
      let hasPattern = false;
      for (let ri = 0; ri < table.rows.length; ri++) {
        const first = (String(table.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
        if (first.includes('期末未分配利润') || first.includes('期末未分配')) {
          hasPattern = true;
          // 取第一个有值的数值列（本期发生额）
          for (let ci = 1; ci < table.rows[ri].length; ci++) {
            const v = parse(table.rows[ri][ci]);
            if (v != null) { closingVal = v; break; }
          }
        }
        // "调整后 期初未分配利润" — 必须含"调整后"，排除"调整 期初未分配利润合计数"
        if (first.includes('调整后') && (first.includes('期初未分配利润') || first.includes('期初未分配'))) {
          hasPattern = true;
          for (let ci = 1; ci < table.rows[ri].length; ci++) {
            const v = parse(table.rows[ri][ci]);
            if (v != null) { openingVal = v; break; }
          }
        }
      }
      if (hasPattern && (closingVal != null || openingVal != null)) {
        return { closing: closingVal, opening: openingVal };
      }
    }

    for (const nid of sec.note_table_ids) {
      const table = noteMap.get(nid);
      if (!table) continue;
      const result = extractFromTable(table);
      if (result.totalRow) {
        totalRow = result.totalRow;
        nt = result.nt;
        break;
      }
      if (!nt) nt = table; // 记住第一个表格作为 fallback
    }

    // 如果没有合计行，尝试从子节点的表格中查找
    if (!totalRow && sec.children.length > 0) {
      for (const child of sec.children) {
        for (const nid of child.note_table_ids) {
          const table = noteMap.get(nid);
          if (!table) continue;
          const result = extractFromTable(table);
          if (result.totalRow) {
            totalRow = result.totalRow;
            nt = result.nt;
            break;
          }
        }
        if (totalRow) break;
      }
    }

    // 如果仍然没有合计行，尝试单行表格回退：
    // 只有一行数据时，该行即为期末/期初数值，直接用于核对
    if (!totalRow && nt && nt.rows.length === 1) {
      totalRow = nt.rows[0];
    }

    // 如果仍然没有合计行，尝试"账面价值"/"账面净值"行（投资性房地产/固定资产等）
    if (!totalRow && nt && nt.rows.length > 0) {
      const BOOK_VALUE_KW = ['账面价值', '账面净值', '净值'];
      // 先确定"合计"列索引（多列表格中优先取合计列的值）
      let bookValTotalCol = -1;
      {
        const allHdrs = nt.headers || [];
        for (let ci = allHdrs.length - 1; ci >= 1; ci--) {
          const h = (String(allHdrs[ci] ?? '')).replace(/\s+/g, '');
          if (h === '合计' || h === '总计') { bookValTotalCol = ci; break; }
        }
      }
      // 辅助：从行中提取金额，优先合计列，否则取最后一个有值的列
      const pickRowVal = (row: any[]): number | undefined => {
        if (bookValTotalCol > 0) {
          const v = parse(row?.[bookValTotalCol]);
          if (v != null) return v;
        }
        for (let ci = row.length - 1; ci >= 1; ci--) {
          const v = parse(row[ci]);
          if (v != null) return v;
        }
        return undefined;
      };

      // 策略A：分别找"期末账面价值"和"期初账面价值"行
      {
        let closingVal: number | undefined;
        let openingVal: number | undefined;
        for (let ri = 0; ri < nt.rows.length; ri++) {
          const first = (String(nt.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
          // 行标签同时包含"期末/年末"和"账面价值"
          if ((first.includes('期末') || first.includes('年末')) && BOOK_VALUE_KW.some(kw => first.includes(kw))) {
            closingVal = pickRowVal(nt.rows[ri]);
          }
          // 行标签同时包含"期初/年初"和"账面价值"
          if ((first.includes('期初') || first.includes('年初')) && BOOK_VALUE_KW.some(kw => first.includes(kw))) {
            openingVal = pickRowVal(nt.rows[ri]);
          }
        }
        if (closingVal != null || openingVal != null) {
          return { closing: closingVal, opening: openingVal };
        }
      }
      // 策略B：在"账面价值"标题行之后，找"期末"和"期初"子行
      {
        let inBookValueSection = false;
        let closingVal: number | undefined;
        let openingVal: number | undefined;
        for (let ri = 0; ri < nt.rows.length; ri++) {
          const first = (String(nt.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
          // 检测"四、账面价值"等标题行（可能有数值但不应直接使用）
          if (BOOK_VALUE_KW.some(kw => first.includes(kw)) && !first.includes('期末') && !first.includes('期初') && !first.includes('年末') && !first.includes('年初')) {
            inBookValueSection = true;
            continue;
          }
          if (inBookValueSection) {
            if (first.includes('期末') || first.includes('年末')) {
              closingVal = pickRowVal(nt.rows[ri]);
            }
            if (first.includes('期初') || first.includes('年初')) {
              openingVal = pickRowVal(nt.rows[ri]);
            }
            // 遇到新的大类标题（如"五、..."）则退出
            if (/^[一二三四五六七八九十]+[、.]/.test(first) && !BOOK_VALUE_KW.some(kw => first.includes(kw))) {
              break;
            }
          }
        }
        if (closingVal != null || openingVal != null) {
          return { closing: closingVal, opening: openingVal };
        }
      }
      // 策略C：最后兜底 — 找包含"账面价值"且有数值的行
      for (let ri = nt.rows.length - 1; ri >= 0; ri--) {
        const first = (String(nt.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
        if (BOOK_VALUE_KW.some(kw => first.includes(kw))) {
          // 优先取合计列
          if (bookValTotalCol > 0) {
            const v = parse(nt.rows[ri]?.[bookValTotalCol]);
            if (v != null) {
              // 单行账面价值 — 只有期末
              return { closing: v };
            }
          }
          // 否则取所有数值及其列索引
          const rowNumsWithIdx: { ci: number; val: number }[] = [];
          for (let ci = 1; ci < nt.rows[ri].length; ci++) {
            const v = parse(nt.rows[ri][ci]);
            if (v != null) rowNumsWithIdx.push({ ci, val: v });
          }
          if (rowNumsWithIdx.length >= 2) {
            // 通过表头语义判断哪个是期末、哪个是期初
            return assignByHeaderSemantic(
              rowNumsWithIdx[0].ci, rowNumsWithIdx[0].val,
              rowNumsWithIdx[1].ci, rowNumsWithIdx[1].val,
              nt
            );
          }
          if (rowNumsWithIdx.length === 1) {
            return { closing: rowNumsWithIdx[0].val };
          }
        }
      }

      // 策略D：无形资产等表格 — 无"账面价值"行，需从 原值-累计摊销-减值准备 计算
      // 表格结构：一、原价/原值 → 二、累计摊销 → 三、减值准备（无四、账面价值）
      // 在每个大类中找"期末余额/期末金额"和"期初余额/期初金额"行，
      // 然后用"合计"列（最后一个有数值的列）的值计算账面价值
      {
        const COST_KW = ['原价', '原值', '账面原值'];
        const AMORT_KW = ['累计摊销', '累计折旧'];
        const IMPAIR_KW = ['减值准备'];
        // 检测表格是否有这种分段结构
        const sectionPattern = /^[一二三四五六七八九十]+[、.]/;
        let hasCostSection = false;
        let hasAmortSection = false;
        for (let ri = 0; ri < nt.rows.length; ri++) {
          const first = (String(nt.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
          if (sectionPattern.test(first)) {
            if (COST_KW.some(kw => first.includes(kw))) hasCostSection = true;
            if (AMORT_KW.some(kw => first.includes(kw))) hasAmortSection = true;
          }
        }
        if (hasCostSection && hasAmortSection) {
          // 找"合计"列索引（表头中最后一个含"合计"的列，或最后一列）
          let totalColIdx = -1;
          const allHeaders = nt.headers || [];
          for (let ci = allHeaders.length - 1; ci >= 1; ci--) {
            const h = (String(allHeaders[ci] ?? '')).replace(/\s+/g, '');
            if (h === '合计' || h === '总计') { totalColIdx = ci; break; }
          }
          // 如果表头没有"合计"列，取最后一列
          if (totalColIdx < 0 && allHeaders.length > 1) {
            totalColIdx = allHeaders.length - 1;
          }

          if (totalColIdx > 0) {
            // 按大类分段，提取每段的期末/期初值
            type SectionVals = { closing?: number; opening?: number };
            let currentSection = '';
            const sectionVals: Record<string, SectionVals> = {};

            for (let ri = 0; ri < nt.rows.length; ri++) {
              const first = (String(nt.rows[ri]?.[0] ?? '')).replace(/\s+/g, '');
              if (sectionPattern.test(first)) {
                if (COST_KW.some(kw => first.includes(kw))) currentSection = 'cost';
                else if (AMORT_KW.some(kw => first.includes(kw))) currentSection = 'amort';
                else if (IMPAIR_KW.some(kw => first.includes(kw))) currentSection = 'impair';
                else currentSection = '';
                continue;
              }
              if (!currentSection) continue;
              // 找"期末余额/期末金额"行
              if (first.includes('期末') || first.includes('年末')) {
                const v = parse(nt.rows[ri]?.[totalColIdx]);
                if (v != null) {
                  if (!sectionVals[currentSection]) sectionVals[currentSection] = {};
                  sectionVals[currentSection].closing = v;
                }
              }
              // 找"期初余额/期初金额"行
              if (first.includes('期初') || first.includes('年初')) {
                const v = parse(nt.rows[ri]?.[totalColIdx]);
                if (v != null) {
                  if (!sectionVals[currentSection]) sectionVals[currentSection] = {};
                  sectionVals[currentSection].opening = v;
                }
              }
            }

            const costV = sectionVals['cost'];
            const amortV = sectionVals['amort'];
            const impairV = sectionVals['impair'];
            if (costV) {
              const closingBV = costV.closing != null
                ? costV.closing - (amortV?.closing ?? 0) - (impairV?.closing ?? 0)
                : undefined;
              const openingBV = costV.opening != null
                ? costV.opening - (amortV?.opening ?? 0) - (impairV?.opening ?? 0)
                : undefined;
              if (closingBV != null || openingBV != null) {
                return { closing: closingBV, opening: openingBV };
              }
            }
          }
        }
      }
    }

    if (!totalRow || !nt) return {};

    // 提取合计行中所有数值及其列索引
    const nums: { idx: number; val: number }[] = [];
    for (let ci = 1; ci < totalRow.length; ci++) {
      const v = parse(totalRow[ci]);
      if (v != null) nums.push({ idx: ci, val: v });
    }
    if (nums.length === 0) return {};

    // ── 简单表格（≤2个数值列）：根据表头语义分配期末/期初 ──
    if (nums.length <= 2) {
      // 尝试通过表头关键词确定每个数值列的语义
      // 检查所有 header_rows 行 + headers，找到能识别关键词的那一行
      const CLOSING_KW = ['期末', '年末', '本期', '本年'];
      const OPENING_KW = ['期初', '年初', '上期', '上年'];
      const allHdrRows = [
        ...(nt.header_rows && nt.header_rows.length > 0 ? nt.header_rows : []),
        nt.headers || [],
      ];
      let closingVal: number | undefined;
      let openingVal: number | undefined;
      // 遍历每一行表头，尝试识别列语义
      for (const hdrRow of allHdrRows) {
        const hdrs = hdrRow.map((h: any) => (h || '').replace(/\s/g, ''));
        let tmpClosing: number | undefined;
        let tmpOpening: number | undefined;
        for (const n of nums) {
          const h = hdrs[n.idx] || '';
          // 先检查 OPENING_KW — "上年年末金额"同时含"年末"和"上年"，应归为期初
          const isOpening = OPENING_KW.some(kw => h.includes(kw));
          const isClosing = CLOSING_KW.some(kw => h.includes(kw));
          if (isOpening) {
            tmpOpening = n.val;
          } else if (isClosing) {
            tmpClosing = n.val;
          }
        }
        if (tmpClosing != null || tmpOpening != null) {
          closingVal = tmpClosing;
          openingVal = tmpOpening;
          break; // 找到能识别的表头行，停止
        }
      }
      // 如果通过表头成功分配了至少一个值，使用语义分配
      if (closingVal != null || openingVal != null) {
        return { closing: closingVal, opening: openingVal };
      }
      // 表头无法识别时，用 detectColSemantic 辅助判断
      if (nums.length === 2) {
        return assignByHeaderSemantic(nums[0].idx, nums[0].val, nums[1].idx, nums[1].val, nt);
      }
      // 单值时也尝试语义判断
      if (nums.length === 1) {
        const hRowsAll = nt.header_rows && nt.header_rows.length > 0 ? nt.header_rows : [];
        const sem = detectColSemantic(nums[0].idx, hRowsAll, nt.headers || []);
        if (sem === 'opening') return { opening: nums[0].val };
        return { closing: nums[0].val };
      }
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
        // 通过父行表头语义判断哪个是期末、哪个是期初
        return assignByHeaderSemantic(
          valueColsInLast[0], parse(totalRow[valueColsInLast[0]]),
          valueColsInLast[1], parse(totalRow[valueColsInLast[1]]),
          nt!
        );
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
          // 通过父行表头语义判断哪组是期末、哪组是期初
          const hRowsLocal = nt!.header_rows && nt!.header_rows.length > 0 ? nt!.header_rows : [];
          const hdrsLocal = nt!.headers || [];
          const sem0 = detectColSemantic(balanceCols[0], hRowsLocal, hdrsLocal);
          const sem1 = detectColSemantic(balanceCols[1], hRowsLocal, hdrsLocal);
          // 只有两组都能明确判断且语义不同时才翻转，否则保持位置假设（第一组=closing）
          let closingGroupIdx = 0, openingGroupIdx = 1;
          if (sem0 && sem1 && sem0 !== sem1 && sem0 === 'opening') {
            closingGroupIdx = 1; openingGroupIdx = 0;
          }
          const closingBal = parse(totalRow[balanceCols[closingGroupIdx]]);
          const closingProv = parse(totalRow[provisionCols[closingGroupIdx]]) ?? 0;
          const openingBal = parse(totalRow[balanceCols[openingGroupIdx]]);
          const openingProv = parse(totalRow[provisionCols[openingGroupIdx]]) ?? 0;
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
      // 排除变动列（本期增加/本期减少等）
      const MOVE_KW = ['增加', '减少', '增减', '转入', '转出', '摊销', '折旧', '计提', '处置', '变动'];
      const filterMoveCols = (cols: number[]): number[] =>
        cols.filter(ci => {
          const h = (hRows[hRows.length - 1][ci] || '').replace(/\s/g, '');
          return !MOVE_KW.some(kw => h.includes(kw));
        });
      const closingColsLast = filterMoveCols(
        findColsByKeyword('期末', hRows.length - 1)
          .concat(findColsByKeyword('本期', hRows.length - 1))
      );
      const openingColsLast = filterMoveCols(
        findColsByKeyword('期初', hRows.length - 1)
          .concat(findColsByKeyword('上期', hRows.length - 1))
          .concat(findColsByKeyword('上年', hRows.length - 1))
      );
      if (closingColsLast.length > 0 || openingColsLast.length > 0) {
        return {
          closing: closingColsLast.length > 0 ? parse(totalRow[closingColsLast[0]]) : undefined,
          opening: openingColsLast.length > 0 ? parse(totalRow[openingColsLast[0]]) : undefined,
        };
      }

      // 策略C：在第一行表头中找"期末"/"期初"父列，然后在子行中定位金额列
      // 排除变动列
      let closingParentCol = -1, openingParentCol = -1;
      for (let ci = 0; ci < firstRow.length; ci++) {
        const h = (firstRow[ci] || '').replace(/\s/g, '');
        if (!h) continue;
        if (MOVE_KW.some(kw => h.includes(kw))) continue;
        if (closingParentCol < 0 && (h.includes('期末') || h.includes('本期'))) closingParentCol = ci;
        if (openingParentCol < 0 && (h.includes('期初') || h.includes('上期') || h.includes('上年'))) openingParentCol = ci;
      }

      // 在子列范围内找最佳金额值：
      // 0. 如果有 subColumnHint，优先匹配子列表头
      // 1. 优先找"账面价值"列直接取值
      // 2. 如果有"账面余额/原值"和"减值准备"列，计算 原值-准备
      // 3. 其次找"金额"/"余额"列（排除"比例"/%列）
      // 4. 最后取范围内第一个有数值的非比例列
      const pickAmountValue = (start: number, end: number): number | undefined => {
        const tr = totalRow!;
        // 如果有 subColumnHint，在子列表头中精确匹配
        if (subColumnHint) {
          for (let ci = start; ci < end; ci++) {
            const h = (lastRow[ci] || '').replace(/\s/g, '');
            if (h.includes(subColumnHint)) return parse(tr[ci]);
          }
          // hint 未匹配到，返回 undefined（避免取到错误的列）
          return undefined;
        }
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
      return assignByHeaderSemantic(
        valueColIndices[0].i, parse(totalRow[valueColIndices[0].i]),
        valueColIndices[1].i, parse(totalRow[valueColIndices[1].i]),
        nt!
      );
    }

    // 找"期末"/"期初"关键词（排除变动列如"本期增加"/"本期减少"等）
    const MOVEMENT_KW = ['增加', '减少', '增减', '转入', '转出', '摊销', '折旧', '计提', '处置', '变动'];
    const isMovementCol = (h: string) => MOVEMENT_KW.some(kw => h.includes(kw));
    const OPEN_KW_ALL = ['期初', '年初', '上期', '上年'];
    let closingIdx = -1, openingIdx = -1;
    // 第一轮：优先找"期末"/"年末"（精确匹配余额列）
    // 注意：如果表头同时含期初/上年关键词（如"上年年末金额"），应归为期初而非期末
    for (let ci = 0; ci < headers.length; ci++) {
      const h = headers[ci];
      if (isMovementCol(h)) continue;
      const hasOpenKw = OPEN_KW_ALL.some(kw => h.includes(kw));
      if (closingIdx < 0 && (h.includes('期末') || h.includes('年末')) && !hasOpenKw) closingIdx = ci;
      if (openingIdx < 0 && (h.includes('期初') || h.includes('年初') || hasOpenKw)) openingIdx = ci;
    }
    // 第二轮：如果没找到，再尝试"本期"/"上期"（但排除变动列）
    if (closingIdx < 0) {
      for (let ci = 0; ci < headers.length; ci++) {
        const h = headers[ci];
        if ((h.includes('本期') || h.includes('本年')) && !isMovementCol(h) && !OPEN_KW_ALL.some(kw => h.includes(kw))) { closingIdx = ci; break; }
      }
    }
    if (openingIdx < 0) {
      for (let ci = 0; ci < headers.length; ci++) {
        const h = headers[ci];
        if ((h.includes('上期') || h.includes('上年')) && !isMovementCol(h)) { openingIdx = ci; break; }
      }
    }
    if (closingIdx >= 0 || openingIdx >= 0) {
      return {
        closing: closingIdx >= 0 ? parse(totalRow[closingIdx]) : undefined,
        opening: openingIdx >= 0 ? parse(totalRow[openingIdx]) : undefined,
      };
    }

    // 最终 fallback：通过表头语义分配第一个和最后一个数值
    if (nums.length >= 2 && nt) {
      return assignByHeaderSemantic(
        nums[0].idx, nums[0].val,
        nums[nums.length - 1].idx, nums[nums.length - 1].val,
        nt
      );
    }
    return { closing: nums[0]?.val, opening: nums[nums.length - 1]?.val };
  }, [noteMap]);

  // ─── 计算各附注页签是否存在勾稽不一致 ───
  const tabMismatchKeys = useMemo(() => {
    const TOL = 0.5;
    const warnKeys = new Set<string>();

    const checkSec = (sec: NoteSection, mode: 'consolidated' | 'parent') => {
      const isContainer = (c: NoteSection) =>
        c.children.length > 0 && c.note_table_ids.length === 0 &&
        c.content_paragraphs.filter(p => p.trim()).length === 0;
      let displayChildren = sec.children;
      if (sec.children.length >= 1 && sec.children.every(isContainer)) {
        displayChildren = [];
        for (const container of sec.children) {
          displayChildren.push(...container.children);
        }
      }
      const allSecs = displayChildren.length > 0 ? displayChildren : [sec];
      for (const child of allSecs) {
        const si = findStmtForSection(child);
        if (!si) continue;
        const stmtClosing = mode === 'parent' ? (si.company_closing_balance ?? si.closing_balance) : si.closing_balance;
        const stmtOpening = mode === 'parent' ? (si.company_opening_balance ?? si.opening_balance) : si.opening_balance;
        const noteTotals = extractNoteTotals(child);
        if (stmtClosing != null && noteTotals.closing != null && Math.abs(stmtClosing - noteTotals.closing) > TOL) return true;
        if (stmtOpening != null && noteTotals.opening != null && Math.abs(stmtOpening - noteTotals.opening) > TOL) return true;
      }
      return false;
    };

    if (noteGroups.mainSec && checkSec(noteGroups.mainSec, 'consolidated')) warnKeys.add('main');
    if (noteGroups.parentSec && checkSec(noteGroups.parentSec, 'parent')) warnKeys.add('parent');
    return warnKeys;
  }, [noteGroups, findStmtForSection, extractNoteTotals]);

  // ─── 渲染报表金额提示条 ───
  const renderStmtAmountBar = (item: StatementItem, mode: 'consolidated' | 'parent', sec: NoteSection) => {
    const fmt = (v?: number) => v != null ? v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
    const TOL = 0.5;

    // 检测是否为"营业收入和营业成本"合并附注
    const secTitle = sec.title.replace(/\s+/g, '');
    const isCombinedRevenueCost = secTitle.includes('营业收入') && secTitle.includes('营业成本');

    // 构建需要校验的科目列表：[{ item, subHint, label }]
    type CheckEntry = { si: StatementItem; subHint?: string; label: string };
    const entries: CheckEntry[] = [];

    if (isCombinedRevenueCost) {
      // 找到营业收入和营业成本两个报表科目
      // 国企版利润表中"营业收入"/"营业成本"可能是"其中："子项（is_sub_item=true）
      // 优先找非子项，找不到再找子项
      const revenueItem = statementItems.find(si =>
        !si.is_sub_item && si.account_name === '营业收入'
      ) || statementItems.find(si =>
        !si.is_sub_item && si.account_name.includes('营业收入') && !si.account_name.includes('成本')
      ) || statementItems.find(si =>
        si.account_name === '营业收入'
      ) || statementItems.find(si =>
        si.account_name.includes('营业收入') && !si.account_name.includes('成本')
      );
      const costItem = statementItems.find(si =>
        !si.is_sub_item && si.account_name === '营业成本'
      ) || statementItems.find(si =>
        !si.is_sub_item && si.account_name.includes('营业成本') && !si.account_name.includes('收入')
      ) || statementItems.find(si =>
        si.account_name === '营业成本'
      ) || statementItems.find(si =>
        si.account_name.includes('营业成本') && !si.account_name.includes('收入')
      );
      if (revenueItem) entries.push({ si: revenueItem, subHint: '收入', label: '营业收入' });
      if (costItem) entries.push({ si: costItem, subHint: '成本', label: '营业成本' });
      // 如果都没找到，仍然按收入/成本分别提取附注合计（用 item 作为占位）
      if (entries.length === 0) {
        entries.push({ si: item, subHint: '收入', label: '营业收入' });
        entries.push({ si: item, subHint: '成本', label: '营业成本' });
      }
    } else {
      // 使用报表类型中文名作为标签；仅当 sheet_name 是正式报表名时才用 sheet_name
      const STMT_TYPE_LABELS: Record<string, string> = {
        balance_sheet: '资产负债表',
        income_statement: '利润表',
        cash_flow: '现金流量表',
        equity_change: '所有者权益变动表',
      };
      const FORMAL_SHEET_KW = ['资产负债', '利润', '损益', '现金流量', '权益变动'];
      const isFormalName = item.sheet_name && FORMAL_SHEET_KW.some(kw => item.sheet_name.includes(kw));
      const sheetLabel = isFormalName ? item.sheet_name : (STMT_TYPE_LABELS[item.statement_type] || item.account_name);
      entries.push({ si: item, label: mode === 'parent' ? '母公司报表' : sheetLabel });
    }

    // 渲染单个科目的报表金额行 + 勾稽校验行
    const renderEntry = (entry: CheckEntry, idx: number) => {
      const stmtClosing = mode === 'parent' ? (entry.si.company_closing_balance ?? entry.si.closing_balance) : entry.si.closing_balance;
      const stmtOpening = mode === 'parent' ? (entry.si.company_opening_balance ?? entry.si.opening_balance) : entry.si.opening_balance;
      const noteTotals = extractNoteTotals(sec, entry.subHint);
      // 当报表金额为0且附注未提取到值时，视为匹配（都是0/无值）
      const closingMatch = (stmtClosing != null && noteTotals.closing != null)
        ? Math.abs(stmtClosing - noteTotals.closing) <= TOL
        : (stmtClosing === 0 && noteTotals.closing == null) ? true : null;
      const openingMatch = (stmtOpening != null && noteTotals.opening != null)
        ? Math.abs(stmtOpening - noteTotals.opening) <= TOL
        : (stmtOpening === 0 && noteTotals.opening == null) ? true : null;

      return (
        <div key={idx}>
          {/* 报表金额行 */}
          <div style={{
            padding: '7px 14px',
            background: `linear-gradient(135deg, ${GT.primaryBg} 0%, ${GT.primaryBgDeep} 100%)`,
            fontSize: 12, display: 'flex', flexWrap: 'wrap', gap: '4px 20px',
            alignItems: 'center',
            borderTop: idx > 0 ? `1px solid ${GT.primary}30` : undefined,
          }}>
            <span style={{ fontWeight: 700, color: GT.primary, fontSize: 12 }}>📊 {entry.label}</span>
            <span style={{ color: GT.primary, fontWeight: 600 }}>
              期末/本期：<span style={{ fontVariantNumeric: 'tabular-nums' }}>{fmt(stmtClosing)}</span>
            </span>
            <span style={{ color: GT.primary, fontWeight: 600 }}>
              期初/上期：<span style={{ fontVariantNumeric: 'tabular-nums' }}>{fmt(stmtOpening)}</span>
            </span>
          </div>
          {/* 勾稽校验行 */}
          <div style={{
            padding: '5px 14px',
            background: (closingMatch === false || openingMatch === false) ? '#fdf0ef'
              : (closingMatch !== null || openingMatch !== null) ? '#eafaf1' : '#f8f8f8',
            borderTop: `1px solid ${GT.primary}20`,
            fontSize: 12, display: 'flex', flexWrap: 'wrap', gap: '4px 20px',
            alignItems: 'center',
          }}>
            <span style={{ fontWeight: 600, color: GT.textSecondary, fontSize: 11 }}>勾稽校验</span>
            {closingMatch !== null ? (
              <span style={{
                color: closingMatch ? GT.success : GT.danger,
                fontWeight: closingMatch ? 400 : 700,
              }}>
                {closingMatch ? '✓' : '✗'} 期末
                {!closingMatch && noteTotals.closing != null && (
                  <span style={{ fontSize: 11, marginLeft: 4 }}>
                    （附注：{fmt(noteTotals.closing)}，差异：{fmt(stmtClosing != null && noteTotals.closing != null ? stmtClosing - noteTotals.closing : undefined)}）
                  </span>
                )}
              </span>
            ) : stmtClosing != null ? (
              <span style={{ color: GT.textMuted, fontSize: 11 }}>— 期末：未提取到附注合计</span>
            ) : null}
            {openingMatch !== null ? (
              <span style={{
                color: openingMatch ? GT.success : GT.danger,
                fontWeight: openingMatch ? 400 : 700,
              }}>
                {openingMatch ? '✓' : '✗'} 期初
                {!openingMatch && noteTotals.opening != null && (
                  <span style={{ fontSize: 11, marginLeft: 4 }}>
                    （附注：{fmt(noteTotals.opening)}，差异：{fmt(stmtOpening != null && noteTotals.opening != null ? stmtOpening - noteTotals.opening : undefined)}）
                  </span>
                )}
              </span>
            ) : stmtOpening != null ? (
              <span style={{ color: GT.textMuted, fontSize: 11 }}>— 期初：未提取到附注合计</span>
            ) : null}
          </div>
        </div>
      );
    };

    return (
      <div style={{
        margin: '4px 0 8px 0', borderRadius: GT.radiusSm,
        border: `1px solid ${GT.primary}40`, overflow: 'hidden',
      }}>
        {entries.map((entry, idx) => renderEntry(entry, idx))}
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

    // 检测是否为"多表多科目"模式：section 有多个表格且映射到不同的报表科目
    // 典型场景：现金流量表项目注释下的子节点，每个表格对应不同的现金流科目
    const perTableMode = (() => {
      if (!showAmountBar || sec.note_table_ids.length <= 1) return false;
      const itemIds = new Set<string>();
      for (const nid of sec.note_table_ids) {
        const mapped = noteToStmtMap.get(nid);
        if (mapped) itemIds.add(mapped.id);
      }
      // 如果映射到多个不同的报表科目，启用逐表模式
      return itemIds.size > 1;
    })();

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

          if (perTableMode) {
            // 逐表模式：每个表格独立查找报表科目并显示金额条
            const tableStmtItem = noteToStmtMap.get(id);
            if (tableStmtItem) {
              // 构造只含当前表格的虚拟 section 用于提取合计值
              const virtualSec: NoteSection = { ...sec, note_table_ids: [id], children: [] };
              return <React.Fragment key={id}>{tableEl}{renderStmtAmountBar(tableStmtItem, mode, virtualSec)}</React.Fragment>;
            }
            return tableEl;
          }

          // 单科目模式：只在第一个表格之后插入报表金额条
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

    // 如果是顶层科目节点但自身没有表格，把金额条下传给子节点
    const selfHasTables = sec.note_table_ids.length > 0;
    const needPassDown = isTopLevel && !selfHasTables;

    // 判断是否有多个子节点各自拥有表格且映射到不同的报表科目
    // （如现金流量表项目注释下的多个子类别，每个对应不同的现金流科目）
    const multiChildMode = (() => {
      if (!needPassDown) return false;
      const childStmtIds = new Set<string>();
      for (const c of sec.children) {
        for (const nid of c.note_table_ids) {
          const mapped = noteToStmtMap.get(nid);
          if (mapped) childStmtIds.add(mapped.id);
        }
        // 也检查孙节点
        for (const gc of c.children) {
          for (const nid of gc.note_table_ids) {
            const mapped = noteToStmtMap.get(nid);
            if (mapped) childStmtIds.add(mapped.id);
          }
        }
      }
      return childStmtIds.size > 1;
    })();

    // 单子节点模式：只传给第一个有表格的子节点（原有逻辑）
    const parentStmtItem = (needPassDown && !multiChildMode) ? findStmtForSection(sec) : null;
    const firstChildWithTable = (needPassDown && !multiChildMode)
      ? sec.children.findIndex(c => c.note_table_ids.length > 0)
      : -1;

    // 顶层科目节点：检测勾稽是否不一致，用于标题变色
    const headerWarn = (() => {
      if (!isTopLevel) return false;
      const TOL = 0.5;
      const si = findStmtForSection(sec);
      if (!si) return false;
      const stmtClosing = mode === 'parent' ? (si.company_closing_balance ?? si.closing_balance) : si.closing_balance;
      const stmtOpening = mode === 'parent' ? (si.company_opening_balance ?? si.opening_balance) : si.opening_balance;
      const noteTotals = extractNoteTotals(sec);
      if (stmtClosing != null && noteTotals.closing != null && Math.abs(stmtClosing - noteTotals.closing) > TOL) return true;
      if (stmtOpening != null && noteTotals.opening != null && Math.abs(stmtOpening - noteTotals.opening) > TOL) return true;
      return false;
    })();

    return (
      <div key={sec.id} style={{ marginBottom: 8 }}>
        {renderCollapseHeader(sec.id, sec.title, sec.level, hasContent, seqNo, headerWarn)}
        {!isCollapsed && hasContent && (
          <div style={{
            background: cBg, padding: '4px 14px',
            borderRadius: `0 0 ${GT.radiusSm}px ${GT.radiusSm}px`,
          }}>
            {renderSectionContent(sec, mode, isTopLevel && selfHasTables)}
            {sec.children.map((child, ci) => {
              if (needPassDown && !multiChildMode && ci === firstChildWithTable && parentStmtItem) {
                // 单子节点模式：传入父级找到的报表科目
                return renderSectionTreeWithStmt(child, seqNo ? `${seqNo}.${ci + 1}` : `${ci + 1}`, mode, parentStmtItem);
              }
              if (multiChildMode) {
                // 多子节点模式：每个子节点独立查找自己的报表科目并显示金额条
                return renderSectionTree(child, seqNo ? `${seqNo}.${ci + 1}` : `${ci + 1}`, mode, true);
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
    // 也收集全部 sections 的标题（防止某些科目被分到其他分组）
    sections.forEach(walk);

    // 同时收集附注表格的 account_name 和 section_title（补充匹配源）
    const noteNames: string[] = notes.map(n => n.account_name).concat(notes.map(n => n.section_title));

    // 构建 matching map 中已匹配的科目名称集合
    const matchedAcctNames = new Set<string>();
    if (matching) {
      const itemMap = new Map(statementItems.map(i => [i.id, i]));
      for (const entry of matching.entries) {
        if (entry.note_table_ids.length > 0) {
          const item = itemMap.get(entry.statement_item_id);
          if (item) matchedAcctNames.add(item.account_name);
        }
      }
    }

    const normalize = (s: string) => s.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');

    const coverage = parentPresetAccounts.map(acct => {
      const foundInSections = allTitles.some(t => {
        const nt = normalize(t);
        return (acct.keywords as string[]).some(kw => nt.includes(kw));
      });
      const foundInNotes = noteNames.some(n => {
        const nn = normalize(n || '');
        return (acct.keywords as string[]).some(kw => nn.includes(kw));
      });
      // 在 matching map 中查找（后端已匹配的科目）
      const foundInMatching = matchedAcctNames.has(acct.name);
      const found = foundInSections || foundInNotes || foundInMatching;
      const hasBalance = statementItems.some(item => {
        const itemNorm = normalize(item.account_name);
        const acctNorm = normalize(acct.name);
        return (itemNorm === acctNorm || itemNorm.includes(acctNorm) || acctNorm.includes(itemNorm))
          && ((item.closing_balance != null && item.closing_balance !== 0) || (item.opening_balance != null && item.opening_balance !== 0));
      });
      return { ...acct, found, hasBalance };
    });

    const foundCount = coverage.filter(c => c.found).length;
    const total = coverage.length;
    const allFound = foundCount === total;
    const realMissing = coverage.filter(c => !c.found && c.hasBalance).length;

    return (
      <div style={{
        margin: '0 0 12px 0', padding: '10px 14px',
        background: (allFound || realMissing === 0) ? GT.successBg : GT.warningBg,
        borderRadius: GT.radiusSm,
        border: `1px solid ${(allFound || realMissing === 0) ? GT.success : GT.warning}`,
        fontSize: 13,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 6, color: (allFound || realMissing === 0) ? GT.success : GT.warning }}>
          模板预设科目覆盖：{foundCount}/{total}
          {allFound ? ' ✓ 全部覆盖' : realMissing === 0 ? ' ✓ 有余额科目全部覆盖' : ` — ${realMissing} 个有余额科目缺失附注`}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 10px' }}>
          {coverage.map((c, i) => (
            <span key={i} style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              color: c.found ? GT.success : c.hasBalance ? GT.danger : GT.textMuted,
              fontWeight: c.found ? 400 : c.hasBalance ? 600 : 400,
            }}>
              <span style={{ fontSize: 11 }}>{c.found ? '✓' : c.hasBalance ? '✗' : '—'}</span>
              {c.name}
            </span>
          ))}
        </div>
      </div>
    );
  };

  // ─── 合并附注预设科目覆盖率面板 ───
  const renderConsolidatedCoveragePanel = (sec: NoteSection) => {
    if (consolidatedPresetAccounts.length === 0) return null;

    // 收集所有附注章节标题（递归，包括 mainSec 及所有子节点）
    const allTitles: string[] = [];
    const walk = (s: NoteSection) => {
      allTitles.push(s.title);
      s.children.forEach(walk);
    };
    sec.children.forEach(walk);
    allTitles.push(sec.title);
    // 也收集全部 sections 的标题（防止某些科目被分到其他分组）
    sections.forEach(walk);

    // 同时收集附注表格的 account_name 和 section_title（补充匹配源）
    const noteNames: string[] = notes.map(n => n.account_name).concat(notes.map(n => n.section_title));

    // 构建 matching map 中已匹配的科目名称集合
    const matchedAcctNames = new Set<string>();
    if (matching) {
      const itemMap = new Map(statementItems.map(i => [i.id, i]));
      for (const entry of matching.entries) {
        if (entry.note_table_ids.length > 0) {
          const item = itemMap.get(entry.statement_item_id);
          if (item) matchedAcctNames.add(item.account_name);
        }
      }
    }

    const normalize = (s: string) => s.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');

    const coverage = consolidatedPresetAccounts.map(acct => {
      // 在章节标题中查找
      const foundInSections = allTitles.some(t => {
        const nt = normalize(t);
        return (acct.keywords as string[]).some(kw => nt.includes(kw));
      });
      // 在附注表格名称中查找
      const foundInNotes = noteNames.some(n => {
        const nn = normalize(n || '');
        return (acct.keywords as string[]).some(kw => nn.includes(kw));
      });
      // 在 matching map 中查找（后端已匹配的科目）
      const foundInMatching = matchedAcctNames.has(acct.name);
      const found = foundInSections || foundInNotes || foundInMatching;
      // 检查该科目在报表中是否有余额（无余额时缺失附注是正常的）
      const hasBalance = statementItems.some(item => {
        const itemNorm = normalize(item.account_name);
        const acctNorm = normalize(acct.name);
        return (itemNorm === acctNorm || itemNorm.includes(acctNorm) || acctNorm.includes(itemNorm))
          && ((item.closing_balance != null && item.closing_balance !== 0) || (item.opening_balance != null && item.opening_balance !== 0));
      });
      return { ...acct, found, hasBalance };
    });

    const foundCount = coverage.filter(c => c.found).length;
    const total = coverage.length;
    const allFound = foundCount === total;
    // 真正缺失 = 未找到 且 有余额
    const realMissing = coverage.filter(c => !c.found && c.hasBalance).length;

    return (
      <div style={{
        margin: '0 0 12px 0', padding: '10px 14px',
        background: (allFound || realMissing === 0) ? GT.successBg : GT.warningBg,
        borderRadius: GT.radiusSm,
        border: `1px solid ${(allFound || realMissing === 0) ? GT.success : GT.warning}`,
        fontSize: 13,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 6, color: (allFound || realMissing === 0) ? GT.success : GT.warning }}>
          模板预设科目覆盖：{foundCount}/{total}
          {allFound ? ' ✓ 全部覆盖' : realMissing === 0 ? ' ✓ 有余额科目全部覆盖' : ` — ${realMissing} 个有余额科目缺失附注`}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 10px' }}>
          {coverage.map((c, i) => (
            <span key={i} style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              color: c.found ? GT.success : c.hasBalance ? GT.danger : GT.textMuted,
              fontWeight: c.found ? 400 : c.hasBalance ? 600 : 400,
            }}>
              <span style={{ fontSize: 11 }}>{c.found ? '✓' : c.hasBalance ? '✗' : '—'}</span>
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
    warnKeys?: Set<string>,
  ) => (
    <div style={{
      display: 'flex', gap: 2, flexWrap: 'wrap',
      borderBottom: `2px solid ${GT.border}`,
      marginBottom: size === 'lg' ? 18 : 14, paddingBottom: 0,
    }}>
      {tabs.map(tab => {
        const isActive = active === tab.key;
        const isWarn = warnKeys?.has(String(tab.key));
        const activeColor = isWarn ? GT.danger : GT.primary;
        return (
          <button key={tab.key} onClick={() => setActive(tab.key)}
            style={{
              padding: size === 'lg' ? '11px 28px' : '8px 18px',
              border: 'none',
              background: isActive ? (isWarn ? '#fdf0ef' : GT.primaryBg) : 'transparent',
              cursor: 'pointer',
              fontSize: size === 'lg' ? 15 : 13,
              fontWeight: isActive ? 700 : 500,
              borderRadius: '6px 6px 0 0',
              transition: 'all 0.15s',
              borderBottom: isActive
                ? `${size === 'lg' ? 3 : 2}px solid ${activeColor}`
                : `${size === 'lg' ? 3 : 2}px solid transparent`,
              color: isActive ? activeColor : isWarn ? GT.danger : GT.textMuted,
              marginBottom: -2,
              maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
            title={tab.label}>
            {tab.label}
            {isWarn && <span style={{ marginLeft: 4, fontSize: 10 }}>⚠</span>}
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
                'sm',
                tabMismatchKeys,
              )}
              {noteTabs[activeNoteTab]?.key === 'before' && renderSectionsPage(noteGroups.before)}
              {noteTabs[activeNoteTab]?.key === 'main' && noteGroups.mainSec && (
                <div>
                  {renderConsolidatedCoveragePanel(noteGroups.mainSec)}
                  {renderStatementNotes(noteGroups.mainSec, 'consolidated')}
                </div>
              )}
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
