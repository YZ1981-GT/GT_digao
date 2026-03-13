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
  NoteTable, NoteSection, MatchingMap,
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
const MAIN_NOTE_KW = ['财务报表主要项目', '主要项目注释', '报表项目注释', '报表主要项目', '合并财务报表项目'];
const PARENT_NOTE_KW = ['母公司财务报表', '公司财务报表主要项目附注', '母公司报表主要项目'];

function isMainNoteSection(title: string): boolean {
  const c = title.replace(/[\s（()）一二三四五六七八九十、.\d]/g, '');
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const noteMap = useMemo(() => new Map(notes.map(n => [n.id, n])), [notes]);

  // ─── 附注分组：前段 / 主项目注释 / 母公司 / 后段 ───
  const noteGroups = useMemo(() => {
    const before: NoteSection[] = [];
    let mainSec: NoteSection | null = null;
    let parentSec: NoteSection | null = null;
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
      } else {
        after.push(sec);
      }
    }
    return { before, mainSec, parentSec, after };
  }, [sections]);

  // 附注页签列表
  const noteTabs = useMemo(() => {
    const tabs: { key: string; label: string }[] = [];
    if (noteGroups.before.length > 0) tabs.push({ key: 'before', label: '会计政策及其他' });
    if (noteGroups.mainSec) tabs.push({ key: 'main', label: '财务报表主要项目注释' });
    if (noteGroups.parentSec) tabs.push({ key: 'parent', label: '母公司报表主要项目附注' });
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
    id: string, title: string, level: number, hasContent: boolean,
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
          borderLeft: `3px solid ${bc}`, borderRadius: GT.radiusSm,
          cursor: hasContent ? 'pointer' : 'default', userSelect: 'none',
          marginBottom: isCollapsed ? 8 : 0,
        }}>
        <span style={{ fontSize: level <= 2 ? 14 : 13, fontWeight: 600, color: tc }}>
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
    return (
      <div key={nt.id} style={{ marginBottom: 14 }}>
        {label && (
          <div style={{
            fontSize: 13, fontWeight: 600, color: tc, background: hBg,
            padding: '6px 12px', borderLeft: `3px solid ${tc}`,
            borderRadius: GT.radiusSm, marginBottom: 4,
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
                    <th key={i} style={{
                      padding: '8px 12px', fontWeight: 600,
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


  // ─── 渲染 section 内容（正文段落 + 表格） ───
  const renderSectionContent = (sec: NoteSection) => {
    const tableTitles = new Set(
      sec.note_table_ids.map(id => noteMap.get(id)?.section_title?.trim()).filter(Boolean) as string[]
    );
    tableTitles.add(sec.title.trim());
    const filteredParas = sec.content_paragraphs.filter(p => !tableTitles.has(p.trim()));
    const shownLabels = new Set<string>();

    return (
      <div style={{ padding: '8px 0' }}>
        {filteredParas.length > 0 && (
          <div style={{ marginBottom: 10, lineHeight: 1.9, fontSize: 14, color: GT.text }}>
            {filteredParas.map((p, i) => <p key={i} style={{ margin: '4px 0' }}>{p}</p>)}
          </div>
        )}
        {sec.note_table_ids.map(id => {
          const nt = noteMap.get(id);
          if (!nt) return null;
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

  // ─── 递归渲染 section（可折叠） ───
  const renderSectionTree = (sec: NoteSection): React.ReactNode => {
    const isCollapsed = collapsedIds.has(sec.id);
    const hasContent = sec.content_paragraphs.length > 0 || sec.note_table_ids.length > 0 || sec.children.length > 0;
    const cBg = lvlBodyBg(sec.level);

    return (
      <div key={sec.id} style={{ marginBottom: 8 }}>
        {renderCollapseHeader(sec.id, sec.title, sec.level, hasContent)}
        {!isCollapsed && hasContent && (
          <div style={{
            background: cBg, padding: '6px 14px',
            borderLeft: `3px solid ${lvlBorder(sec.level)}`,
            borderRadius: `0 0 ${GT.radiusSm}px ${GT.radiusSm}px`,
          }}>
            {renderSectionContent(sec)}
            {sec.children.map(child => renderSectionTree(child))}
          </div>
        )}
      </div>
    );
  };

  // ─── 渲染多个 section 合并页面（带全部展开/折叠） ───
  const renderSectionsPage = (secs: NoteSection[]) => (
    <div>
      {renderExpandCollapseBar(secs)}
      <div style={{ maxHeight: 'calc(100vh - 320px)', overflowY: 'auto', paddingRight: 4 }}>
        {secs.map(sec => renderSectionTree(sec))}
      </div>
    </div>
  );

  // ─── 渲染报表科目注释（财务报表主要项目注释 / 母公司） ───
  const renderStatementNotes = (sec: NoteSection) => {
    // 子节点就是各个科目
    const allSecs = sec.children.length > 0 ? sec.children : [sec];
    return (
      <div>
        {renderExpandCollapseBar(allSecs)}
        <div style={{ maxHeight: 'calc(100vh - 320px)', overflowY: 'auto', paddingRight: 4 }}>
          {/* section 自身的正文 */}
          {(sec.content_paragraphs.length > 0 || sec.note_table_ids.length > 0) && (
            <div style={{ marginBottom: 12 }}>{renderSectionContent(sec)}</div>
          )}
          {sec.children.map(child => renderSectionTree(child))}
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
    if (origHeaders.length === 0 && origData.length === 0) {
      return <div style={{ padding: 30, textAlign: 'center', color: GT.textMuted }}>该 Sheet 无数据</div>;
    }

    // 合并 headers 和 rawData 为统一行数组，从中找到真正的表头行
    const allRows: any[][] = [origHeaders.map(h => h), ...origData];

    // 表头行特征：第一个单元格包含"项目"/"项 目"
    const HEADER_KW = ['项目', '项 目'];
    let headerIdx = -1;
    for (let ri = 0; ri < Math.min(allRows.length, 10); ri++) {
      const firstCell = String(allRows[ri]?.[0] ?? '').replace(/\s+/g, '');
      if (HEADER_KW.some(kw => firstCell === kw.replace(/\s+/g, ''))) {
        headerIdx = ri;
        break;
      }
    }

    // 如果找到了表头行，用它作为 headers，后面的作为数据
    let headers: string[];
    let displayData: any[][];
    if (headerIdx >= 0) {
      headers = allRows[headerIdx].map((v: any) => v != null ? String(v) : '');
      displayData = allRows.slice(headerIdx + 1);
    } else {
      headers = origHeaders;
      displayData = origData;
    }

    // 截断到终止行（含终止行本身）或签章行（不含该行）
    for (let ri = 0; ri < displayData.length; ri++) {
      const firstCell = String(displayData[ri]?.[0] ?? '').replace(/\s+/g, '');
      if (SHEET_END_KW.some(kw => firstCell === kw.replace(/\s+/g, ''))) {
        displayData = displayData.slice(0, ri + 1);
        break;
      }
      // 任意单元格包含签章关键词 → 该行及以下全部截断
      const rowText = displayData[ri].map((c: any) => String(c ?? '')).join('');
      if (SHEET_CUT_KW.some(kw => rowText.includes(kw))) {
        displayData = displayData.slice(0, ri);
        break;
      }
    }
    // 过滤项目列（第一列）为空的行
    displayData = displayData.filter(row => {
      const first = String(row?.[0] ?? '').trim();
      return first.length > 0;
    });
    // 从末尾裁剪注释行和空行
    let endIdx = displayData.length;
    while (endIdx > 0) {
      const row = displayData[endIdx - 1];
      const firstCell = String(row?.[0] ?? '').trim();
      const allEmpty = row.every((c: any) => c == null || String(c).trim() === '');
      if (allEmpty || SHEET_SKIP_KW.some(kw => firstCell.startsWith(kw))) {
        endIdx--;
      } else {
        break;
      }
    }
    displayData = displayData.slice(0, endIdx);

    // ── 行类型检测 ──
    const TOTAL_KW = ['合计', '总计', '资产总计', '负债合计', '所有者权益合计',
      '非流动资产合计', '流动资产合计', '流动负债合计', '非流动负债合计',
      '负债和所有者权益总计', '负债及所有者权益总计', '负债和股东权益总计'];
    const SUBTOTAL_KW = ['小计'];
    const SUB_ITEM_PREFIX = ['其中：', '其中:', '其中'];
    const CATEGORY_KW = ['流动资产：', '流动资产:', '非流动资产：', '非流动资产:',
      '流动负债：', '流动负债:', '非流动负债：', '非流动负债:',
      '所有者权益：', '所有者权益:', '所有者权益（或股东权益）：'];

    type RowType = 'total' | 'subtotal' | 'sub_item' | 'category' | 'normal';
    const getRowType = (row: any[]): RowType => {
      const name = String(row?.[0] ?? '').replace(/\s+/g, '');
      if (TOTAL_KW.some(kw => name === kw.replace(/\s+/g, ''))) return 'total';
      if (SUBTOTAL_KW.some(kw => name.includes(kw))) return 'subtotal';
      const raw = String(row?.[0] ?? '').trim();
      if (SUB_ITEM_PREFIX.some(kw => raw.startsWith(kw))) return 'sub_item';
      if (CATEGORY_KW.some(kw => name === kw.replace(/\s+/g, ''))) return 'category';
      return 'normal';
    };

    const colCount = headers.length || (displayData[0]?.length ?? 0);

    return (
      <div style={{
        overflowX: 'auto', overflowY: 'auto',
        maxHeight: 'calc(100vh - 300px)',
        borderRadius: GT.radius, border: `1px solid ${GT.border}`, boxShadow: GT.shadow,
      }}>
        <table className="amt-table" style={{
          width: '100%', borderCollapse: 'collapse', fontSize: 13,
          tableLayout: 'fixed',
        }}>
          <caption className="sr-only">{sheet.sheet_name}</caption>
          <colgroup>
            {Array.from({ length: colCount }, (_, ci) => (
              <col key={ci} style={{
                width: ci === 0 ? '30%' : `${70 / Math.max(colCount - 1, 1)}%`,
                minWidth: ci === 0 ? 180 : 120,
              }} />
            ))}
          </colgroup>
          {headers.length > 0 && (
            <thead>
              <tr>
                {headers.map((h: string, i: number) => (
                  <th key={i} style={{
                    padding: '10px 14px', fontWeight: 700, color: GT.primary,
                    borderBottom: `2px solid ${GT.primary}`,
                    textAlign: i === 0 ? 'left' : 'right', whiteSpace: 'nowrap',
                    background: GT.primaryBgDeep,
                    position: 'sticky', top: 0, zIndex: 2,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {displayData.slice(0, 300).map((row: any[], ri: number) => {
              const rt = getRowType(row);
              const isTotal = rt === 'total';
              const isSubtotal = rt === 'subtotal';
              const isSub = rt === 'sub_item';
              const isCat = rt === 'category';
              const bg = isTotal ? GT.primaryBgDeep
                : isSubtotal ? '#f0edf6'
                : isCat ? '#f8f6fc'
                : ri % 2 === 0 ? GT.bgWhite : GT.bgPage;
              return (
                <tr key={ri} style={{ background: bg }}>
                  {row.map((c: any, ci: number) => {
                    const isFirst = ci === 0;
                    let cellText = isFirst ? (c != null ? String(c) : '') : fmtNum(c);
                    // 其中项缩进
                    const pl = isFirst
                      ? (isSub ? 32 : isCat ? 8 : 14)
                      : 14;
                    return (
                      <td key={ci} style={{
                        padding: `6px ${14}px 6px ${pl}px`,
                        borderBottom: `1px solid ${isTotal ? GT.primary + '30' : GT.borderLight}`,
                        textAlign: isFirst ? 'left' : 'right',
                        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                        fontVariantNumeric: !isFirst ? 'tabular-nums' : 'normal',
                        fontWeight: (isTotal || isSubtotal || isCat) ? 700 : 400,
                        color: isTotal ? GT.primary : isCat ? GT.primaryLight : GT.text,
                        fontSize: isTotal ? 13.5 : 13,
                        borderTop: isTotal ? `2px solid ${GT.primary}40` : undefined,
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
    <>
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
            color: '#fff', fontSize: 14, fontWeight: 600,
            boxShadow: loading ? 'none' : `0 2px 10px ${GT.primary}40`,
          }}>确认匹配</button>
      </div>
    </>
  );

  return (
    <div style={{ fontFamily: GT.font }}>
      {/* 一级页签 */}
      {renderTabBar(TOP_TABS, activeTopTab, setActiveTopTab, 'lg')}

      {/* ─── 审计报告正文 ─── */}
      {activeTopTab === 'audit_report' && (
        <div>
          {auditReportContent.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: GT.textMuted, fontSize: 14 }}>
              暂无审计报告正文数据，请上传审计报告文件
            </div>
          ) : (
            <div style={{
              maxHeight: 'calc(100vh - 280px)', overflowY: 'auto', paddingRight: 4,
            }}>
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
              {noteTabs[activeNoteTab]?.key === 'main' && noteGroups.mainSec && renderStatementNotes(noteGroups.mainSec)}
              {noteTabs[activeNoteTab]?.key === 'parent' && noteGroups.parentSec && renderStatementNotes(noteGroups.parentSec)}
              {noteTabs[activeNoteTab]?.key === 'after' && renderSectionsPage(noteGroups.after)}
            </>
          )}
        </div>
      )}

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
