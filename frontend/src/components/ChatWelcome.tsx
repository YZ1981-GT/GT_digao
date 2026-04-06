/**
 * ChatWelcome - 欢迎引导组件
 *
 * 空对话或新建对话时显示：
 * - 🤖 问候语
 * - 四大模块快捷入口卡片（2x2 网格）
 * - 使用提示文字
 */
import React, { useState } from 'react';

interface ChatWelcomeProps {
  onSelectMode: (mode: 'review' | 'generate' | 'analysis' | 'report_review') => void;
}

const MODULE_CARDS: Array<{
  icon: string;
  label: string;
  desc: string;
  mode: 'review' | 'generate' | 'analysis' | 'report_review';
}> = [
  { icon: '📋', label: '底稿复核', desc: '上传审计底稿，多维度智能复核', mode: 'review' },
  { icon: '📝', label: '文档生成', desc: '基于模板与知识库生成审计文档', mode: 'generate' },
  { icon: '🔍', label: '文档分析', desc: '上传文档进行总结分析和汇总', mode: 'analysis' },
  { icon: '📊', label: '审计报告复核', desc: '校验金额勾稽、正文规范性', mode: 'report_review' },
];

const ChatWelcome: React.FC<ChatWelcomeProps> = ({ onSelectMode }) => {
  const [hoveredMode, setHoveredMode] = useState<string | null>(null);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '0 var(--gt-space-4)',
        gap: 'var(--gt-space-4)',
      }}
    >
      {/* 问候语 */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 36, marginBottom: 'var(--gt-space-2)' }}>🤖</div>
        <div
          style={{
            fontSize: 'var(--gt-font-base)',
            fontWeight: 600,
            color: 'var(--gt-text-primary, #1a1a1a)',
          }}
        >
          你好！我是致同 AI 审计助手
        </div>
      </div>

      {/* 2x2 模块卡片网格 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 'var(--gt-space-2)',
          width: '100%',
        }}
      >
        {MODULE_CARDS.map((card) => {
          const isHovered = hoveredMode === card.mode;
          return (
            <div
              key={card.mode}
              onClick={() => onSelectMode(card.mode)}
              onMouseEnter={() => setHoveredMode(card.mode)}
              onMouseLeave={() => setHoveredMode(null)}
              style={{
                backgroundColor: '#fff',
                border: isHovered ? '1px solid var(--gt-primary)' : '1px solid #e8e8e8',
                borderRadius: 8,
                padding: 'var(--gt-space-3)',
                cursor: 'pointer',
                transition: 'border-color 0.2s, box-shadow 0.2s',
                boxShadow: isHovered ? '0 2px 8px rgba(75, 45, 119, 0.15)' : 'none',
              }}
            >
              <div style={{ fontSize: 20, marginBottom: 4 }}>{card.icon}</div>
              <div
                style={{
                  fontSize: 'var(--gt-font-sm)',
                  fontWeight: 600,
                  color: 'var(--gt-text-primary, #1a1a1a)',
                  marginBottom: 2,
                }}
              >
                {card.label}
              </div>
              <div
                style={{
                  fontSize: 'var(--gt-font-xs)',
                  color: 'var(--gt-text-secondary)',
                  lineHeight: 1.4,
                }}
              >
                {card.desc}
              </div>
            </div>
          );
        })}
      </div>

      {/* 使用提示 */}
      <div
        style={{
          fontSize: 'var(--gt-font-xs)',
          color: 'var(--gt-text-secondary)',
          textAlign: 'center',
          lineHeight: 1.6,
        }}
      >
        输入 / 快速跳转模块，输入 @ 引用知识库，点击 📎 上传文档
      </div>
    </div>
  );
};

export default ChatWelcome;
