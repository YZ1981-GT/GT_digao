/**
 * 知识库搜索面板组件 - 弹窗形式搜索已上传的知识库内容
 */
import React, { useState, useEffect } from 'react';
import { knowledgeApi } from '../services/api';
import type { KnowledgeLibrary } from '../types';

interface KnowledgeSearchPanelProps {
  libraries: KnowledgeLibrary[];
  onClose: () => void;
}

const KnowledgeSearchPanel: React.FC<KnowledgeSearchPanelProps> = ({ libraries, onClose }) => {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchContent, setSearchContent] = useState('');
  const [selectedLibIds, setSelectedLibIds] = useState<string[]>([]);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // libraries 变化时自动选中有文档的库
  useEffect(() => {
    setSelectedLibIds(libraries.filter(l => l.doc_count > 0).map(l => l.id));
  }, [libraries]);

  const toggleLib = (libId: string) => {
    setSelectedLibIds(prev =>
      prev.includes(libId) ? prev.filter(id => id !== libId) : [...prev, libId]
    );
  };

  const handleSearch = async () => {
    const q = query.trim();
    if (!q) return;
    if (selectedLibIds.length === 0) {
      setMessage({ type: 'error', text: '请至少选择一个知识库' });
      return;
    }
    setSearching(true);
    setSearchContent('');
    setMessage(null);
    try {
      const response = await knowledgeApi.searchKnowledge(selectedLibIds, q);
      if (response.data.success) {
        const content = response.data.content;
        if (content && content.trim()) {
          setSearchContent(content);
        } else {
          setMessage({ type: 'error', text: '未找到相关内容' });
        }
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.message || '搜索失败' });
    } finally {
      setSearching(false);
    }
  };

  const hasDocsLibraries = libraries.filter(l => l.doc_count > 0);

  // 按 ESC 关闭
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black bg-opacity-50" onClick={onClose} />

      {/* 弹窗主体 */}
      <div className="relative bg-white rounded-lg shadow-xl w-full max-w-3xl mx-4 max-h-[85vh] flex flex-col">
        {/* 标题栏 */}
        <div className="px-6 py-4 bg-gray-50 border-b border-gray-200 flex items-center justify-between rounded-t-lg flex-shrink-0">
          <h3 className="text-base font-semibold text-gray-900">🔍 知识库搜索</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none p-1"
            aria-label="关闭"
          >
            ×
          </button>
        </div>

        {/* 内容区 */}
        <div className="p-6 overflow-y-auto flex-1">
          {hasDocsLibraries.length === 0 ? (
            <div className="text-center text-gray-500 py-10 text-sm">
              📭 暂无知识库文档，请先在知识库管理中上传文档
            </div>
          ) : (
            <>
              {/* 知识库选择 */}
              <div className="mb-4">
                <div className="text-sm text-gray-600 mb-2">选择搜索范围：</div>
                <div className="flex flex-wrap gap-2">
                  {hasDocsLibraries.map(lib => (
                    <label
                      key={lib.id}
                      className={`inline-flex items-center px-3 py-1.5 rounded-full text-sm cursor-pointer transition-colors ${
                        selectedLibIds.includes(lib.id)
                          ? 'bg-blue-100 text-blue-700 border border-blue-300'
                          : 'bg-gray-100 text-gray-600 border border-gray-200 hover:bg-gray-200'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedLibIds.includes(lib.id)}
                        onChange={() => toggleLib(lib.id)}
                        className="sr-only"
                      />
                      {lib.name} ({lib.doc_count})
                    </label>
                  ))}
                </div>
              </div>

              {/* 搜索框 */}
              <div className="flex gap-2 mb-4">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
                  placeholder="输入关键词搜索知识库内容..."
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  disabled={searching}
                  autoFocus
                />
                <button
                  onClick={handleSearch}
                  disabled={searching || !query.trim()}
                  className="px-5 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
                >
                  {searching ? '搜索中...' : '搜索'}
                </button>
              </div>

              {/* 消息提示 */}
              {message && (
                <div className={`mb-4 p-3 rounded text-sm ${
                  message.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'
                }`}>{message.text}</div>
              )}

              {/* 搜索结果 */}
              {searchContent && (
                <div className="border border-gray-200 rounded-lg bg-gray-50 max-h-96 overflow-y-auto">
                  <div className="p-4">
                    <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                      {searchContent}
                    </pre>
                  </div>
                </div>
              )}

              {!searchContent && !message && (
                <div className="mt-4 text-sm text-gray-500 text-center">
                  💡 输入关键词搜索已上传到知识库中的文档内容
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default KnowledgeSearchPanel;
