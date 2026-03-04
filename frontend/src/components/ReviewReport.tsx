/**
 * ReviewReport - 复核报告展示组件
 *
 * 按风险等级分组展示问题清单，支持展开详情、标记已处理、导出报告。
 * 实时复核进度条和当前分析维度名称。
 *
 * Requirements: 7.4, 7.5, 4.1-4.6, 9.13-9.16
 */
import React, { useState, useCallback } from 'react';
import type {
  ReviewReport as ReviewReportType,
  ReviewFinding,
  FindingStatus,
  RiskLevel,
} from '../types/audit';
import { RISK_LEVEL_COLORS, DIMENSION_LABELS } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface ReviewReportProps {
  report: ReviewReportType | null;
  isReviewing: boolean;
  reviewProgress: {
    currentDimension: string;
    completedDimensions: number;
    totalDimensions: number;
  } | null;
  onFindingStatusUpdate: (findingId: string, status: FindingStatus) => void;
  onExport: (format: 'word' | 'pdf') => void;
}

/** Risk level display config: color, label, CSS class */
const RISK_CONFIG: Record<RiskLevel, { label: string; badgeClass: string; findingClass: string }> = {
  high: { label: '高风险', badgeClass: 'gt-risk-badge gt-risk-badge--high', findingClass: 'gt-finding--high' },
  medium: { label: '中风险', badgeClass: 'gt-risk-badge gt-risk-badge--medium', findingClass: 'gt-finding--medium' },
  low: { label: '低风险', badgeClass: 'gt-risk-badge gt-risk-badge--low', findingClass: 'gt-finding--low' },
};

/** Order for displaying risk groups */
const RISK_ORDER: RiskLevel[] = ['high', 'medium', 'low'];

