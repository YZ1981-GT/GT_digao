/**
 * FindingDetailPanel - 问题详情面板
 * Task 16.2: 可编辑区域、分析过程、多轮对话、溯源分析、确认/忽略操作
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ReportReviewFinding, FindingConfirmationStatus, FindingConversationMessage, RiskLevel,
} from '../types/audit';
import { SSEParser } from '../utils/sseParser';

const API = process.env.REACT_APP_API_URL || (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

interface Props {
  findingId: string;
  finding: ReportReviewFinding | null;
  sessionId?: string | null;
  onStatusChange: (id: string, status: FindingConfirmationStatus) => void;
  onUpdate: () => void;
}

const FindingDetailPanel: React.FC<Props> = ({ findingId, finding, sessionId, onStatusChange, onUpdate }) => {
  const [messages, setMessages] = useState<FindingConversationMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editDesc, setEditDesc] = useState('');
  const [editSuggestion, setEditSuggestion] = useState('');
  const [editRisk, setEditRisk] = useState<RiskLevel>('medium');
  const [noteTables, setNoteTables] = useState<any[]>([]);
  const [showTable, setShowTable] = useState(true);
  const [showPageImage, setShowPageImage] = useState(true);
  const [pageImageUrl, setPageImageUrl] = useState<string | null>(null);
  const [pageImagesInfo, setPageImagesInfo] = useState<Record<string, { filename: string; pages: number[] }>>({});
  const msgEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!findingId) return;
    fetch(`${API}/api/report-review/finding/${findingId}/conversation`)
      .then(r => r.json())
      .then(data => setMessages(data.messages || []))
      .catch(() => {});
  }, [findingId]);

  useEffect(() => {
    if (finding) {
      setEditDesc(finding.description);
      setEditSuggestion(finding.suggestion);
      setEditRisk(finding.risk_level);
    }
  }, [finding]);

  // 加载关联的附注表格
  useEffect(() => {
    if (!sessionId || !finding) { setNoteTables([]); return; }

    const loadTables = async () => {
      try {
        let tables: any[] = [];

        // 优先使用 finding 上的 note_table_ids 直接查找（最精确）
        if (finding.note_table_ids && finding.note_table_ids.length > 0) {
          const ids = finding.note_table_ids.join(',');
          const url = `${API}/api/report-review/session/${sessionId}/note-tables?note_ids=${encodeURIComponent(ids)}`;
          const r = await fetch(url);
          const data = await r.json();
          tables = data.note_tables || [];
        }

        // 回退：用 account_name 查
        if (tables.length === 0) {
          let url = `${API}/api/report-review/session/${sessionId}/note-tables?account_name=${encodeURIComponent(finding.account_name)}`;
          let r = await fetch(url);
          let data = await r.json();
          tables = data.note_tables || [];

          // 如果没结果，尝试从 location 提取 section_title
          if (tables.length === 0 && finding.location) {
            const match = finding.location.match(/附注'([^']+)'/);
            if (match) {
              url = `${API}/api/report-review/session/${sessionId}/note-tables?account_name=${encodeURIComponent(match[1])}`;
              r = await fetch(url);
              data = await r.json();
              tables = data.note_tables || [];
            }
          }
        }

        setNoteTables(tables);
      } catch {
        setNoteTables([]);
      }
    };

    loadTables();
  }, [sessionId, findingId]);

  useEffect(() => { msgEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // 加载页面截图信息
  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API}/api/report-review/session/${sessionId}/page-images-info`)
      .then(r => r.json())
      .then(data => setPageImagesInfo(data.page_images || {}))
      .catch(() => {});
  }, [sessionId]);

  // 构建页面截图 URL
  useEffect(() => {
    if (!finding?.source_page || !sessionId) {
      setPageImageUrl(null);
      return;
    }
    // 查找包含该页码的 file_id
    const entries = Object.entries(pageImagesInfo);
    for (const [fileId, info] of entries) {
      if (info.pages.includes(finding.source_page)) {
        setPageImageUrl(`${API}/api/report-review/session/${sessionId}/page-image/${fileId}/${finding.source_page}`);
        return;
      }
    }
    // 如果只有一个文件，直接尝试
    if (entries.length > 0) {
      const [fileId] = entries[0];
      setPageImageUrl(`${API}/api/report-review/session/${sessionId}/page-image/${fileId}/${finding.source_page}`);
    } else {
      setPageImageUrl(null);
    }
  }, [finding, sessionId, pageImagesInfo]);

  const sendChat = useCallback(async () => {
    if (!chatInput.trim() || streaming) return;
    const userMsg: FindingConversationMessage = { id: Date.now().toString(), role: 'user', content: chatInput, message_type: 'chat', created_at: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);
    setChatInput('');
    setStreaming(true);
    try {
      const resp = await fetch(`${API}/api/report-review/finding/${findingId}/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: chatInput }),
      });
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      const parser = new SSEParser();
      let assistantContent = '';
      const assistantId = (Date.now() + 1).toString();
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          const dataLines = parser.feed(chunk);
          for (const data of dataLines) {
            if (data === '[DONE]') break;
            try {
              const parsed = JSON.parse(data);
              assistantContent += parsed.content || parsed.text || data;
            } catch {
              assistantContent += data;
            }
          }
          setMessages(prev => {
            const filtered = prev.filter(m => m.id !== assistantId);
            return [...filtered, { id: assistantId, role: 'assistant', content: assistantContent, message_type: 'chat', created_at: new Date().toISOString() }];
          });
        }
        // flush remaining
        const remaining = parser.flush();
        for (const data of remaining) {
          if (data === '[DONE]') break;
          try {
            const parsed = JSON.parse(data);
            assistantContent += parsed.content || parsed.text || data;
          } catch {
            assistantContent += data;
          }
        }
        if (remaining.length > 0) {
          setMessages(prev => {
            const filtered = prev.filter(m => m.id !== assistantId);
            return [...filtered, { id: assistantId, role: 'assistant', content: assistantContent, message_type: 'chat', created_at: new Date().toISOString() }];
          });
        }
      }
    } catch { /* ignore */ }
    setStreaming(false);
  }, [chatInput, findingId, streaming]);

  const sendTrace = useCallback(async (traceType: 'cross_reference' | 'template_compare' | 'data_drill_down') => {
    if (streaming) return;
    setStreaming(true);
    try {
      const resp = await fetch(`${API}/api/report-review/finding/${findingId}/trace`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trace_type: traceType }),
      });
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      const parser = new SSEParser();
      let content = '';
      const traceId = (Date.now() + 2).toString();
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          const dataLines = parser.feed(chunk);
          for (const data of dataLines) {
            if (data === '[DONE]') break;
            try {
              const parsed = JSON.parse(data);
              content += parsed.content || parsed.text || data;
            } catch {
              content += data;
            }
          }
          setMessages(prev => {
            const filtered = prev.filter(m => m.id !== traceId);
            return [...filtered, { id: traceId, role: 'assistant', content, message_type: 'trace', trace_type: traceType, created_at: new Date().toISOString() }];
          });
        }
        const remaining = parser.flush();
        for (const data of remaining) {
          if (data === '[DONE]') break;
          try {
            const parsed = JSON.parse(data);
            content += parsed.content || parsed.text || data;
          } catch {
            content += data;
          }
        }
        if (remaining.length > 0) {
          setMessages(prev => {
            const filtered = prev.filter(m => m.id !== traceId);
            return [...filtered, { id: traceId, role: 'assistant', content, message_type: 'trace', trace_type: traceType, created_at: new Date().toISOString() }];
          });
        }
      }
    } catch { /* ignore */ }
    setStreaming(false);
  }, [findingId, streaming]);

  const saveEdit = async () => {
    await fetch(`${API}/api/report-review/finding/${findingId}/edit`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: editDesc, suggestion: editSuggestion, risk_level: editRisk }),
    });
    setEditMode(false);
    onUpdate();
  };

  if (!finding) return null;

  return (
    <div className="gt-card" style={{ padding: 'var(--gt-space-3)', display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header with actions */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--gt-space-3)' }}>
        <span style={{ fontWeight: 600, fontSize: 15 }}>{finding.account_name}</span>
        <div style={{ display: 'flex', gap: 6 }}>
          {finding.confirmation_status === 'pending_confirmation' && (
            <>
              <button onClick={() => onStatusChange(findingId, 'confirmed')} style={{ fontSize: 12, padding: '3px 10px', backgroundColor: 'var(--gt-success, green)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>确认</button>
              <button onClick={() => onStatusChange(findingId, 'dismissed')} style={{ fontSize: 12, padding: '3px 10px', backgroundColor: '#999', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>忽略</button>
            </>
          )}
          <button onClick={() => setEditMode(!editMode)} style={{ fontSize: 12, padding: '3px 10px', border: '1px solid #ddd', borderRadius: 4, cursor: 'pointer', background: '#fff' }}>
            {editMode ? '取消编辑' : '编辑'}
          </button>
        </div>
      </div>

      {/* Editable fields or display */}
      {editMode ? (
        <div style={{ marginBottom: 'var(--gt-space-3)' }}>
          <label style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>问题描述</label>
          <textarea value={editDesc} onChange={e => setEditDesc(e.target.value)} rows={3} style={{ width: '100%', fontSize: 13, padding: 6, border: '1px solid #ddd', borderRadius: 4 }} />
          <label style={{ fontSize: 12, display: 'block', marginBottom: 4, marginTop: 8 }}>建议</label>
          <textarea value={editSuggestion} onChange={e => setEditSuggestion(e.target.value)} rows={2} style={{ width: '100%', fontSize: 13, padding: 6, border: '1px solid #ddd', borderRadius: 4 }} />
          <label style={{ fontSize: 12, display: 'block', marginBottom: 4, marginTop: 8 }}>风险等级</label>
          <select value={editRisk} onChange={e => setEditRisk(e.target.value as RiskLevel)} style={{ fontSize: 13, padding: 4 }}>
            <option value="high">高</option><option value="medium">中</option><option value="low">低</option>
          </select>
          <button onClick={saveEdit} style={{ marginTop: 8, fontSize: 12, padding: '4px 16px', backgroundColor: 'var(--gt-primary)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>保存</button>
        </div>
      ) : (
        <div style={{ marginBottom: 'var(--gt-space-3)', fontSize: 13 }}>
          <p><span style={{ color: '#888' }}>描述：</span>{finding.description}</p>
          {finding.location && (
            <p style={{ marginTop: 4 }}><span style={{ color: '#888' }}>位置：</span><span style={{ backgroundColor: '#fff8e1', padding: '1px 4px', borderRadius: 3 }}>{finding.location}</span></p>
          )}
          <p><span style={{ color: '#888' }}>建议：</span>{finding.suggestion}</p>
          {finding.analysis_reasoning && (
            <div style={{ marginTop: 8, padding: 8, backgroundColor: '#f8f8f8', borderRadius: 4, fontSize: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>分析过程</div>
              <p style={{ whiteSpace: 'pre-wrap' }}>{finding.analysis_reasoning}</p>
            </div>
          )}
          {finding.template_reference && (
            <div style={{ marginTop: 8, padding: 8, backgroundColor: '#f0f0ff', borderRadius: 4, fontSize: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>模板参考</div>
              <p>{finding.template_reference}</p>
            </div>
          )}
          {finding.difference != null && (
            <p style={{ fontSize: 12, color: '#888' }}>
              报表: {finding.statement_amount?.toLocaleString()} | 附注: {finding.note_amount?.toLocaleString()} | 差异: {finding.difference?.toFixed(2)}
            </p>
          )}
        </div>
      )}

      {/* 源文档页面预览 */}
      {pageImageUrl && (
        <div style={{ marginBottom: 'var(--gt-space-3)' }}>
          <div
            onClick={() => setShowPageImage(!showPageImage)}
            style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: 'var(--gt-primary)', marginBottom: 6 }}
            role="button" tabIndex={0}
          >
            <span style={{ fontSize: 10 }}>{showPageImage ? '▼' : '▶'}</span>
            📄 源文档预览{finding?.source_page ? `（第${finding.source_page}页）` : ''}
          </div>
          {showPageImage && (
            <div style={{ border: '1px solid #e0d8ec', borderRadius: 6, overflow: 'hidden', backgroundColor: '#f9f9f9' }}>
              {finding?.source_file && (
                <div style={{ padding: '4px 8px', backgroundColor: '#f5f0fa', fontSize: 11, color: '#888' }}>
                  文件：{finding.source_file}
                </div>
              )}
              <img
                src={pageImageUrl}
                alt={`源文档第${finding?.source_page || ''}页`}
                style={{ width: '100%', display: 'block' }}
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
              />
            </div>
          )}
        </div>
      )}

      {/* 关联附注表格预览 */}
      {noteTables.length > 0 ? (
        <div style={{ marginBottom: 'var(--gt-space-3)' }}>
          <div
            onClick={() => setShowTable(!showTable)}
            style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: 'var(--gt-primary)', marginBottom: 6 }}
            role="button" tabIndex={0}
          >
            <span style={{ fontSize: 10 }}>{showTable ? '▼' : '▶'}</span>
            原始附注表格（{noteTables.length} 个）
          </div>
          {showTable && noteTables.map((table: any) => (
            <div key={table.id} style={{ marginBottom: 10, border: '1px solid #e0d8ec', borderRadius: 6, overflow: 'hidden' }}>
              <div style={{ padding: '4px 8px', backgroundColor: '#f5f0fa', fontSize: 12, fontWeight: 600, color: '#555' }}>
                {table.section_title}
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  {table.headers && table.headers.length > 0 && (
                    <thead>
                      <tr>
                        {table.headers.map((h: string, i: number) => (
                          <th key={i} style={{
                            padding: '4px 8px', borderBottom: '2px solid #d0c4e0', backgroundColor: '#f9f6fd',
                            textAlign: i === 0 ? 'left' : 'right', whiteSpace: 'nowrap', fontSize: 11, color: '#666',
                          }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                  )}
                  <tbody>
                    {(table.rows || []).map((row: any[], ri: number) => {
                      const label = String(row[0] || '').trim();
                      const isTotal = /合计|总计/.test(label);
                      // 高亮差异行：如果 finding 有 highlight_cells，精确定位单元格
                      const highlightCells = finding?.highlight_cells;
                      const hasHighlightCells = highlightCells && highlightCells.length > 0;
                      // 行级高亮：该行有任何高亮单元格
                      const rowHasHighlight = hasHighlightCells && highlightCells!.some((c: any) => c.row === ri);
                      // 兜底：无 highlight_cells 时沿用旧逻辑
                      let legacyHighlight = false;
                      if (!hasHighlightCells && isTotal && finding?.difference != null && finding.difference !== 0) {
                        legacyHighlight = true;
                      }
                      const rowHighlight = rowHasHighlight || legacyHighlight;
                      return (
                        <tr key={ri} style={{
                          backgroundColor: rowHighlight ? '#fff8e1' : isTotal ? '#f9f6fd' : ri % 2 === 0 ? '#fff' : '#fafafa',
                        }}>
                          {row.map((cell: any, ci: number) => {
                            const isCellHighlighted = hasHighlightCells && highlightCells!.some((c: any) => c.row === ri && c.col === ci);
                            return (
                              <td key={ci} style={{
                                padding: '3px 8px', borderBottom: '1px solid #eee',
                                textAlign: ci === 0 ? 'left' : 'right',
                                fontWeight: isTotal ? 600 : 400,
                                color: isCellHighlighted ? '#c62828' : legacyHighlight && ci > 0 ? '#dc3545' : '#333',
                                backgroundColor: isCellHighlighted ? '#ffecb3' : undefined,
                                whiteSpace: 'nowrap',
                              }}>
                                {cell != null ? String(cell) : ''}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      ) : sessionId ? (
        <div style={{ marginBottom: 'var(--gt-space-3)', padding: 8, fontSize: 12, color: '#999', backgroundColor: '#f8f8f8', borderRadius: 4 }}>
          未找到关联的附注表格
        </div>
      ) : null}

      {/* Trace buttons */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 'var(--gt-space-3)' }}>
        <button onClick={() => sendTrace('cross_reference')} disabled={streaming} style={{ fontSize: 11, padding: '3px 8px', border: '1px solid var(--gt-primary)', borderRadius: 4, cursor: 'pointer', background: '#fff', color: 'var(--gt-primary)' }}>交叉引用</button>
        <button onClick={() => sendTrace('template_compare')} disabled={streaming} style={{ fontSize: 11, padding: '3px 8px', border: '1px solid var(--gt-primary)', borderRadius: 4, cursor: 'pointer', background: '#fff', color: 'var(--gt-primary)' }}>模板比对</button>
        <button onClick={() => sendTrace('data_drill_down')} disabled={streaming} style={{ fontSize: 11, padding: '3px 8px', border: '1px solid var(--gt-primary)', borderRadius: 4, cursor: 'pointer', background: '#fff', color: 'var(--gt-primary)' }}>数据下钻</button>
      </div>

      {/* Conversation */}
      <div style={{ flex: 1, overflowY: 'auto', borderTop: '1px solid #eee', paddingTop: 8 }}>
        {messages.map(m => (
          <div key={m.id} style={{ marginBottom: 8, textAlign: m.role === 'user' ? 'right' : 'left' }}>
            <div style={{
              display: 'inline-block', maxWidth: '85%', padding: '6px 10px', borderRadius: 8, fontSize: 13,
              backgroundColor: m.role === 'user' ? 'var(--gt-primary)' : '#f0f0f0',
              color: m.role === 'user' ? '#fff' : '#333',
            }}>
              {m.message_type === 'trace' && <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 2 }}>溯源分析 - {m.trace_type}</div>}
              <span style={{ whiteSpace: 'pre-wrap' }}>{m.content}</span>
            </div>
          </div>
        ))}
        <div ref={msgEndRef} />
      </div>

      {/* Chat input */}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input
          value={chatInput}
          onChange={e => setChatInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && sendChat()}
          placeholder="输入追问..."
          style={{ flex: 1, padding: '6px 10px', border: '1px solid #ddd', borderRadius: 4, fontSize: 13 }}
          aria-label="追问输入"
        />
        <button onClick={sendChat} disabled={streaming || !chatInput.trim()} style={{ padding: '6px 14px', backgroundColor: 'var(--gt-primary)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 13 }}>
          {streaming ? '...' : '发送'}
        </button>
      </div>
    </div>
  );
};

export default FindingDetailPanel;
