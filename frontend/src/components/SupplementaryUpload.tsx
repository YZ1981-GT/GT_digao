/**
 * SupplementaryUpload - 补充材料上传组件
 *
 * 展示复核引擎识别到的所需相关底稿清单，
 * 提供文件上传入口和文本输入区域供用户补充材料，
 * 展示已上传补充材料列表并支持移除。
 *
 * Requirements: 7.8, 2.11, 2.12
 */
import React, { useState, useRef, useCallback } from 'react';
import { reviewApi } from '../services/api';
import type { SupplementaryMaterial, RequiredReference } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface SupplementaryUploadProps {
  requiredReferences: RequiredReference[];
  supplementaryMaterials: SupplementaryMaterial[];
  onSupplementaryChange: (materials: SupplementaryMaterial[]) => void;
}

const SupplementaryUpload: React.FC<SupplementaryUploadProps> = ({
  requiredReferences,
  supplementaryMaterials,
  onSupplementaryChange,
}) => {
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState('');
  const [isSubmittingText, setIsSubmittingText] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      setIsUploading(true);
      setUploadError(null);

      try {
        const response = await reviewApi.uploadSupplementary(file);
        const material = response.data;
        onSupplementaryChange([...supplementaryMaterials, material]);
      } catch (err: any) {
        setUploadError(err.message || '文件上传失败，请重试');
      } finally {
        setIsUploading(false);
        if (e.target) e.target.value = '';
      }
    },
    [supplementaryMaterials, onSupplementaryChange]
  );

  const handleTextSubmit = useCallback(async () => {
    const trimmed = textContent.trim();
    if (!trimmed) return;

    setIsSubmittingText(true);
    setUploadError(null);

    try {
      const response = await reviewApi.uploadSupplementary(undefined, trimmed);
      const material = response.data;
      onSupplementaryChange([...supplementaryMaterials, material]);
      setTextContent('');
    } catch (err: any) {
      setUploadError(err.message || '提交文本失败，请重试');
    } finally {
      setIsSubmittingText(false);
    }
  }, [textContent, supplementaryMaterials, onSupplementaryChange]);

  const handleRemove = useCallback(
    (id: string) => {
      onSupplementaryChange(supplementaryMaterials.filter((m) => m.id !== id));
    },
    [supplementaryMaterials, onSupplementaryChange]
  );

  return (
    <div className="gt-card">
      <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
        补充材料
      </div>
      <div className="gt-card-content">
        {/* Required references list */}
        {requiredReferences.length > 0 && (
          <section aria-labelledby="required-refs-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
            <h4
              id="required-refs-heading"
              style={{
                fontSize: 'var(--gt-font-base)',
                fontWeight: 600,
                color: 'var(--gt-text-primary)',
                marginBottom: 'var(--gt-space-2)',
              }}
            >
              所需相关底稿清单
            </h4>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {requiredReferences.map((ref, idx) => (
                <li
                  key={`${ref.workpaper_ref}-${idx}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--gt-space-2)',
                    padding: 'var(--gt-space-2) var(--gt-space-3)',
                    borderRadius: 'var(--gt-radius-sm)',
                    backgroundColor: ref.is_uploaded ? 'rgba(40, 167, 69, 0.06)' : 'rgba(255, 193, 7, 0.08)',
                    marginBottom: 'var(--gt-space-2)',
                  }}
                >
                  <span
                    aria-hidden="true"
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      backgroundColor: ref.is_uploaded ? 'var(--gt-success)' : '#FFC107',
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)', fontWeight: 500 }}>
                    {ref.workpaper_ref}
                  </span>
                  <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)', flex: 1 }}>
                    {ref.description}
                  </span>
                  <span
                    style={{
                      fontSize: 'var(--gt-font-xs)',
                      color: ref.is_uploaded ? 'var(--gt-success)' : '#FFC107',
                      fontWeight: 500,
                      flexShrink: 0,
                    }}
                  >
                    {ref.is_uploaded ? '已上传' : '待补充'}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* File upload */}
        <section aria-labelledby="file-upload-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
          <h4
            id="file-upload-heading"
            style={{
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-2)',
            }}
          >
            上传补充文件
          </h4>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--gt-space-3)' }}>
            <label
              htmlFor="supplementary-file-input"
              className="gt-button gt-button--secondary"
              style={{
                cursor: isUploading ? 'not-allowed' : 'pointer',
                opacity: isUploading ? 0.6 : 1,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 'var(--gt-space-1)',
              }}
            >
              {isUploading ? '上传中...' : '选择文件'}
            </label>
            <input
              id="supplementary-file-input"
              ref={fileInputRef}
              type="file"
              onChange={handleFileUpload}
              disabled={isUploading}
              style={{ display: 'none' }}
            />
            {isUploading && (
              <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
                正在上传...
              </span>
            )}
          </div>
        </section>

        {/* Text input */}
        <section aria-labelledby="text-input-heading" style={{ marginBottom: 'var(--gt-space-5)' }}>
          <h4
            id="text-input-heading"
            style={{
              fontSize: 'var(--gt-font-base)',
              fontWeight: 600,
              color: 'var(--gt-text-primary)',
              marginBottom: 'var(--gt-space-2)',
            }}
          >
            输入补充文本
          </h4>
          <textarea
            id="supplementary-text-input"
            aria-label="补充材料文本输入"
            value={textContent}
            onChange={(e) => setTextContent(e.target.value)}
            placeholder="在此输入补充说明或相关信息..."
            rows={4}
            disabled={isSubmittingText}
            style={{
              width: '100%',
              padding: 'var(--gt-space-3)',
              borderRadius: 'var(--gt-radius-sm)',
              border: '1px solid #d0d0d0',
              fontSize: 'var(--gt-font-sm)',
              fontFamily: 'inherit',
              resize: 'vertical',
              boxSizing: 'border-box',
            }}
          />
          <div style={{ marginTop: 'var(--gt-space-2)', textAlign: 'right' }}>
            <button
              className="gt-button gt-button--primary"
              onClick={handleTextSubmit}
              disabled={!textContent.trim() || isSubmittingText}
              style={{ padding: 'var(--gt-space-2) var(--gt-space-4)', fontSize: 'var(--gt-font-sm)' }}
            >
              {isSubmittingText ? '提交中...' : '添加文本'}
            </button>
          </div>
        </section>

        {/* Error message */}
        {uploadError && (
          <div
            role="alert"
            style={{
              padding: 'var(--gt-space-2) var(--gt-space-3)',
              borderRadius: 'var(--gt-radius-sm)',
              backgroundColor: 'rgba(220, 53, 69, 0.08)',
              color: 'var(--gt-danger)',
              fontSize: 'var(--gt-font-sm)',
              marginBottom: 'var(--gt-space-4)',
            }}
          >
            {uploadError}
          </div>
        )}

        {/* Uploaded supplementary materials list */}
        {supplementaryMaterials.length > 0 && (
          <section aria-labelledby="materials-list-heading">
            <h4
              id="materials-list-heading"
              style={{
                fontSize: 'var(--gt-font-base)',
                fontWeight: 600,
                color: 'var(--gt-text-primary)',
                marginBottom: 'var(--gt-space-2)',
              }}
            >
              已上传补充材料（{supplementaryMaterials.length} 项）
            </h4>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {supplementaryMaterials.map((mat) => (
                <li
                  key={mat.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: 'var(--gt-space-2) var(--gt-space-3)',
                    borderRadius: 'var(--gt-radius-sm)',
                    border: '1px solid #e8e8e8',
                    marginBottom: 'var(--gt-space-2)',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span
                      style={{
                        fontSize: 'var(--gt-font-xs)',
                        color: 'var(--gt-text-secondary)',
                        marginRight: 'var(--gt-space-2)',
                        backgroundColor: mat.type === 'file' ? 'rgba(75, 45, 119, 0.08)' : 'rgba(0, 148, 179, 0.08)',
                        padding: '2px 6px',
                        borderRadius: 'var(--gt-radius-sm)',
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
                        : (mat.text_content && mat.text_content.length > 60
                            ? mat.text_content.substring(0, 60) + '...'
                            : mat.text_content)}
                    </span>
                  </div>
                  <button
                    className="gt-button gt-button--secondary"
                    style={{ padding: 'var(--gt-space-1) var(--gt-space-3)', fontSize: 'var(--gt-font-xs)', flexShrink: 0, marginLeft: 'var(--gt-space-2)' }}
                    onClick={() => handleRemove(mat.id)}
                    aria-label={`移除补充材料 ${mat.filename || '文本'}`}
                  >
                    移除
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
};

export default SupplementaryUpload;