const ReviewReportComponent: React.FC<ReviewReportProps> = ({
  report,
  isReviewing,
  reviewProgress,
  onFindingStatusUpdate,
  onExport,
}) => {
  const [expandedFindings, setExpandedFindings] = useState<Set<string>>(new Set());

  const toggleFinding = useCallback((findingId: string) => {
    setExpandedFindings((prev) => {
      const next = new Set(prev);
      if (next.has(findingId)) {
        next.delete(findingId);
      } else {
        next.add(findingId);
      }
      return next;
    });
  }, []);

  const handleMarkResolved = useCallback(
    (findingId: string) => {
      onFindingStatusUpdate(findingId, 'resolved');
    },
    [onFindingStatusUpdate],
  );

  /** Group findings by risk level */
  const groupedFindings: Record<RiskLevel, ReviewFinding[]> = { high: [], medium: [], low: [] };
  if (report) {
    for (const finding of report.findings) {
      groupedFindings[finding.risk_level].push(finding);
    }
  }

  /** Get dimension label, falling back to raw value */
  const getDimensionLabel = (dim: string): string =>
    DIMENSION_LABELS[dim as keyof typeof DIMENSION_LABELS] ?? dim;

  // ── Progress bar (shown while reviewing) ──
  const renderProgress = () => {
    if (!isReviewing || !reviewProgress) return null;
    const { currentDimension, completedDimensions, totalDimensions } = reviewProgress;
    const pct = totalDimensions > 0 ? Math.round((completedDimensions / totalDimensions) * 100) : 0;

    return (
      <div className="gt-card" style={{ marginBottom: 'var(--gt-space-5)' }}>
        <div className="gt-card-content">
          <p
            style={{
              fontSize: 'var(--gt-font-sm)',
              color: 'var(--gt-text-secondary)',
              marginBottom: 'var(--gt-space-2)',
            }}
          >
            正在分析：<strong style={{ color: 'var(--gt-primary)' }}>{getDimensionLabel(currentDimension)}</strong>
          </p>
          <div
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`复核进度 ${pct}%`}
            style={{
              width: '100%',
              height: 8,
              backgroundColor: '#e8e8e8',
              borderRadius: 'var(--gt-radius-sm)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${pct}%`,
                height: '100%',
                backgroundColor: 'var(--gt-primary)',
                borderRadius: 'var(--gt-radius-sm)',
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <p
            style={{
              fontSize: 'var(--gt-font-xs)',
              color: 'var(--gt-text-secondary)',
              marginTop: 'var(--gt-space-1)',
              textAlign: 'right',
            }}
          >
            {completedDimensions} / {totalDimensions} 维度已完成
          </p>
        </div>
      </div>
    );
  };

  // ── Summary section ──
  const renderSummary = () => {
    if (!report) return null;
    const { summary } = report;
    const total = summary.high + summary.medium + summary.low;

    return (
      <section aria-labelledby="report-summary-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
        <div className="gt-card">
          <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
            <h3 id="report-summary-heading" className="gt-h4" style={{ margin: 0 }}>
              复核概要
            </h3>
          </div>
          <div className="gt-card-content">
            <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', marginBottom: 'var(--gt-space-3)' }}>
              复核时间：{report.reviewed_at} &nbsp;|&nbsp; 复核维度：{report.dimensions.map(getDimensionLabel).join('、')}
            </p>
            <div style={{ display: 'flex', gap: 'var(--gt-space-4)', flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: 'var(--gt-font-base)', fontWeight: 600, color: 'var(--gt-text-primary)' }}>
                共发现 {total} 个问题
              </span>
              <span className={RISK_CONFIG.high.badgeClass}>
                <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: RISK_LEVEL_COLORS.high, display: 'inline-block' }} />
                {RISK_CONFIG.high.label}：{summary.high}
              </span>
              <span className={RISK_CONFIG.medium.badgeClass}>
                <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: RISK_LEVEL_COLORS.medium, display: 'inline-block' }} />
                {RISK_CONFIG.medium.label}：{summary.medium}
              </span>
              <span className={RISK_CONFIG.low.badgeClass}>
                <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: RISK_LEVEL_COLORS.low, display: 'inline-block' }} />
                {RISK_CONFIG.low.label}：{summary.low}
              </span>
            </div>
          </div>
        </div>
      </section>
    );
  };

  // ── Single finding row ──
  const renderFinding = (finding: ReviewFinding) => {
    const isExpanded = expandedFindings.has(finding.id);
    const config = RISK_CONFIG[finding.risk_level];
    const isResolved = finding.status === 'resolved';

    return (
      <li
        key={finding.id}
        className={config.findingClass}
        style={{
          listStyle: 'none',
          marginBottom: 'var(--gt-space-3)',
          borderRadius: 'var(--gt-radius-sm)',
          backgroundColor: '#ffffff',
          boxShadow: 'var(--gt-shadow-sm)',
          overflow: 'hidden',
        }}
      >
        {/* Collapsed header – always visible */}
        <button
          onClick={() => toggleFinding(finding.id)}
          aria-expanded={isExpanded}
          aria-controls={`finding-detail-${finding.id}`}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--gt-space-3)',
            width: '100%',
            padding: 'var(--gt-space-3) var(--gt-space-4)',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            textAlign: 'left',
            fontSize: 'var(--gt-font-sm)',
            color: 'var(--gt-text-primary)',
          }}
        >
          {/* Expand/collapse indicator */}
          <span aria-hidden="true" style={{ flexShrink: 0, fontSize: 12, transition: 'transform 0.2s', transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>
            ▶
          </span>

          {/* Risk badge with text label */}
          <span className={config.badgeClass} style={{ flexShrink: 0 }}>
            {config.label}
          </span>

          {/* Dimension */}
          <span style={{ flexShrink: 0, fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
            [{getDimensionLabel(finding.dimension)}]
          </span>

          {/* Location */}
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={finding.location}>
            {finding.location}
          </span>

          {/* Resolved badge */}
          {isResolved && (
            <span
              style={{
                flexShrink: 0,
                fontSize: 'var(--gt-font-xs)',
                fontWeight: 600,
                color: 'var(--gt-success)',
                backgroundColor: 'rgba(40, 167, 69, 0.1)',
                padding: '2px 8px',
                borderRadius: 'var(--gt-radius-sm)',
              }}
            >
              已处理
            </span>
          )}
        </button>

        {/* Expanded detail */}
        {isExpanded && (
          <div
            id={`finding-detail-${finding.id}`}
            style={{
              padding: 'var(--gt-space-3) var(--gt-space-4) var(--gt-space-4)',
              borderTop: '1px solid #e8e8e8',
            }}
          >
            <div style={{ marginBottom: 'var(--gt-space-3)' }}>
              <strong style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)' }}>问题描述</strong>
              <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)', marginTop: 'var(--gt-space-1)', lineHeight: 1.6 }}>
                {finding.description}
              </p>
            </div>

            {finding.reference && (
              <div style={{ marginBottom: 'var(--gt-space-3)' }}>
                <strong style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)' }}>参考依据</strong>
                <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', marginTop: 'var(--gt-space-1)', lineHeight: 1.6 }}>
                  {finding.reference}
                </p>
              </div>
            )}

            {finding.suggestion && (
              <div style={{ marginBottom: 'var(--gt-space-3)' }}>
                <strong style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)' }}>修改建议</strong>
                <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', marginTop: 'var(--gt-space-1)', lineHeight: 1.6 }}>
                  {finding.suggestion}
                </p>
              </div>
            )}

            {!isResolved && (
              <button
                className="gt-button gt-button--secondary"
                onClick={() => handleMarkResolved(finding.id)}
                aria-label={`标记问题 ${finding.location} 为已处理`}
                style={{ marginTop: 'var(--gt-space-2)' }}
              >
                标记为已处理
              </button>
            )}
          </div>
        )}
      </li>
    );
  };

  // ── Findings grouped by risk level ──
  const renderFindings = () => {
    if (!report || report.findings.length === 0) return null;

    return (
      <section aria-labelledby="report-findings-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
        <h3 id="report-findings-heading" className="gt-h4" style={{ marginBottom: 'var(--gt-space-4)' }}>
          问题清单
        </h3>
        {RISK_ORDER.map((level) => {
          const findings = groupedFindings[level];
          if (findings.length === 0) return null;
          const config = RISK_CONFIG[level];

          return (
            <div key={level} style={{ marginBottom: 'var(--gt-space-5)' }}>
              <h4
                style={{
                  fontSize: 'var(--gt-font-base)',
                  fontWeight: 600,
                  color: RISK_LEVEL_COLORS[level],
                  marginBottom: 'var(--gt-space-3)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--gt-space-2)',
                }}
              >
                <span
                  aria-hidden="true"
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: '50%',
                    backgroundColor: RISK_LEVEL_COLORS[level],
                    display: 'inline-block',
                  }}
                />
                {config.label}（{findings.length} 项）
              </h4>
              <ul style={{ padding: 0, margin: 0 }}>
                {findings.map(renderFinding)}
              </ul>
            </div>
          );
        })}
      </section>
    );
  };

  // ── Conclusion section ──
  const renderConclusion = () => {
    if (!report || !report.conclusion) return null;

    return (
      <section aria-labelledby="report-conclusion-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
        <div className="gt-card">
          <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
            <h3 id="report-conclusion-heading" className="gt-h4" style={{ margin: 0 }}>
              复核结论
            </h3>
          </div>
          <div className="gt-card-content">
            <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)', lineHeight: 1.7 }}>
              {report.conclusion}
            </p>
          </div>
        </div>
      </section>
    );
  };

  // ── Export buttons ──
  const renderExportButtons = () => {
    if (!report) return null;

    return (
      <div style={{ display: 'flex', gap: 'var(--gt-space-3)', justifyContent: 'flex-end', marginBottom: 'var(--gt-space-5)' }}>
        <button
          className="gt-button gt-button--secondary"
          onClick={() => onExport('word')}
          aria-label="导出复核报告为 Word 格式"
        >
          导出 Word
        </button>
        <button
          className="gt-button gt-button--secondary"
          onClick={() => onExport('pdf')}
          aria-label="导出复核报告为 PDF 格式"
        >
          导出 PDF
        </button>
      </div>
    );
  };

  // ── Empty state ──
  if (!isReviewing && !report) {
    return (
      <div className="gt-card">
        <div className="gt-card-content" style={{ textAlign: 'center', padding: 'var(--gt-space-10)' }}>
          <p style={{ fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-secondary)' }}>
            暂无复核报告，请先发起复核
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      {renderProgress()}
      {report && (
        <>
          {renderSummary()}
          {renderExportButtons()}
          {renderFindings()}
          {renderConclusion()}
        </>
      )}
    </div>
  );
};

export default ReviewReportComponent;
