/**
 * WorkModeSelector - 工作模式选择组件
 *
 * 系统首页入口，展示"底稿复核"和"文档生成"两个工作模式卡片。
 * 使用 GT Design System 组件样式。
 */
import React from 'react';
import '../styles/gt-design-tokens.css';

interface WorkModeSelectorProps {
  onSelectMode: (mode: 'review' | 'generate' | 'analysis' | 'report_review') => void;
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

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--gt-space-4)', marginBottom: 'var(--gt-space-5)', alignItems: 'stretch' }}>
          {[
            { key: 'review' as const, icon: '📋', title: '底稿复核', desc: '上传审计底稿，从格式规范性、数据勾稽关系、会计准则合规性等多维度进行智能复核', btn: '进入复核 →' },
            { key: 'generate' as const, icon: '📝', title: '文档生成', desc: '基于模板与知识库，智能生成审计计划、审计小结、尽调报告等标准化审计文档', btn: '进入生成 →' },
            { key: 'analysis' as const, icon: '🔍', title: '文档分析', desc: '上传文档进行总结分析、整理汇总或生成汇总台账，自动标注引用来源', btn: '进入分析 →' },
            { key: 'report_review' as const, icon: '📊', title: '审计报告复核', desc: '上传审计报告、报表及附注，自动校验金额勾稽、正文规范性、附注完整性等', btn: '进入复核 →' },
          ].map((item) => (
            <div
              key={item.key}
              onClick={() => onSelectMode(item.key)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter') onSelectMode(item.key); }}
              style={{
                border: '2px solid #e8e8e8',
                borderRadius: 'var(--gt-radius-md, 8px)',
                padding: 'var(--gt-space-4)',
                cursor: 'pointer',
                transition: 'all 0.2s',
                backgroundColor: '#fff',
                display: 'flex',
                flexDirection: 'column',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--gt-primary)'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(75,45,119,0.12)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#e8e8e8'; e.currentTarget.style.boxShadow = 'none'; }}
            >
              <div style={{ fontSize: 26, marginBottom: 8 }}>{item.icon}</div>
              <h3 style={{ fontSize: 'var(--gt-font-base)', fontWeight: 600, color: 'var(--gt-primary)', margin: '0 0 8px 0' }}>
                {item.title}
              </h3>
              <p style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', lineHeight: 1.6, margin: 0, flex: 1 }}>
                {item.desc}
              </p>
              <div style={{ marginTop: 12 }}>
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
                  {item.btn}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* 快速指引 */}
        <div style={{ borderTop: '1px solid #e8e8e8', paddingTop: 'var(--gt-space-3)' }}>
          <h3 style={{ fontSize: 'var(--gt-font-sm)', fontWeight: 600, color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-3)' }}>
            快速开始
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--gt-space-3)', alignItems: 'stretch' }}>
            {[
              { title: '底稿复核流程', steps: ['上传底稿文件（Excel/Word/PDF）', '选择提示词与复核维度', '上传补充材料并确认', '查看复核报告并导出'] },
              { title: '文档生成流程', steps: ['上传模板并关联知识库', '确认章节大纲结构', '逐章节生成与编辑', '导出 Word 文档'] },
              { title: '文档分析流程', steps: ['上传文档并预览编辑缓存', '选择分析模式与自定义要求', '确认自动生成的章节框架', '逐章节生成内容（标注出处）'] },
              { title: '审计报告复核流程', steps: ['上传报告/报表/附注文件', '确认科目与附注对照关系', '配置复核参数并启动', '逐项确认问题并导出报告'] },
            ].map((item) => (
              <div key={item.title} style={{ padding: 'var(--gt-space-3)', backgroundColor: '#f9f7fc', borderRadius: 'var(--gt-radius-sm)', fontSize: 'var(--gt-font-xs)' }}>
                <div style={{ fontWeight: 600, color: 'var(--gt-primary)', marginBottom: 4 }}>{item.title}</div>
                <div style={{ color: 'var(--gt-text-secondary)', lineHeight: 1.6 }}>
                  {item.steps.map((s, i) => (
                    <React.Fragment key={i}>{i > 0 && <br />}{i + 1}. {s}</React.Fragment>
                  ))}
                </div>
              </div>
            ))}
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
