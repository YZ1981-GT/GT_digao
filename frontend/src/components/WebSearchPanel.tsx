/**
 * 网络搜索面板组件 - 搜索互联网资料并收集参考内容
 */
import React, { useState, useRef } from 'react';
import { searchApi } from '../services/api';
import type { SearchResult, WebReference } from '../types';

interface WebSearchPanelProps {
  references: WebReference[];
  onReferencesChange: (refs: WebReference[]) => void;
  onClose: () => void;
}

const WebSearchPanel: React.FC<WebSearchPanelProps> = ({ references, onReferencesChange, onClose }) => {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loadingUrl, setLoadingUrl] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState<{ title: string; url: string; content: string } | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setResults([]);
    setPreviewContent(null);
    setMessage(null);
    try {
      const response = await searchApi.search(q);
      if (response.data.success) {
        setResults(response.data.results);
        if (response.data.results.length === 0) {
          setMessage({ type: 'error', text: '未找到相关结果' });
        }
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.message || '搜索失败' });
    } finally {
      setSearching(false);
    }
  };

  const handleLoadUrl = async (url: string, title: string) => {
    setLoadingUrl(url);
    setMessage(null);
    try {
      const response = await searchApi.loadUrl(url, 8000);
      if (response.data.success) {
        setPreviewContent({
          title: response.data.title || title,
          url,
          content: response.data.content,
        });
      } else {
        setMessage({ type: 'error', text: response.data.message || '读取失败' });
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.message || '读取网页失败' });
    } finally {
      setLoadingUrl(null);
    }
  };

  const handleAddReference = (ref: { title: string; url: string; content: string }) => {
    if (references.some(r => r.url === ref.url)) {
      setMessage({ type: 'error', text: '该参考资料已添加' });
      return;
    }
    onReferencesChange([...references, ref]);
    setMessage({ type: 'success', text: `已添加「${ref.title}」` });
    setTimeout(() => setMessage(null), 2000);
  };

  const handleRemoveReference = (url: string) => {
    onReferencesChange(references.filter(r => r.url !== url));
  };

  return (
    <div className="mt-4 border border-gray-200 rounded-lg bg-white overflow-hidden">
      {/* 标题栏 */}
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <h4 className="text-sm font-medium text-gray-900">🌐 网络搜索参考资料</h4>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
      </div>

      <div className="p-4">
        {/* 搜索框 */}
        <div className="flex gap-2 mb-3">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
            placeholder="输入关键词搜索互联网资料..."
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={searching}
          />
          <button
            onClick={handleSearch}
            disabled={searching || !query.trim()}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
          >
            {searching ? '搜索中...' : '搜索'}
          </button>
        </div>

        {/* 消息提示 */}
        {message && (
          <div className={`mb-3 p-2 rounded text-xs ${
            message.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'
          }`}>{message.text}</div>
        )}

        <div className="flex gap-4" style={{ maxHeight: '400px' }}>
          {/* 左侧：搜索结果 */}
          <div className="flex-1 overflow-y-auto">
            {results.length > 0 && (
              <div className="space-y-2">
                {results.map((r, idx) => (
                  <div
                    key={idx}
                    className={`p-3 border rounded-lg cursor-pointer transition-colors hover:bg-blue-50 ${
                      previewContent?.url === r.href ? 'border-blue-300 bg-blue-50' : 'border-gray-200'
                    }`}
                    onClick={() => handleLoadUrl(r.href, r.title)}
                  >
                    <div className="text-sm font-medium text-blue-700 truncate">{r.title}</div>
                    <div className="text-xs text-gray-500 truncate mt-0.5">{r.href}</div>
                    <div className="text-xs text-gray-600 mt-1 line-clamp-2">{r.body}</div>
                    <div className="flex items-center gap-2 mt-2">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleLoadUrl(r.href, r.title); }}
                        disabled={loadingUrl === r.href}
                        className="text-xs text-blue-600 hover:text-blue-800"
                      >
                        {loadingUrl === r.href ? '读取中...' : '👁️ 读取全文'}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleAddReference({ title: r.title, url: r.href, content: r.body });
                        }}
                        disabled={references.some(ref => ref.url === r.href)}
                        className="text-xs text-green-600 hover:text-green-800 disabled:text-gray-400"
                      >
                        {references.some(ref => ref.url === r.href) ? '✅ 已添加' : '➕ 添加摘要'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 右侧：内容预览 */}
          {previewContent && (
            <div className="flex-1 border border-gray-200 rounded-lg flex flex-col bg-gray-50">
              <div className="p-3 border-b border-gray-200 flex items-center justify-between">
                <div className="text-sm font-medium text-gray-900 truncate flex-1" title={previewContent.title}>
                  📄 {previewContent.title}
                </div>
                <button
                  onClick={() => handleAddReference(previewContent)}
                  disabled={references.some(r => r.url === previewContent.url)}
                  className="ml-2 px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 disabled:bg-gray-400 whitespace-nowrap"
                >
                  {references.some(r => r.url === previewContent.url) ? '✅ 已添加' : '➕ 添加全文'}
                </button>
              </div>
              <div className="flex-1 p-3 overflow-y-auto">
                <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                  {previewContent.content}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* 已收集的参考资料 */}
        {references.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <div className="text-xs font-medium text-gray-700 mb-2">
              📎 已收集 {references.length} 条参考资料（将在生成时提供给AI）
            </div>
            <div className="flex flex-wrap gap-2">
              {references.map((ref, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center gap-1 px-2 py-1 bg-blue-50 border border-blue-200 rounded text-xs text-blue-700"
                >
                  {ref.title.length > 20 ? ref.title.substring(0, 20) + '...' : ref.title}
                  <button
                    onClick={() => handleRemoveReference(ref.url)}
                    className="text-blue-400 hover:text-red-500 ml-1"
                  >×</button>
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="mt-3 text-xs text-gray-500">
          💡 搜索互联网资料，点击结果可读取全文。添加的参考资料会在AI生成内容时作为补充参考。
        </div>
      </div>
    </div>
  );
};

export default WebSearchPanel;
