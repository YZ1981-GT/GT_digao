/**
 * CrossReferenceGraph - 交叉引用关系图组件
 *
 * 展示底稿与其他底稿的关联关系图（列表式可视化），
 * 标注关联底稿名称、引用方向和缺失引用。
 * 一致性发现以列表形式展示在关系图下方。
 *
 * Requirements: 8.5
 */
import React from 'react';
import type { CrossReferenceAnalysis, CrossReference, ReviewFinding } from '../types/audit';
import { RISK_LEVEL_COLORS } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface CrossReferenceGraphProps {
  analysis: CrossReferenceAnalysis | null;
}

/** Risk level label mapping */
const RISK_LABELS: Record<string, string> = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
};

/** Render a single reference row */
const ReferenceRow: React.FC<{ ref_item: CrossReference }> = ({ ref_item }) => {
  const isMissing = ref_item.is_missing;

  return (
    <li
      role="listitem"
      aria-label={
        isMissing
          ? `缺失引用：${ref_item.source_workpaper_name} 引用 ${ref_item.target_workpaper_ref}（未找到）`
          : `${ref_item.source_workpaper_name} 引用 ${ref_item.target_workpaper_ref}`
      }
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--gt-space-3)',
        padding: 'var(--gt-space-3) var(--gt-space-4)',
        marginBottom: 'var(--gt-space-2)',
        borderRadius: 'var(--gt-radius-sm)',
        backgroundColor: isMissing ? 'rgba(220, 53, 69, 0.06)' : '#ffffff',
        border: isMissing
          ? '1px solid var(--gt-danger)'
          : '1px solid #e8e8e8',
        boxShadow: 'var(--gt-shadow-sm)',
        flexWrap: 'wrap',
      }}
    >
      {/* Source workpaper */}
      <span
        style={{
          fontWeight: 600,
          fontSize: 'var(--gt-font-sm)',
          color: 'var(--gt-primary)',
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={ref_item.source_workpaper_name}
      >
        {ref_item.source_workpaper_name}
      </span>

      {/* Arrow indicator */}
      <span
        aria-hidden="true"
        style={{
          flexShrink: 0,
          fontSize: 'var(--gt-font-base)',
          color: isMissing ? 'var(--gt-danger)' : 'var(--gt-text-secondary)',
        }}
      >
        →
      </span>

      {/* Target workpaper */}
      <span
        style={{
          fontWeight: 600,
          fontSize: 'var(--gt-font-sm)',
          color: isMissing ? 'var(--gt-danger)' : 'var(--gt-primary)',
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={ref_item.target_workpaper_ref}
      >
        {ref_item.target_workpaper_ref}
      </span>

      {/* Reference type badge */}
      <span
        style={{
          flexShrink: 0,
          fontSize: 'var(--gt-font-xs)',
          color: 'var(--gt-text-secondary)',
          backgroundColor: '#f0f0f0',
          padding: '2px 8px',
          borderRadius: 'var(--gt-radius-sm)',
        }}
      >
        {ref_item.reference_type}
      </span>

      {/* Missing badge */}
      {isMissing && (
        <span
          style={{
            flexShrink: 0,
            fontSize: 'var(--gt-font-xs)',
            fontWeight: 600,
            color: '#ffffff',
            backgroundColor: 'var(--gt-danger)',
            padding: '2px 8px',
            borderRadius: 'var(--gt-radius-sm)',
          }}
        >
          缺失引用
        </span>
      )}
    </li>
  );
};

/** Render a consistency finding */
const ConsistencyFindingRow: React.FC<{ finding: ReviewFinding }> = ({ finding }) => {
  const color = RISK_LEVEL_COLORS[finding.risk_level] ?? 'var(--gt-text-secondary)';
  const label = RISK_LABELS[finding.risk_level] ?? finding.risk_level;

  return (
    <li
      style={{
        listStyle: 'none',
        padding: 'var(--gt-space-3) var(--gt-space-4)',
        marginBottom: 'var(--gt-space-2)',
        borderLeft: `4px solid ${color}`,
        borderRadius: 'var(--gt-radius-sm)',
        backgroundColor: '#ffffff',
        boxShadow: 'var(--gt-shadow-sm)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-2)', marginBottom: 'var(--gt-space-1)' }}>
        <span
          aria-hidden="true"
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: color,
            display: 'inline-block',
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 'var(--gt-font-xs)',
            fontWeight: 600,
            color,
          }}
        >
          {label}
        </span>
        {finding.location && (
          <span style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
            {finding.location}
          </span>
        )}
      </div>
      <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)', margin: 0, lineHeight: 1.6 }}>
        {finding.description}
      </p>
      {finding.suggestion && (
        <p style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)', margin: 0, marginTop: 'var(--gt-space-1)', lineHeight: 1.5 }}>
          建议：{finding.suggestion}
        </p>
      )}
    </li>
  );
};

