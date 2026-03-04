/**
 * ReviewConfirmation - 复核确认页面组件
 *
 * 汇总展示已选底稿、复核维度、所选提示词、已上传补充材料，
 * 用户点击"确认并开始复核"按钮后才正式发起复核。
 *
 * Requirements: 2.13, 7.8
 */
import React from 'react';
import type { WorkpaperParseResult, ReviewDimension, SupplementaryMaterial } from '../types/audit';
import { DIMENSION_LABELS } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface ReviewConfirmationProps {
  workpapers: WorkpaperParseResult[];
  selectedDimensions: ReviewDimension[];
  customDimensions: string[];
  selectedPromptId: string | null;
  customPrompt: string;
  supplementaryMaterials: SupplementaryMaterial[];
  isReviewing: boolean;
  onConfirmAndStart: () => void;
}

const ReviewConfirmation: React.FC<ReviewConfirmationProps> = ({
  workpapers,
  selectedDimensions,
  customDimensions,
  selectedPromptId,
  customPrompt,
  supplementaryMaterials,
  isReviewing,
  onConfirmAndStart,
}) => {
  return (
    <div className="gt-card">
      <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
        复核配置确认
      </div>
      <div className="gt-card-content">
        {/* Selected workpapers */}
        <section aria-labelledby="confirm-workpapers-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
          <h4
            id="confirm-workpapers-heading"
            style={{
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-2)',
            }}
          >
            已选底稿（{workpapers.length} 份）
          </h4>
          {workpapers.length > 0 ? (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {workpapers.map((wp) => (
                <li
                  key={wp.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--gt-space-2)',
                    padding: 'var(--gt-space-2) var(--gt-space-3)',
                    borderRadius: 'var(--gt-radius-sm)',
                    border: '1px solid #e8e8e8',
                    marginBottom: 'var(--gt-space-2)',
                  }}
                >
                  <span
                    style={{
                      fontSize: 'var(--gt-font-xs)',
                      color: 'var(--gt-text-secondary)',
                      backgroundColor: 'rgba(75, 45, 119, 0.08)',
                      padding: '2px 6px',
                      borderRadius: 'var(--gt-radius-sm)',
                      flexShrink: 0,
                    }}
                  >
                    {wp.file_format.toUpperCase()}
                  </span>
                  <span
                    style={{
                      fontSize: 'var(--gt-font-sm)',
                      color: 'var(--gt-text-primary)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={wp.filename}
                  >
                    {wp.filename}
                  </span>
                  {wp.classification.business_cycle && (
                    <span
                      style={{
                        fontSize: 'var(--gt-font-xs)',
                        color: 'var(--gt-accent-teal)',
                        marginLeft: 'auto',
                        flexShrink: 0,
                      }}
                    >
                      {wp.classification.business_cycle}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
              未选择底稿
            </p>
          )}
        </section>

        {/* Review dimensions */}
        <section aria-labelledby="confirm-dimensions-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
          <h4
            id="confirm-dimensions-heading"
            style={{
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-2)',
            }}
          >
            复核维度
          </h4>
          {selectedDimensions.length > 0 || customDimensions.length > 0 ? (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexWrap: 'wrap', gap: 'var(--gt-space-2)' }}>
              {selectedDimensions.map((dim) => (
                <li
                  key={dim}
                  style={{
                    fontSize: 'var(--gt-font-sm)',
                    color: 'var(--gt-primary)',
                    backgroundColor: 'rgba(75, 45, 119, 0.08)',
                    padding: 'var(--gt-space-1) var(--gt-space-3)',
                    borderRadius: 'var(--gt-radius-md)',
                  }}
                >
                  {DIMENSION_LABELS[dim]}
                </li>
              ))}
              {customDimensions.map((cd, idx) => (
                <li
                  key={`custom-${idx}`}
                  style={{
                    fontSize: 'var(--gt-font-sm)',
                    color: 'var(--gt-accent-teal)',
                    backgroundColor: 'rgba(0, 148, 179, 0.08)',
                    padding: 'var(--gt-space-1) var(--gt-space-3)',
                    borderRadius: 'var(--gt-radius-md)',
                  }}
                >
                  {cd}
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
              未选择复核维度
            </p>
          )}
        </section>

        {/* Prompt info */}
        <section aria-labelledby="confirm-prompt-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
          <h4
            id="confirm-prompt-heading"
            style={{
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-2)',
            }}
          >
            复核提示词
          </h4>
          <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)' }}>
            {selectedPromptId
              ? `预置提示词 (ID: ${selectedPromptId})`
              : customPrompt
                ? '自定义提示词'
                : '未选择提示词'}
          </p>
          {customPrompt && !selectedPromptId && (
            <p
              style={{
                fontSize: 'var(--gt-font-xs)',
                color: 'var(--gt-text-secondary)',
                marginTop: 'var(--gt-space-1)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                maxWidth: '100%',
              }}
              title={customPrompt}
            >
              {customPrompt.length > 100 ? customPrompt.substring(0, 100) + '...' : customPrompt}
            </p>
          )}
        </section>

        {/* Supplementary materials */}
        <section aria-labelledby="confirm-materials-heading" style={{ marginBottom: 'var(--gt-space-6)' }}>
          <h4
            id="confirm-materials-heading"
            style={{
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-2)',
            }}
          >
            补充材料（{supplementaryMaterials.length} 项）
          </h4>
          {supplementaryMaterials.length > 0 ? (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {supplementaryMaterials.map((mat) => (
                <li
                  key={mat.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--gt-space-2)',
                    padding: 'var(--gt-space-2) var(--gt-space-3)',
                    borderRadius: 'var(--gt-radius-sm)',
                    border: '1px solid #e8e8e8',
                    marginBottom: 'var(--gt-space-2)',
                  }}
                >
                  <span
                    style={{
                      fontSize: 'var(--gt-font-xs)',
                      color: 'var(--gt-text-secondary)',
                      backgroundColor: mat.type === 'file' ? 'rgba(75, 45, 119, 0.08)' : 'rgba(0, 148, 179, 0.08)',
                      padding: '2px 6px',
                      borderRadius: 'var(--gt-radius-sm)',
                      flexShrink: 0,
                    }}
                  >
                    {mat.type === 'file' ? '文件' : '文本'}
                  </span>
                  <span
                    style={{
                      fontSize: 'var(--gt-font-sm)',
                      color: 'var(--gt-text-primary)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={mat.filename || mat.text_content}
                  >
                    {mat.type === 'file'
                      ? mat.filename
                      : mat.text_content && mat.text_content.length > 60
                        ? mat.text_content.substring(0, 60) + '...'
                        : mat.text_content}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
              无补充材料
            </p>
          )}
        </section>

        {/* Confirm button */}
        <div style={{ textAlign: 'center' }}>
          <button
            className="gt-button gt-button--primary"
            onClick={onConfirmAndStart}
            disabled={isReviewing}
            aria-busy={isReviewing}
            aria-label="确认并开始复核"
            style={{
              padding: 'var(--gt-space-3) var(--gt-space-8)',
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
            }}
          >
            {isReviewing ? '复核进行中...' : '确认并开始复核'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ReviewConfirmation;
