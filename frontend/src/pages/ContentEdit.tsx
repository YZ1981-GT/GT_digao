/**
 * 内容编辑页面 - 完整文档预览和生成
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { OutlineData, OutlineItem, KnowledgeLibrary, KnowledgeDocument } from '../types';
import { DocumentTextIcon, PlayIcon, DocumentArrowDownIcon, CheckCircleIcon, ExclamationCircleIcon } from '@heroicons/react/24/outline';
import { contentApi, ChapterContentRequest, documentApi, knowledgeApi } from '../services/api';
import { saveAs } from 'file-saver';
import { draftStorage } from '../utils/draftStorage';
import { SSEParser } from '../utils/sseParser';
import WebSearchPanel from '../components/WebSearchPanel';
import KnowledgeSearchPanel from '../components/KnowledgeSearchPanel';
import type { WebReference } from '../types';

interface ContentEditProps {
  outlineData: OutlineData | null;
  projectOverview: string;
  selectedChapter: string;
  onChapterSelect: (chapterId: string) => void;
}

interface GenerationProgress {
  total: number;
  completed: number;
  current: string;
  failed: string[];
  generating: Set<string>;
}

interface ChapterDialogState {
  isOpen: boolean;
  chapterId: string;
  chapterTitle: string;
  chapterContent: string;
  messages: Array<{role: string; content: string}>;
  userInput: string;
  isRevising: boolean;
  targetWordCount?: number;
}

interface ManualEditState {
  isOpen: boolean;
  chapterId: string;
  chapterTitle: string;
  editContent: string;
  aiInput: string;
  aiProcessing: boolean;
  selectedText: string;
  selectionStart: number;
  selectionEnd: number;
  targetWordCount?: number;
}


const ContentEdit: React.FC<ContentEditProps> = ({
  outlineData,
  projectOverview,
  selectedChapter,
  onChapterSelect,
}) => {
  const [isGenerating, setIsGenerating] = useState(false);
  const shouldStopRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [progress, setProgress] = useState<GenerationProgress>({
    total: 0,
    completed: 0,
    current: '',
    failed: [],
    generating: new Set<string>()
  });
  const [leafItems, setLeafItems] = useState<OutlineItem[]>([]);
  
  // 章节对话状态
  const [chapterDialog, setChapterDialog] = useState<ChapterDialogState>({
    isOpen: false,
    chapterId: '',
    chapterTitle: '',
    chapterContent: '',
    messages: [],
    userInput: '',
    isRevising: false,
  });
  
  // 手动编辑状态
  const [manualEdit, setManualEdit] = useState<ManualEditState>({
    isOpen: false,
    chapterId: '',
    chapterTitle: '',
    editContent: '',
    aiInput: '',
    aiProcessing: false,
    selectedText: '',
    selectionStart: 0,
    selectionEnd: 0,
  });
  
  // 知识库相关状态
  const [showKnowledgeSelector, setShowKnowledgeSelector] = useState(false);
  const [knowledgeLibraries, setKnowledgeLibraries] = useState<KnowledgeLibrary[]>([]);
  const [libraryDocuments, setLibraryDocuments] = useState<{[key: string]: KnowledgeDocument[]}>({});
  const [selectedDocuments, setSelectedDocuments] = useState<{[key: string]: string[]}>({});
  const [expandedLibraries, setExpandedLibraries] = useState<Set<string>>(new Set());

  // 网络搜索相关状态
  const [showWebSearch, setShowWebSearch] = useState(false);
  const [webReferences, setWebReferences] = useState<WebReference[]>([]);
  const [showKnowledgeSearch, setShowKnowledgeSearch] = useState(false);

  // 加载知识库列表
  useEffect(() => {
    loadKnowledgeLibraries();
  }, []);

  const loadKnowledgeLibraries = async () => {
    try {
      const response = await knowledgeApi.getLibraries();
      if (response.data.success) {
        setKnowledgeLibraries(response.data.libraries);
      }
    } catch (error) {
      console.error('加载知识库列表失败:', error);
    }
  };

  const toggleLibraryExpand = async (libId: string) => {
    const newExpanded = new Set(expandedLibraries);
    if (newExpanded.has(libId)) {
      newExpanded.delete(libId);
    } else {
      newExpanded.add(libId);
      // 加载该库的文档列表
      if (!libraryDocuments[libId]) {
        try {
          const response = await knowledgeApi.getDocuments(libId);
          if (response.data.success) {
            setLibraryDocuments(prev => ({
              ...prev,
              [libId]: response.data.documents as KnowledgeDocument[]
            }));
            // 默认选中该库的所有文档
            setSelectedDocuments(prev => ({
              ...prev,
              [libId]: (response.data.documents as KnowledgeDocument[]).map((doc) => doc.id)
            }));
          }
        } catch (error) {
          console.error('加载文档列表失败:', error);
        }
      }
    }
    setExpandedLibraries(newExpanded);
  };

  const toggleDocumentSelection = (libId: string, docId: string) => {
    setSelectedDocuments(prev => {
      const libDocs = prev[libId] || [];
      const newLibDocs = libDocs.includes(docId)
        ? libDocs.filter(id => id !== docId)
        : [...libDocs, docId];
      return { ...prev, [libId]: newLibDocs };
    });
  };

  const selectAllDocuments = (libId: string) => {
    const docs = libraryDocuments[libId] || [];
    setSelectedDocuments(prev => ({
      ...prev,
      [libId]: docs.map((doc) => doc.id)
    }));
  };

  const clearAllDocuments = (libId: string) => {
    setSelectedDocuments(prev => ({
      ...prev,
      [libId]: []
    }));
  };

  // 收集所有叶子节点
  const collectLeafItems = useCallback((items: OutlineItem[]): OutlineItem[] => {
    let leaves: OutlineItem[] = [];
    items.forEach(item => {
      if (!item.children || item.children.length === 0) {
        leaves.push(item);
      } else {
        leaves = leaves.concat(collectLeafItems(item.children));
      }
    });
    return leaves;
  }, []);

  // 获取章节的上级章节信息
  const getParentChapters = useCallback((targetId: string, items: OutlineItem[], parents: OutlineItem[] = []): OutlineItem[] => {
    for (const item of items) {
      if (item.id === targetId) {
        return parents;
      }
      if (item.children && item.children.length > 0) {
        const found = getParentChapters(targetId, item.children, [...parents, item]);
        if (found.length > 0 || item.children.some(child => child.id === targetId)) {
          return found.length > 0 ? found : [...parents, item];
        }
      }
    }
    return [];
  }, []);

  // 获取章节的同级章节信息
  const getSiblingChapters = useCallback((targetId: string, items: OutlineItem[]): OutlineItem[] => {
    // 直接在当前级别查找
    if (items.some(item => item.id === targetId)) {
      return items;
    }
    
    // 递归在子级别查找
    for (const item of items) {
      if (item.children && item.children.length > 0) {
        const siblings = getSiblingChapters(targetId, item.children);
        if (siblings.length > 0) {
          return siblings;
        }
      }
    }
    
    return [];
  }, []);

  useEffect(() => {
    if (outlineData) {
      const leaves = collectLeafItems(outlineData.outline);
      // 恢复本地缓存的正文内容（仅对叶子节点生效）
      const filtered = draftStorage.filterContentByOutlineLeaves(outlineData.outline);
      const mergedLeaves = leaves.map((leaf) => {
        const cached = filtered[leaf.id];
        return cached ? { ...leaf, content: cached } : leaf;
      });

      // 目录变更时，顺手清理掉无效的旧缓存（只保留当前叶子节点）
      draftStorage.saveContentById(filtered);

      setLeafItems(mergedLeaves);
      setProgress(prev => ({ ...prev, total: leaves.length }));
    }
  }, [outlineData, collectLeafItems]);

  // 获取叶子节点的实时内容
  const getLeafItemContent = (itemId: string): string | undefined => {
    const leafItem = leafItems.find(leaf => leaf.id === itemId);
    return leafItem?.content;
  };

  // 检查是否为叶子节点
  const isLeafNode = (item: OutlineItem): boolean => {
    return !item.children || item.children.length === 0;
  };

  // 渲染目录结构
  const renderOutline = (items: OutlineItem[], level: number = 1): React.ReactElement[] => {
    return items.map((item) => {
      const isLeaf = isLeafNode(item);
      const currentContent = isLeaf ? getLeafItemContent(item.id) : item.content;
      
      return (
        <div key={item.id} className={level === 1 ? 'mb-8' : 'mb-4'}>
          {/* 标题 */}
          <div className={`${level === 1 ? 'text-xl font-bold' : level === 2 ? 'text-lg font-semibold' : 'text-base font-semibold'} text-gray-900 mb-2`}>
            {item.id} {item.title}
          </div>
          
          {/* 描述 */}
          <div className="text-base text-gray-600 mb-4">
            {item.description}
          </div>

          {/* 内容（仅叶子节点） */}
          {isLeaf && (
            <>
              <div className="border-l-4 border-blue-200 pl-4 mb-4">
                {currentContent ? (
                  <div className="prose max-w-none prose-p:text-base prose-p:leading-relaxed">
                    <ReactMarkdown>{currentContent}</ReactMarkdown>
                  </div>
                ) : (
                  <div className="text-gray-400 italic py-4">
                    <DocumentTextIcon className="inline w-4 h-4 mr-2" />
                    {progress.generating.has(item.id) ? (
                      <span className="text-blue-600">正在生成内容...</span>
                    ) : (
                      '内容待生成...'
                    )}
                  </div>
                )}
              </div>
              
              {/* 章节操作按钮 - 始终显示（正在生成本章节时除外） */}
              {!progress.generating.has(item.id) && (
                <div className="flex flex-wrap items-center gap-2 mb-6 pl-4">
                  {currentContent ? (
                    <>
                      <button
                        onClick={() => handleConfirmChapter(item.id)}
                        className="inline-flex items-center px-3 py-1.5 border border-green-300 text-sm font-medium rounded-md text-green-700 bg-green-50 hover:bg-green-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
                      >
                        <CheckCircleIcon className="w-4 h-4 mr-1" />
                        确认
                      </button>
                      
                      <div className="text-sm text-gray-600 px-3 py-1.5 bg-gray-50 rounded-md border border-gray-200">
                        📊 字数: {getChapterWordCount(currentContent)}
                        {item.target_word_count && (
                          <span className="text-gray-400 ml-1">/ 目标 {item.target_word_count}</span>
                        )}
                      </div>
                      
                      <button
                        onClick={() => handleOpenManualEdit(item)}
                        className="inline-flex items-center px-3 py-1.5 border border-purple-300 text-sm font-medium rounded-md text-purple-700 bg-purple-50 hover:bg-purple-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-purple-500"
                      >
                        ✍️ 手动编辑
                      </button>
                      
                      <button
                        onClick={() => handleOpenChapterDialog(item)}
                        className="inline-flex items-center px-3 py-1.5 border border-blue-300 text-sm font-medium rounded-md text-blue-700 bg-blue-50 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                      >
                        🤖 AI修改
                      </button>
                      
                      <button
                        onClick={() => handleRegenerateChapter(item)}
                        className="inline-flex items-center px-3 py-1.5 border border-orange-300 text-sm font-medium rounded-md text-orange-700 bg-orange-50 hover:bg-orange-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500"
                      >
                        🔄 重新生成
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => handleRegenerateChapter(item)}
                      className="inline-flex items-center px-3 py-1.5 border border-blue-300 text-sm font-medium rounded-md text-blue-700 bg-blue-50 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                    >
                      <PlayIcon className="w-4 h-4 mr-1" />
                      生成本章
                    </button>
                  )}
                </div>
              )}
            </>
          )}

          {/* 子章节 */}
          {item.children && item.children.length > 0 && (
            <div className={level === 1 ? 'ml-4 mt-4' : level === 2 ? 'ml-8 mt-4' : 'ml-12 mt-4'}>
              {renderOutline(item.children, level + 1)}
            </div>
          )}
        </div>
      );
    });
  };

  // 生成单个章节内容
  const generateItemContent = async (item: OutlineItem, projectOverview: string): Promise<OutlineItem> => {
    if (!outlineData) throw new Error('缺少目录数据');
    
    // 将当前项目添加到正在生成的集合中
    setProgress(prev => ({ 
      ...prev, 
      current: item.title,
      generating: new Set([...Array.from(prev.generating), item.id])
    }));
    
    try {
      // 获取上级章节和同级章节信息
      const parentChapters = getParentChapters(item.id, outlineData.outline);
      const siblingChapters = getSiblingChapters(item.id, outlineData.outline);

      const request: ChapterContentRequest = {
        chapter: item,
        parent_chapters: parentChapters,
        sibling_chapters: siblingChapters,
        project_overview: projectOverview,
        library_docs: Object.keys(selectedDocuments).length > 0 ? selectedDocuments : undefined,
        web_references: webReferences.length > 0 ? webReferences : undefined,
        signal: abortControllerRef.current?.signal
      };

      const response = await contentApi.generateChapterContentStream(request);

      if (!response.ok) throw new Error('生成失败');

      const reader = response.body?.getReader();
      if (!reader) throw new Error('无法读取响应');

      let content = '';
      const updatedItem = { ...item };
      const sseParser = new SSEParser();
      
      try {
        while (true) {
          // 每次读取前检查停止信号
          if (shouldStopRef.current) {
            console.log(`[停止] 章节 ${item.title} 检测到停止信号，取消读取`);
            await reader.cancel();
            break;
          }

          const { done, value } = await reader.read();
          if (done) break;

          const chunk = new TextDecoder().decode(value, { stream: true });
          const dataLines = sseParser.feed(chunk);
          
          for (const data of dataLines) {
            if (data === '[DONE]') continue;
              
            try {
                const parsed = JSON.parse(data);
                
                if (parsed.status === 'loading_knowledge') {
                  // 显示知识库读取进度
                  setProgress(prev => ({ 
                    ...prev, 
                    current: `${item.title} - 读取知识库...`
                  }));
                } else if (parsed.status === 'streaming' && parsed.content) {
                  // 前端自行拼接增量 chunk
                  content += parsed.content;
                  updatedItem.content = content;
                  // 本地持久化（刷新后可恢复）
                  draftStorage.upsertChapterContent(item.id, content);
                  
                  // 更新进度显示
                  setProgress(prev => ({ 
                    ...prev, 
                    current: `${item.title} - 生成中...`
                  }));
                  
                  // 实时更新叶子节点数据以触发重新渲染
                  setLeafItems(prevItems => {
                    const newItems = [...prevItems];
                    const index = newItems.findIndex(i => i.id === item.id);
                    if (index !== -1) {
                      newItems[index] = { ...updatedItem };
                    }
                    return newItems;
                  });
                } else if (parsed.status === 'completed' && parsed.content) {
                  content = parsed.content;
                  updatedItem.content = content;
                  // 本地持久化（最终结果）
                  draftStorage.upsertChapterContent(item.id, content);
                } else if (parsed.status === 'error') {
                  throw new Error(parsed.message);
                }
            } catch (e) {
                // 忽略JSON解析错误
            }
          }
        }
      } catch (readError: any) {
        // AbortError 表示用户主动取消，不算失败
        if (readError.name === 'AbortError') {
          console.log(`[停止] 章节 ${item.title} 请求已取消`);
        } else {
          throw readError;
        }
      }

      return updatedItem;
    } catch (error: any) {
      // AbortError 不计入失败
      if (error.name === 'AbortError') {
        console.log(`[停止] 章节 ${item.title} 被用户取消`);
        return { ...item };
      }
      setProgress(prev => ({
        ...prev,
        failed: [...prev.failed, item.title]
      }));
      throw error;
    } finally {
      // 从正在生成的集合中移除当前项目
      setProgress(prev => {
        const newGenerating = new Set(Array.from(prev.generating));
        newGenerating.delete(item.id);
        return {
          ...prev,
          generating: newGenerating
        };
      });
    }
  };

  // 停止生成
  const handleStopGeneration = () => {
    console.log('用户点击停止生成');
    shouldStopRef.current = true;
    // 取消正在进行的网络请求
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      // 创建新的 controller，旧的已失效
      abortControllerRef.current = null;
    }
    // 立即更新UI状态
    setIsGenerating(false);
    setProgress(prev => ({ ...prev, current: '已停止', generating: new Set<string>() }));
  };

  // 清空已生成的内容
  const handleClearContent = () => {
    if (window.confirm('确定要清空所有已生成的内容吗？此操作不可恢复。')) {
      // 使用 draftStorage 清空所有章节内容
      draftStorage.saveContentById({});

      // 停止当前生成
      shouldStopRef.current = true;
      setIsGenerating(false);

      // 重置进度状态
      setProgress({
        total: leafItems.length,
        completed: 0,
        current: '',
        failed: [],
        generating: new Set<string>()
      });

      // 重新加载叶子节点，清空内容
      if (outlineData?.outline) {
        const leaves = collectLeafItems(outlineData.outline);
        const clearedLeaves = leaves.map(leaf => ({
          ...leaf,
          content: undefined
        }));
        setLeafItems(clearedLeaves);
      }

      alert('已清空所有已生成的内容');
    }
  };

  // 预加载知识库到后端缓存（批量生成前调用一次，SSE 流式显示进度）
  const preloadKnowledge = async () => {
    try {
      const docs = Object.keys(selectedDocuments).length > 0 ? selectedDocuments : undefined;
      const response = await contentApi.preloadKnowledgeStream({ library_docs: docs });
      
      if (!response.ok) {
        console.error('知识库预加载请求失败:', response.status);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) return;

      const sseParser = new SSEParser();
      let done = false;

      while (!done) {
        const { done: readerDone, value } = await reader.read();
        if (readerDone) break;

        const chunk = new TextDecoder().decode(value, { stream: true });
        const dataLines = sseParser.feed(chunk);

        for (const data of dataLines) {
          if (data === '[DONE]') { done = true; break; }
          try {
            const evt = JSON.parse(data);
            if (evt.status === 'reading') {
              setProgress(prev => ({
                ...prev,
                current: `📚 读取知识库 (${evt.loaded}/${evt.total}) ${evt.lib_name}: ${evt.filename}`,
              }));
            } else if (evt.status === 'read_done') {
              setProgress(prev => ({
                ...prev,
                current: `📚 知识库读取完成 (${evt.original_chars} 字符)，正在适配模型...`,
              }));
            } else if (evt.status === 'truncating') {
              setProgress(prev => ({ ...prev, current: `⚙️ ${evt.message}` }));
            } else if (evt.status === 'done') {
              const truncInfo = evt.original_chars !== evt.truncated_chars
                ? `${evt.original_chars} → ${evt.truncated_chars} 字符`
                : `${evt.original_chars} 字符`;
              setProgress(prev => ({
                ...prev,
                current: `✅ 知识库预加载完成 (${truncInfo})`,
              }));
              console.log('[知识库预加载]', evt);
            } else if (evt.status === 'error') {
              console.error('知识库预加载错误:', evt.message);
            }
          } catch (e) { /* ignore parse errors */ }
        }
      }
    } catch (error) {
      console.error('知识库预加载失败:', error);
      // 预加载失败不阻塞生成，后端会回退到直接读取
    }
  };

  // 开始生成所有内容（逐章顺序生成，支持打断）
  const handleGenerateContent = async () => {
    if (!outlineData || leafItems.length === 0) return;

    setIsGenerating(true);
    shouldStopRef.current = false;
    abortControllerRef.current = new AbortController();
    setProgress({
      total: leafItems.length,
      completed: 0,
      current: '正在预加载知识库...',
      failed: [],
      generating: new Set<string>()
    });

    // 预加载知识库（一次性读取并缓存）
    await preloadKnowledge();

    const updatedItems = [...leafItems];

    try {
      // 逐章顺序生成，一章完成后再生成下一章
      for (let i = 0; i < leafItems.length; i++) {
        // 检查是否被用户打断
        if (shouldStopRef.current) {
          console.log('检测到停止信号，终止生成');
          break;
        }

        const item = leafItems[i];
        
        // 跳过已有内容的章节
        if (item.content) {
          setProgress(prev => ({ ...prev, completed: prev.completed + 1 }));
          continue;
        }

        // 每个章节使用独立的 AbortController，确保停止后可以正确取消
        if (!abortControllerRef.current || abortControllerRef.current.signal.aborted) {
          abortControllerRef.current = new AbortController();
        }

        try {
          const updatedItem = await generateItemContent(item, projectOverview || '');
          
          // 再次检查停止标志（生成完成后）
          if (shouldStopRef.current) {
            console.log('生成完成后检测到停止信号');
            break;
          }
          
          const index = updatedItems.findIndex(ui => ui.id === updatedItem.id);
          if (index !== -1) {
            updatedItems[index] = updatedItem;
          }
          setProgress(prev => ({ ...prev, completed: prev.completed + 1 }));
        } catch (error: any) {
          // AbortError 表示用户主动停止，直接退出循环
          if (error.name === 'AbortError' || shouldStopRef.current) {
            console.log('生成被用户停止');
            break;
          }
          console.error(`生成内容失败 ${item.title}:`, error);
          setProgress(prev => ({ ...prev, completed: prev.completed + 1 }));
        }
      }

      setLeafItems(updatedItems);
      
    } catch (error) {
      console.error('生成内容时出错:', error);
    } finally {
      setIsGenerating(false);
      shouldStopRef.current = false;
      abortControllerRef.current = null;
      setProgress(prev => ({ ...prev, current: '', generating: new Set<string>() }));
    }
  };

  // 并行生成所有内容（多章节同时生成，速度更快）
  const handleParallelGenerate = async () => {
    if (!outlineData || leafItems.length === 0) return;

    // 筛选需要生成的章节（跳过已有内容的）
    const toGenerate = leafItems.filter(item => !item.content);
    if (toGenerate.length === 0) {
      alert('所有章节已有内容，无需生成');
      return;
    }

    setIsGenerating(true);
    shouldStopRef.current = false;
    setProgress({
      total: leafItems.length,
      completed: leafItems.length - toGenerate.length,
      current: '正在预加载知识库...',
      failed: [],
      generating: new Set<string>()
    });

    // 预加载知识库（一次性读取并缓存）
    await preloadKnowledge();

    if (shouldStopRef.current) {
      setIsGenerating(false);
      return;
    }

    try {
      const CONCURRENCY = 3;
      const allResults: { id: string; item?: OutlineItem; error?: string }[] = [];
      const totalBatches = Math.ceil(toGenerate.length / CONCURRENCY);
      console.log(`[并行生成] 共 ${toGenerate.length} 章节，分 ${totalBatches} 批，每批 ${CONCURRENCY} 个`);

      for (let batchIdx = 0; batchIdx < totalBatches; batchIdx++) {
        if (shouldStopRef.current) {
          console.log(`[并行生成] 第${batchIdx + 1}批开始前检测到停止信号，退出`);
          break;
        }

        const batchStart = batchIdx * CONCURRENCY;
        const batch = toGenerate.slice(batchStart, batchStart + CONCURRENCY);
        console.log(`[并行生成] 开始第${batchIdx + 1}/${totalBatches}批，章节:`, batch.map(i => i.title));

        // 每批创建新的 AbortController，确保上一批的 abort 不影响下一批
        const batchController = new AbortController();
        abortControllerRef.current = batchController;

        setProgress(prev => ({
          ...prev,
          current: `并行生成中 第${batchIdx + 1}/${totalBatches}批 (${batch.length}章节)...`,
        }));

        const batchPromises = batch.map(async (item) => {
          if (shouldStopRef.current) {
            console.log(`[并行生成] 章节 ${item.title} 跳过（停止信号）`);
            return { id: item.id };
          }
          try {
            const updatedItem = await generateItemContent(item, projectOverview || '');
            console.log(`[并行生成] 章节 ${item.title} 完成，内容长度: ${updatedItem.content?.length || 0}`);
            return { id: item.id, item: updatedItem };
          } catch (error: any) {
            if (error.name === 'AbortError' || shouldStopRef.current) {
              console.log(`[并行生成] 章节 ${item.title} 被取消`);
              return { id: item.id };
            }
            console.error(`[并行生成] 章节 ${item.title} 失败:`, error);
            return { id: item.id, error: item.title };
          }
        });

        console.log(`[并行生成] 第${batchIdx + 1}批等待 Promise.all...`);
        const batchResults = await Promise.all(batchPromises);
        console.log(`[并行生成] 第${batchIdx + 1}批完成，结果:`, batchResults.map(r => ({
          id: r.id,
          hasContent: !!r.item?.content,
          error: r.error,
        })));
        allResults.push(...batchResults);

        // 更新进度
        const completedCount = allResults.filter(r => r.item || r.error).length;
        const failedTitles = allResults.filter(r => r.error).map(r => r.error!);
        setProgress(prev => ({
          ...prev,
          completed: (leafItems.length - toGenerate.length) + completedCount,
          failed: failedTitles,
          current: shouldStopRef.current
            ? '已停止'
            : `已完成 ${completedCount}/${toGenerate.length} 章节`,
        }));

        console.log(`[并行生成] 累计完成 ${completedCount}/${toGenerate.length}，失败 ${failedTitles.length}，shouldStop=${shouldStopRef.current}`);

        // 批次间等待 5 秒，避免 API 限流（TPM limit）
        if (batchIdx < totalBatches - 1 && !shouldStopRef.current) {
          setProgress(prev => ({ ...prev, current: `等待 5 秒后开始第${batchIdx + 2}/${totalBatches}批...` }));
          await new Promise(resolve => setTimeout(resolve, 5000));
        }
      }

      console.log(`[并行生成] 所有批次完成，合并结果`);
      // 将结果合并到 leafItems
      setLeafItems(prevItems => {
        const newItems = [...prevItems];
        for (const r of allResults) {
          if (r.item) {
            const idx = newItems.findIndex(i => i.id === r.id);
            if (idx !== -1) newItems[idx] = r.item;
          }
        }
        return newItems;
      });

    } catch (error) {
      console.error('并行生成出错:', error);
    } finally {
      setIsGenerating(false);
      shouldStopRef.current = false;
      abortControllerRef.current = null;
      setProgress(prev => ({ ...prev, current: '', generating: new Set<string>() }));
    }
  };

  // 获取叶子节点的最新内容（包括生成的内容）
  const getLatestContent = (item: OutlineItem): string => {
    if (!item.children || item.children.length === 0) {
      // 叶子节点，从 leafItems 获取最新内容
      const leafItem = leafItems.find(leaf => leaf.id === item.id);
      return leafItem?.content || item.content || '';
    }
    return item.content || '';
  };

  // 解析Markdown内容为Word段落
  // （已提取到文件顶层，供后续导出Word等复用）

  // 导出Word文档
  const handleExportWord = async () => {
    if (!outlineData) return;

    try {
      // 构建带有最新内容的导出数据（leafItems 中存的是实时内容）
      const buildExportOutline = (items: OutlineItem[]): OutlineItem[] => {
        return items.map(item => {
          const latestContent = getLatestContent(item);
          const exportedItem: OutlineItem = {
            ...item,
            content: latestContent,
          };
          if (item.children && item.children.length > 0) {
            exportedItem.children = buildExportOutline(item.children);
          }
          return exportedItem;
        });
      };

      const exportPayload = {
        project_name: outlineData.project_name,
        project_overview: projectOverview,
        outline: buildExportOutline(outlineData.outline),
      };

      const response = await documentApi.exportWord(exportPayload);
      if (!response.ok) {
        throw new Error('导出失败');
      }
      const blob = await response.blob();
      saveAs(blob, `${outlineData.project_name || '审计文档'}.docx`);
      
    } catch (error) {
      console.error('导出失败:', error);
      alert('导出失败，请重试');
    }
  };

  // 单章节重新生成（清空已有内容后重新调用AI）
  const handleRegenerateChapter = async (item: OutlineItem) => {
    if (progress.generating.has(item.id)) return; // 防止重复触发

    // 如果已有内容，先确认
    const existing = getLeafItemContent(item.id);
    if (existing && !window.confirm(`确定要重新生成「${item.title}」吗？当前内容将被覆盖。`)) {
      return;
    }

    // 清空当前内容
    setLeafItems(prev => {
      const newItems = [...prev];
      const idx = newItems.findIndex(i => i.id === item.id);
      if (idx !== -1) {
        newItems[idx] = { ...newItems[idx], content: undefined };
      }
      return newItems;
    });

    try {
      const controller = new AbortController();
      abortControllerRef.current = controller;
      await generateItemContent(item, projectOverview || '');
    } catch (error) {
      console.error(`重新生成章节失败 ${item.title}:`, error);
    } finally {
      abortControllerRef.current = null;
    }
  };

  // 打开章节修改对话框
  const handleOpenChapterDialog = (item: OutlineItem) => {
    const content = getLeafItemContent(item.id) || '';
    setChapterDialog({
      isOpen: true,
      chapterId: item.id,
      chapterTitle: item.title,
      chapterContent: content,
      messages: [],
      userInput: '',
      isRevising: false,
      targetWordCount: item.target_word_count,
    });
  };

  // 关闭章节修改对话框
  const handleCloseChapterDialog = () => {
    // 关闭前，如果用户修改了目标字数，回写到 leafItems
    if (chapterDialog.chapterId && chapterDialog.targetWordCount) {
      setLeafItems(prevItems => {
        const newItems = [...prevItems];
        const index = newItems.findIndex(i => i.id === chapterDialog.chapterId);
        if (index !== -1 && newItems[index].target_word_count !== chapterDialog.targetWordCount) {
          newItems[index] = { ...newItems[index], target_word_count: chapterDialog.targetWordCount };
        }
        return newItems;
      });
    }

    setChapterDialog({
      isOpen: false,
      chapterId: '',
      chapterTitle: '',
      chapterContent: '',
      messages: [],
      userInput: '',
      isRevising: false,
      targetWordCount: undefined,
    });
  };

  // 确认章节内容
  const handleConfirmChapter = (itemId: string) => {
    console.log(`章节 ${itemId} 已确认`);
  };

  // 计算章节字数
  const getChapterWordCount = (content: string): number => {
    if (!content) return 0;
    // 移除Markdown标记和空白字符后计算字数
    const plainText = content
      .replace(/[#*`_()[\]!>~]/g, '')  // 移除常见Markdown标记字符
      .replace(/\s+/g, '');
    return plainText.length;
  };

  // 打开手动编辑对话框
  const handleOpenManualEdit = (item: OutlineItem) => {
    const content = getLeafItemContent(item.id) || '';
    setManualEdit({
      isOpen: true,
      chapterId: item.id,
      chapterTitle: item.title,
      editContent: content,
      aiInput: '',
      aiProcessing: false,
      selectedText: '',
      selectionStart: 0,
      selectionEnd: 0,
      targetWordCount: item.target_word_count,
    });
  };

  // 关闭手动编辑对话框
  const handleCloseManualEdit = () => {
    // 关闭前，如果用户修改了目标字数，回写到 leafItems
    if (manualEdit.chapterId && manualEdit.targetWordCount) {
      setLeafItems(prevItems => {
        const newItems = [...prevItems];
        const index = newItems.findIndex(i => i.id === manualEdit.chapterId);
        if (index !== -1 && newItems[index].target_word_count !== manualEdit.targetWordCount) {
          newItems[index] = { ...newItems[index], target_word_count: manualEdit.targetWordCount };
        }
        return newItems;
      });
    }

    setManualEdit({
      isOpen: false,
      chapterId: '',
      chapterTitle: '',
      editContent: '',
      aiInput: '',
      aiProcessing: false,
      selectedText: '',
      selectionStart: 0,
      selectionEnd: 0,
      targetWordCount: undefined,
    });
  };

  // 保存手动编辑的内容
  const handleSaveManualEdit = () => {
    if (!manualEdit.editContent.trim()) {
      alert('内容不能为空');
      return;
    }

    // 更新leafItems中的内容
    setLeafItems(prevItems => {
      const newItems = [...prevItems];
      const index = newItems.findIndex(i => i.id === manualEdit.chapterId);
      if (index !== -1) {
        newItems[index] = { ...newItems[index], content: manualEdit.editContent };
        // 本地持久化
        draftStorage.upsertChapterContent(manualEdit.chapterId, manualEdit.editContent);
      }
      return newItems;
    });

    // 关闭对话框
    handleCloseManualEdit();
  };

  // 手动编辑页面的 textarea ref，用于获取选区
  const manualEditTextareaRef = useRef<HTMLTextAreaElement>(null);
  // 高亮背景层 ref，用于同步滚动
  const manualEditHighlightRef = useRef<HTMLDivElement>(null);

  // 同步 textarea 滚动到高亮层
  const handleManualEditScroll = () => {
    const ta = manualEditTextareaRef.current;
    const hl = manualEditHighlightRef.current;
    if (ta && hl) {
      hl.scrollTop = ta.scrollTop;
      hl.scrollLeft = ta.scrollLeft;
    }
  };

  // 记录用户在编辑器中的选区
  const handleManualEditSelect = () => {
    const ta = manualEditTextareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = ta.value.substring(start, end);
    setManualEdit(prev => ({
      ...prev,
      selectedText: selected,
      selectionStart: start,
      selectionEnd: end,
    }));
  };

  // 手动编辑中的 AI 辅助修改
  const handleManualEditAI = async () => {
    if (!manualEdit.aiInput.trim() || manualEdit.aiProcessing) return;

    const hasSelection = manualEdit.selectedText.length > 0;
    const contentToRevise = hasSelection ? manualEdit.selectedText : manualEdit.editContent;

    if (!contentToRevise.trim()) return;

    setManualEdit(prev => ({ ...prev, aiProcessing: true }));

    try {
      const request = {
        chapter: { id: manualEdit.chapterId, title: manualEdit.chapterTitle, description: '' },
        current_content: contentToRevise,
        messages: [],
        user_instruction: manualEdit.aiInput + (hasSelection ? '\n\n【注意】只修改上述选中的部分内容，保持格式和风格一致。' : ''),
        project_overview: projectOverview || '',
        parent_chapters: [],
        sibling_chapters: [],
        web_references: webReferences.length > 0 ? webReferences : undefined,
      };

      const response = await contentApi.reviseChapterStream(request);
      if (!response.ok) throw new Error('AI修改失败');

      const reader = response.body?.getReader();
      if (!reader) throw new Error('无法读取响应');

      let revisedContent = '';
      const aiParser = new SSEParser();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = new TextDecoder().decode(value, { stream: true });
        const dataLines = aiParser.feed(chunk);
        for (const data of dataLines) {
          if (data === '[DONE]') continue;
          try {
            const parsed = JSON.parse(data);
            if (parsed.status === 'streaming' && parsed.content) {
              revisedContent += parsed.content;
            } else if (parsed.status === 'completed' && parsed.content) {
              revisedContent = parsed.content;
            } else if (parsed.status === 'error') {
              throw new Error(parsed.message);
            }
          } catch (e) { /* ignore parse errors */ }
        }
      }

      if (revisedContent) {
        if (hasSelection) {
          // 只替换选中部分
          const before = manualEdit.editContent.substring(0, manualEdit.selectionStart);
          const after = manualEdit.editContent.substring(manualEdit.selectionEnd);
          setManualEdit(prev => ({
            ...prev,
            editContent: before + revisedContent + after,
            aiInput: '',
            aiProcessing: false,
            selectedText: '',
          }));
        } else {
          // 替换全部内容
          setManualEdit(prev => ({
            ...prev,
            editContent: revisedContent,
            aiInput: '',
            aiProcessing: false,
          }));
        }
      } else {
        setManualEdit(prev => ({ ...prev, aiProcessing: false }));
      }
    } catch (error) {
      console.error('AI辅助修改失败:', error);
      alert(`AI修改失败: ${error}`);
      setManualEdit(prev => ({ ...prev, aiProcessing: false }));
    }
  };

  // 提交修改指令
  const handleSubmitRevision = async () => {
    if (!chapterDialog.userInput.trim() || !outlineData) return;

    const userInstruction = chapterDialog.userInput.trim()
      + (chapterDialog.targetWordCount ? `\n\n【字数硬性要求 - 最高优先级】本章节必须达到 ${chapterDialog.targetWordCount} 字左右（允许±10%浮动，即 ${Math.round(chapterDialog.targetWordCount * 0.9)}~${Math.round(chapterDialog.targetWordCount * 1.1)} 字）。如果当前内容不足，请大幅扩充每个要点的论述深度、增加更多细节和案例、补充更多分析维度，直到达到字数要求。绝对不能少于目标字数的80%。` : '');
    
    // 先保存当前的messages（不包含新消息）
    const currentMessages = chapterDialog.messages;
    
    setChapterDialog(prev => ({
      ...prev,
      isRevising: true,
      userInput: '',
    }));

    try {
      // 找到对应的章节对象
      const findChapter = (items: OutlineItem[]): OutlineItem | null => {
        for (const item of items) {
          if (item.id === chapterDialog.chapterId) return item;
          if (item.children) {
            const found = findChapter(item.children);
            if (found) return found;
          }
        }
        return null;
      };

      const chapter = findChapter(outlineData.outline);
      if (!chapter) throw new Error('找不到章节');

      // 获取上级章节和同级章节信息
      const parentChapters = getParentChapters(chapterDialog.chapterId, outlineData.outline);
      const siblingChapters = getSiblingChapters(chapterDialog.chapterId, outlineData.outline);

      const request = {
        chapter: {
          id: chapter.id,
          title: chapter.title,
          description: chapter.description,
        },
        current_content: chapterDialog.chapterContent,
        messages: currentMessages,
        user_instruction: userInstruction,
        project_overview: projectOverview || '',
        parent_chapters: parentChapters,
        sibling_chapters: siblingChapters,
        library_docs: Object.keys(selectedDocuments).length > 0 ? selectedDocuments : undefined,
        web_references: webReferences.length > 0 ? webReferences : undefined,
      };

      console.log('发送修改请求:', {
        url: '/api/content/revise-chapter-stream',
        chapter_id: chapter.id,
        chapter_title: chapter.title,
        content_length: chapterDialog.chapterContent.length,
        messages_count: currentMessages.length,
        instruction: userInstruction,
        has_library_docs: !!request.library_docs,
      });

      const response = await contentApi.reviseChapterStream(request);
      
      console.log('响应状态:', response.status, response.statusText);
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error('响应错误:', errorText);
        throw new Error(`修改失败 (${response.status}): ${errorText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('无法读取响应');

      let revisedContent = '';
      
      // 添加用户消息到历史
      setChapterDialog(prev => ({
        ...prev,
        messages: [...prev.messages, { role: 'user', content: userInstruction }],
      }));
      
      const revisionParser = new SSEParser();
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = new TextDecoder().decode(value, { stream: true });
        const dataLines = revisionParser.feed(chunk);
        
        /* eslint-disable no-loop-func */
        for (const data of dataLines) {
          if (data === '[DONE]') continue;
            
          try {
              const parsed = JSON.parse(data);
              
              if (parsed.status === 'streaming' && parsed.content) {
                revisedContent += parsed.content;
                // 实时更新对话框中的内容
                setChapterDialog(prev => ({
                  ...prev,
                  chapterContent: revisedContent,
                }));
              } else if (parsed.status === 'completed' && parsed.content) {
                revisedContent = parsed.content;
                // 更新对话框内容
                setChapterDialog(prev => ({
                  ...prev,
                  chapterContent: revisedContent,
                  messages: [...prev.messages, { role: 'assistant', content: '内容已更新' }],
                  isRevising: false,
                }));
                
                // 更新leafItems中的内容和目标字数
                setLeafItems(prevItems => {
                  const newItems = [...prevItems];
                  const index = newItems.findIndex(i => i.id === chapterDialog.chapterId);
                  if (index !== -1) {
                    const updated = { ...newItems[index], content: revisedContent };
                    // 如果用户设置了自定义字数，回写到 target_word_count
                    if (chapterDialog.targetWordCount) {
                      updated.target_word_count = chapterDialog.targetWordCount;
                    }
                    newItems[index] = updated;
                    // 本地持久化
                    draftStorage.upsertChapterContent(chapterDialog.chapterId, revisedContent);
                  }
                  return newItems;
                });
              } else if (parsed.status === 'error') {
                throw new Error(parsed.message);
              }
          } catch (e) {
              console.error('解析响应错误:', e);
          }
        }
        /* eslint-enable no-loop-func */
      }
    } catch (error) {
      console.error('修改章节失败:', error);
      setChapterDialog(prev => ({
        ...prev,
        isRevising: false,
        messages: [...prev.messages, { role: 'assistant', content: `错误: ${error}` }],
      }));
    }
  };

  if (!outlineData) {
    return (
      <div className="max-w-6xl mx-auto">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="text-center py-12">
            <DocumentTextIcon className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">暂无内容</h3>
            <p className="mt-1 text-sm text-gray-500">
              请先在"目录编辑"步骤中生成目录结构
            </p>
          </div>
        </div>
      </div>
    );
  }

  const completedItems = leafItems.filter(item => item.content).length;

  return (
    <div className="max-w-6xl mx-auto">
      {/* 顶部工具栏 */}
      <div className="bg-white rounded-lg shadow mb-6">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">文档内容</h2>
              <p className="text-sm text-gray-500 mt-1">
                共 {leafItems.length} 个章节，已生成 {completedItems} 个
                {progress.failed.length > 0 && (
                  <span className="text-red-500 ml-2">失败 {progress.failed.length} 个</span>
                )}
                <span className="ml-3 text-gray-600 font-medium">
                  📊 实际总字数: {leafItems.reduce((sum, item) => sum + getChapterWordCount(item.content || ''), 0).toLocaleString()}
                  <span className="text-gray-400 ml-1">
                    / 目标 {leafItems.reduce((sum, item) => sum + (item.target_word_count || 0), 0).toLocaleString()}
                  </span>
                </span>
              </p>
            </div>
            
            <div className="flex items-center space-x-3">
              {isGenerating ? (
                <>
                  <button
                    onClick={handleStopGeneration}
                    className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-red-600 hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
                  >
                    <ExclamationCircleIcon className="w-4 h-4 mr-2" />
                    停止生成
                  </button>
                  
                  <button
                    onClick={handleClearContent}
                    className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500"
                  >
                    🗑️ 清空
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => {
                      const next = !showKnowledgeSelector;
                      setShowKnowledgeSelector(next);
                      if (next) loadKnowledgeLibraries();
                    }}
                    className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                  >
                    📚 选择知识库 ({Object.values(selectedDocuments).flat().length} 文档)
                  </button>
                  
                  <button
                    onClick={() => {
                      const next = !showKnowledgeSearch;
                      setShowKnowledgeSearch(next);
                      if (next) loadKnowledgeLibraries();
                    }}
                    className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                  >
                    🔍 知识库搜索
                  </button>
                  
                  <button
                    onClick={() => setShowWebSearch(!showWebSearch)}
                    className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                  >
                    🌐 网络搜索 {webReferences.length > 0 ? `(${webReferences.length})` : ''}
                  </button>
                  
                  <button
                    onClick={handleGenerateContent}
                    className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                  >
                    <PlayIcon className="w-4 h-4 mr-2" />
                    生成文档
                  </button>
                  
                  <button
                    onClick={handleParallelGenerate}
                    className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
                  >
                    ⚡ 并行生成
                  </button>
                  
                  <button
                    onClick={handleClearContent}
                    className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500"
                  >
                    🗑️ 清空
                  </button>
                </>
              )}
              
              <button
                onClick={handleExportWord}
                disabled={isGenerating}
                className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <DocumentArrowDownIcon className="w-4 h-4 mr-2" />
                导出Word
              </button>
            </div>
          </div>
          
          {/* 知识库选择面板 */}
          {showKnowledgeSelector && (
            <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-md max-h-96 overflow-y-auto">
              <h4 className="text-sm font-medium text-gray-900 mb-3">选择要使用的知识库和文档</h4>
              <div className="space-y-2">
                {knowledgeLibraries.map(lib => (
                  <div key={lib.id} className="border border-gray-200 rounded-lg bg-white">
                    {/* 知识库标题行 */}
                    <div className="flex items-center p-3">
                      <button
                        onClick={() => toggleLibraryExpand(lib.id)}
                        className="mr-2 text-gray-500 hover:text-gray-700"
                      >
                        {expandedLibraries.has(lib.id) ? '▼' : '▶'}
                      </button>
                      <div className="flex-1">
                        <div className="text-sm font-medium text-gray-900">{lib.name}</div>
                        <div className="text-xs text-gray-500">{lib.desc}</div>
                      </div>
                      <div className="text-xs text-blue-600 ml-2">
                        {lib.doc_count} 个文档
                        {selectedDocuments[lib.id] && selectedDocuments[lib.id].length > 0 && (
                          <span className="ml-1">({selectedDocuments[lib.id].length} 已选)</span>
                        )}
                      </div>
                    </div>
                    
                    {/* 展开的文档列表 */}
                    {expandedLibraries.has(lib.id) && libraryDocuments[lib.id] && (
                      <div className="border-t border-gray-200 p-3 bg-gray-50">
                        <div className="flex justify-between items-center mb-2">
                          <span className="text-xs text-gray-600">选择具体文档：</span>
                          <div className="space-x-2">
                            <button
                              onClick={() => selectAllDocuments(lib.id)}
                              className="text-xs text-blue-600 hover:text-blue-700"
                            >
                              全选
                            </button>
                            <button
                              onClick={() => clearAllDocuments(lib.id)}
                              className="text-xs text-gray-600 hover:text-gray-700"
                            >
                              清空
                            </button>
                          </div>
                        </div>
                        <div className="space-y-1 max-h-48 overflow-y-auto">
                          {libraryDocuments[lib.id].map((doc) => (
                            <label
                              key={doc.id}
                              className="flex items-center p-2 rounded hover:bg-white cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={selectedDocuments[lib.id]?.includes(doc.id) || false}
                                onChange={() => toggleDocumentSelection(lib.id, doc.id)}
                                className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                              />
                              <div className="ml-2 flex-1">
                                <div className="text-xs text-gray-900">{doc.filename}</div>
                                <div className="text-xs text-gray-500">{doc.created_at}</div>
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-3 text-xs text-gray-500">
                💡 点击知识库名称左侧的箭头展开，可以选择具体的文档。未展开的知识库将使用全部文档。
              </div>
            </div>
          )}

          {/* 知识库搜索面板 */}
          {showKnowledgeSearch && (
            <KnowledgeSearchPanel
              libraries={knowledgeLibraries}
              onClose={() => setShowKnowledgeSearch(false)}
            />
          )}

          {/* 网络搜索面板 */}
          {showWebSearch && (
            <WebSearchPanel
              references={webReferences}
              onReferencesChange={setWebReferences}
              onClose={() => setShowWebSearch(false)}
            />
          )}
          
          {/* 进度条 */}
          {isGenerating && (
            <div className="mt-4">
              <div className="flex items-center justify-between text-sm text-gray-600 mb-2">
                <span>正在生成: {progress.current}</span>
                <span>{progress.completed} / {progress.total}</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${(progress.completed / progress.total) * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 文档内容 */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-8">
          <div className="prose max-w-none">
            {/* 文档标题 */}
            <h1 className="text-3xl font-bold text-gray-900 mb-8">
              {outlineData.project_name || '审计文档'}
            </h1>
            
            {/* 目录结构和内容 */}
            <div className="space-y-8">
              {renderOutline(outlineData.outline)}
            </div>
          </div>
        </div>
      </div>

      {/* 底部统计 */}
      <div className="mt-6 bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between text-sm text-gray-600">
          <div className="flex items-center space-x-6">
            <div className="flex items-center">
              <CheckCircleIcon className="w-4 h-4 text-green-500 mr-1" />
              <span>已完成: {completedItems}</span>
            </div>
            <div className="flex items-center">
              <DocumentTextIcon className="w-4 h-4 text-gray-400 mr-1" />
              <span>待生成: {leafItems.length - completedItems}</span>
            </div>
            {progress.failed.length > 0 && (
              <div className="flex items-center">
                <ExclamationCircleIcon className="w-4 h-4 text-red-500 mr-1" />
                <span className="text-red-600">失败: {progress.failed.length}</span>
              </div>
            )}
          </div>
          <div>
            <span>总字数: {leafItems.reduce((sum, item) => sum + getChapterWordCount(item.content || ''), 0)}</span>
          </div>
        </div>
      </div>

      {/* 章节修改对话框 */}
      {chapterDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[70] p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] flex flex-col">
            {/* 对话框头部 */}
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">AI修改章节</h3>
                <p className="text-sm text-gray-500 mt-1">{chapterDialog.chapterTitle}</p>
              </div>
              <div className="flex items-center space-x-3">
                <div className="flex items-center space-x-2">
                  <label htmlFor="dialog-word-count" className="text-xs text-gray-500 whitespace-nowrap">目标字数</label>
                  <input
                    id="dialog-word-count"
                    type="number"
                    value={chapterDialog.targetWordCount ?? ''}
                    onChange={(e) => setChapterDialog(prev => ({ ...prev, targetWordCount: e.target.value ? parseInt(e.target.value) : undefined }))}
                    placeholder="自动"
                    min={100}
                    max={50000}
                    step={100}
                    className="w-24 px-2 py-1 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <button
                  onClick={handleCloseChapterDialog}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            {/* 对话框内容 */}
            <div className="flex-1 overflow-y-auto p-6">
              {/* 当前内容预览 */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-sm font-medium text-gray-700">当前内容</h4>
                  <span className="text-xs text-gray-500">
                    字数: {getChapterWordCount(chapterDialog.chapterContent)}
                  </span>
                </div>
                <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 max-h-96 overflow-y-auto">
                  <div className="prose prose-sm max-w-none prose-p:text-base prose-p:leading-relaxed">
                    <ReactMarkdown>{chapterDialog.chapterContent || '暂无内容'}</ReactMarkdown>
                  </div>
                </div>
              </div>

              {/* 对话历史 */}
              {chapterDialog.messages.length > 0 && (
                <div className="mb-4">
                  <h4 className="text-sm font-medium text-gray-700 mb-2">修改历史</h4>
                  <div className="space-y-2">
                    {chapterDialog.messages.map((msg, idx) => (
                      <div
                        key={idx}
                        className={`p-3 rounded-lg ${
                          msg.role === 'user'
                            ? 'bg-blue-50 border border-blue-200'
                            : 'bg-green-50 border border-green-200'
                        }`}
                      >
                        <div className="text-xs font-medium text-gray-600 mb-1">
                          {msg.role === 'user' ? '👤 你' : '🤖 AI'}
                        </div>
                        <div className="text-sm text-gray-800">{msg.content}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* 对话框底部 - 输入区 */}
            <div className="px-6 py-4 border-t border-gray-200">
              <div className="flex items-end space-x-3">
                <div className="flex-1">
                  <label htmlFor="revision-input" className="block text-sm font-medium text-gray-700 mb-2">
                    修改要求
                  </label>
                  <textarea
                    id="revision-input"
                    value={chapterDialog.userInput}
                    onChange={(e) => setChapterDialog(prev => ({ ...prev, userInput: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && e.ctrlKey) {
                        handleSubmitRevision();
                      }
                    }}
                    placeholder="请输入修改要求，例如：增加更多案例、调整语气、扩充内容等..."
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                    rows={3}
                    disabled={chapterDialog.isRevising}
                  />
                  <p className="text-xs text-gray-500 mt-1">按 Ctrl+Enter 快速提交</p>
                </div>
                <button
                  onClick={handleSubmitRevision}
                  disabled={!chapterDialog.userInput.trim() || chapterDialog.isRevising}
                  className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-400 disabled:cursor-not-allowed h-[42px]"
                >
                  {chapterDialog.isRevising ? '修改中...' : '提交'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 手动编辑对话框 */}
      {manualEdit.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[70] p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-6xl w-full max-h-[90vh] flex flex-col">
            {/* 对话框头部 */}
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">手动编辑章节</h3>
                <p className="text-sm text-gray-500 mt-1">{manualEdit.chapterTitle}</p>
              </div>
              <div className="flex items-center space-x-3">
                <div className="flex items-center space-x-2">
                  <label htmlFor="manual-edit-word-count" className="text-xs text-gray-500 whitespace-nowrap">目标字数</label>
                  <input
                    id="manual-edit-word-count"
                    type="number"
                    value={manualEdit.targetWordCount ?? ''}
                    onChange={(e) => setManualEdit(prev => ({ ...prev, targetWordCount: e.target.value ? parseInt(e.target.value) : undefined }))}
                    placeholder="自动"
                    min={100}
                    max={50000}
                    step={100}
                    className="w-24 px-2 py-1 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
                <button
                  onClick={handleCloseManualEdit}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            {/* 对话框内容 - 编辑区 */}
            <div className="flex-1 overflow-hidden p-6 flex gap-4">
              {/* 左侧：编辑器 */}
              <div className="flex-1 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <label htmlFor="manual-edit-textarea" className="text-sm font-medium text-gray-700">
                    编辑内容（支持 Markdown）
                  </label>
                  <span className="text-xs text-gray-500">
                    字数: {getChapterWordCount(manualEdit.editContent)}
                  </span>
                </div>
                <div className="flex-1 w-full relative">
                  {/* 高亮背景层：与 textarea 完全重叠，用于在失焦后保持选中高亮 */}
                  <div
                    ref={manualEditHighlightRef}
                    aria-hidden="true"
                    className="absolute inset-0 px-4 py-3 font-mono text-sm whitespace-pre-wrap break-words overflow-hidden pointer-events-none border border-transparent rounded-lg"
                    style={{ color: 'transparent', background: 'white' }}
                  >
                    {manualEdit.selectedText && manualEdit.selectionStart !== manualEdit.selectionEnd ? (
                      <>
                        {manualEdit.editContent.substring(0, manualEdit.selectionStart)}
                        <mark className="bg-blue-200 rounded-sm" style={{ color: 'transparent' }}>
                          {manualEdit.editContent.substring(manualEdit.selectionStart, manualEdit.selectionEnd)}
                        </mark>
                        {manualEdit.editContent.substring(manualEdit.selectionEnd)}
                      </>
                    ) : manualEdit.editContent}
                  </div>
                  <textarea
                    id="manual-edit-textarea"
                    ref={manualEditTextareaRef}
                    value={manualEdit.editContent}
                    onChange={(e) => setManualEdit(prev => ({ ...prev, editContent: e.target.value }))}
                    onSelect={handleManualEditSelect}
                    onScroll={handleManualEditScroll}
                    className="relative w-full h-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono text-sm resize-none"
                    style={{ background: 'transparent' }}
                    placeholder="在此输入或编辑章节内容..."
                  />
                </div>
                {manualEdit.selectedText && (
                  <div className="mt-1 text-xs text-blue-600">
                    已选中 {manualEdit.selectedText.length} 字
                  </div>
                )}
              </div>

              {/* 右侧：预览 */}
              <div className="flex-1 flex flex-col">
                <h4 className="text-sm font-medium text-gray-700 mb-2">实时预览</h4>
                <div className="flex-1 border border-gray-200 rounded-lg p-4 bg-gray-50 overflow-y-auto">
                  <div className="prose prose-sm max-w-none prose-p:text-base prose-p:leading-relaxed">
                    <ReactMarkdown>{manualEdit.editContent || '暂无内容'}</ReactMarkdown>
                  </div>
                </div>
              </div>
            </div>

            {/* 对话框底部 - AI辅助 + 操作按钮 */}
            <div className="px-6 py-4 border-t border-gray-200 space-y-3">
              {/* AI辅助修改区 */}
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label htmlFor="manual-ai-input" className="block text-xs font-medium text-gray-600 mb-1">
                    🤖 AI辅助修改 {manualEdit.selectedText ? `（将修改选中的 ${manualEdit.selectedText.length} 字）` : '（将修改全部内容）'}
                  </label>
                  <textarea
                    id="manual-ai-input"
                    value={manualEdit.aiInput}
                    onChange={(e) => setManualEdit(prev => ({ ...prev, aiInput: e.target.value }))}
                    onKeyDown={(e) => { if (e.key === 'Enter' && e.ctrlKey) handleManualEditAI(); }}
                    placeholder="输入修改要求，如：精简这段内容、补充更多细节、调整为更正式的语气..."
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-purple-500 text-sm resize-none"
                    rows={2}
                    disabled={manualEdit.aiProcessing}
                  />
                </div>
                <button
                  onClick={handleManualEditAI}
                  disabled={!manualEdit.aiInput.trim() || manualEdit.aiProcessing}
                  className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-400 disabled:cursor-not-allowed text-sm whitespace-nowrap h-[42px]"
                >
                  {manualEdit.aiProcessing ? '处理中...' : manualEdit.selectedText ? '修改选中' : 'AI修改'}
                </button>
              </div>

              {/* 操作按钮行 */}
              <div className="flex items-center justify-between">
                <div className="text-xs text-gray-500">
                  💡 选中部分文本后可只对选中内容进行AI修改，Ctrl+Enter 快速提交
                </div>
                <div className="flex items-center space-x-3">
                  <button
                    onClick={handleCloseManualEdit}
                    className="px-4 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-500"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleSaveManualEdit}
                    className="px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500"
                  >
                    💾 保存
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ContentEdit;