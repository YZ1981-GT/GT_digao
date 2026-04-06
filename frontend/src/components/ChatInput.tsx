/**
 * ChatInput - 聊天输入区域组件
 *
 * 独立的输入组件，包含自动调整高度的 textarea、发送/停止按钮、Enter 发送。
 * 支持 @ 触发知识库候选列表（KnowledgePopup），选中后显示为带背景色的标签（Tag）。
 * 支持 / 触发快捷指令候选列表（CommandPopup），选中后跳转到对应工作模块。
 * 支持 📎 上传按钮（点击选择文件）和拖拽上传。
 * 支持 🎤 语音按钮（MediaRecorder 录音 → Whisper API 语音识别）。
 */
import React, { useCallback, useRef, useEffect, useState } from 'react';
import KnowledgePopup from './KnowledgePopup';
import type { KnowledgePopupHandle, KnowledgeLibrary } from './KnowledgePopup';
import CommandPopup from './CommandPopup';
import type { CommandPopupHandle } from './CommandPopup';
import type { QuickCommand } from '../types/chat';
import { chatApi } from '../services/api';

/** 支持的上传文件格式 */
const ACCEPTED_FILE_TYPES = '.pdf,.docx,.doc,.xlsx,.xls,.csv,.txt,.md,.png,.jpg,.jpeg,.bmp,.webp';

/** 格式化文件大小 */
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** 待上传的图片项 */
export interface PendingImage {
  blob: Blob;
  thumbnailUrl: string;
}

export interface ChatInputProps {
  inputText: string;
  onInputChange: (text: string) => void;
  onSend: () => void;
  onStop: () => void;
  isStreaming: boolean;
  onSelectMode: (mode: 'review' | 'generate' | 'analysis' | 'report_review') => void;
  /** 当前选中的知识库列表（受控） */
  selectedLibraries?: Array<KnowledgeLibrary>;
  /** 知识库选择变化回调 */
  onLibrariesChange?: (libs: Array<KnowledgeLibrary>) => void;
  /** 文件上传回调 */
  onFileUpload?: (file: File) => void;
  /** 当前已上传的文件信息 */
  uploadedFile?: { filename: string; size: number } | null;
  /** 移除已上传文件回调 */
  onRemoveFile?: () => void;
  /** 待上传的图片列表（受控） */
  pendingImages?: PendingImage[];
  /** 图片列表变化回调 */
  onImagesChange?: (images: PendingImage[]) => void;
}

