/**
 * KnowledgePopup - 知识库候选列表弹窗
 *
 * 当用户在 ChatInput 中输入 @ 时弹出，显示知识库分类列表。
 * 支持模糊过滤、键盘上下导航（ArrowUp/ArrowDown）、Enter 选择、Escape 关闭。
 * 从 /api/knowledge/libraries 获取分类列表。
 *
 * 通过 forwardRef + useImperativeHandle 暴露 handleKeyDown 方法给 ChatInput 调用。
 */
import React, { useState, useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { knowledgeApi } from '../services/api';

export interface KnowledgeLibrary {
  id: string;
  name: string;
}

export interface KnowledgePopupHandle {
  /** 返回 true 表示按键已被弹窗消费 */
  handleKeyDown: (e: React.KeyboardEvent) => boolean;
}

interface KnowledgePopupProps {
  filter: string;
  onSelect: (library: KnowledgeLibrary) => void;
  onClose: () => void;
  visible: boolean;
}

const KnowledgePopup = forwardRef<KnowledgePopupHandle, KnowledgePopupProps>(
  ({ filter, onSelect, onClose, visible }, ref) => {
    const [libraries, setLibraries] = useState<KnowledgeLibrary[]>([]);
    const [activeIndex, setActiveIndex] = useState(0);
    const listRef = useRef<HTMLDivElement>(null);

    /* ─── 获取知识库列表（弹窗可见时加载一次） ─── */
    useEffect(() => {
      if (!visible) return;
      knowledgeApi
        .getLibraries()
        .then((res) => {
          const libs: KnowledgeLibrary[] = (res.data?.libraries || []).map(
            (lib: { id: string; name: string }) => ({ id: lib.id, name: lib.name }),
          );
          setLibraries(libs);
        })
        .catch(() => setLibraries([]));
    }, [visible]);

    /* ─── 模糊过滤 ─── */
    const filtered = libraries.filter((lib) =>
      lib.name.toLowerCase().includes(filter.toLowerCase()),
    );

    /* ─── activeIndex 越界修正 ─── */
    useEffect(() => {
      if (activeIndex >= filtered.length) {
        setActiveIndex(Math.max(0, filtered.length - 1));
      }
    }, [filtered.length, activeIndex]);

    /* ─── filter 变化时重置 activeIndex ─── */
    useEffect(() => {
      setActiveIndex(0);
    }, [filter]);

    /* ─── 滚动选中项到可见区域 ─── */
    useEffect(() => {
      const container = listRef.current;
      if (!container) return;
      const activeEl = container.children[activeIndex] as HTMLElement | undefined;
      activeEl?.scrollIntoView({ block: 'nearest' });
    }, [activeIndex]);

    /* ─── 暴露键盘处理方法给父组件 ─── */
    useImperativeHandle(ref, () => ({
      handleKeyDown(e: React.KeyboardEvent): boolean {
        if (!visible || filtered.length === 0) return false;

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setActiveIndex((prev) => (prev + 1) % filtered.length);
          return true;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setActiveIndex((prev) => (prev - 1 + filtered.length) % filtered.length);
          return true;
        }
        if (e.key === 'Enter') {
          e.preventDefault();
          if (filtered[activeIndex]) {
            onSelect(filtered[activeIndex]);
          }
          return true;
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          onClose();
          return true;
        }
        return false;
      },
    }), [visible, filtered, activeIndex, onSelect, onClose]);

    if (!visible || filtered.length === 0) return null;

    return (
      <div
        role="listbox"
        aria-label="知识库列表"
        ref={listRef}
        style={{
          position: 'absolute',
          bottom: '100%',
          left: 0,
          right: 0,
          marginBottom: 4,
          backgroundColor: '#fff',
          border: '1px solid #e8e8e8',
          borderRadius: 'var(--gt-radius-md)',
          boxShadow: 'var(--gt-shadow-md)',
          maxHeight: 200,
          overflowY: 'auto',
          zIndex: 100,
        }}
      >
        {filtered.map((lib, idx) => (
          <div
            key={lib.id}
            role="option"
            aria-selected={idx === activeIndex}
            onClick={() => onSelect(lib)}
            onMouseEnter={() => setActiveIndex(idx)}
            style={{
              padding: '8px 12px',
              cursor: 'pointer',
              fontSize: 'var(--gt-font-sm)',
              backgroundColor:
                idx === activeIndex ? 'var(--gt-primary)' : 'transparent',
              color: idx === activeIndex ? '#fff' : 'var(--gt-text-primary)',
              transition: 'background-color 0.1s',
            }}
          >
            📚 {lib.name}
          </div>
        ))}
      </div>
    );
  },
);

KnowledgePopup.displayName = 'KnowledgePopup';

export default KnowledgePopup;