const CrossReferenceGraph: React.FC<CrossReferenceGraphProps> = ({ analysis }) => {
  // ── Empty state ──
  if (!analysis) {
    return (
      <div className="gt-card">
        <div className="gt-card-content" style={{ textAlign: 'center', padding: 'var(--gt-space-10)' }}>
          <p style={{ fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-secondary)' }}>
            暂无交叉引用分析数据
          </p>
        </div>
      </div>
    );
  }

  const { references, missing_references, consistency_findings } = analysis;
  const hasReferences = (references?.length ?? 0) > 0;
  const hasMissing = (missing_references?.length ?? 0) > 0;
  const hasConsistency = (consistency_findings?.length ?? 0) > 0;

  // No data at all
  if (!hasReferences && !hasMissing && !hasConsistency) {
    return (
      <div className="gt-card">
        <div className="gt-card-content" style={{ textAlign: 'center', padding: 'var(--gt-space-10)' }}>
          <p style={{ fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-secondary)' }}>
            未发现底稿间交叉引用关系
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* ── Reference relationships ── */}
      <section aria-labelledby="cross-ref-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
        <div className="gt-card">
          <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
            <h3 id="cross-ref-heading" className="gt-h4" style={{ margin: 0 }}>
              交叉引用关系
            </h3>
          </div>
          <div className="gt-card-content">
            {hasReferences ? (
              <ul role="list" style={{ padding: 0, margin: 0 }}>
                {references.map((ref, idx) => (
                  <ReferenceRow key={`ref-${ref.source_workpaper_id}-${ref.target_workpaper_ref}-${idx}`} ref_item={ref} />
                ))}
              </ul>
            ) : (
              <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
                未发现有效的交叉引用关系
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ── Missing references ── */}
      {hasMissing && (
        <section aria-labelledby="missing-ref-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
          <div className="gt-card">
            <div
              className="gt-card-header"
              style={{
                color: 'var(--gt-danger)',
                borderLeftColor: 'var(--gt-danger)',
              }}
            >
              <h3 id="missing-ref-heading" className="gt-h4" style={{ margin: 0, color: 'var(--gt-danger)' }}>
                缺失引用（{missing_references.length} 项）
              </h3>
            </div>
            <div className="gt-card-content">
              <ul role="list" style={{ padding: 0, margin: 0 }}>
                {missing_references.map((ref, idx) => (
                  <ReferenceRow key={`missing-${ref.source_workpaper_id}-${ref.target_workpaper_ref}-${idx}`} ref_item={ref} />
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      {/* ── Consistency findings ── */}
      {hasConsistency && (
        <section aria-labelledby="consistency-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
          <div className="gt-card">
            <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
              <h3 id="consistency-heading" className="gt-h4" style={{ margin: 0 }}>
                一致性检查发现（{consistency_findings.length} 项）
              </h3>
            </div>
            <div className="gt-card-content">
              <ul role="list" style={{ padding: 0, margin: 0 }}>
                {consistency_findings.map((finding) => (
                  <ConsistencyFindingRow key={finding.id} finding={finding} />
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}
    </div>
  );
};

export default CrossReferenceGraph;
