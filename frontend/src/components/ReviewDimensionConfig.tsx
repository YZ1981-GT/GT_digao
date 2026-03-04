/**
 * ReviewDimensionConfig - 复核维度配置组件
 *
 * 展示 5 个标准复核维度（格式规范性、数据勾稽关系、会计准则合规性、
 * 审计程序完整性、审计证据充分性），支持勾选需要执行的维度，
 * 支持添加自定义复核关注点。
 *
 * Requirements: 7.3, 2.6
 */
import React, { useState, useCallback } from 'react';
import type { ReviewDimension } from '../types/audit';
import { DIMENSION_LABELS } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface ReviewDimensionConfigProps {
  selectedDimensions: ReviewDimension[];
  customDimensions: string[];
  onDimensionsChange: (dimensions: ReviewDimension[]) => void;
  onCustomDimensionsChange: (customDimensions: string[]) => void;
}

/** Brief descriptions for each standard review dimension */
const DIMENSION_DESCRIPTIONS: Record<ReviewDimension, string> = {
  format: '检查底稿是否符合事务所模板的格式要求，包括编号规范、标题层级、必填字段完整性',
  data_reconciliation: '检查底稿中数值数据的逻辑一致性，包括加总关系、交叉引用和财务报表勾稽',
  accounting_compliance: '检查底稿涉及的会计处理是否符合中国企业会计准则和相关监管规定',
  audit_procedure: '检查底稿是否覆盖该业务循环所要求的全部审计程序步骤',
  evidence_sufficiency: '检查底稿中记录的审计证据是否充分、适当，包括样本量和证据类型',
};

/** All standard dimensions in display order */
const ALL_DIMENSIONS: ReviewDimension[] = [
  'format',
  'data_reconciliation',
  'accounting_compliance',
  'audit_procedure',
  'evidence_sufficiency',
];

const ReviewDimensionConfig: React.FC<ReviewDimensionConfigProps> = ({
  selectedDimensions,
  customDimensions,
  onDimensionsChange,
  onCustomDimensionsChange,
}) => {
  const [customInput, setCustomInput] = useState('');

  const handleDimensionToggle = useCallback(
    (dimension: ReviewDimension) => {
      if (selectedDimensions.includes(dimension)) {
        onDimensionsChange(selectedDimensions.filter((d) => d !== dimension));
      } else {
        onDimensionsChange([...selectedDimensions, dimension]);
      }
    },
    [selectedDimensions, onDimensionsChange]
  );

  const handleAddCustom = useCallback(() => {
    const trimmed = customInput.trim();
    if (trimmed && !customDimensions.includes(trimmed)) {
      onCustomDimensionsChange([...customDimensions, trimmed]);
      setCustomInput('');
    }
  }, [customInput, customDimensions, onCustomDimensionsChange]);

  const handleRemoveCustom = useCallback(
    (index: number) => {
      onCustomDimensionsChange(customDimensions.filter((_, i) => i !== index));
    },
    [customDimensions, onCustomDimensionsChange]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleAddCustom();
      }
    },
    [handleAddCustom]
  );

  return (
    <div className="gt-card">
      <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
        复核维度配置
      </div>
      <div className="gt-card-content">
        {/* Standard dimensions */}
        <fieldset
          style={{ border: 'none', margin: 0, padding: 0 }}
        >
          <legend
            style={{
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-3)',
            }}
          >
            标准复核维度
          </legend>

          {ALL_DIMENSIONS.map((dim) => {
            const isChecked = selectedDimensions.includes(dim);
            const inputId = `dimension-${dim}`;
            return (
              <div
                key={dim}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 'var(--gt-space-3)',
                  padding: 'var(--gt-space-3) var(--gt-space-4)',
                  marginBottom: 'var(--gt-space-2)',
                  borderRadius: 'var(--gt-radius-sm)',
                  backgroundColor: isChecked ? 'rgba(75, 45, 119, 0.04)' : 'transparent',
                  transition: 'background-color 0.15s',
                }}
              >
                <input
                  type="checkbox"
                  id={inputId}
                  checked={isChecked}
                  onChange={() => handleDimensionToggle(dim)}
                  style={{ marginTop: 3, accentColor: 'var(--gt-primary)' }}
                />
                <label htmlFor={inputId} style={{ cursor: 'pointer', flex: 1 }}>
                  <span
                    style={{
                      fontSize: 'var(--gt-font-sm)',
                      fontWeight: 600,
                      color: 'var(--gt-text-primary)',
                    }}
                  >
                    {DIMENSION_LABELS[dim]}
                  </span>
                  <span
                    style={{
                      display: 'block',
                      fontSize: 'var(--gt-font-xs)',
                      color: 'var(--gt-text-secondary)',
                      marginTop: 'var(--gt-space-1)',
                    }}
                  >
                    {DIMENSION_DESCRIPTIONS[dim]}
                  </span>
                </label>
              </div>
            );
          })}
        </fieldset>

        {/* Custom review focus points */}
        <div style={{ marginTop: 'var(--gt-space-6)' }}>
          <label
            htmlFor="custom-dimension-input"
            style={{
              display: 'block',
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-3)',
            }}
          >
            自定义复核关注点
          </label>

          <div style={{ display: 'flex', gap: 'var(--gt-space-2)' }}>
            <input
              id="custom-dimension-input"
              type="text"
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入自定义复核关注点"
              style={{
                flex: 1,
                padding: 'var(--gt-space-2) var(--gt-space-3)',
                fontSize: 'var(--gt-font-sm)',
                border: '1px solid #d0d0d0',
                borderRadius: 'var(--gt-radius-sm)',
                color: 'var(--gt-text-primary)',
                outline: 'none',
              }}
            />
            <button
              className="gt-button gt-button--primary"
              onClick={handleAddCustom}
              disabled={!customInput.trim()}
              style={{
                padding: 'var(--gt-space-2) var(--gt-space-4)',
                fontSize: 'var(--gt-font-sm)',
                whiteSpace: 'nowrap',
              }}
            >
              添加
            </button>
          </div>

          {/* Custom dimensions list */}
          {customDimensions.length > 0 && (
            <ul
              style={{
                listStyle: 'none',
                margin: 0,
                padding: 0,
                marginTop: 'var(--gt-space-3)',
              }}
            >
              {customDimensions.map((cd, idx) => (
                <li
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: 'var(--gt-space-2) var(--gt-space-3)',
                    marginBottom: 'var(--gt-space-1)',
                    backgroundColor: 'rgba(0, 148, 179, 0.06)',
                    borderRadius: 'var(--gt-radius-sm)',
                    fontSize: 'var(--gt-font-sm)',
                    color: 'var(--gt-text-primary)',
                  }}
                >
                  <span>{cd}</span>
                  <button
                    className="gt-button gt-button--secondary"
                    onClick={() => handleRemoveCustom(idx)}
                    aria-label={`移除自定义关注点：${cd}`}
                    style={{
                      padding: 'var(--gt-space-1) var(--gt-space-2)',
                      fontSize: 'var(--gt-font-xs)',
                    }}
                  >
                    移除
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
};

export default ReviewDimensionConfig;
