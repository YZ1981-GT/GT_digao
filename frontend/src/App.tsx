/**
 * 主应用组件
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useAppState } from './hooks/useAppState';
import ConfigPanel from './components/ConfigPanel';
import StepBar from './components/StepBar';
import DocumentAnalysis from './pages/DocumentAnalysis';
import OutlineEdit from './pages/OutlineEdit';
import ContentEdit from './pages/ContentEdit';
import WorkModeSelector from './components/WorkModeSelector';
import ReviewWorkflow from './components/ReviewWorkflow';
import GenerateWorkflow from './components/GenerateWorkflow';
import './App.css';
import './styles/gt-design-tokens.css';

/** 工作模式类型：select=模式选择首页, review=底稿复核, generate=文档生成, bid=文档写作(原有) */
type WorkMode = 'select' | 'review' | 'generate' | 'bid';

const API_BASE_URL =
  process.env.REACT_APP_API_URL ||
  (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

function App() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null); // null = 检测中
  const [workMode, setWorkMode] = useState<WorkMode>('select');

  const checkBackend = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/health`, { method: 'GET', signal: AbortSignal.timeout(3000) });
      setBackendOnline(res.ok);
    } catch {
      setBackendOnline(false);
    }
  }, []);

  useEffect(() => {
    checkBackend();
    // 后端离线时每 5 秒自动重试
    const timer = setInterval(checkBackend, 5000);
    return () => clearInterval(timer);
  }, [checkBackend]);

  const {
    state,
    updateConfig,
    updateFileContent,
    updateAnalysisResults,
    updateOutline,
    updateSelectedChapter,
    nextStep,
    prevStep,
  } = useAppState();

  // 侧边栏可拖拽宽度
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(320);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const delta = e.clientX - startX.current;
      const newWidth = Math.min(Math.max(startWidth.current + delta, 200), 600);
      setSidebarWidth(newWidth);
    };
    const onMouseUp = () => {
      if (isDragging.current) {
        isDragging.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, []);

  const handleDragStart = (e: React.MouseEvent) => {
    isDragging.current = true;
    startX.current = e.clientX;
    startWidth.current = sidebarWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const steps = ['文档解析', '目录编辑', '正文编辑'];

  // ─── 回到顶部按钮：跟随滚动条位置 ───
  const [scrollInfo, setScrollInfo] = useState({ show: false, btnTop: 60, percent: 0 });

  const handleMainScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const { scrollTop, scrollHeight, clientHeight } = el;
    const maxScroll = scrollHeight - clientHeight;
    if (maxScroll <= 0) {
      setScrollInfo({ show: false, btnTop: 60, percent: 0 });
      return;
    }
    const ratio = scrollTop / maxScroll;                // 0 ~ 1
    const percent = Math.round(ratio * 100);
    // 按钮活动区域：距容器顶部 40px ~ (容器高度 - 40px)
    const padding = 40;
    const btnTop = padding + ratio * (clientHeight - padding * 2);
    setScrollInfo({ show: scrollTop > 50, btnTop, percent });
  }, []);

  const scrollToTop = useCallback(() => {
    const el = document.getElementById('app-main-scroll');
    if (el) el.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  const handleSelectMode = useCallback((mode: 'review' | 'generate') => {
    setWorkMode(mode);
  }, []);

  const renderCurrentPage = () => {
    switch (state.currentStep) {
      case 0:
        return (
          <DocumentAnalysis
            fileContent={state.fileContent}
            projectOverview={state.projectOverview}
            techRequirements={state.techRequirements}
            onFileUpload={updateFileContent}
            onAnalysisComplete={updateAnalysisResults}
          />
        );
      case 1:
        return (
          <OutlineEdit
            projectOverview={state.projectOverview}
            techRequirements={state.techRequirements}
            outlineData={state.outlineData}
            onOutlineGenerated={updateOutline}
          />
        );
      case 2:
        return (
          <ContentEdit
            outlineData={state.outlineData}
            projectOverview={state.projectOverview}
            selectedChapter={state.selectedChapter}
            onChapterSelect={updateSelectedChapter}
          />
        );
      default:
        return null;
    }
  };

  // ─── 审计模式（review / generate）渲染 ───
  const renderAuditMode = () => (
    <div className="h-screen overflow-hidden bg-gray-50 flex flex-col">
      {/* 后端离线提示 */}
      {backendOnline === false && (
        <div className="bg-red-600 text-white text-center py-2 text-sm flex-shrink-0">
          ⚠️ 后端服务未启动，请先在 backend 目录运行 <code className="bg-red-800 px-1 rounded">python run.py</code> 启动后端（端口 9980）
          <button onClick={checkBackend} className="ml-3 underline hover:text-red-200">重新检测</button>
        </div>
      )}

      {/* 顶部导航栏 */}
      <header
        style={{
          background: 'var(--gt-primary)',
          color: 'var(--gt-text-on-purple)',
          padding: 'var(--gt-space-3) var(--gt-space-6)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 'var(--gt-font-base)' }}>
          {workMode === 'review' ? '底稿复核' : '文档生成'}
        </span>
        <button
          style={{
            color: '#ffffff',
            borderColor: 'rgba(255,255,255,0.6)',
            border: '1px solid rgba(255,255,255,0.6)',
            backgroundColor: 'transparent',
            fontSize: 'var(--gt-font-sm)',
            padding: 'var(--gt-space-1) var(--gt-space-3)',
            borderRadius: 'var(--gt-radius-md, 6px)',
            cursor: 'pointer',
          }}
          onClick={() => setWorkMode('select')}
        >
          切换模式
        </button>
      </header>

      {/* 工作流内容 */}
      <div className="flex-1 overflow-y-auto">
        {workMode === 'review' ? <ReviewWorkflow /> : <GenerateWorkflow />}
      </div>
    </div>
  );

  // ─── 文档写作模式（原有功能）渲染 ───
  const renderBidMode = () => (
    <div className="h-screen overflow-hidden bg-gray-50 flex flex-col">
      {/* 后端离线提示 */}
      {backendOnline === false && (
        <div className="bg-red-600 text-white text-center py-2 text-sm flex-shrink-0">
          ⚠️ 后端服务未启动，请先在 backend 目录运行 <code className="bg-red-800 px-1 rounded">python run.py</code> 启动后端（端口 9980）
          <button onClick={checkBackend} className="ml-3 underline hover:text-red-200">重新检测</button>
        </div>
      )}

      <div className="flex-1 flex min-h-0">
      {/* 左侧配置面板 */}
      <div style={{ width: sidebarWidth, flexShrink: 0 }}>
        <ConfigPanel
          config={state.config}
          onConfigChange={updateConfig}
        />
      </div>

      {/* 拖拽分隔条 */}
      <div
        onMouseDown={handleDragStart}
        className="w-1 hover:w-1.5 bg-gray-200 hover:bg-blue-400 cursor-col-resize flex-shrink-0 transition-colors"
      />

      {/* 主内容区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 步骤导航 */}
        <div className="sticky top-0 z-50 bg-white shadow-sm px-6">
          <StepBar steps={steps} currentStep={state.currentStep} />
        </div>

        {/* 页面内容 */}
        <div className="flex-1 relative min-h-0">
          <div id="app-main-scroll" className="h-full p-6 overflow-y-auto" onScroll={handleMainScroll}>
            {renderCurrentPage()}
          </div>
          {/* 回到顶部按钮 */}
          {scrollInfo.show && (
            <button
              onClick={scrollToTop}
              style={{ top: `${scrollInfo.btnTop}px` }}
              className="absolute right-5 w-7 h-7 flex items-center justify-center bg-blue-500 hover:bg-blue-600 active:bg-blue-700 text-white rounded-full shadow-md transition-colors z-30 opacity-80 hover:opacity-100"
              title={`回到顶部 (${scrollInfo.percent}%)`}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
              </svg>
            </button>
          )}
        </div>

        {/* 底部导航按钮 */}
        <div className="sticky bottom-0 z-50 bg-white border-t border-gray-200 px-6 py-4">
          <div className="flex justify-between">
            <div className="flex items-center space-x-3">
              <button
                onClick={() => setWorkMode('select')}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
              >
                返回首页
              </button>

              <button
                onClick={prevStep}
                disabled={state.currentStep === 0}
                className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
              >
                上一步
              </button>
            </div>

            <button
              onClick={nextStep}
              disabled={state.currentStep === steps.length - 1}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              下一步
            </button>
          </div>
        </div>
      </div>
      </div>
    </div>
  );

  // ─── 根据工作模式渲染对应界面 ───
  if (workMode === 'select') {
    return (
      <div className="h-screen overflow-hidden bg-gray-50 flex flex-col">
        {backendOnline === false && (
          <div className="bg-red-600 text-white text-center py-2 text-sm flex-shrink-0">
            ⚠️ 后端服务未启动，请先在 backend 目录运行 <code className="bg-red-800 px-1 rounded">python run.py</code> 启动后端（端口 9980）
            <button onClick={checkBackend} className="ml-3 underline hover:text-red-200">重新检测</button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto">
          <WorkModeSelector onSelectMode={handleSelectMode} />
        </div>
      </div>
    );
  }

  if (workMode === 'review' || workMode === 'generate') {
    return renderAuditMode();
  }

  return renderBidMode();
}

export default App;