const ChatInput: React.FC<ChatInputProps> = ({
  inputText,
  onInputChange,
  onSend,
  onStop,
  isStreaming,
  onSelectMode,
  selectedLibraries: externalLibraries,
  onLibrariesChange,
  onFileUpload,
  uploadedFile,
  onRemoveFile,
  pendingImages = [],
  onImagesChange,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const popupRef = useRef<KnowledgePopupHandle>(null);
  const commandPopupRef = useRef<CommandPopupHandle>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /* ─── @ 知识库弹窗状态 ─── */
  const [showKnowledgePopup, setShowKnowledgePopup] = useState(false);
  const [knowledgeFilter, setKnowledgeFilter] = useState('');

  /* ─── / 快捷指令弹窗状态 ─── */
  const [showCommandPopup, setShowCommandPopup] = useState(false);
  const [commandFilter, setCommandFilter] = useState('');

  /* ─── 内部知识库标签状态（当外部不受控时使用） ─── */
  const [internalLibraries, setInternalLibraries] = useState<KnowledgeLibrary[]>([]);
  const selectedLibraries = externalLibraries ?? internalLibraries;

  /* ─── 拖拽上传状态 ─── */
  const [isDragOver, setIsDragOver] = useState(false);

  /* ─── 🎤 语音录音状态 ─── */
  const [isRecording, setIsRecording] = useState(false);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [isTranscribing, setIsTranscribing] = useState(false);

  /** 检测浏览器是否支持 MediaRecorder */
  const supportsMediaRecorder = typeof window !== 'undefined' && !!window.MediaRecorder;

  const updateLibraries = useCallback(
    (libs: KnowledgeLibrary[]) => {
      if (onLibrariesChange) {
        onLibrariesChange(libs);
      } else {
        setInternalLibraries(libs);
      }
    },
    [onLibrariesChange],
  );

  /* ─── 录音清理 ─── */
  useEffect(() => {
    return () => {
      // 组件卸载时清理录音资源
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      if (recordingTimeoutRef.current) clearTimeout(recordingTimeoutRef.current);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  /** 停止录音并发送语音识别请求 */
  const stopRecordingAndTranscribe = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === 'inactive') return;

    // 清理定时器
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
    if (recordingTimeoutRef.current) {
      clearTimeout(recordingTimeoutRef.current);
      recordingTimeoutRef.current = null;
    }

    recorder.stop();
    setIsRecording(false);
  }, []);

  /** 开始录音 */
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // 选择 mimeType：优先 webm，回退 ogg
      const mimeType = MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : 'audio/ogg';
      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        // 合并 chunks
        const blob = new Blob(audioChunksRef.current, { type: mimeType });
        audioChunksRef.current = [];

        // 停止所有音轨
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((t) => t.stop());
          streamRef.current = null;
        }

        // 调用语音识别 API
        if (blob.size > 0) {
          setIsTranscribing(true);
          try {
            const resp = await chatApi.speechToText(blob);
            const data = resp.data as { success: boolean; text: string; error?: string };
            if (data.success && data.text) {
              // 将识别结果追加到输入框
              onInputChange(inputText ? inputText + ' ' + data.text : data.text);
            } else if (data.error) {
              console.error('语音识别失败:', data.error);
            }
          } catch (err) {
            console.error('语音识别请求失败:', err);
          } finally {
            setIsTranscribing(false);
          }
        }
      };

      recorder.start();
      setIsRecording(true);
      setRecordingDuration(0);

      // 计时器：每秒更新录音时长
      recordingTimerRef.current = setInterval(() => {
        setRecordingDuration((prev) => prev + 1);
      }, 1000);

      // 120 秒超时自动停止
      recordingTimeoutRef.current = setTimeout(() => {
        stopRecordingAndTranscribe();
      }, 120_000);
    } catch (err) {
      console.error('无法获取麦克风权限:', err);
    }
  }, [inputText, onInputChange, stopRecordingAndTranscribe]);

  /** 🎤 按钮点击：切换录音状态 */
  const handleVoiceClick = useCallback(() => {
    if (isRecording) {
      stopRecordingAndTranscribe();
    } else {
      startRecording();
    }
  }, [isRecording, startRecording, stopRecordingAndTranscribe]);

  /** 格式化录音时长 MM:SS */
  const formatDuration = (seconds: number): string => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  /* ─── 自动调整 textarea 高度 ─── */
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [inputText]);

  /* ─── 检测 @ 字符，提取过滤关键词 ─── */
  const detectAtTrigger = useCallback(
    (text: string, cursorPos: number) => {
      // 从光标位置往前找最近的 @
      const beforeCursor = text.slice(0, cursorPos);
      const atIndex = beforeCursor.lastIndexOf('@');

      if (atIndex === -1) {
        setShowKnowledgePopup(false);
        setKnowledgeFilter('');
        return;
      }

      // @ 后面到光标之间不能有空格（空格表示用户已结束 @ 输入）
      const afterAt = beforeCursor.slice(atIndex + 1);
      if (afterAt.includes(' ') || afterAt.includes('\n')) {
        setShowKnowledgePopup(false);
        setKnowledgeFilter('');
        return;
      }

      setShowKnowledgePopup(true);
      setKnowledgeFilter(afterAt);
    },
    [],
  );

  /* ─── onChange 处理 ─── */
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newText = e.target.value;
      onInputChange(newText);
      detectAtTrigger(newText, e.target.selectionStart ?? newText.length);

      // / 快捷指令检测：仅当文本以 / 开头时触发
      if (newText.startsWith('/')) {
        setShowCommandPopup(true);
        setCommandFilter(newText.slice(1)); // / 后面的文字作为过滤关键词
      } else {
        setShowCommandPopup(false);
        setCommandFilter('');
      }
    },
    [onInputChange, detectAtTrigger],
  );

  /* ─── 选中知识库：替换 @xxx 文本，添加标签 ─── */
  const handleSelectLibrary = useCallback(
    (library: KnowledgeLibrary) => {
      // 避免重复添加
      if (selectedLibraries.some((lib) => lib.id === library.id)) {
        setShowKnowledgePopup(false);
        setKnowledgeFilter('');
        // 仍需移除 @xxx 文本
        const textarea = textareaRef.current;
        const cursorPos = textarea?.selectionStart ?? inputText.length;
        const beforeCursor = inputText.slice(0, cursorPos);
        const atIndex = beforeCursor.lastIndexOf('@');
        if (atIndex !== -1) {
          const newText = inputText.slice(0, atIndex) + inputText.slice(cursorPos);
          onInputChange(newText);
        }
        return;
      }

      // 从输入文本中移除 @xxx
      const textarea = textareaRef.current;
      const cursorPos = textarea?.selectionStart ?? inputText.length;
      const beforeCursor = inputText.slice(0, cursorPos);
      const atIndex = beforeCursor.lastIndexOf('@');

      let newText = inputText;
      if (atIndex !== -1) {
        newText = inputText.slice(0, atIndex) + inputText.slice(cursorPos);
      }
      onInputChange(newText);

      // 添加到已选列表
      updateLibraries([...selectedLibraries, library]);

      // 关闭弹窗
      setShowKnowledgePopup(false);
      setKnowledgeFilter('');

      // 聚焦回输入框
      setTimeout(() => textareaRef.current?.focus(), 0);
    },
    [inputText, onInputChange, selectedLibraries, updateLibraries],
  );

  /* ─── 移除知识库标签 ─── */
  const handleRemoveLibrary = useCallback(
    (libraryId: string) => {
      updateLibraries(selectedLibraries.filter((lib) => lib.id !== libraryId));
    },
    [selectedLibraries, updateLibraries],
  );

  /* ─── 选中快捷指令：调用 onSelectMode 跳转，清空输入 ─── */
  const handleSelectCommand = useCallback(
    (command: QuickCommand) => {
      onSelectMode(command.mode);
      onInputChange('');
      setShowCommandPopup(false);
      setCommandFilter('');
      setTimeout(() => textareaRef.current?.focus(), 0);
    },
    [onSelectMode, onInputChange],
  );

  /* ─── 键盘事件：弹窗导航优先，然后 Enter 发送 ─── */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // 快捷指令弹窗优先
      if (showCommandPopup && commandPopupRef.current) {
        const consumed = commandPopupRef.current.handleKeyDown(e);
        if (consumed) return;
      }

      // 知识库弹窗次之
      if (showKnowledgePopup && popupRef.current) {
        const consumed = popupRef.current.handleKeyDown(e);
        if (consumed) return;
      }

      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        onSend();
      }
    },
    [onSend, showKnowledgePopup, showCommandPopup],
  );

  /* ─── 点击外部关闭弹窗 ─── */
  const handleClosePopup = useCallback(() => {
    setShowKnowledgePopup(false);
    setKnowledgeFilter('');
  }, []);

  const handleCloseCommandPopup = useCallback(() => {
    setShowCommandPopup(false);
    setCommandFilter('');
  }, []);

  /* ─── 📎 文件上传处理 ─── */
  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file && onFileUpload) {
        onFileUpload(file);
      }
      // 重置 input 以允许重复选择同一文件
      e.target.value = '';
    },
    [onFileUpload],
  );

  /* ─── 拖拽上传处理 ─── */
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
      const file = e.dataTransfer.files?.[0];
      if (file && onFileUpload) {
        onFileUpload(file);
      }
    },
    [onFileUpload],
  );

  /* ─── Ctrl+V 粘贴图片处理 ─── */
  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const items = e.clipboardData?.items;
      if (!items || !onImagesChange) return;

      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.type.startsWith('image/')) {
          e.preventDefault();
          if (pendingImages.length >= 5) return; // 最多 5 张
          const blob = item.getAsFile();
          if (!blob) return;
          const thumbnailUrl = URL.createObjectURL(blob);
          onImagesChange([...pendingImages, { blob, thumbnailUrl }]);
          return;
        }
      }
    },
    [pendingImages, onImagesChange],
  );

  /* ─── 移除待上传图片 ─── */
  const handleRemoveImage = useCallback(
    (index: number) => {
      if (!onImagesChange) return;
      const updated = [...pendingImages];
      URL.revokeObjectURL(updated[index].thumbnailUrl);
      updated.splice(index, 1);
      onImagesChange(updated);
    },
    [pendingImages, onImagesChange],
  );

  const canSend = inputText.trim().length > 0 || selectedLibraries.length > 0 || pendingImages.length > 0;

  return (
    <div
      style={{
        borderTop: '1px solid #e8e8e8',
        padding: 'var(--gt-space-3)',
        backgroundColor: '#fff',
        flexShrink: 0,
      }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* 脉冲动画样式 */}
      <style>{`
        @keyframes voice-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
      {/* ─── 拖拽上传视觉反馈 ─── */}
      {isDragOver && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundColor: 'rgba(75, 45, 119, 0.08)',
            border: '2px dashed var(--gt-primary)',
            borderRadius: 'var(--gt-radius-md)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10,
            pointerEvents: 'none',
          }}
        >
          <span style={{ color: 'var(--gt-primary)', fontSize: 'var(--gt-font-sm)', fontWeight: 500 }}>
            松开以上传文件
          </span>
        </div>
      )}

      {/* ─── 知识库标签区域 ─── */}
      {selectedLibraries.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '6px',
            marginBottom: 'var(--gt-space-2)',
          }}
        >
          {selectedLibraries.map((lib) => (
            <span
              key={lib.id}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '2px 8px',
                backgroundColor: 'rgba(75, 45, 119, 0.12)',
                color: 'var(--gt-primary)',
                borderRadius: 'var(--gt-radius-sm)',
                fontSize: 'var(--gt-font-xs)',
                fontWeight: 500,
                lineHeight: 1.6,
              }}
            >
              @{lib.name}
              <button
                onClick={() => handleRemoveLibrary(lib.id)}
                aria-label={`移除 ${lib.name}`}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  margin: 0,
                  cursor: 'pointer',
                  color: 'var(--gt-primary)',
                  fontSize: 12,
                  lineHeight: 1,
                  display: 'flex',
                  alignItems: 'center',
                  opacity: 0.6,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.opacity = '1';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.opacity = '0.6';
                }}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}

      {/* ─── 已上传文件卡片 ─── */}
      {uploadedFile && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '6px 10px',
            marginBottom: 'var(--gt-space-2)',
            backgroundColor: '#f5f5f5',
            borderRadius: 'var(--gt-radius-md)',
            fontSize: 'var(--gt-font-xs)',
          }}
        >
          <span>📄</span>
          <span
            style={{
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              color: 'var(--gt-text-primary)',
            }}
          >
            {uploadedFile.filename}
          </span>
          <span style={{ color: 'var(--gt-text-secondary)', flexShrink: 0 }}>
            {formatFileSize(uploadedFile.size)}
          </span>
          <button
            onClick={onRemoveFile}
            aria-label="移除文件"
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              margin: 0,
              cursor: 'pointer',
              color: 'var(--gt-text-secondary)',
              fontSize: 14,
              lineHeight: 1,
              display: 'flex',
              alignItems: 'center',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--gt-danger)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--gt-text-secondary)';
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ─── 图片缩略图预览区 ─── */}
      {pendingImages.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '8px',
            marginBottom: 'var(--gt-space-2)',
            alignItems: 'flex-end',
          }}
        >
          {pendingImages.map((img, idx) => (
            <div
              key={idx}
              style={{
                position: 'relative',
                width: 48,
                height: 48,
                borderRadius: 'var(--gt-radius-sm)',
                overflow: 'hidden',
                border: '1px solid #e0e0e0',
                flexShrink: 0,
              }}
            >
              <img
                src={img.thumbnailUrl}
                alt={`待上传图片 ${idx + 1}`}
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              />
              <button
                onClick={() => handleRemoveImage(idx)}
                aria-label={`移除图片 ${idx + 1}`}
                style={{
                  position: 'absolute',
                  top: -2,
                  right: -2,
                  width: 16,
                  height: 16,
                  borderRadius: '50%',
                  border: 'none',
                  backgroundColor: 'rgba(0,0,0,0.55)',
                  color: '#fff',
                  fontSize: 10,
                  lineHeight: 1,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                }}
              >
                ✕
              </button>
            </div>
          ))}
          {pendingImages.length >= 5 && (
            <span style={{ fontSize: 'var(--gt-font-xs)', color: 'var(--gt-text-secondary)' }}>
              最多 5 张
            </span>
          )}
        </div>
      )}

      {/* ─── 输入区域（含弹窗定位容器） ─── */}
      <div style={{ position: 'relative' }}>
        {/* KnowledgePopup 弹窗 */}
        <KnowledgePopup
          ref={popupRef}
          filter={knowledgeFilter}
          onSelect={handleSelectLibrary}
          onClose={handleClosePopup}
          visible={showKnowledgePopup}
        />

        {/* CommandPopup 快捷指令弹窗 */}
        <CommandPopup
          ref={commandPopupRef}
          filter={commandFilter}
          onSelect={handleSelectCommand}
          onClose={handleCloseCommandPopup}
          visible={showCommandPopup}
        />

        {/* 隐藏的文件 input */}
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_FILE_TYPES}
          style={{ display: 'none' }}
          onChange={handleFileInputChange}
        />

        <div style={{ display: 'flex', gap: 'var(--gt-space-2)', alignItems: 'flex-end' }}>
          {/* 📎 上传按钮 */}
          <button
            onClick={() => fileInputRef.current?.click()}
            title="上传文件"
            aria-label="上传文件"
            style={{
              width: 36,
              height: 36,
              borderRadius: 'var(--gt-radius-sm)',
              border: '1px solid #d0d0d0',
              backgroundColor: '#fff',
              color: 'var(--gt-text-secondary)',
              fontSize: 18,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              transition: 'border-color 0.2s, color 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--gt-primary)';
              e.currentTarget.style.color = 'var(--gt-primary)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = '#d0d0d0';
              e.currentTarget.style.color = 'var(--gt-text-secondary)';
            }}
          >
            📎
          </button>

          {/* 🎤 语音按钮（仅在支持 MediaRecorder 时显示） */}
          {supportsMediaRecorder && (
            <>
              <button
                onClick={handleVoiceClick}
                disabled={isTranscribing}
                title={isRecording ? '停止录音' : isTranscribing ? '识别中...' : '语音输入'}
                aria-label={isRecording ? '停止录音' : isTranscribing ? '识别中' : '语音输入'}
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 'var(--gt-radius-sm)',
                  border: isRecording ? '1px solid #FF5149' : '1px solid #d0d0d0',
                  backgroundColor: isRecording ? 'rgba(255, 81, 73, 0.08)' : '#fff',
                  color: isRecording ? '#FF5149' : isTranscribing ? 'var(--gt-primary)' : 'var(--gt-text-secondary)',
                  fontSize: 18,
                  cursor: isTranscribing ? 'wait' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  transition: 'border-color 0.2s, color 0.2s, background-color 0.2s',
                  animation: isRecording ? 'voice-pulse 1.5s ease-in-out infinite' : 'none',
                }}
                onMouseEnter={(e) => {
                  if (!isRecording && !isTranscribing) {
                    e.currentTarget.style.borderColor = 'var(--gt-primary)';
                    e.currentTarget.style.color = 'var(--gt-primary)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isRecording && !isTranscribing) {
                    e.currentTarget.style.borderColor = '#d0d0d0';
                    e.currentTarget.style.color = 'var(--gt-text-secondary)';
                  }
                }}
              >
                {isTranscribing ? '⏳' : '🎤'}
              </button>
              {/* 录音时长计时器 */}
              {isRecording && (
                <span
                  style={{
                    fontSize: 'var(--gt-font-xs)',
                    color: '#FF5149',
                    fontWeight: 500,
                    fontVariantNumeric: 'tabular-nums',
                    flexShrink: 0,
                    alignSelf: 'center',
                  }}
                >
                  {formatDuration(recordingDuration)}
                </span>
              )}
            </>
          )}

          <textarea
            ref={textareaRef}
            value={inputText}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder="输入消息... (/ 指令, @ 知识库)"
            rows={3}
            style={{
              flex: 1,
              resize: 'none',
              border: '1px solid #d0d0d0',
              borderRadius: 'var(--gt-radius-md)',
              padding: 'var(--gt-space-3)',
              fontSize: 'var(--gt-font-sm)',
              lineHeight: 1.6,
              outline: 'none',
              fontFamily: 'inherit',
              minHeight: 64,
              maxHeight: 160,
              overflowY: 'auto',
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = 'var(--gt-primary)';
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = '#d0d0d0';
            }}
          />
          <button
            onClick={isStreaming ? onStop : onSend}
            disabled={!isStreaming && !canSend}
            aria-label={isStreaming ? '停止生成' : '发送消息'}
            style={{
              width: 36,
              height: 36,
              borderRadius: 'var(--gt-radius-sm)',
              border: 'none',
              backgroundColor: isStreaming ? 'var(--gt-danger)' : 'var(--gt-primary)',
              color: '#fff',
              fontSize: 16,
              cursor: !isStreaming && !canSend ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              opacity: !isStreaming && !canSend ? 0.5 : 1,
              transition: 'background-color 0.2s, opacity 0.2s',
            }}
          >
            {isStreaming ? '⏹' : '➤'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatInput;
