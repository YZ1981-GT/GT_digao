/**
 * WorkpaperUpload - 底稿上传组件
 *
 * 支持拖拽上传和点击选择文件两种方式，展示上传进度和解析状态，
 * 展示已上传底稿列表（文件名、格式、分类、解析状态）。
 * 使用 GT Design System 组件样式。
 *
 * Requirements: 7.2, 1.1-1.8
 */
import React, { useState, useRef, useCallback } from 'react';
import { reviewApi } from '../services/api';
import type { WorkpaperParseResult } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface WorkpaperUploadProps {
  workpapers: WorkpaperParseResult[];
  onWorkpapersChange: (workpapers: WorkpaperParseResult[]) => void;
}

interface UploadingFile {
  id: string;
  filename: string;
  progress: number;
  status: 'uploading' | 'success' | 'error';
  errorMessage?: string;
}

const ACCEPTED_FORMATS = '.xlsx,.xls,.doc,.docx,.pdf';

function getFormatLabel(format: string): string {
  const map: Record<string, string> = {
    xlsx: 'Excel (.xlsx)',
    xls: 'Excel (.xls)',
    doc: 'Word (.doc)',
    docx: 'Word (.docx)',
    pdf: 'PDF',
  };
  return map[format] || format;
}

function getStatusLabel(status: string): { text: string; className: string } {
  if (status === 'success') return { text: '解析成功', className: 'gt-success' };
  if (status === 'error') return { text: '解析失败', className: 'gt-error' };
  return { text: status, className: '' };
}

