/**
 * 配置面板组件 - 支持多供应商管理与使用统计
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ConfigData, ProviderInfo, PresetProvider, ProviderUsage } from '../types';
import { configApi } from '../services/api';
import KnowledgePanel from './KnowledgePanel';
import ModelSelector from './ModelSelector';

interface ConfigPanelProps {
  config: ConfigData;
  onConfigChange: (config: ConfigData) => void;
}

const ConfigPanel: React.FC<ConfigPanelProps> = ({ config, onConfigChange }) => {
  const [localConfig, setLocalConfig] = useState<ConfigData>(config);
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [knowledgePanelOpen, setKnowledgePanelOpen] = useState(false);

  // 供应商相关
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [presets, setPresets] = useState<PresetProvider[]>([]);
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [newProvider, setNewProvider] = useState({ id: '', name: '', api_key: '', base_url: '' });
  const [editingName, setEditingName] = useState<string | null>(null); // 正在编辑名称的供应商ID
  const [editNameValue, setEditNameValue] = useState('');

  // 使用统计
  const [usageStats, setUsageStats] = useState<ProviderUsage[]>([]);
  const [showUsage, setShowUsage] = useState(false);

  const onConfigChangeRef = useRef(onConfigChange);
  onConfigChangeRef.current = onConfigChange;

  const loadConfig = useCallback(async () => {
    try {
      const response = await configApi.loadConfig();
      if (response.data) {
        const loadedConfig = { ...response.data, word_count: response.data.word_count || 100000 };
        setLocalConfig(loadedConfig);
        if (response.data.providers) setProviders(response.data.providers);
        onConfigChangeRef.current(loadedConfig);
      }
    } catch (error) {
      console.error('加载配置失败:', error);
    }
  }, []);

  const loadProviders = useCallback(async () => {
    try {
      const response = await configApi.getProviders();
      if (response.data.success) {
        setProviders(response.data.providers);
        setPresets(response.data.presets);
      }
    } catch (error) {
      console.error('加载供应商列表失败:', error);
    }
  }, []);

  const loadUsage = useCallback(async () => {
    try {
      const response = await configApi.getUsageStats();
      if (response.data.success) {
        setUsageStats(response.data.providers || []);
      }
    } catch (error) {
      console.error('加载使用统计失败:', error);
    }
  }, []);

  useEffect(() => {
    loadConfig();
    loadProviders();
  }, [loadConfig, loadProviders]);

  const isMaskedApiKey = (key: string) => /\*{3,}/.test(key);

  // 保存全局配置（模型名、字数）
  const handleSave = async () => {
    try {
      setLoading(true);
      const configToSave = { ...localConfig };
      if (isMaskedApiKey(configToSave.api_key)) {
        configToSave.api_key = '';
      }
      const response = await configApi.saveConfig(configToSave);
      if (response.data.success) {
        onConfigChange(localConfig);
        setMessage({ type: 'success', text: '配置保存成功' });
        setTimeout(() => setMessage(null), 3000);
      } else {
        setMessage({ type: 'error', text: response.data.message || '保存失败' });
      }
    } catch (error) {
      setMessage({ type: 'error', text: '配置保存失败' });
    } finally {
      setLoading(false);
    }
  };

  // 添加/更新供应商
  const handleSaveProvider = async () => {
    if (!newProvider.api_key && !newProvider.base_url) {
      setMessage({ type: 'error', text: '请填写 API Key' });
      return;
    }
    // ID 和名称交给后端自动推断，前端不做处理
    try {
      setLoading(true);
      const response = await configApi.saveProvider(newProvider);
      if (response.data.success) {
        setMessage({ type: 'success', text: '供应商已保存' });
        setShowAddProvider(false);
        setNewProvider({ id: '', name: '', api_key: '', base_url: '' });
        loadProviders();
        loadConfig();
        setTimeout(() => setMessage(null), 3000);
      }
    } catch (error) {
      setMessage({ type: 'error', text: '保存供应商失败' });
    } finally {
      setLoading(false);
    }
  };

  // 切换供应商
  const handleActivateProvider = async (providerId: string) => {
    try {
      const response = await configApi.activateProvider(providerId);
      if (response.data.success) {
        setMessage({ type: 'success', text: '已切换供应商' });
        // 切换供应商后清空模型列表，因为不同供应商的模型不同
        setModels([]);
        loadProviders();
        loadConfig();
        setTimeout(() => setMessage(null), 2000);
      }
    } catch (error) {
      setMessage({ type: 'error', text: '切换失败' });
    }
  };

  // 删除供应商
  const handleDeleteProvider = async (providerId: string) => {
    if (!window.confirm('确定要删除这个供应商配置吗？')) return;
    try {
      const response = await configApi.deleteProvider(providerId);
      if (response.data.success) {
        setMessage({ type: 'success', text: '已删除' });
        loadProviders();
        loadConfig();
        setTimeout(() => setMessage(null), 2000);
      }
    } catch (error) {
      setMessage({ type: 'error', text: '删除失败' });
    }
  };

  // 从预设快速添加
  const handleQuickAdd = (preset: PresetProvider) => {
    setNewProvider({ id: preset.id, name: preset.name, api_key: '', base_url: preset.base_url });
    setShowAddProvider(true);
  };

  // 开始编辑供应商名称
  const handleStartEditName = (e: React.MouseEvent, provider: ProviderInfo) => {
    e.stopPropagation();
    setEditingName(provider.id);
    setEditNameValue(provider.name);
  };

  // 保存供应商名称
  const handleSaveProviderName = async (providerId: string) => {
    const trimmed = editNameValue.trim();
    if (!trimmed) { setEditingName(null); return; }
    try {
      // 用 saveProvider 更新名称（api_key 为空表示不更新）
      const provider = providers.find(p => p.id === providerId);
      await configApi.saveProvider({
        id: providerId,
        name: trimmed,
        api_key: '',
        base_url: provider?.base_url || '',
      });
      setEditingName(null);
      loadProviders();
    } catch {
      setMessage({ type: 'error', text: '名称保存失败' });
    }
  };

  // 获取模型列表
  const handleGetModels = async () => {
    const activeProvider = providers.find(p => p.is_active);
    if (!activeProvider?.has_key && !localConfig.api_key) {
      setMessage({ type: 'error', text: '请先配置供应商的 API Key' });
      return;
    }
    try {
      setLoading(true);
      const response = await configApi.getModels(localConfig);
      if (response.data.success) {
        setModels(response.data.models);
        if (response.data.models.length > 0 && !response.data.models.includes(localConfig.model_name)) {
          setLocalConfig(prev => ({ ...prev, model_name: response.data.models[0] }));
        }
        setMessage({ type: 'success', text: `获取到 ${response.data.models.length} 个模型` });
        setTimeout(() => setMessage(null), 3000);
      } else {
        setMessage({ type: 'error', text: response.data.message });
      }
    } catch (error) {
      setMessage({ type: 'error', text: '获取模型列表失败' });
    } finally {
      setLoading(false);
    }
  };

  const formatTokens = (n: number) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return String(n);
  };

  return (
    <div className="bg-white shadow-sm border-r border-gray-200 h-full p-6 overflow-y-auto">
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">致同AI审计助手</h1>
          <hr className="mt-4 border-gray-200" />
        </div>

        {/* 消息提示 */}
        {message && (
          <div className={`p-3 rounded-md text-sm ${
            message.type === 'success'
              ? 'bg-green-100 text-green-700 border border-green-200'
              : 'bg-red-100 text-red-700 border border-red-200'
          }`}>{message.text}</div>
        )}

        {/* ─── 供应商管理 ─── */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-medium text-gray-900">🔑 API 供应商</h2>
            <button
              onClick={() => setShowAddProvider(!showAddProvider)}
              className="text-xs px-2 py-1 rounded bg-primary-50 text-primary-700 hover:bg-primary-100"
            >
              {showAddProvider ? '取消' : '+ 添加'}
            </button>
          </div>

          {/* 已保存的供应商列表 */}
          {providers.length > 0 ? (
            <div className="space-y-2 mb-3">
              {providers.map(p => (
                <div
                  key={p.id}
                  className={`p-3 rounded-lg border text-sm cursor-pointer transition-colors ${
                    p.is_active
                      ? 'border-primary-300 bg-primary-50'
                      : 'border-gray-200 bg-gray-50 hover:bg-gray-100'
                  }`}
                  onClick={() => handleActivateProvider(p.id)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {p.is_active && <span className="text-primary-600 text-xs">✓ 当前</span>}
                      {editingName === p.id ? (
                        <input
                          type="text"
                          value={editNameValue}
                          onChange={e => setEditNameValue(e.target.value)}
                          onBlur={() => handleSaveProviderName(p.id)}
                          onKeyDown={e => { if (e.key === 'Enter') handleSaveProviderName(p.id); if (e.key === 'Escape') setEditingName(null); }}
                          onClick={e => e.stopPropagation()}
                          className="border border-primary-300 rounded px-1 py-0 text-sm font-medium w-28 focus:outline-none focus:ring-1 focus:ring-primary-500"
                          autoFocus
                        />
                      ) : (
                        <span
                          className="font-medium text-gray-900 hover:text-primary-700"
                          onDoubleClick={e => handleStartEditName(e, p)}
                          title="双击编辑名称"
                        >{p.name}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {editingName !== p.id && (
                        <button
                          onClick={e => handleStartEditName(e, p)}
                          className="text-gray-400 hover:text-primary-600 text-xs"
                          title="编辑名称"
                        >✎</button>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteProvider(p.id); }}
                        className="text-gray-400 hover:text-red-500 text-xs"
                      >✕</button>
                    </div>
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    {p.base_url || '默认'}
                    {p.has_key && <span className="ml-2 text-green-600">Key 已配置</span>}
                    {!p.has_key && <span className="ml-2 text-red-500">未配置 Key</span>}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 mb-3">暂无供应商，请添加或从预设中选择</p>
          )}

          {/* 添加供应商表单 */}
          {showAddProvider && (
            <div className="p-3 border border-gray-200 rounded-lg bg-gray-50 space-y-3 mb-3">
              {/* 快速选择预设 */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">快速选择</label>
                <div className="flex flex-wrap gap-1">
                  {presets.filter(p => !providers.some(ep => ep.id === p.id)).map(p => (
                    <button
                      key={p.id}
                      onClick={() => handleQuickAdd(p)}
                      className="text-xs px-2 py-1 rounded bg-white border border-gray-300 hover:bg-primary-50 hover:border-primary-300"
                    >{p.name}</button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600">Base URL</label>
                <input
                  type="text"
                  value={newProvider.base_url}
                  onChange={e => setNewProvider({ ...newProvider, base_url: e.target.value })}
                  className="mt-0.5 block w-full rounded border-gray-300 text-sm"
                  placeholder="如 https://api.deepseek.com/v1"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600">API Key</label>
                <input
                  type="password"
                  value={newProvider.api_key}
                  onChange={e => setNewProvider({ ...newProvider, api_key: e.target.value })}
                  className="mt-0.5 block w-full rounded border-gray-300 text-sm"
                  placeholder="输入 API Key"
                />
              </div>
              <button
                onClick={handleSaveProvider}
                disabled={loading}
                className="w-full py-1.5 text-sm rounded bg-primary-600 text-white hover:bg-primary-700 disabled:bg-gray-400"
              >{loading ? '保存中...' : '保存供应商'}</button>
            </div>
          )}
        </div>

        {/* ─── 模型配置 ─── */}
        <div>
          <h3 className="text-base font-medium text-gray-900 mb-3">🤖 模型配置</h3>
          <button
            onClick={handleGetModels}
            disabled={loading}
            className="w-full mb-3 inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 disabled:bg-gray-400"
          >{loading ? '获取中...' : '🔄 获取可用模型'}</button>
          <div>
            <label htmlFor="model_name" className="block text-sm font-medium text-gray-700">模型名称</label>
            {models.length > 0 ? (
              <ModelSelector
                models={models}
                selectedModel={localConfig.model_name}
                onModelChange={(model) => setLocalConfig({ ...localConfig, model_name: model })}
              />
            ) : (
              <input
                type="text"
                id="model_name"
                value={localConfig.model_name}
                onChange={(e) => setLocalConfig({ ...localConfig, model_name: e.target.value })}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                placeholder="输入模型名称"
              />
            )}
          </div>
        </div>

        {/* ─── 知识库 ─── */}
        <div>
          <h3 className="text-base font-medium text-gray-900 mb-3">📚 知识库</h3>
          <button
            onClick={() => setKnowledgePanelOpen(true)}
            className="w-full inline-flex justify-center items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
          >📂 管理知识库</button>
          <p className="mt-2 text-xs text-gray-500">上传参考资料，AI生成时自动检索</p>
        </div>

        {/* ─── 保存按钮 ─── */}
        <button
          onClick={handleSave}
          disabled={loading}
          className="w-full inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:bg-gray-400"
        >{loading ? '保存中...' : '💾 保存配置'}</button>

        {/* ─── 使用统计 ─── */}
        <div className="border-t border-gray-200 pt-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-gray-900">📊 使用统计</h3>
            <button
              onClick={() => { setShowUsage(!showUsage); if (!showUsage) loadUsage(); }}
              className="text-xs text-primary-600 hover:text-primary-800"
            >{showUsage ? '收起' : '查看'}</button>
          </div>
          {showUsage && (
            <div className="space-y-3">
              {usageStats.length === 0 ? (
                <p className="text-xs text-gray-500">暂无使用记录</p>
              ) : usageStats.map(stat => (
                <div key={stat.provider_id} className="p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-gray-900">{stat.provider_name}</span>
                    <span className="text-xs text-gray-500">
                      共 {stat.total_calls} 次调用
                    </span>
                  </div>
                  <div className="text-xs text-gray-600 mb-2">
                    输入 {formatTokens(stat.total_input_tokens)} tokens · 输出 {formatTokens(stat.total_output_tokens)} tokens
                    {stat.last_used && <span className="ml-2">· 最近 {stat.last_used}</span>}
                  </div>
                  {stat.models.length > 0 && (
                    <div className="space-y-1">
                      {stat.models.map(m => (
                        <div key={m.model} className="flex items-center justify-between text-xs py-1 border-t border-gray-100">
                          <span className="text-gray-700 font-mono">{m.model}</span>
                          <span className="text-gray-500">
                            {m.calls}次 · {formatTokens(m.input_tokens + m.output_tokens)} tokens
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ─── 使用说明 ─── */}
        <div className="border-t border-gray-200 pt-4">
          <h3 className="text-sm font-medium text-gray-900 mb-2">📋 使用说明</h3>
          <div className="text-sm text-gray-600 space-y-1">
            <p>1. 添加 API 供应商并配置 Key</p>
            <p>2. 获取可用模型，选择合适的模型</p>
            <p>3. 选择工作模式（底稿复核/文档生成）</p>
            <p>4. 按工作流步骤完成操作</p>
            <p>5. 查看报告或导出文档</p>
          </div>
        </div>

        {/* 底部图标 */}
        <div className="border-t border-gray-200 pt-4">
          <div className="flex items-center justify-center">
            <a href="https://www.grantthornton.cn" target="_blank" rel="noopener noreferrer" className="hover:opacity-75 transition-opacity" title="致同官网">
              <img src="/gt-logo.png" alt="致同" className="h-8" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
            </a>
          </div>
        </div>
      </div>

      <KnowledgePanel isOpen={knowledgePanelOpen} onClose={() => setKnowledgePanelOpen(false)} />
    </div>
  );
};

export default ConfigPanel;
