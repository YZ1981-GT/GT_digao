/**
 * NotesSidebar - 笔记侧边栏组件
 *
 * 从右侧滑出，按日期分组展示笔记列表。
 * 默认展开最近 3 天，点击笔记标题预览内容，支持删除确认。
 * 支持单条/多选/整个日期文件夹的移动/复制操作。
 */
import React, { useEffect, useState, useCallback } from 'react';
import { chatApi } from '../services/api';
import type { NoteGroup, NoteItem } from '../types/chat';
import LibraryTargetSelector from './LibraryTargetSelector';
import '../styles/gt-design-tokens.css';

interface NotesSidebarProps {
  visible: boolean;
  onClose: () => void;
}

const NotesSidebar: React.FC<NotesSidebarProps> = ({ visible, onClose }) => {
  const [groups, setGroups] = useState<NoteGroup[]>([]);
  const [expandedDates, setExpandedDates] = useState<Set<string>>(new Set());
  const [previewNote, setPreviewNote] = useState<NoteItem | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // 移动/复制相关状态
  const [showTargetSelector, setShowTargetSelector] = useState(false);
  const [moveOrCopy, setMoveOrCopy] = useState<'move' | 'copy'>('move');
  const [pendingDocIds, setPendingDocIds] = useState<string[]>([]);
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [selectedNoteIds, setSelectedNoteIds] = useState<Set<string>>(new Set());

  const fetchNotes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await chatApi.getNotes();
      const data = res.data;
      const noteGroups: NoteGroup[] = (data?.groups || []).map((g: any) => ({
        date: g.date,
        notes: (g.notes || []).map((n: any) => ({
          id: n.id,
          title: n.title,
          createdAt: n.created_at || n.createdAt,
          size: n.size,
        })),
      }));
      setGroups(noteGroups);
      const recentDates = new Set(noteGroups.slice(0, 3).map((g) => g.date));
      setExpandedDates(recentDates);
    } catch {
      /* 静默失败 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (visible) fetchNotes();
  }, [visible, fetchNotes]);

  const toggleDate = useCallback((date: string) => {
    setExpandedDates((prev) => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date);
      else next.add(date);
      return next;
    });
  }, []);

  const handleDelete = useCallback(async (noteId: string) => {
    try {
      await chatApi.deleteNote(noteId);
      setGroups((prev) =>
        prev
          .map((g) => ({ ...g, notes: g.notes.filter((n) => n.id !== noteId) }))
          .filter((g) => g.notes.length > 0),
      );
      setDeleteConfirm(null);
      if (previewNote?.id === noteId) setPreviewNote(null);
    } catch {
      /* 静默失败 */
    }
  }, [previewNote]);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  // 发起移动/复制
  const startMoveOrCopy = (docIds: string[], action: 'move' | 'copy') => {
    setPendingDocIds(docIds);
    setMoveOrCopy(action);
    setShowTargetSelector(true);
  };

  // 整个日期文件夹移动/复制
  const startFolderMoveOrCopy = (group: NoteGroup, action: 'move' | 'copy') => {
    const ids = group.notes.map((n) => n.id);
    startMoveOrCopy(ids, action);
  };

  const handleTargetSelect = async (targetLibraryId: string, targetDateFolder?: string) => {
    if (pendingDocIds.length === 0) return;
    setShowTargetSelector(false);
    const apiCall = moveOrCopy === 'move' ? chatApi.moveDocuments : chatApi.copyDocuments;
    try {
      await apiCall({
        doc_ids: pendingDocIds,
        source_library_id: 'notes',
        target_library_id: targetLibraryId,
        target_date_folder: targetDateFolder,
      });
      const label = moveOrCopy === 'move' ? '移动' : '复制';
      setMessage({ type: 'success', text: `已${label} ${pendingDocIds.length} 个文档` });
      fetchNotes();
      setMultiSelectMode(false);
      setSelectedNoteIds(new Set());
    } catch (e: any) {
      setMessage({ type: 'error', text: `操作失败: ${e?.response?.data?.detail || e.message}` });
    }
    setPendingDocIds([]);
    setTimeout(() => setMessage(null), 3000);
  };

  const toggleNoteSelect = (noteId: string) => {
    setSelectedNoteIds((prev) => {
      const next = new Set(prev);
      if (next.has(noteId)) next.delete(noteId);
      else next.add(noteId);
      return next;
    });
  };

  if (!visible) return null;

  return (
    <div
      style={{
        position: 'fixed',
        right: 0,
        top: 0,
        bottom: 0,
        width: 300,
        backgroundColor: '#fff',
        boxShadow: '-2px 0 8px rgba(0,0,0,0.1)',
        zIndex: 10001,
        display: 'flex',
        flexDirection: 'column',
        animation: 'slideInRight 0.2s ease-out',
      }}
    >
      {/* 头部 */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid #e8e8e8',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 'var(--gt-font-base)', color: 'var(--gt-primary)' }}>
          📒 笔记库
        </span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button
            onClick={() => { setMultiSelectMode((p) => !p); setSelectedNoteIds(new Set()); }}
            style={{
              background: multiSelectMode ? '#f3f0f8' : 'none',
              border: multiSelectMode ? '1px solid var(--gt-primary)' : '1px solid transparent',
              borderRadius: 'var(--gt-radius-sm)',
              fontSize: 11,
              cursor: 'pointer',
              color: multiSelectMode ? 'var(--gt-primary)' : 'var(--gt-text-secondary)',
              padding: '2px 8px',
            }}
          >
            {multiSelectMode ? '✕ 取消' : '☑ 多选'}
          </button>
          <button
            onClick={onClose}
            aria-label="关闭笔记侧边栏"
            style={{
              background: 'none',
              border: 'none',
              fontSize: 18,
              cursor: 'pointer',
              color: 'var(--gt-text-secondary)',
              padding: '2px 6px',
            }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* 消息提示 */}
      {message && (
        <div style={{
          margin: '8px 12px 0',
          padding: '6px 10px',
          borderRadius: 'var(--gt-radius-sm)',
          fontSize: 12,
          backgroundColor: message.type === 'success' ? '#f0fdf4' : '#fef2f2',
          color: message.type === 'success' ? '#166534' : '#991b1b',
          border: `1px solid ${message.type === 'success' ? '#bbf7d0' : '#fecaca'}`,
        }}>
          {message.text}
        </div>
      )}

      {/* 多选批量操作栏 */}
      {multiSelectMode && (
        <div style={{
          padding: '8px 12px',
          borderBottom: '1px solid #e8e8e8',
          display: 'flex',
          gap: 6,
          alignItems: 'center',
          flexShrink: 0,
          backgroundColor: '#faf5ff',
        }}>
          <span style={{ fontSize: 11, color: '#666' }}>已选 {selectedNoteIds.size} 项</span>
          <div style={{ flex: 1 }} />
          <button
            disabled={selectedNoteIds.size === 0}
            onClick={() => startMoveOrCopy(Array.from(selectedNoteIds), 'move')}
            style={{
              fontSize: 11,
              padding: '2px 8px',
              border: 'none',
              borderRadius: 'var(--gt-radius-sm)',
              cursor: selectedNoteIds.size === 0 ? 'not-allowed' : 'pointer',
              backgroundColor: selectedNoteIds.size === 0 ? '#e5e7eb' : '#3b82f6',
              color: selectedNoteIds.size === 0 ? '#9ca3af' : '#fff',
            }}
          >
            📦 移动
          </button>
          <button
            disabled={selectedNoteIds.size === 0}
            onClick={() => startMoveOrCopy(Array.from(selectedNoteIds), 'copy')}
            style={{
              fontSize: 11,
              padding: '2px 8px',
              border: 'none',
              borderRadius: 'var(--gt-radius-sm)',
              cursor: selectedNoteIds.size === 0 ? 'not-allowed' : 'pointer',
              backgroundColor: selectedNoteIds.size === 0 ? '#e5e7eb' : '#16a34a',
              color: selectedNoteIds.size === 0 ? '#9ca3af' : '#fff',
            }}
          >
            📋 复制
          </button>
        </div>
      )}

      {/* 笔记列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
        {loading && (
          <div style={{ textAlign: 'center', padding: 20, color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
            加载中...
          </div>
        )}
        {!loading && groups.length === 0 && (
          <div style={{ textAlign: 'center', padding: 20, color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)' }}>
            暂无笔记
          </div>
        )}
        {groups.map((group) => {
          const isExpanded = expandedDates.has(group.date);
          return (
            <div key={group.date}>
              {/* 日期分组标题 */}
              <div
                style={{
                  padding: '6px 16px',
                  fontSize: 'var(--gt-font-xs)',
                  fontWeight: 600,
                  color: 'var(--gt-primary)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  userSelect: 'none',
                }}
              >
                <span
                  onClick={() => toggleDate(group.date)}
                  style={{ display: 'flex', alignItems: 'center', gap: 4, flex: 1 }}
                >
                  <span style={{ fontSize: 10, transition: 'transform 0.2s', transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>
                    ▶
                  </span>
                  {group.date}
                  <span style={{ color: 'var(--gt-text-secondary)', fontWeight: 400 }}>
                    ({group.notes.length})
                  </span>
                </span>
                {/* 日期文件夹操作按钮 */}
                <span style={{ display: 'flex', gap: 2, flexShrink: 0 }}>
                  <button
                    onClick={(e) => { e.stopPropagation(); startFolderMoveOrCopy(group, 'move'); }}
                    title={`移动整个 ${group.date} 文件夹`}
                    style={{
                      background: 'none',
                      border: 'none',
                      fontSize: 11,
                      cursor: 'pointer',
                      color: 'var(--gt-text-secondary)',
                      padding: '0 2px',
                      opacity: 0.5,
                      transition: 'opacity 0.15s',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.5'; }}
                  >
                    📦
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); startFolderMoveOrCopy(group, 'copy'); }}
                    title={`复制整个 ${group.date} 文件夹`}
                    style={{
                      background: 'none',
                      border: 'none',
                      fontSize: 11,
                      cursor: 'pointer',
                      color: 'var(--gt-text-secondary)',
                      padding: '0 2px',
                      opacity: 0.5,
                      transition: 'opacity 0.15s',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.5'; }}
                  >
                    📋
                  </button>
                </span>
              </div>
              {/* 笔记条目 */}
              {isExpanded && group.notes.map((note) => (
                <div
                  key={note.id}
                  style={{
                    padding: '6px 16px 6px 28px',
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 4,
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#f9f7fc'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
                >
                  {/* 多选 checkbox */}
                  {multiSelectMode && (
                    <input
                      type="checkbox"
                      checked={selectedNoteIds.has(note.id)}
                      onChange={() => toggleNoteSelect(note.id)}
                      onClick={(e) => e.stopPropagation()}
                      style={{ marginRight: 4, flexShrink: 0 }}
                    />
                  )}
                  <div
                    onClick={() => setPreviewNote(note)}
                    style={{ flex: 1, minWidth: 0 }}
                  >
                    <div style={{
                      fontSize: 'var(--gt-font-sm)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {note.title}
                    </div>
                    <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
                      {formatSize(note.size)}
                    </div>
                  </div>
                  {/* 操作按钮 */}
                  {!multiSelectMode && deleteConfirm === note.id ? (
                    <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                      <button
                        onClick={() => handleDelete(note.id)}
                        style={{
                          background: 'var(--gt-danger)',
                          color: '#fff',
                          border: 'none',
                          borderRadius: 'var(--gt-radius-sm)',
                          fontSize: 11,
                          padding: '1px 6px',
                          cursor: 'pointer',
                        }}
                      >
                        确认
                      </button>
                      <button
                        onClick={() => setDeleteConfirm(null)}
                        style={{
                          background: '#eee',
                          border: 'none',
                          borderRadius: 'var(--gt-radius-sm)',
                          fontSize: 11,
                          padding: '1px 6px',
                          cursor: 'pointer',
                        }}
                      >
                        取消
                      </button>
                    </div>
                  ) : !multiSelectMode && (
                    <div style={{ display: 'flex', gap: 2, flexShrink: 0 }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); startMoveOrCopy([note.id], 'move'); }}
                        title="移动到..."
                        style={{
                          background: 'none',
                          border: 'none',
                          fontSize: 12,
                          cursor: 'pointer',
                          color: 'var(--gt-text-secondary)',
                          padding: '0 2px',
                          opacity: 0.4,
                          transition: 'opacity 0.15s',
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.4'; }}
                      >
                        📦
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); startMoveOrCopy([note.id], 'copy'); }}
                        title="复制到..."
                        style={{
                          background: 'none',
                          border: 'none',
                          fontSize: 12,
                          cursor: 'pointer',
                          color: 'var(--gt-text-secondary)',
                          padding: '0 2px',
                          opacity: 0.4,
                          transition: 'opacity 0.15s',
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.4'; }}
                      >
                        📋
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeleteConfirm(note.id); }}
                        title="删除笔记"
                        style={{
                          background: 'none',
                          border: 'none',
                          fontSize: 12,
                          cursor: 'pointer',
                          color: 'var(--gt-text-secondary)',
                          padding: '0 2px',
                          opacity: 0.4,
                          transition: 'opacity 0.15s',
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.4'; }}
                      >
                        🗑️
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {/* 笔记预览 */}
      {previewNote && (
        <div
          style={{
            borderTop: '1px solid #e8e8e8',
            padding: 12,
            maxHeight: 200,
            overflowY: 'auto',
            flexShrink: 0,
            backgroundColor: '#fafafa',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 'var(--gt-font-sm)', color: 'var(--gt-primary)' }}>
              {previewNote.title}
            </span>
            <button
              onClick={() => setPreviewNote(null)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, color: 'var(--gt-text-secondary)' }}
            >
              ✕
            </button>
          </div>
          <div style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
            {previewNote.createdAt} · {formatSize(previewNote.size)}
          </div>
        </div>
      )}

      {/* 目标选择器弹窗 */}
      <LibraryTargetSelector
        visible={showTargetSelector}
        onClose={() => { setShowTargetSelector(false); setPendingDocIds([]); }}
        onSelect={handleTargetSelect}
        excludeLibraryId="notes"
      />

      {/* 滑入动画 */}
      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
      `}</style>
    </div>
  );
};

export default NotesSidebar;
