/**
 * 文档分析页面
 */
import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { documentApi } from '../services/api';
import { CloudArrowUpIcon, DocumentIcon } from '@heroicons/react/24/outline';
import { draftStorage } from '../utils/draftStorage';
import { processSSEStream } from '../utils/sseParser';

interface DocumentAnalysisProps {
  fileContent: string;
  projectOverview: string;
  techRequirements: string;
  onFileUpload: (content: string) => void;
  onAnalysisComplete: (overview: string, requirements: string) => void;
}

// 可配置的 ReactMarkdown 组件工厂（避免两套样式重复定义）
const createMarkdownComponents = (theme: {
  text: string; heading: string; accent: string;
  border: string; bg: string; codeBg: string;
  size: 'sm' | 'xs'; spacing: 'normal' | 'tight';
}) => {
  const textSize = theme.size === 'sm' ? 'text-sm' : 'text-xs';
  const headingSizes = theme.size === 'sm'
    ? { h1: 'text-lg', h2: 'text-base', h3: 'text-sm' }
    : { h1: 'text-sm', h2: 'text-xs', h3: 'text-xs' };
  const mb = theme.spacing === 'normal' ? { p: 'mb-3', list: 'mb-4', h1: 'mb-3', h2: 'mb-2', h3: 'mb-2' }
    : { p: 'mb-2', list: 'mb-2', h1: 'mb-2', h2: 'mb-1.5', h3: 'mb-1' };
  const lineHeight = theme.spacing === 'normal' ? '1.5' : '1.3';
  const listPl = theme.spacing === 'normal' ? 'pl-5' : 'pl-3';
  const listSpace = theme.spacing === 'normal' ? 'space-y-1.5' : 'space-y-0.5';

  return {
    p: ({ children }: any) => <p className={`${mb.p} leading-relaxed ${textSize} ${theme.text}`} style={{ whiteSpace: 'pre-wrap', lineHeight }}>{children}</p>,
    ul: ({ children }: any) => <ul className={`${mb.list} ${listPl} ${listSpace} list-disc ${theme.text}`}>{children}</ul>,
    ol: ({ children }: any) => <ol className={`${mb.list} ${listPl} ${listSpace} list-decimal ${theme.text}`}>{children}</ol>,
    li: ({ children }: any) => <li className={`${textSize} leading-relaxed ${theme.text}`}>{children}</li>,
    h1: ({ children }: any) => <h1 className={`${headingSizes.h1} font-semibold ${mb.h1} ${theme.heading} border-b ${theme.border} pb-2`}>{children}</h1>,
    h2: ({ children }: any) => <h2 className={`${headingSizes.h2} font-semibold ${mb.h2} ${theme.heading}`}>{children}</h2>,
    h3: ({ children }: any) => <h3 className={`${headingSizes.h3} font-semibold ${mb.h3} ${theme.accent}`}>{children}</h3>,
    strong: ({ children }: any) => <strong className={`font-semibold ${theme.heading}`}>{children}</strong>,
    em: ({ children }: any) => <em className={`italic ${theme.accent}`}>{children}</em>,
    blockquote: ({ children }: any) => <blockquote className={`border-l-4 ${theme.border} pl-4 my-3 italic ${theme.accent}`}>{children}</blockquote>,
    code: ({ children }: any) => <code className={`${theme.codeBg} px-1.5 py-0.5 rounded text-xs font-mono`}>{children}</code>,
    table: ({ children }: any) => <table className={`w-full border-collapse border ${theme.border} my-3`}>{children}</table>,
    thead: ({ children }: any) => <thead className={theme.bg}>{children}</thead>,
    th: ({ children }: any) => <th className={`border ${theme.border} px-3 py-2 text-left font-semibold text-xs ${theme.heading}`}>{children}</th>,
    td: ({ children }: any) => <td className={`border ${theme.border} px-3 py-2 text-xs ${theme.text}`}>{children}</td>,
    br: () => <br className="my-1" />,
  };
};

// 公共的 ReactMarkdown 组件配置
const markdownComponents = createMarkdownComponents({
  text: 'text-gray-800', heading: 'text-gray-900', accent: 'text-gray-700',
  border: 'border-gray-200', bg: 'bg-gray-50', codeBg: 'bg-gray-100',
  size: 'sm', spacing: 'normal',
});

