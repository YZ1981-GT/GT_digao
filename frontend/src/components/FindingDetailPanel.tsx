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
  onStatusChange: (id: string, status: FindingConfirmationStatus) => void;
  onUpdate: () => void;
}

const FindingDetailPanel: React.FC<Props> = ({ findingId, finding, onStatusChange, onUpdate }) => {
  const [messages, setMessages] = useState<FindingConversationMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editDesc, setEditDesc] = useState('');
  const [editSuggestion, setEditSuggestion] = useState('');
  const [editRisk, setEditRisk] = useState<RiskLevel>('medium');
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

  useEffect(() => { msgEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

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
              报表: {finding.statement_amount?.toLocaleString()} | 附注: {finding.note_amount?.toLocaleString()} | 差异: {finding.difference?.toLocaleString()}
            </p>
          )}
        </div>
      )}

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
