/**
 * WorkModeSelector - 工作模式选择组件
 *
 * 系统首页入口，展示"底稿复核"和"文档生成"两个工作模式卡片。
 * 使用 GT Design System 组件样式（gt-card, gt-button--primary, gt-grid-2）。
 *
 * Requirements: 10.1, 10.5, 9.6, 9.12
 */
import React from 'react';
import '../styles/gt-design-tokens.css';

interface WorkModeSelectorProps {
  onSelectMode: (mode: 'review' | 'generate') => void;
}

const WorkModeSelector: React.FC<WorkModeSelectorProps> = ({ onSelectMode }) => {
  return (
    <nav aria-label="工作模式选择" className="gt-container" style={{ paddingTop: 'var(--gt-space-12)' }}>
      <h1 className="gt-h1" style={{ textAlign: 'center', marginBottom: 'var(--gt-space-2)' }}>
        审计底稿智能复核与文档生成
      </h1>
      <p
        style={{
          textAlign: 'center',
          color: 'var(--gt-text-secondary)',
          fontSize: 'var(--gt-font-base)',
          marginBottom: 'var(--gt-space-10)',
        }}
      >
        请选择工作模式
      </p>

      <div className="gt-grid-2" style={{ maxWidth: 720, margin: '0 auto' }}>
        {/* 底稿复核卡片 */}
        <div className="gt-card">
          <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
            底稿复核
          </div>
          <div className="gt-card-content">
            <p style={{ color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)', marginBottom: 'var(--gt-space-6)', lineHeight: 1.6 }}>
              上传审计底稿，系统从格式规范性、数据勾稽关系、会计准则合规性等多维度进行智能复核，生成结构化复核报告。
            </p>
            <button
              className="gt-button gt-button--primary"
              style={{ width: '100%' }}
              onClick={() => onSelectMode('review')}
            >
              进入底稿复核
            </button>
          </div>
        </div>

        {/* 文档生成卡片 */}
        <div className="gt-card">
          <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
            文档生成
          </div>
          <div className="gt-card-content">
            <p style={{ color: 'var(--gt-text-secondary)', fontSize: 'var(--gt-font-sm)', marginBottom: 'var(--gt-space-6)', lineHeight: 1.6 }}>
              基于底稿模板与知识库，智能生成审计计划、审计小结、尽调报告等标准化审计文档，支持逐章节编辑与导出。
            </p>
            <button
              className="gt-button gt-button--primary"
              style={{ width: '100%' }}
              onClick={() => onSelectMode('generate')}
            >
              进入文档生成
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
};

export default WorkModeSelector;
