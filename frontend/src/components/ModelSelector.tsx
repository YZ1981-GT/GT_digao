/**
 * 自定义模型选择器组件 - 支持分组折叠
 */
import React, { useState, useRef, useEffect, useMemo } from 'react';

interface ModelGroup {
  label: string;
  icon: string;
  models: string[];
}

interface ModelSelectorProps {
  models: string[];
  selectedModel: string;
  onModelChange: (model: string) => void;
}

const ModelSelector: React.FC<ModelSelectorProps> = ({ models, selectedModel, onModelChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const dropdownRef = useRef<HTMLDivElement>(null);

  // ─── 各厂商推荐模型白名单（模型太多时只显示这些） ───
  const RECOMMENDED: Record<string, string[]> = {
    qwen: [
      // Qwen3 旗舰（长文本能力强）
      'Qwen/Qwen3-235B-A22B-Instruct-2507', 'Qwen/Qwen3-235B-A22B-Thinking-2507',
      'Qwen/Qwen3-Coder-480B-A35B-Instruct', 'Qwen/Qwen3-Next-80B-A3B-Instruct',
      'Qwen/Qwen3-Next-80B-A3B-Thinking', 'Qwen/Qwen3-32B', 'Qwen/Qwen3-14B',
      'Qwen/Qwen3-30B-A3B-Instruct-2507', 'Qwen/Qwen3-Coder-30B-A3B-Instruct',
      // QwQ 推理
      'Qwen/QwQ-32B',
      // Qwen2.5 长文本
      'Qwen/Qwen2.5-72B-Instruct-128K', 'Qwen/Qwen2.5-72B-Instruct',
      'Qwen/Qwen2.5-32B-Instruct', 'Qwen/Qwen2.5-Coder-32B-Instruct',
      // 通义千问平台专属名称
      'Qwen3.5-Plus', 'Qwen3-Max-2026-01-23', 'qwen3-max-preview', 'qwen3-long', 'qwen-long',
      'Qwen3-235B-A22B', 'qwen3-235b-a22b',
    ],
    gpt: [
      'gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
      'gpt-5', 'gpt-5-mini', 'gpt-5-pro', 'gpt-5.1', 'gpt-5.2',
      'o3', 'o3-mini', 'o3-pro', 'o4-mini',
      'chatgpt-4o-latest',
    ],
    claude: [
      'claude-opus-4-6', 'claude-opus-4-6-think',
      'claude-sonnet-4-6', 'claude-sonnet-4-6-think',
      'claude-sonnet-4-5-20250929', 'claude-sonnet-4-5-think',
      'claude-opus-4-5-20251101', 'claude-opus-4-5-think',
      'claude-3-7-sonnet-latest', 'claude-3-5-sonnet-latest',
      'claude-3-5-haiku-latest',
    ],
    gemini: [
      'gemini-3.1-pro-preview', 'gemini-3-pro-preview', 'gemini-3-flash-preview',
      'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite',
      'gemini-2.0-flash', 'gemini-2.0-flash-lite',
      'gemini-1.5-pro', 'gemini-1.5-flash',
    ],
    deepseek: [
      // DeepSeek 官方API
      'deepseek-chat', 'deepseek-reasoner',
      // 硅基流动（已验证可用）
      'deepseek-ai/DeepSeek-R1', 'deepseek-ai/DeepSeek-V3',
      'deepseek-ai/DeepSeek-V3.1-Terminus', 'deepseek-ai/DeepSeek-V3.2',
      'deepseek-ai/DeepSeek-R1-0528-Qwen3-8B',
      'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B',
      'deepseek-ai/DeepSeek-R1-Distill-Qwen-14B',
      'deepseek-ai/DeepSeek-V2.5',
      // AiHubMix 等代理
      'DeepSeek-R1', 'DeepSeek-R1-0528',
      'DeepSeek-V3.1', 'DeepSeek-V3.1-Fast', 'deepseek-v3.2-speciale',
    ],
  };

  // ─── 已知免费文本模型白名单（长文本优先） ───
  const FREE_TEXT_MODELS: string[] = [
    // AiHubMix 免费模型（文本处理，已验证可用）
    'gemini-2.0-flash-free',
    'gemini-3-flash-preview-free',
    'gpt-4.1-free',
    'gpt-4.1-mini-free',
    'gpt-4.1-nano-free',
    'gpt-4o-free',
    'glm-4.7-flash-free',
    // 硅基流动 Pro 免费加速版（已验证可用）
    'Pro/deepseek-ai/DeepSeek-R1',
    'Pro/deepseek-ai/DeepSeek-V3',
    'Pro/deepseek-ai/DeepSeek-V3.1-Terminus',
    'Pro/deepseek-ai/DeepSeek-V3.2',
    'Pro/Qwen/Qwen2.5-7B-Instruct',
    'Pro/THUDM/glm-4-9b-chat',
    'Pro/MiniMaxAI/MiniMax-M2.1',
    'Pro/MiniMaxAI/MiniMax-M2.5',
    'Pro/moonshotai/Kimi-K2-Instruct-0905',
    'Pro/moonshotai/Kimi-K2-Thinking',
    'Pro/moonshotai/Kimi-K2.5',
    'Pro/zai-org/GLM-4.7',
    'Pro/zai-org/GLM-5',
    // 硅基流动小模型（免费额度）
    'Qwen/Qwen3-8B',
    'Qwen/Qwen2.5-7B-Instruct',
    'THUDM/glm-4-9b-chat',
    'deepseek-ai/DeepSeek-R1-Distill-Qwen-7B',
    'deepseek-ai/DeepSeek-R1-Distill-Qwen-14B',
  ];

  // 模型分组配置
  const modelGroups = useMemo((): ModelGroup[] => {
    const groups: ModelGroup[] = [];
    const usedModels = new Set<string>();
    const markUsed = (list: string[]) => list.forEach(m => usedModels.add(m));

    // 辅助：过滤 + 精选
    const filterAndRecommend = (
      allModels: string[],
      recommended: string[],
      threshold: number = 15,
    ) => {
      if (allModels.length <= threshold) return allModels;
      const filtered = allModels.filter(m =>
        recommended.some(r => m.toLowerCase() === r.toLowerCase())
      );
      return filtered.length > 0 ? filtered : allModels.slice(0, threshold);
    };

    // ★★ 免费模型组 — 放在最前面，方便用户快速选择 ★★
    const freeModels = models.filter(m => {
      const l = m.toLowerCase();
      // 匹配白名单中的免费模型
      return FREE_TEXT_MODELS.some(f => f.toLowerCase() === l) ||
        // 匹配名称中带 "-free" 后缀的模型（排除 coding 类）
        (l.endsWith('-free') && !l.includes('coding'));
    });
    if (freeModels.length > 0) {
      groups.push({ label: '🆓 免费模型', icon: '🆓', models: freeModels });
      markUsed(freeModels);
    }

    // ★ 通义千问 / Qwen 排在最前面（长文本能力强，文档写作首选）
    const allQwenModels = models.filter(m => {
      const l = m.toLowerCase();
      return (l.includes('qwen') || l.includes('qwq') || l.includes('qvq')) && !usedModels.has(m);
    });
    if (allQwenModels.length > 0) {
      const picked = filterAndRecommend(allQwenModels, RECOMMENDED.qwen, 12);
      groups.push({ label: '通义千问 / Qwen', icon: '💬', models: picked });
      markUsed(picked);
    }

    // DeepSeek
    const deepseekModels = models.filter(m => m.toLowerCase().includes('deepseek') && !usedModels.has(m));
    if (deepseekModels.length > 0) {
      const picked = filterAndRecommend(deepseekModels, RECOMMENDED.deepseek);
      groups.push({ label: 'DeepSeek', icon: '🔍', models: picked });
      markUsed(picked);
    }

    // OpenAI / GPT
    const gptModels = models.filter(m => {
      const l = m.toLowerCase();
      return (l.startsWith('gpt-') || l.startsWith('o1') || l.startsWith('o3') || l.startsWith('o4') || l === 'chatgpt-4o-latest') && !usedModels.has(m);
    });
    if (gptModels.length > 0) {
      const picked = filterAndRecommend(gptModels, RECOMMENDED.gpt);
      groups.push({ label: 'OpenAI / GPT', icon: '🟢', models: picked });
      markUsed(picked);
    }

    // Claude / Anthropic
    const claudeModels = models.filter(m => {
      const l = m.toLowerCase();
      return (l.includes('claude') || l.includes('anthropic')) && !usedModels.has(m);
    });
    if (claudeModels.length > 0) {
      const picked = filterAndRecommend(claudeModels, RECOMMENDED.claude);
      groups.push({ label: 'Anthropic / Claude', icon: '🟠', models: picked });
      markUsed(picked);
    }

    // Gemini / Google
    const geminiModels = models.filter(m => {
      const l = m.toLowerCase();
      return (l.startsWith('gemini') || l.startsWith('gemma')) && !usedModels.has(m);
    });
    if (geminiModels.length > 0) {
      const picked = filterAndRecommend(geminiModels, RECOMMENDED.gemini);
      groups.push({ label: 'Google / Gemini', icon: '🔵', models: picked });
      markUsed(picked);
    }

    // Grok / xAI
    const grokModels = models.filter(m => m.toLowerCase().startsWith('grok') && !usedModels.has(m));
    if (grokModels.length > 0) {
      groups.push({ label: 'xAI / Grok', icon: '⚡', models: grokModels });
      markUsed(grokModels);
    }

    // Kimi / Moonshot
    const kimiModels = models.filter(m =>
      (m.toLowerCase().includes('kimi') || m.toLowerCase().startsWith('moonshot')) && !usedModels.has(m)
    );
    if (kimiModels.length > 0) {
      groups.push({ label: 'Kimi / Moonshot', icon: '🌙', models: kimiModels });
      markUsed(kimiModels);
    }

    // MiniMax
    const minimaxModels = models.filter(m =>
      (m.toLowerCase().includes('minimax') || m.startsWith('abab')) && !usedModels.has(m)
    );
    if (minimaxModels.length > 0) {
      groups.push({ label: 'MiniMax', icon: '🔷', models: minimaxModels });
      markUsed(minimaxModels);
    }

    // 智谱 GLM
    const glmModels = models.filter(m =>
      (m.toLowerCase().includes('glm') || m.toLowerCase().includes('thudm')) && !usedModels.has(m)
    );
    if (glmModels.length > 0) {
      groups.push({ label: '智谱 GLM', icon: '🧩', models: glmModels });
      markUsed(glmModels);
    }

    // 豆包 / 字节
    const doubaoModels = models.filter(m => m.toLowerCase().startsWith('doubao') && !usedModels.has(m));
    if (doubaoModels.length > 0) {
      groups.push({ label: '豆包 / 字节', icon: '🫘', models: doubaoModels });
      markUsed(doubaoModels);
    }

    // Meta / Llama
    const llamaModels = models.filter(m =>
      (m.toLowerCase().includes('llama') || m.toLowerCase().includes('meta-llama')) && !usedModels.has(m)
    );
    if (llamaModels.length > 0) {
      groups.push({ label: 'Meta / Llama', icon: '🦙', models: llamaModels });
      markUsed(llamaModels);
    }

    // 其他模型
    const otherModels = models.filter(m => !usedModels.has(m));
    if (otherModels.length > 0) {
      groups.push({ label: '其他模型', icon: '🔧', models: otherModels });
    }

    return groups;
  }, [models]);

  // 当模型列表变化时，默认折叠所有分组（模型多时更清晰）
  useEffect(() => {
    if (models.length > 0) {
      // 免费模型组始终展开，再展开前2个其他分组
      const freeGroup = modelGroups.find(g => g.label.includes('免费'));
      const otherGroups = modelGroups.filter(g => !g.label.includes('免费'));
      const toExpand = [
        ...(freeGroup ? [freeGroup.label] : []),
        ...otherGroups.slice(0, 2).map(g => g.label),
      ];
      setExpandedGroups(new Set(toExpand));
    }
  }, [models, modelGroups]);

  // 点击外部关闭下拉框
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  // 切换分组展开/折叠
  const toggleGroup = (groupLabel: string) => {
    const newExpanded = new Set(expandedGroups);
    if (newExpanded.has(groupLabel)) {
      newExpanded.delete(groupLabel);
    } else {
      newExpanded.add(groupLabel);
    }
    setExpandedGroups(newExpanded);
  };

  // 选择模型
  const handleSelectModel = (model: string) => {
    onModelChange(model);
    setIsOpen(false);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {/* 选择框 */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-left shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
      >
        <span className="block truncate">{selectedModel}</span>
        <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
          <svg
            className={`h-5 w-5 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fillRule="evenodd"
              d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
              clipRule="evenodd"
            />
          </svg>
        </span>
      </button>

      {/* 下拉列表 */}
      {isOpen && (
        <div className="absolute z-10 mt-1 w-full rounded-md bg-white shadow-lg border border-gray-200 max-h-96 overflow-y-auto">
          {modelGroups.map((group) => (
            <div key={group.label} className="border-b border-gray-100 last:border-b-0">
              {/* 分组标题 */}
              <button
                type="button"
                onClick={() => toggleGroup(group.label)}
                className={`w-full px-3 py-2 text-left text-sm font-medium flex items-center justify-between ${
                  group.label.includes('免费')
                    ? 'text-green-700 bg-green-50 hover:bg-green-100'
                    : 'text-gray-700 bg-gray-50 hover:bg-gray-100'
                }`}
              >
                <span>
                  <span className="mr-2">{group.icon}</span>
                  {group.label}
                  <span className="ml-2 text-xs text-gray-500">({group.models.length})</span>
                </span>
                <svg
                  className={`h-4 w-4 text-gray-500 transition-transform ${
                    expandedGroups.has(group.label) ? 'rotate-180' : ''
                  }`}
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path
                    fillRule="evenodd"
                    d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                    clipRule="evenodd"
                  />
                </svg>
              </button>

              {/* 分组模型列表 */}
              {expandedGroups.has(group.label) && (
                <div className="bg-white">
                  {group.models.map((model) => (
                    <button
                      key={model}
                      type="button"
                      onClick={() => handleSelectModel(model)}
                      className={`w-full px-4 py-2 text-left text-sm hover:bg-blue-50 ${
                        model === selectedModel
                          ? 'bg-blue-100 text-blue-900 font-medium'
                          : 'text-gray-700'
                      }`}
                    >
                      {model}
                      {model === selectedModel && (
                        <span className="float-right text-blue-600">✓</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ModelSelector;
