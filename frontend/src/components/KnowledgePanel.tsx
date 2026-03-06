/**
 * 知识库管理面板组件 - 支持拖拽、调整大小和内容预览
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { knowledgeApi } from '../services/api';

interface Library {
  id: string;
  name: string;
  desc: string;
  doc_count: number;
}

interface Document {
  id: string;
  filename: string;
  size: number;
  created_at: string;
}

interface KnowledgePanelProps {
  isOpen: boolean;
  onClose: () => void;
}

const KnowledgePanel: React.FC<KnowledgePanelProps> = ({ isOpen, onClose }) => {
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [selectedLib, setSelectedLib] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number; currentFile: string; results: Array<{ name: string; success: boolean; message?: string }> } | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  // 预览相关状态
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  const [previewContent, setPreviewContent] = useState<string>('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewInfo, setPreviewInfo] = useState<{ total: number; truncated: boolean } | null>(null);

  // 拖拽和调整大小相关状态
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [size, setSize] = useState({ width: 1000, height: 600 });
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const panelRef = useRef<HTMLDivElement>(null);

  // 重置位置和预览状态
  useEffect(() => {
    if (isOpen) {
      loadLibraries();
      setPosition({ x: 0, y: 0 });
      setPreviewDoc(null);
      setPreviewContent('');
    }
  }, [isOpen]);

  useEffect(() => {
    if (selectedLib) {
      loadDocuments(selectedLib);
      setPreviewDoc(null);
    }
  }, [selectedLib]);

  // 拖拽处理
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.drag-handle')) {
      setIsDragging(true);
      setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
    }
  }, [position]);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setIsResizing(true);
    setDragStart({ x: e.clientX, y: e.clientY });
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging) {
        setPosition({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
      } else if (isResizing) {
        const dx = e.clientX - dragStart.x;
        const dy = e.clientY - dragStart.y;
        setSize(prev => ({
          width: Math.max(600, prev.width + dx),
          height: Math.max(400, prev.height + dy)
        }));
        setDragStart({ x: e.clientX, y: e.clientY });
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      setIsResizing(false);
    };

    if (isDragging || isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      return () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [isDragging, isResizing, dragStart]);

  // 预览文档
  const handlePreview = async (doc: Document) => {
    if (!selectedLib) return;
    setPreviewDoc(doc);
    setPreviewLoading(true);
    try {
      const response = await knowledgeApi.previewDocument(selectedLib, doc.id);
      if (response.data.success) {
        setPreviewContent(response.data.content);
        setPreviewInfo({
          total: response.data.total_length,
          truncated: response.data.truncated
        });
      }
    } catch (error) {
      console.error('预览文档失败:', error);
      setPreviewContent('预览加载失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const loadLibraries = async () => {
    try {
      setLoading(true);
      const response = await knowledgeApi.getLibraries();
      if (response.data.success) {
        setLibraries(response.data.libraries);
        if (response.data.libraries.length > 0 && !selectedLib) {
          setSelectedLib(response.data.libraries[0].id);
        }
      }
    } catch (error) {
      console.error('加载知识库列表失败:', error);
      setMessage({ type: 'error', text: '加载知识库列表失败' });
    } finally {
      setLoading(false);
    }
  };

  const loadDocuments = async (libraryId: string) => {
    try {
      const response = await knowledgeApi.getDocuments(libraryId);
      if (response.data.success) {
        setDocuments(response.data.documents);
      }
    } catch (error) {
      console.error('加载文档列表失败:', error);
    }
  };

  const SUPPORTED_EXTS = ['.txt', '.md', '.markdown', '.pdf', '.doc', '.docx'];

  const isSupportedFile = (name: string) => {
    const ext = name.substring(name.lastIndexOf('.')).toLowerCase();
    return SUPPORTED_EXTS.includes(ext);
  };

  // 递归读取 DataTransferItem 中的所有文件（支持多文件夹）
  const readAllEntries = async (items: DataTransferItemList): Promise<File[]> => {
    const files: File[] = [];

    const readEntry = (entry: FileSystemEntry): Promise<void> => {
      return new Promise((resolve) => {
        if (entry.isFile) {
          (entry as FileSystemFileEntry).file((f) => {
            if (isSupportedFile(f.name)) files.push(f);
            resolve();
          }, () => resolve());
        } else if (entry.isDirectory) {
          const reader = (entry as FileSystemDirectoryEntry).createReader();
          const readBatch = () => {
            reader.readEntries(async (entries) => {
              if (entries.length === 0) { resolve(); return; }
              for (const e of entries) await readEntry(e);
              readBatch(); // 继续读取（readEntries 可能分批返回）
            }, () => resolve());
          };
          readBatch();
        } else {
          resolve();
        }
      });
    };

    const promises: Promise<void>[] = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry?.();
      if (entry) promises.push(readEntry(entry));
    }
    await Promise.all(promises);
    return files;
  };

  // 通用上传逻辑
  const doUploadFiles = async (files: File[]) => {
    if (!selectedLib || files.length === 0) return;

    const totalFiles = files.length;
    try {
      setUploading(true);
      setMessage(null);
      setUploadProgress({ current: 0, total: totalFiles, currentFile: files[0].name, results: [] });

      let successCount = 0;
      let failCount = 0;
      const results: Array<{ name: string; success: boolean; message?: string }> = [];

      for (let i = 0; i < totalFiles; i++) {
        const file = files[i];
        setUploadProgress(prev => prev ? { ...prev, current: i, currentFile: file.name } : null);

        try {
          const response = await knowledgeApi.uploadDocument(selectedLib, file);
          if (response.data.success) {
            successCount++;
            results.push({ name: file.name, success: true, message: response.data.message });
          } else {
            failCount++;
            results.push({ name: file.name, success: false, message: response.data.message });
          }
        } catch (error: any) {
          console.error(`上传文档 ${file.name} 失败:`, error);
          failCount++;
          results.push({ name: file.name, success: false, message: error.message || '上传失败' });
        }

        setUploadProgress(prev => prev ? { ...prev, current: i + 1, results: [...results] } : null);
      }

      if (failCount === 0) {
        setMessage({ type: 'success', text: `成功上传 ${successCount} 个文档` });
      } else if (successCount === 0) {
        setMessage({ type: 'error', text: `上传失败，${failCount} 个文档上传失败` });
      } else {
        setMessage({ type: 'success', text: `上传完成：成功 ${successCount} 个，失败 ${failCount} 个` });
      }

      loadDocuments(selectedLib);
      loadLibraries();
    } catch (error) {
      console.error('上传文档失败:', error);
      setMessage({ type: 'error', text: '上传文档失败' });
    } finally {
      setUploading(false);
      setTimeout(() => setUploadProgress(null), 3000);
      if (fileInputRef.current) fileInputRef.current.value = '';
      if (folderInputRef.current) folderInputRef.current.value = '';
    }
    setTimeout(() => setMessage(null), 5000);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawFiles = e.target.files;
    if (!rawFiles || rawFiles.length === 0 || !selectedLib) return;

    const files = Array.from(rawFiles).filter((f) => isSupportedFile(f.name));

    if (files.length === 0) {
      setMessage({ type: 'error', text: '没有找到支持的文档格式（.txt, .md, .pdf, .doc, .docx）' });
      setTimeout(() => setMessage(null), 5000);
      e.target.value = '';
      return;
    }

    await doUploadFiles(files);
  };

  // 拖拽上传处理（支持多文件夹+多文件混合）
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (uploading || !selectedLib) return;

    const items = e.dataTransfer.items;
    if (!items || items.length === 0) return;

    setMessage({ type: 'success', text: '正在扫描文件...' });
    const files = await readAllEntries(items);

    if (files.length === 0) {
      setMessage({ type: 'error', text: '没有找到支持的文档格式（.txt, .md, .pdf, .doc, .docx）' });
      setTimeout(() => setMessage(null), 5000);
      return;
    }

    await doUploadFiles(files);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!uploading) setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDelete = async (docId: string) => {
    if (!selectedLib || !window.confirm('确定要删除这个文档吗？')) return;

    try {
      const response = await knowledgeApi.deleteDocument(selectedLib, docId);
      if (response.data.success) {
        setMessage({ type: 'success', text: '文档已删除' });
        loadDocuments(selectedLib);
        loadLibraries();
      }
    } catch (error) {
      console.error('删除文档失败:', error);
      setMessage({ type: 'error', text: '删除文档失败' });
    }
    setTimeout(() => setMessage(null), 3000);
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };

  if (!isOpen) return null;

  const selectedLibInfo = libraries.find(lib => lib.id === selectedLib);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div
        ref={panelRef}
        className="bg-white rounded-lg shadow-xl flex flex-col select-none relative"
        style={{
          width: size.width,
          height: size.height,
          transform: `translate(${position.x}px, ${position.y}px)`,
          cursor: isDragging ? 'grabbing' : 'default'
        }}
        onMouseDown={handleMouseDown}
      >
        {/* 标题栏 - 可拖拽 */}
        <div className="drag-handle px-6 py-4 border-b border-gray-200 flex justify-between items-center cursor-grab active:cursor-grabbing bg-gray-50 rounded-t-lg">
          <h2 className="text-xl font-semibold text-gray-900">📚 知识库管理</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
          >
            ×
          </button>
        </div>

        {/* 消息提示 */}
        {message && (
          <div className={`mx-6 mt-4 p-3 rounded-md text-sm ${
            message.type === 'success'
              ? 'bg-green-100 text-green-700 border border-green-200'
              : 'bg-red-100 text-red-700 border border-red-200'
          }`}>
            {message.text}
          </div>
        )}

        {/* 上传进度 */}
        {uploadProgress && (
          <div className="mx-6 mt-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
            <div className="flex items-center justify-between text-sm text-blue-800 mb-2">
              <span>
                {uploadProgress.current < uploadProgress.total
                  ? `正在上传: ${uploadProgress.currentFile}`
                  : '上传完成'}
              </span>
              <span>{uploadProgress.current} / {uploadProgress.total}</span>
            </div>
            <div className="w-full bg-blue-200 rounded-full h-2 mb-2">
              <div
                className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                style={{ width: `${(uploadProgress.current / uploadProgress.total) * 100}%` }}
              />
            </div>
            {uploadProgress.results.length > 0 && (
              <div className="space-y-1 max-h-32 overflow-y-auto">
                {uploadProgress.results.map((r, idx) => (
                  <div key={idx} className="flex items-center text-xs">
                    <span className={r.success ? 'text-green-600' : 'text-red-600'}>
                      {r.success ? '✅' : '❌'}
                    </span>
                    <span className="ml-1.5 text-gray-700 truncate">{r.name}</span>
                    {r.message && (
                      <span className={`ml-1 truncate ${r.success ? 'text-gray-500' : 'text-red-500'}`}>- {r.message}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="flex flex-1 overflow-hidden">
          {/* 左侧知识库列表 */}
          <div className="w-64 border-r border-gray-200 p-4 overflow-y-auto">
            <h3 className="text-sm font-medium text-gray-500 mb-3">知识库列表</h3>
            {loading ? (
              <div className="text-center text-gray-500 py-4">加载中...</div>
            ) : (
              <div className="space-y-2">
                {libraries.map(lib => (
                  <div
                    key={lib.id}
                    onClick={() => setSelectedLib(lib.id)}
                    className={`p-3 rounded-lg cursor-pointer transition-colors ${
                      selectedLib === lib.id
                        ? 'bg-blue-50 border border-blue-200'
                        : 'bg-gray-50 hover:bg-gray-100 border border-transparent'
                    }`}
                  >
                    <div className="font-medium text-gray-900">{lib.name}</div>
                    <div className="text-xs text-gray-500 mt-1">{lib.desc}</div>
                    <div className="text-xs text-blue-600 mt-1">{lib.doc_count} 个文档</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 右侧文档列表 - 拖拽上传区 */}
          <div
            className={`flex-1 p-4 overflow-y-auto relative ${isDragOver ? 'bg-blue-50' : ''}`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
          >
            {/* 拖拽覆盖层 */}
            {isDragOver && (
              <div className="absolute inset-0 bg-blue-50 bg-opacity-90 border-2 border-dashed border-blue-400 rounded-lg flex items-center justify-center z-10 pointer-events-none">
                <div className="text-center">
                  <div className="text-4xl mb-2">📂</div>
                  <div className="text-blue-700 font-medium">松开鼠标上传文件或文件夹</div>
                  <div className="text-xs text-blue-500 mt-1">支持同时拖入多个文件夹</div>
                </div>
              </div>
            )}
            {selectedLibInfo && (
              <>
                <div className="flex justify-between items-center mb-4">
                  <div>
                    <h3 className="text-lg font-medium text-gray-900">{selectedLibInfo.name}</h3>
                    <p className="text-sm text-gray-500">{selectedLibInfo.desc}</p>
                  </div>
                  <div className="flex gap-2">
                    <input
                      ref={fileInputRef}
                      type="file"
                      onChange={handleUpload}
                      accept=".txt,.md,.markdown,.pdf,.doc,.docx"
                      multiple
                      className="hidden"
                      id="file-upload"
                    />
                    <label
                      htmlFor="file-upload"
                      className={`inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white cursor-pointer ${
                        uploading
                          ? 'bg-gray-400 cursor-not-allowed'
                          : 'bg-blue-600 hover:bg-blue-700'
                      }`}
                    >
                      {uploading ? '上传中...' : '📤 上传文档'}
                    </label>
                    <input
                      ref={folderInputRef}
                      type="file"
                      onChange={handleUpload}
                      accept=".txt,.md,.markdown,.pdf,.doc,.docx"
                      className="hidden"
                      id="folder-upload"
                      {...{ webkitdirectory: '', directory: '' } as any}
                    />
                    <label
                      htmlFor="folder-upload"
                      className={`inline-flex items-center px-4 py-2 border text-sm font-medium rounded-md cursor-pointer ${
                        uploading
                          ? 'bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed'
                          : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      📁 上传文件夹
                    </label>
                  </div>
                </div>

                {documents.length === 0 ? (
                  <div
                    className="text-center text-gray-500 py-12 cursor-pointer hover:bg-gray-50 rounded-lg border-2 border-dashed border-gray-300 hover:border-blue-400 transition-colors"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <div className="text-4xl mb-2">📭</div>
                    <div>暂无文档，点击此处上传</div>
                    <div className="text-xs mt-2">支持 .txt, .md, .pdf, .doc, .docx 格式</div>
                    <div className="text-xs text-blue-600">支持多文件上传，可拖拽多个文件夹到此处</div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {documents.map(doc => (
                      <div
                        key={doc.id}
                        onClick={() => handlePreview(doc)}
                        className={`flex items-center justify-between p-3 rounded-lg cursor-pointer transition-colors ${
                          previewDoc?.id === doc.id
                            ? 'bg-blue-50 border border-blue-200'
                            : 'bg-gray-50 hover:bg-gray-100'
                        }`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-gray-900 truncate">{doc.filename}</div>
                          <div className="text-xs text-gray-500">
                            {formatSize(doc.size)} · {doc.created_at}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 ml-2">
                          <button
                            onClick={(e) => { e.stopPropagation(); handlePreview(doc); }}
                            className="text-blue-500 hover:text-blue-700 text-sm"
                          >
                            👁️ 预览
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDelete(doc.id); }}
                            className="text-red-500 hover:text-red-700 text-sm"
                          >
                            🗑️ 删除
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          {/* 预览面板 */}
          {previewDoc && (
            <div className="w-80 border-l border-gray-200 flex flex-col bg-gray-50">
              <div className="p-3 border-b border-gray-200 flex justify-between items-center">
                <div className="font-medium text-gray-900 truncate text-sm" title={previewDoc.filename}>
                  📄 {previewDoc.filename}
                </div>
                <button
                  onClick={() => setPreviewDoc(null)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  ×
                </button>
              </div>
              <div className="flex-1 p-3 overflow-y-auto">
                {previewLoading ? (
                  <div className="text-center text-gray-500 py-8">加载中...</div>
                ) : (
                  <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                    {previewContent}
                  </pre>
                )}
              </div>
              {previewInfo && (
                <div className="p-2 border-t border-gray-200 text-xs text-gray-500 text-center">
                  总字符数: {previewInfo.total.toLocaleString()}
                  {previewInfo.truncated && ' (已截断)'}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 底部说明 */}
        <div className="px-6 py-3 border-t border-gray-200 bg-gray-50 text-sm text-gray-500 rounded-b-lg">
          💡 上传的文档会在AI生成内容时自动检索，作为参考资料优先使用。支持拖拽多个文件夹到文档区域批量上传。
        </div>

        {/* 调整大小手柄 */}
        <div
          className="absolute bottom-0 right-0 w-4 h-4 cursor-se-resize"
          onMouseDown={handleResizeStart}
          style={{
            background: 'linear-gradient(135deg, transparent 50%, #cbd5e1 50%)',
            borderBottomRightRadius: '0.5rem'
          }}
        />
      </div>
    </div>
  );
};

export default KnowledgePanel;
