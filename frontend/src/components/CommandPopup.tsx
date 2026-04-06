/**
 * CommandPopup - 快捷指令候选列表弹窗
 *
 * 当用户在 ChatInput 中输入 / 时弹出，显示 QUICK_COMMANDS 列表。
 * 支持模糊过滤（command 或 label）、键盘上下导航、Enter 选择、Escape 关闭。
 *
 * 通过 forwardRef + useImperativeHandle 暴露 handleKeyDown 方法给 ChatInput 调用。
 */
import React, { useState, useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { QUICK_COMMANDS } from '../types/chat';
import type { QuickCommand } from '../types/chat';

export interface CommandPopupHandle {
  /** 返回 true 表示按键已被弹窗消费 */
  handleKeyDown: (e: React.KeyboardEvent) => boolean;
}

interface CommandPopupProps {
  filter: string;
  onSelect: (command: QuickCommand) => void;
  onClose: () => void;
  visible: boolean;
}

const CommandPopup = forwardRef<CommandPopupHandle, CommandPopupProps>(
  ({ filter, onSelect, onClose, visible }, ref) => {
    const [activeIndex, setActiveIndex] = useState(0);
    const listRef = useRef<HTMLDivElement>(null);

    /* ─── 模糊过滤：匹配 command 或 label ─── */
    const filtered = QUICK_COMMANDS.filter((cmd) => {
      const lowerFilter = filter.toLowerCase();
      return (
        cmd.command.toLowerCase().includes(lowerFilter) ||
        cmd.label.toLowerCase().includes(lowerFilter)
      );
    });

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
        aria-label="快捷指令列表"
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
        {filtered.map((cmd, idx) => (
          <div
            key={cmd.command}
            role="option"
            aria-selected={idx === activeIndex}
            onClick={() => onSelect(cmd)}
            onMouseEnter={() => setActiveIndex(idx)}
            style={{
              padding: '8px 12px',
              cursor: 'pointer',
              fontSize: 'var(--gt-font-sm)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              backgroundColor:
                idx === activeIndex ? 'var(--gt-primary)' : 'transparent',
              color: idx === activeIndex ? '#fff' : 'var(--gt-text-primary)',
              transition: 'background-color 0.1s',
            }}
          >
            <span style={{ fontSize: 16 }}>{cmd.icon}</span>
            <span style={{ fontWeight: 500 }}>{cmd.label}</span>
            <span
              style={{
                marginLeft: 'auto',
                opacity: 0.6,
                fontSize: 'var(--gt-font-xs)',
              }}
            >
              {cmd.command}
            </span>
          </div>
        ))}
      </div>
    );
  },
);

CommandPopup.displayName = 'CommandPopup';

export default CommandPopup;