// 流式显示的紧凑样式配置
const streamingComponents = createMarkdownComponents({
  text: 'text-blue-400', heading: 'text-blue-500', accent: 'text-blue-400',
  border: 'border-blue-200', bg: 'bg-blue-50', codeBg: 'bg-blue-50',
  size: 'xs', spacing: 'tight',
});

const DocumentAnalysis: React.FC<DocumentAnalysisProps> = ({
  fileContent,
  projectOverview,
  techRequirements,
  onFileUpload,
  onAnalysisComplete,
}) => {
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [localOverview, setLocalOverview] = useState(projectOverview);
  const [localRequirements, setLocalRequirements] = useState(techRequirements);

  // 当父组件 props 更新时（如从 localStorage 恢复），同步本地状态
  useEffect(() => {
    setLocalOverview(projectOverview);
  }, [projectOverview]);

  useEffect(() => {
    setLocalRequirements(techRequirements);
  }, [techRequirements]);
  

  // 处理换行符的函数 - 只做基本转换
  const normalizeLineBreaks = (text: string) => {
    if (!text) return text;
    
    return text
      .replace(/\\n/g, '\n')  // 将字符串 \n 转换为实际换行符
      .replace(/\r\n/g, '\n') // Windows换行符
      .replace(/\r/g, '\n');  // Mac换行符
  };
  
  // 流式显示状态
  const [currentAnalysisStep, setCurrentAnalysisStep] = useState<'overview' | 'requirements' | null>(null);
  const [streamingOverview, setStreamingOverview] = useState('');
  const [streamingRequirements, setStreamingRequirements] = useState('');

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setUploadedFile(file);
      handleFileUpload(file);
    }
  };

  const handleFileUpload = async (file: File) => {
    try {
      setUploading(true);
      setMessage(null);

      const response = await documentApi.uploadFile(file);
      
      if (response.data.success && response.data.file_content) {
        // 上传新文档：清空上一轮 localStorage（按你的需求）
        // 注意：这会同时清掉之前保存的草稿/正文内容缓存等
        draftStorage.clearAll();
        onFileUpload(response.data.file_content);
        setMessage({ type: 'success', text: response.data.message });
      } else {
        setMessage({ type: 'error', text: response.data.message });
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.response?.data?.detail || '文件上传失败' });
    } finally {
      setUploading(false);
    }
  };

  const handleAnalysis = async () => {
    if (!fileContent) {
      setMessage({ type: 'error', text: '请先上传文档' });
      return;
    }

    try {
      setAnalyzing(true);
      setMessage(null);
      setStreamingOverview('');
      setStreamingRequirements('');

      let overviewResult = '';
      let requirementsResult = '';

      // 处理流式响应的通用函数
      const processStream = async (response: Response, onChunk: (chunk: string) => void) => {
        await processSSEStream(
          response,
          (data) => {
            try {
              const parsed = JSON.parse(data);
              if (parsed.chunk) {
                onChunk(parsed.chunk);
              }
            } catch (_e) {
              // 忽略JSON解析错误
            }
          },
        );
      };

      // 第一步：分析项目概述
      setCurrentAnalysisStep('overview');
      const overviewResponse = await documentApi.analyzeDocumentStream({
        file_content: fileContent,
        analysis_type: 'overview',
      });

      await processStream(overviewResponse, (chunk) => {
        overviewResult += chunk;
        const normalizedContent = normalizeLineBreaks(overviewResult);
        setStreamingOverview(normalizedContent);
      });

      const finalOverview = normalizeLineBreaks(overviewResult);
      setLocalOverview(finalOverview);

      // 第二步：分析技术评分要求
      setCurrentAnalysisStep('requirements');
      const requirementsResponse = await documentApi.analyzeDocumentStream({
        file_content: fileContent,
        analysis_type: 'requirements',
      });

      await processStream(requirementsResponse, (chunk) => {
        requirementsResult += chunk;
        const normalizedContent = normalizeLineBreaks(requirementsResult);
        setStreamingRequirements(normalizedContent);
      });

      const finalRequirements = normalizeLineBreaks(requirementsResult);
      setLocalRequirements(finalRequirements);

      // 完成后更新父组件状态（使用已规范化的结果）
      onAnalysisComplete(finalOverview, finalRequirements);
      setMessage({ type: 'success', text: '文档解析完成' });
      
      // 清空流式内容
      setStreamingOverview('');
      setStreamingRequirements('');
      setCurrentAnalysisStep(null);

    } catch (error: any) {
      setMessage({ type: 'error', text: error.message || '文档解析失败' });
      setStreamingOverview('');
      setStreamingRequirements('');
      setCurrentAnalysisStep(null);
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* 文件上传区域 */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">📄 文档上传</h2>
        
        <div 
          className="border-2 border-dashed border-gray-300 rounded-lg p-12 text-center hover:border-gray-400 transition-colors cursor-pointer"
          onClick={() => fileInputRef.current?.click()}
        >
          <CloudArrowUpIcon className="mx-auto h-12 w-12 text-gray-400" />
          <div className="mt-4">
            <p className="text-lg text-gray-600">
              {uploadedFile ? uploadedFile.name : '点击选择文件或拖拽文件到这里'}
            </p>
            <p className="text-sm text-gray-500 mt-2">
              支持 PDF 和 Word 文档，最大 10MB
            </p>
          </div>
          
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.doc"
            onChange={handleFileSelect}
            className="hidden"
          />
        </div>
        
        {uploading && (
          <div className="mt-4 text-center">
            <div className="inline-flex items-center px-4 py-2 text-sm text-blue-600">
              <div className="animate-spin -ml-1 mr-3 h-5 w-5 text-blue-600">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              </div>
              正在上传和处理文件...
            </div>
          </div>
        )}
      </div>

      {/* 文档分析区域 */}
      {fileContent && (
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">🔍 文档分析</h2>
          
          <div className="flex justify-center mb-6">
            <button
              onClick={handleAnalysis}
              disabled={analyzing}
              className="inline-flex items-center justify-center px-6 py-3 border border-transparent text-base font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              {analyzing ? (
                <>
                  <div className="animate-spin -ml-1 mr-3 h-5 w-5 text-white">
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  </div>
                  {currentAnalysisStep === 'overview' ? '正在分析项目概述...' : 
                   currentAnalysisStep === 'requirements' ? '正在分析技术评分要求...' : 
                   '正在解析文档...'}
                </>
              ) : (
                <>
                  <DocumentIcon className="w-5 h-5 mr-2" />
                  解析文档
                </>
              )}
            </button>
          </div>

          {/* 流式分析内容显示 */}
          {analyzing && (((currentAnalysisStep === 'overview') && streamingOverview) || ((currentAnalysisStep === 'requirements') && streamingRequirements)) && (
            <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <h4 className="text-sm font-medium text-blue-800 mb-3">
                {currentAnalysisStep === 'overview' ? '正在分析项目概述...' : '正在分析技术评分要求...'}
              </h4>
              <div className="bg-white p-3 rounded-lg border border-gray-200 max-h-64 overflow-y-auto shadow-sm">
                <div className="text-xs prose prose-sm max-w-none">
                  <ReactMarkdown components={streamingComponents}>
                    {currentAnalysisStep === 'overview' ? streamingOverview : streamingRequirements}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          )}


          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* 项目概述 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-3">
                项目概述
              </label>
              <div className="w-full p-4 border border-gray-300 rounded-lg focus-within:ring-blue-500 focus-within:border-blue-500 max-h-80 overflow-y-auto bg-white shadow-sm">
                <div className="prose prose-sm max-w-none text-gray-800">
                  <ReactMarkdown components={markdownComponents}>
                    {localOverview || '项目概述将在这里显示...'}
                  </ReactMarkdown>
                </div>
              </div>
            </div>

            {/* 技术评分要求 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-3">
                技术评分要求
              </label>
              <div className="w-full p-4 border border-gray-300 rounded-lg focus-within:ring-green-500 focus-within:border-green-500 max-h-80 overflow-y-auto bg-white shadow-sm">
                <div className="prose prose-sm max-w-none text-gray-800">
                  <ReactMarkdown components={markdownComponents}>
                    {localRequirements || '技术评分要求将在这里显示...'}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 消息提示 */}
      {message && (
        <div className={`p-4 rounded-md ${
          message.type === 'success' 
            ? 'bg-green-100 text-green-700 border border-green-200' 
            : 'bg-red-100 text-red-700 border border-red-200'
        }`}>
          {message.text}
        </div>
      )}
    </div>
  );
};

export default DocumentAnalysis;