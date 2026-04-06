/**
 * LibraryTargetSelector - 目标知识库选择器弹窗
 *
 * 用于移动/复制文档时选择目标知识库分类。
 * 列出所有知识库分类，笔记库额外展示日期子文件夹。
 */
import React, { useEffect, useState } from 'react';
import { knowledgeApi, chatApi } from '../services/api';
import type { NoteGroup } from '../types/chat';
import '../styles/gt-design-tokens.css';

interface Library {
  id: string;
  name: string;
  desc: string;
  doc_count: number;
}

interface LibraryTargetSelectorProps {
  visible: boolean;
  onClose: () => void;
  onSelect: (targetLibraryId: string, targetDateFolder?: string) => void;
  excludeLibraryId?: string;
}

const LibraryTargetSelector: React.FC<LibraryTargetSelectorProps> = ({
  visible,
  onClose,
  onSelect,
  excludeLibraryId,
}) => {
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [noteDateFolders, setNoteDateFolders] = useState<string[]>([]);
  const [expandNotes, setExpandNotes] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setLoading(true);
    Promise.all([
      knowledgeApi.getLibraries().catch(() => ({ data: { libraries: [] } })),
      chatApi.getNotes().catch(() => ({ data: { groups: [] } })),
    ]).then(([libRes, notesRes]) => {
      const libs: Library[] = libRes.data?.libraries || [];
      setLibraries(libs);
      const groups: NoteGroup[] = (notesRes.data?.groups || []).map((g: any) => ({
        date: g.date,
        notes: g.notes || [],
      }));
      setNoteDateFolders(groups.map((g) => g.date));
    }).finally(() => setLoading(false));
  }, [visible]);

  if (!visible) return null;

  const filteredLibs = libraries.filter((lib) => lib.id !== excludeLibraryId);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.4)',
        zIndex: 10100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: '#fff',
          borderRadius: 'var(--gt-radius-lg, 12px)',
          width: 360,
          maxHeight: '70vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div
          style={{
            padding: '14px 18px',
            borderBottom: '1px solid #e8e8e8',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span style={{ fontWeight: 600, fontSize: 15, color: 'var(--gt-primary, #4b2d77)' }}>
            选择目标位置
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#999' }}
          >
            ✕
          </button>
        </div>

        {/* 列表 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 24, color: '#999', fontSize: 13 }}>加载中...</div>
          ) : (
            filteredLibs.map((lib) => {
              const isNotes = lib.id === 'notes';
              return (
                <div key={lib.id}>
                  <div
                    onClick={() => {
                      if (isNotes) {
                        setExpandNotes((p) => !p);
                      } else {
                        onSelect(lib.id);
                      }
                    }}
                    style={{
                      padding: '10px 18px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#f9f7fc'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
                  >
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 500 }}>{lib.name}</div>
                      <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                        {lib.desc} · {lib.doc_count} 个文档
                      </div>
                    </div>
                    {isNotes && (
                      <span style={{ fontSize: 10, color: '#999', transform: expandNotes ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>
                        ▶
                      </span>
                    )}
                  </div>
                  {/* 笔记库日期子文件夹 */}
                  {isNotes && expandNotes && (
                    <div style={{ paddingLeft: 32 }}>
                      {/* 直接放入笔记库根目录（今天） */}
                      <div
                        onClick={() => onSelect('notes')}
                        style={{
                          padding: '6px 12px',
                          fontSize: 13,
                          cursor: 'pointer',
                          color: 'var(--gt-primary, #4b2d77)',
                          transition: 'background 0.15s',
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#f3f0f8'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
                      >
                        📅 今天（默认）
                      </div>
                      {noteDateFolders.map((date) => (
                        <div
                          key={date}
                          onClick={() => onSelect('notes', date)}
                          style={{
                            padding: '6px 12px',
                            fontSize: 13,
                            cursor: 'pointer',
                            transition: 'background 0.15s',
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#f3f0f8'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
                        >
                          📁 {date}
                        </div>
                      ))}
                      {noteDateFolders.length === 0 && (
                        <div style={{ padding: '6px 12px', fontSize: 12, color: '#bbb' }}>暂无日期文件夹</div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

export default LibraryTargetSelector;
