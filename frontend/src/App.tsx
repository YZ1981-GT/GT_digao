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
import AnalysisWorkflow from './components/AnalysisWorkflow';
import AuditReportWorkflow from './components/AuditReportWorkflow';
import './App.css';
import './styles/gt-design-tokens.css';

/** 工作模式类型：select=模式选择首页, review=底稿复核, generate=文档生成, analysis=文档分析, bid=文档写作(原有) */
type WorkMode = 'select' | 'review' | 'generate' | 'analysis' | 'bid' | 'report_review';

const API_BASE_URL =
  process.env.REACT_APP_API_URL ||
  (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:9980');

function App() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null); // null = 检测中
  const [workMode, setWorkMode] = useState<WorkMode>('select');
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const failCountRef = React.useRef(0);

  // ─── 全局返回顶部按钮 ───
  const [showScrollTop, setShowScrollTop] = useState(false);

  useEffect(() => {
    const onScroll = () => setShowScrollTop(window.scrollY > 100);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // 同时监听页面内 overflow 容器的滚动
  useEffect(() => {
    const handler = () => {
      // 检查 window 滚动
      if (window.scrollY > 100) { setShowScrollTop(true); return; }
      // 检查常见的 overflow 滚动容器
      let found = false;
      document.querySelectorAll('.overflow-y-auto, .overflow-auto').forEach(el => {
        if (el.scrollTop > 100) found = true;
      });
      setShowScrollTop(found);
    };
    document.addEventListener('scroll', handler, { capture: true, passive: true });
    return () => document.removeEventListener('scroll', handler, { capture: true });
  }, []);

  const handleGlobalScrollTop = useCallback(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    // 同时滚动所有 overflow 容器
    document.querySelectorAll('.overflow-y-auto, .overflow-auto').forEach(el => {
      el.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }, []);

  const checkBackend = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/health`, { method: 'GET', signal: AbortSignal.timeout(8000) });
      if (res.ok) {
        failCountRef.current = 0;
        setBackendOnline(true);
      } else {
        failCountRef.current += 1;
        if (failCountRef.current >= 2) setBackendOnline(false);
      }
    } catch {
      failCountRef.current += 1;
      // 连续 2 次失败才判定离线，避免长请求期间误报
      if (failCountRef.current >= 2) setBackendOnline(false);
    }
  }, []);

  useEffect(() => {
    checkBackend();
    // 后端在线时 30 秒检查一次，离线时 5 秒重试
    const timer = setInterval(checkBackend, backendOnline ? 30000 : 5000);
    return () => clearInterval(timer);
  }, [checkBackend, backendOnline]);

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

  const handleSelectMode = useCallback((mode: 'review' | 'generate' | 'analysis' | 'report_review') => {
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

  // ─── 审计模式（review / generate / analysis）渲染 ───
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
          {workMode === 'review' ? '底稿复核' : workMode === 'generate' ? '文档生成' : workMode === 'report_review' ? '审计报告复核' : '文档分析'}
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
        {workMode === 'review' ? <ReviewWorkflow /> : workMode === 'generate' ? <GenerateWorkflow /> : workMode === 'report_review' ? <AuditReportWorkflow /> : <AnalysisWorkflow />}
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
  const renderSelectMode = () => (
      <div className="h-screen overflow-hidden bg-gray-50 flex flex-col">
        {backendOnline === false && (
          <div className="bg-red-600 text-white text-center py-2 text-sm flex-shrink-0">
            ⚠️ 后端服务未启动，请先在 backend 目录运行 <code className="bg-red-800 px-1 rounded">python run.py</code> 启动后端（端口 9980）
            <button onClick={checkBackend} className="ml-3 underline hover:text-red-200">重新检测</button>
          </div>
        )}
        <div className="flex-1 flex min-h-0">
          {/* 左侧配置面板 */}
          {sidebarVisible && (
            <div style={{ width: 320, flexShrink: 0, position: 'relative' }}>
              <ConfigPanel
                config={state.config}
                onConfigChange={updateConfig}
              />
              {/* 收起按钮 */}
              <button
                onClick={() => setSidebarVisible(false)}
                title="收起侧栏"
                style={{
                  position: 'absolute',
                  top: 12,
                  right: -14,
                  width: 28,
                  height: 28,
                  borderRadius: '50%',
                  border: '1px solid #d0d0d0',
                  backgroundColor: '#fff',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 14,
                  color: '#666',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
                  zIndex: 10,
                }}
              >
                ◀
              </button>
            </div>
          )}
          {/* 展开按钮（侧栏隐藏时显示） */}
          {!sidebarVisible && (
            <button
              onClick={() => setSidebarVisible(true)}
              title="展开配置面板"
              style={{
                position: 'fixed',
                left: 0,
                top: '50%',
                transform: 'translateY(-50%)',
                width: 24,
                height: 48,
                borderRadius: '0 6px 6px 0',
                border: '1px solid #d0d0d0',
                borderLeft: 'none',
                backgroundColor: '#fff',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 12,
                color: '#666',
                boxShadow: '2px 0 4px rgba(0,0,0,0.08)',
                zIndex: 10,
              }}
            >
              ▶
            </button>
          )}
          {/* 右侧工作模式选择 */}
          <div className="flex-1 overflow-y-auto">
            <WorkModeSelector onSelectMode={handleSelectMode} />
          </div>
        </div>
      </div>
  );

  // ─── 全局返回顶部浮动按钮 ───
  const scrollTopButton = showScrollTop ? (
    <button
      onClick={handleGlobalScrollTop}
      title="返回顶部"
      aria-label="返回顶部"
      style={{
        position: 'fixed',
        right: 28,
        bottom: 28,
        width: 44,
        height: 44,
        borderRadius: '50%',
        border: '2px solid #fff',
        backgroundColor: '#6b7280',
        color: '#fff',
        fontSize: 20,
        lineHeight: 1,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        boxShadow: '0 2px 10px rgba(0,0,0,0.25)',
        zIndex: 99999,
        transition: 'transform 0.2s, opacity 0.2s',
        padding: 0,
        outline: 'none',
        opacity: 0.85,
      }}
      onMouseEnter={(e) => { const t = e.currentTarget; t.style.transform = 'scale(1.1)'; t.style.opacity = '1'; }}
      onMouseLeave={(e) => { const t = e.currentTarget; t.style.transform = 'scale(1)'; t.style.opacity = '0.85'; }}
    >
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" style={{ display: 'block' }}>
        <path d="M10 4L4 12h4v4h4v-4h4L10 4z" fill="#fff"/>
      </svg>
    </button>
  ) : null;

  if (workMode === 'select') {
    return (
      <>
        {renderSelectMode()}
        {scrollTopButton}
      </>
    );
  }

  if (workMode === 'review' || workMode === 'generate' || workMode === 'analysis' || workMode === 'report_review') {
    return (
      <>
        {renderAuditMode()}
        {scrollTopButton}
      </>
    );
  }

  return (
    <>
      {renderBidMode()}
      {scrollTopButton}
    </>
  );
}

export default App;