const WorkpaperUpload: React.FC<WorkpaperUploadProps> = ({ workpapers, onWorkpapersChange }) => {
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const fileArray = Array.from(files);
      if (fileArray.length === 0) return;

      // Create uploading entries with simulated progress
      const newUploading: UploadingFile[] = fileArray.map((f, i) => ({
        id: `upload-${Date.now()}-${i}`,
        filename: f.name,
        progress: 0,
        status: 'uploading' as const,
      }));
      setUploadingFiles((prev) => [...prev, ...newUploading]);

      // Simulate progress increments
      const progressIntervals = newUploading.map((entry) => {
        return setInterval(() => {
          setUploadingFiles((prev) =>
            prev.map((u) =>
              u.id === entry.id && u.status === 'uploading' && u.progress < 90
                ? { ...u, progress: Math.min(u.progress + 10 + Math.random() * 15, 90) }
                : u
            )
          );
        }, 300);
      });

      try {
        let results: WorkpaperParseResult[];

        if (fileArray.length === 1) {
          const response = await reviewApi.upload(fileArray[0]);
          const data = response.data;
          if (data.success && data.workpaper) {
            results = [data.workpaper];
          } else {
            // Single file error
            progressIntervals.forEach(clearInterval);
            setUploadingFiles((prev) =>
              prev.map((u) =>
                u.id === newUploading[0].id
                  ? { ...u, progress: 100, status: 'error', errorMessage: data.message }
                  : u
              )
            );
            return;
          }
        } else {
          const response = await reviewApi.uploadBatch(fileArray);
          const batchData = response.data;
          results = (Array.isArray(batchData) ? batchData : [batchData])
            .filter((r: any) => r.success && r.workpaper)
            .map((r: any) => r.workpaper);

          // Mark failed ones
          const batchArr = Array.isArray(batchData) ? batchData : [batchData];
          batchArr.forEach((r: any, idx: number) => {
            if (!r.success && newUploading[idx]) {
              setUploadingFiles((prev) =>
                prev.map((u) =>
                  u.id === newUploading[idx].id
                    ? { ...u, progress: 100, status: 'error', errorMessage: r.message }
                    : u
                )
              );
            }
          });
        }

        // Clear intervals and mark successes
        progressIntervals.forEach(clearInterval);
        setUploadingFiles((prev) =>
          prev.map((u) => {
            const matchIdx = newUploading.findIndex((n) => n.id === u.id);
            if (matchIdx >= 0 && u.status === 'uploading') {
              return { ...u, progress: 100, status: 'success' };
            }
            return u;
          })
        );

        // Add parsed workpapers to list
        if (results.length > 0) {
          onWorkpapersChange([...workpapers, ...results]);
        }

        // Remove completed uploads after a short delay
        setTimeout(() => {
          setUploadingFiles((prev) =>
            prev.filter((u) => !newUploading.some((n) => n.id === u.id))
          );
        }, 1500);
      } catch (err: any) {
        progressIntervals.forEach(clearInterval);
        const errorMsg = err.message || '上传失败，请重试';
        setUploadingFiles((prev) =>
          prev.map((u) =>
            newUploading.some((n) => n.id === u.id) && u.status === 'uploading'
              ? { ...u, progress: 100, status: 'error', errorMessage: errorMsg }
              : u
          )
        );
      }
    },
    [workpapers, onWorkpapersChange]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      if (e.dataTransfer.files.length > 0) {
        handleFiles(e.dataTransfer.files);
      }
    },
    [handleFiles]
  );

  const handleClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleClick();
      }
    },
    [handleClick]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFiles(e.target.files);
        e.target.value = '';
      }
    },
    [handleFiles]
  );

  const handleRemoveWorkpaper = useCallback(
    (id: string) => {
      onWorkpapersChange(workpapers.filter((w) => w.id !== id));
    },
    [workpapers, onWorkpapersChange]
  );

  return (
    <div className="gt-card">
      <div className="gt-card-header" style={{ color: 'var(--gt-primary)' }}>
        底稿上传
      </div>
      <div className="gt-card-content">
        {/* Drop zone */}
        <div
          role="button"
          tabIndex={0}
          aria-label="点击或拖拽文件到此区域上传底稿，支持 xlsx、xls、doc、docx、pdf 格式"
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={handleClick}
          onKeyDown={handleKeyDown}
          style={{
            border: `2px dashed ${isDragOver ? 'var(--gt-primary)' : '#d0d0d0'}`,
            borderRadius: 'var(--gt-radius-md)',
            padding: 'var(--gt-space-10) var(--gt-space-6)',
            textAlign: 'center',
            cursor: 'pointer',
            backgroundColor: isDragOver ? 'rgba(75, 45, 119, 0.04)' : 'transparent',
            transition: 'border-color 0.2s, background-color 0.2s',
            marginBottom: 'var(--gt-space-4)',
          }}
        >
          <p style={{ fontSize: 'var(--gt-font-base)', color: 'var(--gt-text-primary)', marginBottom: 'var(--gt-space-2)' }}>
            {isDragOver ? '释放文件以上传' : '拖拽文件到此处，或点击选择文件'}
          </p>
          <p style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
            支持 .xlsx、.xls、.doc、.docx、.pdf 格式，可批量上传
          </p>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_FORMATS}
          multiple
          onChange={handleInputChange}
          style={{ display: 'none' }}
          aria-hidden="true"
        />

        {/* Upload progress list */}
        {uploadingFiles.length > 0 && (
          <div style={{ marginBottom: 'var(--gt-space-4)' }}>
            {uploadingFiles.map((uf) => (
              <div key={uf.id} style={{ marginBottom: 'var(--gt-space-2)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--gt-space-1)' }}>
                  <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)' }}>{uf.filename}</span>
                  <span
                    style={{
                      fontSize: 'var(--gt-font-xs)',
                      color: uf.status === 'error' ? 'var(--gt-danger)' : uf.status === 'success' ? 'var(--gt-success)' : 'var(--gt-text-secondary)',
                    }}
                  >
                    {uf.status === 'uploading' ? `${Math.round(uf.progress)}%` : uf.status === 'success' ? '完成' : uf.errorMessage || '失败'}
                  </span>
                </div>
                <div
                  role="progressbar"
                  aria-valuenow={Math.round(uf.progress)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${uf.filename} 上传进度`}
                  style={{
                    height: 6,
                    borderRadius: 3,
                    backgroundColor: '#e8e8e8',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${uf.progress}%`,
                      backgroundColor: uf.status === 'error' ? 'var(--gt-danger)' : '#4b2d77',
                      borderRadius: 3,
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Uploaded workpapers table */}
        {workpapers.length > 0 && (
          <table className="gt-table" aria-label="已上传底稿列表">
            <caption style={{ textAlign: 'left', padding: 'var(--gt-space-2) 0', fontWeight: 600, fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-primary)' }}>
              已上传底稿（{workpapers.length} 个）
            </caption>
            <thead>
              <tr>
                <th scope="col">文件名</th>
                <th scope="col">格式</th>
                <th scope="col">分类</th>
                <th scope="col">解析状态</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {workpapers.map((wp) => {
                const statusInfo = getStatusLabel(wp.parse_status);
                return (
                  <tr key={wp.id}>
                    <td style={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={wp.filename}>
                      {wp.filename}
                    </td>
                    <td>{getFormatLabel(wp.file_format)}</td>
                    <td>{wp.classification.business_cycle || wp.classification.workpaper_type || '—'}</td>
                    <td>
                      <span className={statusInfo.className}>{statusInfo.text}</span>
                      {wp.error_message && (
                        <span style={{ display: 'block', fontSize: 'var(--gt-font-xs)', color: 'var(--gt-danger)', marginTop: 2 }}>
                          {wp.error_message}
                        </span>
                      )}
                    </td>
                    <td>
                      <button
                        className="gt-button gt-button--secondary"
                        style={{ padding: 'var(--gt-space-1) var(--gt-space-3)', fontSize: 'var(--gt-font-xs)' }}
                        onClick={() => handleRemoveWorkpaper(wp.id)}
                        aria-label={`移除 ${wp.filename}`}
                      >
                        移除
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

export default WorkpaperUpload;
