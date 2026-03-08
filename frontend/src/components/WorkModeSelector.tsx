/**
 * WorkModeSelector - 工作模式选择组件
 *
 * 系统首页入口，展示"底稿复核"和"文档生成"两个工作模式卡片。
 * 使用 GT Design System 组件样式。
 */
import React from 'react';
import '../styles/gt-design-tokens.css';

interface WorkModeSelectorProps {
  onSelectMode: (mode: 'review' | 'generate') => void;
}

const WorkModeSelector: React.FC<WorkModeSelectorProps> = ({ onSelectMode }) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 顶部 banner */}
      <div
        style={{
          background: 'linear-gradient(135deg, var(--gt-primary) 0%, var(--gt-primary-dark, #2B1D4D) 100%)',
          padding: 'var(--gt-space-5) var(--gt-space-6)',
          color: '#fff',
        }}
      >
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>
          审计底稿智能复核与文档生成
        </h1>
        <p style={{ fontSize: 13, opacity: 0.8, marginTop: 6, marginBottom: 0 }}>
          面向审计项目组的智能复核与文档生成平台
        </p>
      </div>

      {/* 主内容区 */}
      <div style={{ flex: 1, padding: 'var(--gt-space-5)', overflowY: 'auto' }}>
        {/* 工作模式选择 */}
        <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', marginBottom: 'var(--gt-space-3)' }}>
          请选择工作模式
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--gt-space-4)', marginBottom: 'var(--gt-space-5)' }}>
          {/* 底稿复核卡片 */}
          <div
            onClick={() => onSelectMode('review')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter') onSelectMode('review'); }}
            style={{
              border: '2px solid #e8e8e8',
              borderRadius: 'var(--gt-radius-md, 8px)',
              padding: 'var(--gt-space-4)',
              cursor: 'pointer',
              transition: 'all 0.2s',
              backgroundColor: '#fff',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--gt-primary)'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(75,45,119,0.12)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.boxShadow = 'none'; }}
          >
            <div style={{ fontSize: 24, marginBottom: 6 }}>📋</div>
            <h3 style={{ fontSize: 'var(--gt-font-base)', fontWeight: 600, color: 'var(--gt-primary)', margin: '0 0 6px 0' }}>
              底稿复核
            </h3>
            <p style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', lineHeight: 1.5, margin: 0 }}>
              上传审计底稿，从格式规范性、数据勾稽关系、会计准则合规性等多维度进行智能复核
            </p>
            <div style={{ marginTop: 10 }}>
              <span
                style={{
                  display: 'inline-block',
                  padding: '4px 12px',
                  borderRadius: 'var(--gt-radius-sm)',
                  fontSize: 'var(--gt-font-xs)',
                  fontWeight: 600,
                  color: '#fff',
                  backgroundColor: 'var(--gt-primary)',
                }}
              >
                进入复核 →
              </span>
            </div>
          </div>

          {/* 文档生成卡片 */}
          <div
            onClick={() => onSelectMode('generate')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter') onSelectMode('generate'); }}
            style={{
              border: '2px solid #e8e8e8',
              borderRadius: 'var(--gt-radius-md, 8px)',
              padding: 'var(--gt-space-4)',
              cursor: 'pointer',
              transition: 'all 0.2s',
              backgroundColor: '#fff',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--gt-primary)'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(75,45,119,0.12)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.boxShadow = 'none'; }}
          >
            <div style={{ fontSize: 24, marginBottom: 6 }}>📝</div>
            <h3 style={{ fontSize: 'var(--gt-font-base)', fontWeight: 600, color: 'var(--gt-primary)', margin: '0 0 6px 0' }}>
              文档生成
            </h3>
            <p style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', lineHeight: 1.5, margin: 0 }}>
              基于模板与知识库，智能生成审计计划、审计小结、尽调报告等标准化审计文档
            </p>
            <div style={{ marginTop: 10 }}>
              <span
                style={{
                  display: 'inline-block',
                  padding: '4px 12px',
                  borderRadius: 'var(--gt-radius-sm)',
                  fontSize: 'var(--gt-font-xs)',
                  fontWeight: 600,
                  color: '#fff',
                  backgroundColor: 'var(--gt-primary)',
                }}
              >
                进入生成 →
              </span>
            </div>
          </div>
        </div>

        {/* 快速指引 */}
        <div style={{ borderTop: '1px solid #e8e8e8', paddingTop: 'var(--gt-space-3)' }}>
          <h3 style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-3)' }}>
            快速开始
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--gt-space-3)' }}>
            <div style={{ padding: 'var(--gt-space-2)', backgroundColor: '#f9f7fc', borderRadius: 'var(--gt-radius-sm)', fontSize: 'var(--gt-font-xs)' }}>
              <div style={{ fontWeight: 600, color: 'var(--gt-primary)', marginBottom: 3 }}>底稿复核流程</div>
              <div style={{ color: 'var(--gt-text-secondary)', lineHeight: 1.5 }}>
                1. 上传底稿文件（Excel/Word/PDF）<br />
                2. 选择提示词与复核维度<br />
                3. 上传补充材料并确认<br />
                4. 查看复核报告并导出
              </div>
            </div>
            <div style={{ padding: 'var(--gt-space-2)', backgroundColor: '#f9f7fc', borderRadius: 'var(--gt-radius-sm)', fontSize: 'var(--gt-font-xs)' }}>
              <div style={{ fontWeight: 600, color: 'var(--gt-primary)', marginBottom: 3 }}>文档生成流程</div>
              <div style={{ color: 'var(--gt-text-secondary)', lineHeight: 1.5 }}>
                1. 上传模板并关联知识库<br />
                2. 确认章节大纲结构<br />
                3. 逐章节生成与编辑<br />
                4. 导出 Word 文档
              </div>
            </div>
          </div>
        </div>

        {/* 支持格式 */}
        <div style={{ marginTop: 'var(--gt-space-3)', padding: 'var(--gt-space-3)', backgroundColor: '#fafafa', borderRadius: 'var(--gt-radius-sm)', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
          <span style={{ fontWeight: 600, color: 'var(--gt-text-primary)' }}>支持格式：</span>
          Excel (.xlsx/.xls) · Word (.doc/.docx) · PDF · Markdown · TXT
        </div>
      </div>

      {/* 底部 */}
      <div style={{ padding: 'var(--gt-space-2) var(--gt-space-5)', borderTop: '1px solid #e8e8e8', textAlign: 'center', fontSize: 11, color: 'var(--gt-text-secondary)' }}>
        致同研究院 · 审计底稿智能复核与文档生成平台
      </div>
    </div>
  );
};

export default WorkModeSelector;
