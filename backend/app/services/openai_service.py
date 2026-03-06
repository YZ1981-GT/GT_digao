"""OpenAI服务"""
import openai
from typing import Dict, Any, List, AsyncGenerator
import json
import asyncio
import copy
import logging
import traceback
import re

from ..utils.outline_util import get_random_indexes, calculate_nodes_distribution, calculate_nodes_distribution_by_weights, generate_one_outline_json_by_level1
from ..utils.json_util import check_json
from ..utils.config_manager import config_manager
from ..utils.prompt_manager import chapter_content_system_prompt, chapter_revision_system_prompt
from ..config import settings as app_settings
from .knowledge_service import knowledge_service
from .knowledge_retriever import knowledge_retriever, _estimate_tokens as _kb_estimate_tokens

logger = logging.getLogger(__name__)


def estimate_token_count(text: str) -> int:
    """粗略估算token数量：中文约1.5token/字，英文约0.25token/词"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.5 + other_chars * 0.4)


# 常见模型的上下文窗口大小（token数）
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    # MiniMax
    'MiniMax-M2.5': 204800, 'MiniMax-M2.5-highspeed': 204800, 'MiniMax-M2.1': 204800,
    # Kimi / Moonshot
    'kimi-k2.5': 262000, 'kimi-k2-thinking': 262000, 'kimi-k2-thinking-turbo': 262000,
    'moonshot-v1-128k': 128000, 'moonshot-v1-32k': 32000,
    # 通义千问（官方 API 短名）
    'qwen3-max': 262000, 'qwen-max': 32000, 'qwen-plus': 131000,
    'qwen-max-latest': 32000, 'qwen3-max-preview': 262000, 'qwen-plus-latest': 131000,
    'qwen-turbo': 131000, 'qwen3-235b-a22b': 128000, 'qwen-long': 10000000,
    # DeepSeek 官方 API
    'deepseek-v3.2': 64000, 'deepseek-r1': 128000,
    'deepseek-chat': 64000, 'deepseek-reasoner': 128000,
    # 智谱 GLM
    'glm-5': 128000, 'glm-4.6': 128000, 'glm-4-plus': 128000,
    # Ollama 本地（带冒号的模型名区分于云端 API）
    'deepseek-r1:32b': 128000, 'qwen2.5:32b': 128000, 'llama3.1:70b': 128000,
    # ─── SiliconFlow 平台模型名（带厂商前缀） ───
    'deepseek-ai/DeepSeek-V3': 131072,
    'deepseek-ai/DeepSeek-V3-0324': 131072,
    'deepseek-ai/DeepSeek-R1': 131072,
    'deepseek-ai/DeepSeek-R1-0528': 131072,
    'deepseek-ai/DeepSeek-V2.5': 131072,
    'deepseek-ai/DeepSeek-V3.1': 131072,
    'deepseek-ai/DeepSeek-V3.2': 131072,
    'Pro/deepseek-ai/DeepSeek-V3': 131072,
    'Pro/deepseek-ai/DeepSeek-R1': 131072,
    'Qwen/Qwen3-235B-A22B': 131072,
    'Qwen/Qwen3-32B': 131072,
    'Qwen/Qwen3-30B-A3B': 131072,
    'Qwen/Qwen2.5-72B-Instruct': 131072,
    'Qwen/Qwen2.5-32B-Instruct': 131072,
    'Qwen/QwQ-32B': 131072,
    'Pro/Qwen/Qwen3-235B-A22B': 131072,
    'Pro/Qwen/Qwen3-32B': 131072,
    'Pro/Qwen/Qwen3-30B-A3B': 131072,
    'THUDM/GLM-4-32B-0414': 131072,
    'THUDM/GLM-Z1-32B-0414': 131072,
    'Pro/THUDM/GLM-4-32B-0414': 131072,
    'Pro/THUDM/GLM-Z1-32B-0414': 131072,
    'meta-llama/Llama-3.3-70B-Instruct': 131072,
    # ─── AiHubMix 免费模型 ───
    'google/gemma-3-27b-it': 131072,
    'deepseek-ai/DeepSeek-V3-0324-free': 131072,
    'deepseek-r1-free': 131072,
    'Qwen/Qwen3-235B-A22B-free': 131072,
    'meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8-free': 131072,
}
DEFAULT_CONTEXT_LIMIT = 32000


def _get_context_limit(model_name: str) -> int:
    """获取模型上下文限制，支持精确匹配和大小写不敏感回退"""
    # 精确匹配
    if model_name in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[model_name]
    # 大小写不敏感回退
    lower = model_name.lower()
    for key, val in MODEL_CONTEXT_LIMITS.items():
        if key.lower() == lower:
            return val
    return DEFAULT_CONTEXT_LIMIT
OUTPUT_RESERVE_RATIO = 0.3


def truncate_to_token_limit(text: str, max_tokens: int) -> str:
    """截断文本使其不超过指定token数"""
    estimated = estimate_token_count(text)
    if estimated <= max_tokens:
        return text
    ratio = max_tokens / estimated
    cut_len = int(len(text) * ratio * 0.95)
    logger.warning(f"[Token截断] 文本从约 {estimated} tokens 截断到约 {max_tokens} tokens（{len(text)} -> {cut_len} 字符）")
    return text[:cut_len] + "\n\n...(内容因token限制已截断)"


# ─── 知识库预加载已统一到 knowledge_retriever 单例 ───


class OpenAIService:
    """OpenAI服务类"""
    
    def __init__(self, api_key: str = None, base_url: str = None, model_name: str = None):
        """初始化OpenAI服务。
        
        若未传入参数，则从 config_manager 读取配置（默认行为）。
        传入参数时直接使用，不读取磁盘，适用于临时调用场景（如获取模型列表）。
        """
        if api_key is not None:
            # 直接使用传入的参数，不读磁盘
            self.api_key = api_key
            self.base_url = base_url or ''
            self.model_name = model_name or app_settings.default_model
        else:
            # 从配置管理器加载配置
            config = config_manager.load_config()
            self.api_key = config.get('api_key', '')
            self.base_url = config.get('base_url', '')
            self.model_name = config.get('model_name', app_settings.default_model)

        # 初始化OpenAI客户端 - 使用异步客户端
        self.client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url if self.base_url else None
        )

    def preload_knowledge_stream(self, library_ids: List[str] = None, library_docs: Dict[str, List[str]] = None):
        """预加载知识库内容，全量缓存不截断，按需检索相关片段。

        Yields:
            dict 进度事件
        """
        # 1. 使用 knowledge_retriever 预加载（全量缓存 + 建立索引）
        for evt in knowledge_retriever.preload(
            knowledge_service,
            library_ids=library_ids,
            library_docs=library_docs,
        ):
            yield evt

        # 2. 根据当前模型配置检索策略
        context_limit = _get_context_limit(self.model_name)
        knowledge_retriever.configure_for_model(
            model_name=self.model_name,
            context_limit=context_limit,
            output_reserve_ratio=OUTPUT_RESERVE_RATIO,
        )

        stats = knowledge_retriever.stats
        yield {
            'status': 'done',
            'message': f'知识库预加载完成（{"智能检索" if stats["use_retrieval"] else "全量注入"}模式）',
            'original_chars': stats['total_chars'],
            'original_tokens': stats['total_tokens'],
            'truncated_chars': stats['total_chars'],
            'max_kb_tokens': stats['max_kb_tokens'],
            'model_name': self.model_name,
            'context_limit': context_limit,
            'use_retrieval': stats['use_retrieval'],
        }

    @staticmethod
    def get_knowledge_for_chapter(chapter_title: str, chapter_description: str = '') -> str:
        """根据章节信息获取知识库内容（委托给 knowledge_retriever）。"""
        return knowledge_retriever.get_knowledge_for_chapter(chapter_title, chapter_description)

    @staticmethod
    def clear_knowledge_cache():
        """清除知识库缓存"""
        knowledge_retriever.clear()
        logger.info("[知识库预加载] 缓存已清除")
    
    async def get_available_models(self) -> List[str]:
        """获取可用的模型列表。

        返回精选推荐列表，只包含适合文档生成的对话模型。
        """
        return [
            # 通义千问
            'qwen3-max', 'qwen-max', 'qwen-plus',
            'qwen-max-latest', 'qwen-plus-latest',
            'qwen-turbo', 'qwen3-235b-a22b', 'qwen-long',
            # DeepSeek
            'deepseek-chat', 'deepseek-reasoner',
            # MiniMax
            'MiniMax-M2.5', 'MiniMax-M2.5-highspeed', 'MiniMax-M2.1',
            # Kimi / Moonshot
            'kimi-k2.5', 'kimi-k2-thinking', 'kimi-k2-thinking-turbo', 'moonshot-v1-128k',
            # 智谱 GLM
            'glm-5', 'glm-4.6', 'glm-4-plus',
            # 硅基流动
            'Pro/deepseek-ai/DeepSeek-V3', 'Pro/Qwen/Qwen2.5-72B-Instruct',
            # Ollama 本地
            'deepseek-r1:32b', 'qwen2.5:32b', 'llama3.1:70b',
        ]
    
    async def stream_chat_completion(
        self, 
        messages: list, 
        temperature: float = 0.7,
        response_format: dict = None
    ) -> AsyncGenerator[str, None]:
        """流式聊天完成请求 - 真正的异步实现，含 429 限流自动重试"""
        # DeepSeek R1 / reasoner 等思考模型不支持 response_format 和 temperature 参数
        model_lower = self.model_name.lower()
        is_reasoner = 'reasoner' in model_lower or model_lower.startswith('deepseek-r1')

        # 构建基础参数
        kwargs: dict = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
        }
        if not is_reasoner:
            kwargs["temperature"] = temperature
            if response_format is not None:
                kwargs["response_format"] = response_format

        # 429 限流重试配置
        MAX_RETRIES = 5
        BASE_DELAY = 15  # 秒，TPM 限流通常需要等较长时间

        for attempt in range(MAX_RETRIES + 1):
            try:
                # 尝试带 stream_options 调用（获取 usage 统计），失败则退回不带该参数
                use_stream_options = True
                try:
                    kwargs_with_opts = {**kwargs, "stream_options": {"include_usage": True}}
                    stream = await self.client.chat.completions.create(**kwargs_with_opts)
                except Exception as e:
                    err_msg = str(e).lower()
                    if 'stream_options' in err_msg or 'unknown' in err_msg or 'unexpected' in err_msg:
                        logger.info(f"[stream_options] API 不支持 stream_options，退回普通流式调用")
                        use_stream_options = False
                        stream = await self.client.chat.completions.create(**kwargs)
                    elif '429' in err_msg or 'rate' in err_msg:
                        raise  # 让外层 429 重试逻辑处理
                    else:
                        raise Exception(f"AI模型调用失败: {str(e)}")

                input_tokens = 0
                output_tokens = 0
                try:
                    async for chunk in stream:
                        if chunk.choices:
                            delta = chunk.choices[0].delta
                            text = getattr(delta, 'content', None)
                            if text is not None:
                                yield text
                        if use_stream_options and hasattr(chunk, 'usage') and chunk.usage:
                            input_tokens = getattr(chunk.usage, 'prompt_tokens', 0) or 0
                            output_tokens = getattr(chunk.usage, 'completion_tokens', 0) or 0

                    # 记录使用统计
                    try:
                        if input_tokens == 0:
                            input_tokens = sum(estimate_token_count(m.get("content", "")) for m in messages)
                        provider_id = config_manager._guess_provider_id(self.base_url)
                        config_manager.record_usage(provider_id, self.model_name, input_tokens, output_tokens)
                    except Exception:
                        pass

                except Exception as e:
                    raise Exception(f"AI模型调用失败: {str(e)}")

                # 成功完成，退出重试循环
                return

            except Exception as e:
                err_str = str(e)
                is_rate_limit = '429' in err_str or 'rate' in err_str.lower() or 'TPM' in err_str or 'RPM' in err_str
                if is_rate_limit and attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (attempt + 1)  # 递增等待：15s, 30s, 45s, 60s, 75s
                    logger.warning(f"[429限流] 第{attempt + 1}次重试，等待 {delay}s 后重试... ({err_str[:100]})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise Exception(f"AI模型调用失败: {err_str}")

    async def _collect_stream_text(
        self,
        messages: list,
        temperature: float = 0.7,
        response_format: dict | None = None,
    ) -> str:
        """收集流式返回的文本到一个完整字符串"""
        full_content = ""
        async for chunk in self.stream_chat_completion(
            messages,
            temperature=temperature,
            response_format=response_format,
        ):
            full_content += chunk
        return full_content

    async def _digest_knowledge_batches(
        self,
        chapter_title: str,
        chapter_description: str,
        max_tokens_per_call: int,
    ) -> str:
        """分批让 AI 消化知识库内容，提取与章节相关的要点。

        当知识库相关内容超出单次 prompt 的 token 限制时，
        使用 knowledge_retriever 的溢出分组功能将内容分成多组，
        每组让 AI 阅读并提取要点，最终合并为一份完整的消化摘要。

        Args:
            chapter_title: 章节标题
            chapter_description: 章节描述
            max_tokens_per_call: 每次 LLM 调用的知识库 token 预算

        Returns:
            消化后的知识库要点摘要文本
        """
        groups = knowledge_retriever.get_overflow_batches_for_chapter(
            chapter_title=chapter_title,
            chapter_description=chapter_description,
            max_tokens_per_call=max_tokens_per_call,
        )

        if not groups:
            return ""

        if len(groups) == 1:
            # 只有一组，直接拼接格式化文本返回，不需要消化
            parts = [b['formatted'] for b in groups[0]]
            return (
                "========== 知识库参考资料（必须严格遵守） ==========\n"
                "以下是致同会计师事务所的真实资料，生成内容时必须优先使用这些信息。\n"
                "严禁编造任何不存在于以下资料中的案例、人员、制度、流程等具体信息。\n\n"
                + "\n\n".join(parts) +
                "\n\n========== 知识库参考资料结束 ==========\n\n"
            )

        logger.info(
            f"[分批消化] 章节 '{chapter_title}' 知识库内容分为 {len(groups)} 组消化"
        )

        digest_system = (
            "你是致同会计师事务所的资深审计专家。你的任务是阅读知识库资料，"
            "提取与指定章节相关的所有要点信息。\n"
            "要求：\n"
            "1. 保留所有与章节相关的具体数据、案例、制度、流程、人员等事实性信息\n"
            "2. 保留原文的关键表述，不要过度概括\n"
            "3. 按主题分类整理，便于后续写作引用\n"
            "4. 如果资料与章节无关，直接跳过\n"
            "5. 输出格式为结构化的要点列表"
        )

        accumulated_digest = ""

        for group_idx, group_batches in enumerate(groups):
            batch_text = "\n\n".join(b['formatted'] for b in group_batches)
            group_tokens = sum(b['tokens'] for b in group_batches)

            # 构建本组的 prompt
            if accumulated_digest:
                user_content = (
                    f"章节标题：{chapter_title}\n"
                    f"章节描述：{chapter_description}\n\n"
                    f"前面批次已提取的要点：\n{accumulated_digest}\n\n"
                    f"请继续阅读以下知识库资料（第 {group_idx + 1}/{len(groups)} 组），"
                    f"提取与该章节相关的新增要点，与前面的要点合并输出完整的要点列表：\n\n"
                    f"{batch_text}"
                )
            else:
                user_content = (
                    f"章节标题：{chapter_title}\n"
                    f"章节描述：{chapter_description}\n\n"
                    f"请阅读以下知识库资料（第 {group_idx + 1}/{len(groups)} 组），"
                    f"提取与该章节相关的所有要点信息：\n\n"
                    f"{batch_text}"
                )

            messages = [
                {"role": "system", "content": digest_system},
                {"role": "user", "content": user_content},
            ]

            accumulated_digest = await self._collect_stream_text(
                messages, temperature=0.3
            )

            logger.info(
                f"[分批消化] 第 {group_idx + 1}/{len(groups)} 组完成，"
                f"本组 {group_tokens} tokens，摘要 {len(accumulated_digest)} 字符"
            )

        # 将消化后的摘要格式化为知识库注入文本
        if accumulated_digest.strip():
            result = (
                "========== 知识库参考资料（已消化整理，必须严格遵守） ==========\n"
                "以下是从致同会计师事务所知识库中提取的与本章节相关的要点信息。\n"
                "生成内容时必须优先使用这些信息，严禁编造不存在的事实。\n\n"
                f"{accumulated_digest}\n\n"
                "========== 知识库参考资料结束 ==========\n\n"
            )
            logger.info(
                f"[分批消化] 章节 '{chapter_title}' 消化完成，"
                f"最终摘要 {len(result)} 字符"
            )
            return result

        return ""

    # 单次生成的安全字数上限（大多数模型 max_output_tokens ≈ 4096~8192 tokens ≈ 2500~5000 中文字）
    SINGLE_BATCH_CHAR_LIMIT = 3000

    async def _generate_long_content_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        target_word_count: int,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """
        智能分批生成长内容。

        当 target_word_count <= SINGLE_BATCH_CHAR_LIMIT 时直接单次生成；
        否则先让 AI 规划小节提纲，再逐小节生成并流式输出。
        """
        if target_word_count <= self.SINGLE_BATCH_CHAR_LIMIT:
            # 短内容，直接单次生成
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            async for chunk in self.stream_chat_completion(messages, temperature=temperature):
                yield chunk
            return

        # --- 长内容：分批生成 ---
        num_sections = max(target_word_count // self.SINGLE_BATCH_CHAR_LIMIT, 2)
        words_per_section = target_word_count // num_sections

        logger.info(f"[分批生成] 目标 {target_word_count} 字，拆分为 {num_sections} 个小节，每节约 {words_per_section} 字")

        # 第一步：让 AI 规划小节结构
        plan_prompt = f"""{user_prompt}

【特别指令 - 仅规划小节结构】
本章节目标字数为 {target_word_count} 字，需要拆分为 {num_sections} 个小节分批撰写。
请先规划小节结构，每个小节给出：序号、小节标题、要点概述（一句话）。
只输出小节规划列表，不要生成正文内容。格式如下：
1. 小节标题 - 要点概述
2. 小节标题 - 要点概述
..."""

        plan_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": plan_prompt},
        ]

        plan_text = await self._collect_stream_text(plan_messages, temperature=temperature)
        logger.info(f"[分批生成] 小节规划:\n{plan_text[:500]}")

        # 解析小节列表（简单按行解析，每行一个小节）
        sections = []
        for line in plan_text.strip().split('\n'):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                sections.append(line)

        if not sections:
            # 解析失败，退化为单次生成
            logger.warning("[分批生成] 小节规划解析失败，退化为单次生成")
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            async for chunk in self.stream_chat_completion(messages, temperature=temperature):
                yield chunk
            return

        logger.info(f"[分批生成] 解析到 {len(sections)} 个小节")

        # 第二步：逐小节生成内容
        generated_so_far = ""
        for idx, section_desc in enumerate(sections):
            is_last = (idx == len(sections) - 1)
            remaining_words = target_word_count - len(generated_so_far.replace(' ', '').replace('\n', ''))
            section_target = remaining_words if is_last else words_per_section

            section_prompt = f"""{user_prompt}

【分批生成指令 - 第 {idx + 1}/{len(sections)} 节】
完整小节规划：
{plan_text}

当前要生成的是第 {idx + 1} 节：{section_desc}
本节目标字数：约 {section_target} 字

{"已生成的前文内容（请自然衔接，不要重复）：" + chr(10) + generated_so_far[-1500:] if generated_so_far else "这是第一节，请直接开始撰写。"}

【要求】
1. 只生成本节内容，不要生成其他小节的内容
2. 与前文自然衔接，不要重复已有内容
3. 本节必须达到约 {section_target} 字
4. 直接输出正文，不要输出小节标题编号
5. 写作风格要像真人撰写：段落长短自然变化，禁止"首先...其次...再次"结构，禁止使用赋能、闭环、抓手等AI词汇"""

            section_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": section_prompt},
            ]

            section_content = ""
            async for chunk in self.stream_chat_completion(section_messages, temperature=temperature):
                section_content += chunk
                yield chunk

            generated_so_far += section_content

            # 小节之间加换行分隔
            if not is_last:
                separator = "\n\n"
                generated_so_far += separator
                yield separator

            logger.info(f"[分批生成] 第 {idx + 1}/{len(sections)} 节完成，本节 {len(section_content)} 字，累计 {len(generated_so_far)} 字")


    async def _generate_with_json_check(
        self,
        messages: list,
        schema: str | Dict[str, Any],
        max_retries: int = 3,
        temperature: float = 0.7,
        response_format: dict | None = None,
        log_prefix: str = "",
        raise_on_fail: bool = True,
    ) -> str:
        """
        通用的带 JSON 结构校验与重试的生成函数。

        返回：通过校验的 full_content；如果 raise_on_fail=False，则在多次失败后返回最后一次内容。
        """
        attempt = 0
        last_error_msg = ""

        while True:
            full_content = await self._collect_stream_text(
                messages,
                temperature=temperature,
                response_format=response_format,
            )

            isok, error_msg = check_json(str(full_content), schema)
            if isok:
                return full_content

            last_error_msg = error_msg
            prefix = f"{log_prefix} " if log_prefix else ""

            if attempt >= max_retries:
                logger.warning(f"{prefix}check_json 校验失败，已达到最大重试次数({max_retries})：{last_error_msg}")
                if raise_on_fail:
                    raise Exception(f"{prefix}check_json 校验失败: {last_error_msg}")
                # 不抛异常，返回最后一次内容（保持原有行为）
                return full_content

            attempt += 1
            logger.warning(f"{prefix}check_json 校验失败，进行第 {attempt}/{max_retries} 次重试：{last_error_msg}")
            await asyncio.sleep(0.5)

    async def generate_content_for_outline(self, outline: Dict[str, Any], project_overview: str = "") -> Dict[str, Any]:
        """为目录结构生成内容"""
        try:
            if not isinstance(outline, dict) or 'outline' not in outline:
                raise Exception("无效的outline数据格式")
            
            # 深拷贝outline数据
            result_outline = copy.deepcopy(outline)
            
            # 递归处理目录
            await self._process_outline_recursive(result_outline['outline'], [], project_overview)
            
            return result_outline
            
        except Exception as e:
            raise Exception(f"处理过程中发生错误: {str(e)}")
    
    async def _process_outline_recursive(self, chapters: list, parent_chapters: list = None, project_overview: str = ""):
        """递归处理章节列表"""
        for chapter in chapters:
            chapter_id = chapter.get('id', 'unknown')
            chapter_title = chapter.get('title', '未命名章节')
            
            # 检查是否为叶子节点
            is_leaf = 'children' not in chapter or not chapter.get('children', [])
            
            # 准备当前章节信息
            current_chapter_info = {
                'id': chapter_id,
                'title': chapter_title,
                'description': chapter.get('description', '')
            }
            
            # 构建完整的上级章节列表
            current_parent_chapters = []
            if parent_chapters:
                current_parent_chapters.extend(parent_chapters)
            current_parent_chapters.append(current_chapter_info)
            
            if is_leaf:
                # 为叶子节点生成内容，传递同级章节信息
                content = ""
                async for chunk in self._generate_chapter_content(
                    chapter, 
                    current_parent_chapters[:-1],  # 上级章节列表（排除当前章节）
                    chapters,  # 同级章节列表
                    project_overview
                ):
                    content += chunk
                if content:
                    chapter['content'] = content
            else:
                # 递归处理子章节
                await self._process_outline_recursive(chapter['children'], current_parent_chapters, project_overview)
    
    async def _generate_chapter_content(self, chapter: dict, parent_chapters: list = None, sibling_chapters: list = None, project_overview: str = "", target_word_count: int = 1500, library_ids: List[str] = None, library_docs: Dict[str, List[str]] = None, web_references: List[Dict[str, str]] = None) -> AsyncGenerator[str, None]:
        """
        为单个章节流式生成内容

        Args:
            chapter: 章节数据
            parent_chapters: 上级章节列表，每个元素包含章节id、标题和描述
            sibling_chapters: 同级章节列表，避免内容重复
            project_overview: 项目概述信息，提供项目背景和要求
            target_word_count: 目标字数，根据用户配置自动计算

        Yields:
            生成的内容流
        """
        try:
            chapter_id = chapter.get('id', 'unknown')
            chapter_title = chapter.get('title', '未命名章节')
            chapter_description = chapter.get('description', '')

            # 构建提示词（集中管理于 prompt_manager）
            system_prompt = chapter_content_system_prompt()

            # 构建上下文信息
            context_info = ""
            
            # 上级章节信息
            if parent_chapters:
                context_info += "上级章节信息：\n"
                for parent in parent_chapters:
                    context_info += f"- {parent['id']} {parent['title']}\n  {parent['description']}\n"
            
            # 同级章节信息（排除当前章节）
            if sibling_chapters:
                context_info += "同级章节信息（请避免内容重复）：\n"
                for sibling in sibling_chapters:
                    if sibling.get('id') != chapter_id:  # 排除当前章节
                        context_info += f"- {sibling.get('id', 'unknown')} {sibling.get('title', '未命名')}\n  {sibling.get('description', '')}\n"

            # 构建用户提示词
            project_info = ""
            if project_overview.strip():
                project_info = f"项目概述信息：\n{project_overview}\n\n"
            
            # 优先使用预加载的知识库缓存，避免每个章节重复读取磁盘
            knowledge_info = ""
            cached_kb = self.get_knowledge_for_chapter(chapter_title, chapter_description)
            if cached_kb:
                knowledge_info = cached_kb
                mode = '智能检索' if knowledge_retriever.use_retrieval else '全量注入'
                logger.info(f"[知识库] 章节 {chapter_title} 使用预加载缓存（{mode}模式，{len(cached_kb)} 字符）")
            else:
                # 没有预加载缓存，回退到直接读取（兼容单章节生成场景）
                try:
                    if library_docs:
                        kb_content = knowledge_service.get_selected_knowledge(library_docs)
                    else:
                        kb_content = knowledge_service.get_all_knowledge_full(library_ids)
                    
                    if kb_content.strip():
                        knowledge_info = f"""
========== 知识库参考资料（必须严格遵守） ==========
以下是致同会计师事务所的真实资料，生成内容时必须优先使用这些信息。
严禁编造任何不存在于以下资料中的案例、人员、制度、流程等具体信息。

{kb_content}

========== 知识库参考资料结束 ==========

"""
                        logger.info(f"[知识库] 章节 {chapter_title} 直接读取，长度: {len(kb_content)} 字符")
                    else:
                        logger.info(f"[知识库] 知识库为空，无参考资料")
                except Exception as e:
                    logger.error(f"读取知识库时出错: {str(e)}")
            
            # 判断是否有知识库内容
            has_knowledge = bool(knowledge_info.strip())
            
            # 构建网络搜索参考资料
            web_ref_info = ""
            if web_references:
                ref_texts = []
                for ref in web_references:
                    ref_texts.append(f"来源: {ref.get('title', '未知')}\nURL: {ref.get('url', '')}\n内容:\n{ref.get('content', '')}")
                web_ref_info = f"""
========== 网络搜索参考资料 ==========
以下是用户从互联网搜索收集的参考资料，可作为补充参考，但知识库资料优先级更高。

{chr(10).join(ref_texts)}

========== 网络搜索参考资料结束 ==========

"""
                logger.info(f"[网络参考] 已加载 {len(web_references)} 条网络参考资料")

            user_prompt = f"""请为以下审计文档章节生成具体内容：

{project_info}{knowledge_info if has_knowledge else "【注意】知识库中未找到与本章节相关的参考资料。\n\n"}{web_ref_info}{context_info if context_info else ''}当前章节信息：
章节ID: {chapter_id}
章节标题: {chapter_title}

【重要说明】
章节描述仅供参考理解章节要求，不要在正文中输出描述内容本身。
章节描述：{chapter_description}

【生成要求】
1. {"先仔细阅读知识库参考资料，找到与本章节相关的内容，优先将知识库原文（适当调整措辞）作为正文输出；知识库没有覆盖的部分再用通用方法论补充" if has_knowledge else "由于没有相关参考资料，请用【待补充：xxx】标注需要填写真实信息的地方"}
2. 不要编造任何具体数字，除非知识库中明确提供了该数据
3. 确保与上级章节逻辑相承，避免与同级章节内容重复
4. 本章节目标字数约{target_word_count}字，请确保内容充实完整
5. 直接输出正文，不要输出章节描述、章节标题、"根据章节描述..."等元信息
6. 不要使用Markdown标题格式（# ## ###），用中文序号组织层次

【写作风格提醒——请务必遵守】
- 你是一个真正的审计从业者在撰写审计文档，不是AI在生成文本
- 段落长短要自然变化，分点数量根据内容决定（2点、4点、6点都行，不要总是3点）
- 禁止"首先...其次...再次...最后"结构，禁止每段都用"从而实现..."收尾
- 禁止使用：赋能、闭环、抓手、打通、全方位、多维度、深度融合、无缝衔接、精准施策、提质增效、协同联动
- 开头不要千篇一律地用"针对本项目..."或"根据项目需求..."，直接切入实质内容
- 适当使用长句和复合句，全是短句会显得像AI生成的"""

            # 调用AI流式生成内容
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # Token限制检查与智能调整
            context_limit = _get_context_limit(self.model_name)
            max_input_tokens = int(context_limit * (1 - OUTPUT_RESERVE_RATIO))
            total_tokens = sum(estimate_token_count(m["content"]) for m in messages)
            if total_tokens > max_input_tokens:
                logger.warning(f"[Token限制] 章节 {chapter_title} 输入约 {total_tokens} tokens，超过限制 {max_input_tokens}")
                overflow = total_tokens - max_input_tokens
                if knowledge_info:
                    kb_tokens = estimate_token_count(knowledge_info)
                    new_kb_max = max(kb_tokens - overflow - 500, 1000)

                    # 检索模式下：尝试分批消化，确保所有相关知识都被 AI 读到
                    if knowledge_retriever.use_retrieval and knowledge_retriever.is_loaded:
                        # 获取所有相关 batch 的总 token 数
                        all_batches = knowledge_retriever.get_batches_for_chapter(
                            chapter_title, chapter_description, max_tokens=0)
                        all_relevant_tokens = sum(b['tokens'] for b in all_batches)

                        if all_relevant_tokens > new_kb_max and len(all_batches) > 1:
                            # 知识库内容超出预算，分批消化
                            logger.info(
                                f"[分批消化] 章节 {chapter_title} 相关知识 {all_relevant_tokens} tokens "
                                f"超出预算 {new_kb_max}，启动分批消化"
                            )
                            knowledge_info = await self._digest_knowledge_batches(
                                chapter_title=chapter_title,
                                chapter_description=chapter_description,
                                max_tokens_per_call=new_kb_max,
                            )
                        else:
                            # 重新检索更少的内容
                            knowledge_info = knowledge_retriever.get_formatted_for_chapter(
                                chapter_title=chapter_title,
                                chapter_description=chapter_description,
                                max_tokens=new_kb_max,
                            )
                            logger.info(f"[Token限制] 重新检索，缩减到 {len(knowledge_info)} 字符")
                    else:
                        knowledge_info = truncate_to_token_limit(knowledge_info, new_kb_max)

                    # 重建user_prompt
                    user_prompt = f"""请为以下审计文档章节生成具体内容：

{project_info}{knowledge_info}{context_info if context_info else ''}当前章节信息：
章节ID: {chapter_id}
章节标题: {chapter_title}

章节描述（仅供理解要求，不要在正文中输出）：{chapter_description}

【生成要求】
1. 优先将知识库中与本章节相关的原文内容作为正文输出，知识库没有的再补充
2. 不要编造任何具体数字，除非知识库中明确提供
3. 确保与上级章节逻辑相承，避免与同级章节内容重复
4. 本章节目标字数约{target_word_count}字
5. 不要使用Markdown标题格式，用中文序号组织层次
6. 直接输出正文，不要输出元信息

【写作风格提醒】
- 像真正的审计从业者撰写审计文档，不要像AI生成文本
- 禁止"首先...其次...再次...最后"结构，禁止总是分成3点
- 禁止使用：赋能、闭环、抓手、打通、全方位、多维度、深度融合、无缝衔接、精准施策、提质增效
- 段落长短自然变化，适当使用长句"""
                    messages[1]["content"] = user_prompt

            # 使用智能分批生成（长内容自动拆分小节）
            async for chunk in self._generate_long_content_stream(
                system_prompt=messages[0]["content"],
                user_prompt=messages[1]["content"],
                target_word_count=target_word_count,
                temperature=0.7,
            ):
                yield chunk

        except Exception as e:
            logger.error(f"生成章节内容时出错: {str(e)}")
            raise Exception(f"生成章节内容失败: {str(e)}")

    async def generate_outline_v2(self, overview: str, requirements: str, word_count: int = 100000, progress_callback=None) -> Dict[str, Any]:
        schema_json = json.dumps({
            "business_section": {
                "title": "商务部分",
                "chapters": [
                    {"rating_item": "原评分项（如有）", "new_title": "章节标题", "score": 0}
                ]
            },
            "technical_section": {
                "title": "技术部分", 
                "chapters": [
                    {"rating_item": "原评分项（如有）", "new_title": "章节标题", "score": 0}
                ]
            }
        }, ensure_ascii=False)

        system_prompt = f"""
### 角色
你是致同会计师事务所的专业审计文档编写专家，擅长根据项目需求编写审计文档。

### 任务
根据项目概述(overview)和文档结构要求(requirements)，设计审计文档的一级目录结构。

### 致同审计文档结构要求
审计文档必须分为两大部分：

**一、商务部分** - 展示事务所实力和资质，包括但不限于：
- 事务所简介及行业经验
- 项目团队及人员配置
- 类似项目业绩及案例
- 质量控制与风险管理
- 服务承诺与保障
- 报价及付款方式
- 其他商务条款

**二、技术部分** - 针对本项目的具体服务方案，包括但不限于：
- 项目理解与需求分析
- 审计方法与技术路线
- 工作计划与时间安排
- 重点难点分析及应对
- 交付成果与服务标准
- 增值服务方案

### 说明
1. 根据文档结构要求，将各要求项归类到商务部分或技术部分
2. 一级标题名称要专业化，不能完全照搬要求原文
3. 商务部分侧重"我们是谁、做过什么"，技术部分侧重"我们怎么做这个项目"
4. 确保覆盖所有要求项，同时可以适当补充必要章节
5. **每个部分至少要有3个章节**

### 分值（score）填写规则
- **score** 字段表示该章节在文档评审中的权重分值
- 如果文档要求中明确标注了该项的分值，直接填写对应分值
- 如果一个要求项被拆分为多个章节，按合理比例拆分分值
- 如果是你补充的章节（要求中没有对应项），score 填 0
- score 的单位与要求中的分值单位一致（通常是分）

### 重要提醒
- business_section.chapters 必须是一个非空数组，至少包含3个章节
- technical_section.chapters 必须是一个非空数组，至少包含3个章节
- 每个章节必须包含 rating_item、new_title、score 三个字段
- score 必须是数字（整数或小数），不能是字符串

### Output Format in JSON
{schema_json}

### 示例输出
{{
  "business_section": {{
    "title": "商务部分",
    "chapters": [
      {{"rating_item": "公司资质（5分）", "new_title": "公司简介及资质", "score": 5}},
      {{"rating_item": "项目团队（10分）", "new_title": "项目团队配置", "score": 10}},
      {{"rating_item": "", "new_title": "类似项目业绩", "score": 0}}
    ]
  }},
  "technical_section": {{
    "title": "技术部分",
    "chapters": [
      {{"rating_item": "技术方案（30分）", "new_title": "审计工作方案", "score": 30}},
      {{"rating_item": "项目理解（15分）", "new_title": "项目理解与分析", "score": 15}},
      {{"rating_item": "质量保障（10分）", "new_title": "质量控制措施", "score": 10}}
    ]
  }}
}}
"""
        user_prompt = f"""
### 项目信息

<overview>
{overview}
</overview>

<requirements>
{requirements}
</requirements>

请根据以上信息，设计分为商务部分和技术部分的审计文档一级目录。
直接返回json，不要任何额外说明或格式标记。
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        full_content = await self._generate_with_json_check(
            messages=messages,
            schema=schema_json,
            max_retries=3,
            temperature=0.7,
            response_format={"type": "json_object"},
            log_prefix="一级提纲",
            raise_on_fail=False,  # 不抛出异常，返回最后一次结果
        )

        # 通过校验后再进行 JSON 解析
        try:
            parsed_result = json.loads(full_content.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[目录生成] JSON解析失败: {str(e)}")
            # 返回默认结构
            parsed_result = {
                "business_section": {
                    "title": "商务部分",
                    "chapters": [
                        {"rating_item": "公司资质与经验", "new_title": "公司简介及资质", "score": 0},
                        {"rating_item": "项目团队", "new_title": "项目团队配置", "score": 0},
                        {"rating_item": "类似项目业绩", "new_title": "项目业绩案例", "score": 0}
                    ]
                },
                "technical_section": {
                    "title": "技术部分",
                    "chapters": [
                        {"rating_item": "项目理解", "new_title": "项目理解与需求分析", "score": 0},
                        {"rating_item": "工作方案", "new_title": "审计工作方案", "score": 0},
                        {"rating_item": "质量保障", "new_title": "质量控制措施", "score": 0}
                    ]
                }
            }
        
        # 合并商务部分和技术部分的章节
        level_l1 = []
        business_chapters = parsed_result.get("business_section", {}).get("chapters", [])
        technical_chapters = parsed_result.get("technical_section", {}).get("chapters", [])
        
        # 如果章节为空，使用默认章节
        if not business_chapters:
            logger.warning("[目录生成] 商务部分章节为空，使用默认章节")
            business_chapters = [
                {"rating_item": "公司资质与经验", "new_title": "公司简介及资质", "score": 0},
                {"rating_item": "项目团队", "new_title": "项目团队配置", "score": 0},
                {"rating_item": "类似项目业绩", "new_title": "项目业绩案例", "score": 0}
            ]
        
        if not technical_chapters:
            logger.warning("[目录生成] 技术部分章节为空，使用默认章节")
            technical_chapters = [
                {"rating_item": "项目理解", "new_title": "项目理解与需求分析", "score": 0},
                {"rating_item": "工作方案", "new_title": "审计工作方案", "score": 0},
                {"rating_item": "质量保障", "new_title": "质量控制措施", "score": 0}
            ]
        
        # 添加商务部分标记
        for ch in business_chapters:
            ch["section_type"] = "business"
        for ch in technical_chapters:
            ch["section_type"] = "technical"
            
        level_l1 = business_chapters + technical_chapters

        expected_word_count = word_count
        
        # 商务部分固定 2%，技术部分 98%
        business_total_words = int(expected_word_count * 0.02)
        technical_total_words = int(expected_word_count * 0.98)
        
        logger.info(f"[字数分配] 总字数: {expected_word_count}, 商务部分: {business_total_words} (2%), 技术部分: {technical_total_words} (98%)")

        # --- 提取技术部分各章节的分值权重 ---
        tech_scores = [float(ch.get("score", 0)) for ch in technical_chapters]
        has_scores = any(s > 0 for s in tech_scores)
        
        if has_scores:
            # 有分值的章节按分值比例分配；无分值的补充章节给一个最小权重
            min_score = min((s for s in tech_scores if s > 0), default=1)
            tech_weights = [s if s > 0 else min_score * 0.3 for s in tech_scores]
            logger.info(f"[字数分配] 技术部分按评分权重分配: scores={tech_scores}, weights={tech_weights}")
        else:
            # 评分要求中没有分值，均匀分配
            tech_weights = [1.0] * len(technical_chapters)
            logger.info(f"[字数分配] 技术部分无评分分值，均匀分配")

        # --- 计算叶子节点总数 ---
        # 商务部分
        business_leaf_node_target = max(business_total_words // 1500, len(business_chapters))
        
        # 技术部分
        technical_leaf_node_target = max(technical_total_words // 1500, len(technical_chapters))
        
        # --- 节点分布 ---
        # 商务部分：均匀 + 随机加权
        if len(business_chapters) > 0:
            business_index1, business_index2 = get_random_indexes(len(business_chapters))
            business_nodes_distribution = calculate_nodes_distribution(
                len(business_chapters), 
                (business_index1, business_index2), 
                business_leaf_node_target
            )
            logger.info(f"[节点分布] 商务部分: leaf_nodes={business_nodes_distribution['leaf_nodes']}")
        else:
            business_nodes_distribution = {'level2_nodes': [], 'leaf_nodes': [], 'leaf_per_level2': []}
        
        # 技术部分：按分值权重分配叶子节点
        if len(technical_chapters) > 0:
            technical_nodes_distribution = calculate_nodes_distribution_by_weights(
                tech_weights,
                technical_leaf_node_target
            )
            logger.info(f"[节点分布] 技术部分(按权重): leaf_nodes={technical_nodes_distribution['leaf_nodes']}")
        else:
            technical_nodes_distribution = {'level2_nodes': [], 'leaf_nodes': [], 'leaf_per_level2': []}
        
        # --- 根据实际叶子节点总数反算 words_per_leaf，确保总字数精确匹配 ---
        actual_business_leaves = sum(business_nodes_distribution.get('leaf_nodes', []))
        actual_technical_leaves = sum(technical_nodes_distribution.get('leaf_nodes', []))
        
        business_words_per_leaf = max(business_total_words // actual_business_leaves, 300) if actual_business_leaves > 0 else 300
        technical_words_per_leaf = max(technical_total_words // actual_technical_leaves, 500) if actual_technical_leaves > 0 else 1500
        
        logger.info(f"[字数分配] 商务: {len(business_chapters)} 章, {actual_business_leaves} 叶子, 每叶 {business_words_per_leaf} 字, 预计总字数 {actual_business_leaves * business_words_per_leaf}")
        logger.info(f"[字数分配] 技术: {len(technical_chapters)} 章, {actual_technical_leaves} 叶子, 每叶 {technical_words_per_leaf} 字, 预计总字数 {actual_technical_leaves * technical_words_per_leaf}")
        logger.info(f"[字数分配] 预计总字数: {actual_business_leaves * business_words_per_leaf + actual_technical_leaves * technical_words_per_leaf} (目标: {expected_word_count})")
        
        # 并发生成每个一级节点的提纲，保持结果顺序
        # 为商务和技术部分使用不同的words_per_leaf和nodes_distribution
        tasks = []
        business_count = len(business_chapters)
        
        for i, level1_node in enumerate(level_l1):
            if level1_node.get("section_type") == "business":
                words_per_leaf = business_words_per_leaf
                # 商务部分使用商务的nodes_distribution，索引从0开始
                nodes_dist = business_nodes_distribution
                node_index = i  # 在商务部分中的索引
                logger.info(f"[目录生成] 第{i+1}章（商务）: {level1_node.get('new_title')}, 每叶字数: {words_per_leaf}")
            else:
                words_per_leaf = technical_words_per_leaf
                # 技术部分使用技术的nodes_distribution，索引需要减去商务部分的数量
                nodes_dist = technical_nodes_distribution
                node_index = i - business_count  # 在技术部分中的索引
                logger.info(f"[目录生成] 第{i+1}章（技术）: {level1_node.get('new_title')}, 每叶字数: {words_per_leaf}")
            
            tasks.append(
                self.process_level1_node(node_index, level1_node, nodes_dist, level_l1, overview, requirements, words_per_leaf)
            )
        
        logger.info(f"[目录生成] 开始并发生成 {len(tasks)} 个章节的详细目录...")
        if progress_callback:
            await progress_callback(f"一级目录已生成（{len(level_l1)} 章），正在并发生成二三级目录...")
        try:
            total_tasks = len(tasks)
            completed_count = 0

            async def _run_with_progress(idx, coro):
                """包装协程，完成后报告进度"""
                nonlocal completed_count
                try:
                    result = await coro
                    completed_count += 1
                    chapter_name = level_l1[idx].get('new_title', f'第{idx+1}章')
                    logger.info(f"[目录生成] 完成 {completed_count}/{total_tasks}: {chapter_name}")
                    if progress_callback:
                        await progress_callback(f"已完成 {completed_count}/{total_tasks} 个章节：{chapter_name}")
                    return result
                except Exception as e:
                    completed_count += 1
                    if progress_callback:
                        await progress_callback(f"已完成 {completed_count}/{total_tasks}（第{idx+1}章失败，将重试）")
                    raise

            wrapped_tasks = [_run_with_progress(i, t) for i, t in enumerate(tasks)]
            all_results = await asyncio.gather(*wrapped_tasks, return_exceptions=True)
            
            # 分离成功和失败的结果
            all_chapters = []
            failed_indices = []
            for i, result in enumerate(all_results):
                if isinstance(result, Exception):
                    logger.error(f"[目录生成] 第{i+1}章生成失败: {str(result)}")
                    failed_indices.append(i)
                else:
                    all_chapters.append(result)
            
            # 对失败的章节进行单独重试（最多1次）
            if failed_indices:
                logger.warning(f"[目录生成] {len(failed_indices)} 个章节失败，开始重试...")
                for idx in failed_indices:
                    level1_node = level_l1[idx]
                    try:
                        if level1_node.get("section_type") == "business":
                            wpl = business_words_per_leaf
                            nd = business_nodes_distribution
                            ni = idx
                        else:
                            wpl = technical_words_per_leaf
                            nd = technical_nodes_distribution
                            ni = idx - business_count
                        retry_result = await self.process_level1_node(ni, level1_node, nd, level_l1, overview, requirements, wpl)
                        all_chapters.append(retry_result)
                        logger.info(f"[目录生成] 重试成功: {level1_node.get('new_title')}")
                    except Exception as retry_e:
                        logger.error(f"[目录生成] 重试仍失败: {level1_node.get('new_title')}: {str(retry_e)}")
            
            logger.info(f"[目录生成] 目录生成完成，成功 {len(all_chapters)}/{len(level_l1)} 个章节")
        except Exception as e:
            logger.error(f"[目录生成] 并发生成失败: {str(e)}")
            traceback.print_exc()
            raise
        
        # 按商务/技术分组返回
        business_outline = [ch for ch in all_chapters if ch.get("section_type") == "business"]
        technical_outline = [ch for ch in all_chapters if ch.get("section_type") == "technical"]
        
        # 计算各部分的总字数
        business_word_count = sum(ch.get("target_word_count", 0) for ch in business_outline)
        technical_word_count = sum(ch.get("target_word_count", 0) for ch in technical_outline)
        
        return {
            "outline": [
                {
                    "id": "1",
                    "title": "商务部分",
                    "description": "展示事务所实力和资质",
                    "target_word_count": business_word_count,
                    "children": business_outline
                },
                {
                    "id": "2", 
                    "title": "技术部分",
                    "description": "针对本项目的具体服务方案",
                    "target_word_count": technical_word_count,
                    "children": technical_outline
                }
            ]
        }
    
    async def process_level1_node(self, node_index, level1_node, nodes_distribution, level_l1, overview, requirements, words_per_leaf: int = 1500):
        """
        处理单个一级节点的函数
        
        Args:
            node_index: 节点在其所属部分（商务或技术）中的索引（从0开始）
            level1_node: 一级节点数据
            nodes_distribution: 节点分布信息（商务或技术部分的）
            level_l1: 所有一级节点列表
            overview: 项目概述
            requirements: 评分要求
            words_per_leaf: 每个叶子节点的目标字数
        """

        # 生成json（包含每个章节的目标字数）
        # node_index是从0开始的，generate_one_outline_json_by_level1需要从1开始的索引
        json_outline = generate_one_outline_json_by_level1(level1_node["new_title"], node_index + 1, nodes_distribution, words_per_leaf)
        logger.info(f"正在处理章节: {level1_node['new_title']} (索引: {node_index + 1})")
        
        # 其他标题（排除当前节点）
        other_outline = "\n".join([f"{j+1}. {node['new_title']}" 
                            for j, node in enumerate(level_l1) 
                            if node.get('new_title') != level1_node.get('new_title')])

        system_prompt = f"""
    ### 角色
    你是专业的审计文档编写专家，擅长根据项目需求编写审计文档。
    
    ### 任务
    1. 根据得到项目概述(overview)、文档结构要求(requirements)补全审计文档的提纲的二三级目录
    
    ### 说明
    1. 你将会得到一段json，这是提纲的其中一个章节，你需要在原结构上补全标题(title)和描述(description)
    2. 二级标题根据一级标题撰写,三级标题根据二级标题撰写
    3. 补全的内容要参考项目概述(overview)、评分要求(requirements)等项目信息
    4. 你还会收到其他章节的标题(other_outline)，你需要确保本章节的内容不会包含其他章节的内容
    
    ### 注意事项
    在原json上补全信息，禁止修改json结构，禁止修改一级标题

    ### Output Format in JSON
    {json_outline}

    """
        user_prompt = f"""
    ### 项目信息

    <overview>
    {overview}
    </overview>

    <requirements>
    {requirements}
    </requirements>
    
    <other_outline>
    {other_outline}
    </other_outline>


    直接返回json，不要任何额外说明或格式标记

    """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # 使用通用方法进行 JSON 校验与重试（失败时不抛异常，保持原有"返回最后一次结果"的行为）
        full_content = await self._generate_with_json_check(
            messages=messages,
            schema=json_outline,
            max_retries=3,
            temperature=0.7,
            response_format={"type": "json_object"},
            log_prefix=f"{level1_node['new_title']}",
            raise_on_fail=False,
        )

        result = json.loads(full_content.strip())
        # 保留section_type标记
        if "section_type" in level1_node:
            result["section_type"] = level1_node["section_type"]
        
        # 重新注入target_word_count（AI可能会丢失这个字段）
        self._inject_word_count(result, json_outline)
        logger.debug(f"[字数注入] {level1_node['new_title']} 注入后: target_word_count={result.get('target_word_count')}")
        
        return result
    
    def _inject_word_count(self, result: dict, original: dict):
        """将原始的target_word_count注入到AI生成的结果中"""
        if isinstance(original, dict) and "target_word_count" in original:
            result["target_word_count"] = original["target_word_count"]
        
        # 递归处理children
        result_children = result.get("children", [])
        original_children = original.get("children", []) if isinstance(original, dict) else []
        
        for r_child, o_child in zip(result_children, original_children):
            self._inject_word_count(r_child, o_child)
    
    async def revise_chapter_content(
        self,
        chapter: dict,
        current_content: str,
        messages: list,
        user_instruction: str,
        project_overview: str = "",
        parent_chapters: list = None,
        sibling_chapters: list = None,
        library_docs: Dict[str, List[str]] = None,
        web_references: List[Dict[str, str]] = None
    ) -> AsyncGenerator[str, None]:
        """
        基于用户指令修改章节内容（支持对话历史）

        Args:
            chapter: 章节信息
            current_content: 当前章节内容
            messages: 对话历史 [{"role": "user/assistant", "content": "..."}]
            user_instruction: 用户的修改指令
            project_overview: 项目概述
            parent_chapters: 上级章节列表
            sibling_chapters: 同级章节列表
            library_docs: 要使用的具体文档

        Yields:
            修改后的内容流
        """
        try:
            chapter_title = chapter.get('title', '未命名章节')
            chapter_description = chapter.get('description', '')
            
            logger.info(f"[章节修改] 章节: {chapter_title}")
            logger.info(f"[章节修改] 当前内容长度: {len(current_content)}")
            logger.info(f"[章节修改] 历史消息数: {len(messages)}")
            logger.info(f"[章节修改] 用户指令: {user_instruction}")

            # 构建系统提示词（集中管理于 prompt_manager）
            system_prompt = chapter_revision_system_prompt()

            # 读取知识库内容
            knowledge_info = ""
            if library_docs:
                try:
                    from .knowledge_service import knowledge_service
                    kb_content = knowledge_service.get_selected_knowledge(library_docs)
                    if kb_content.strip():
                        knowledge_info = f"""
========== 知识库参考资料 ==========
{kb_content}
========== 知识库参考资料结束 ==========

"""
                        logger.info(f"[章节修改] 已读取知识库，长度: {len(kb_content)}")
                except Exception as e:
                    logger.error(f"[章节修改] 读取知识库时出错: {str(e)}")

            # 构建上下文信息
            context_info = ""
            
            # 上级章节信息
            if parent_chapters:
                context_info += "上级章节信息（请确保修改后的内容与上级章节逻辑相承）：\n"
                for parent in parent_chapters:
                    context_info += f"- {parent.get('id', '')} {parent.get('title', '')}\n  {parent.get('description', '')}\n"
                context_info += "\n"
            
            # 同级章节信息
            if sibling_chapters:
                context_info += "同级章节信息（请避免内容重复）：\n"
                for sibling in sibling_chapters:
                    if sibling.get('id') != chapter.get('id'):  # 排除当前章节
                        context_info += f"- {sibling.get('id', '')} {sibling.get('title', '')}\n  {sibling.get('description', '')}\n"
                context_info += "\n"

            # 构建初始上下文
            web_ref_info = ""
            if web_references:
                ref_texts = []
                for ref in web_references:
                    ref_texts.append(f"来源: {ref.get('title', '未知')}\nURL: {ref.get('url', '')}\n内容:\n{ref.get('content', '')}")
                web_ref_info = f"""
========== 网络搜索参考资料 ==========
{chr(10).join(ref_texts)}
========== 网络搜索参考资料结束 ==========

"""

            initial_context = f"""
章节信息：
- 标题：{chapter_title}

【重要说明】
章节描述仅供参考理解章节要求，不要在正文中输出描述内容本身。
章节描述：{chapter_description}

项目概述：
{project_overview if project_overview.strip() else '无'}

{context_info}{knowledge_info}{web_ref_info}当前章节内容：
{current_content}
"""

            # 构建消息列表
            chat_messages = [{"role": "system", "content": system_prompt}]
            
            # 如果是第一次对话，添加上下文
            if not messages or len(messages) == 0:
                chat_messages.append({
                    "role": "user",
                    "content": f"{initial_context}\n\n用户修改要求：\n{user_instruction}\n\n【重要提醒】\n1. 请确保修改后的内容与整体文档风格一致，参照知识库中的表达方式，避免AI痕迹。\n2. 不要在正文中输出章节描述内容本身，描述仅供理解要求。\n3. 直接生成正文内容，不要输出'根据章节描述...'等元信息。\n4. 严格保持原内容的排版格式：如果原文使用'一、二、三'，修改后也必须用'一、二、三'；如果原文使用'（一）（二）'，修改后也必须用'（一）（二）'。不要改变标题层级、列表样式、缩进格式。"
                })
                logger.info(f"[章节修改] 首次对话，消息数: {len(chat_messages)}")
            else:
                # 添加历史对话
                chat_messages.append({
                    "role": "user",
                    "content": initial_context
                })
                for msg in messages:
                    chat_messages.append({
                        "role": msg.get("role"),
                        "content": msg.get("content")
                    })
                # 添加最新的用户指令
                chat_messages.append({
                    "role": "user",
                    "content": f"{user_instruction}\n\n【重要提醒】\n1. 请确保修改后的内容与整体文档风格一致，参照知识库中的表达方式，避免AI痕迹。\n2. 不要在正文中输出章节描述内容本身，描述仅供理解要求。\n3. 直接生成正文内容，不要输出'根据章节描述...'等元信息。\n4. 严格保持原内容的排版格式：如果原文使用'一、二、三'，修改后也必须用'一、二、三'；如果原文使用'（一）（二）'，修改后也必须用'（一）（二）'。不要改变标题层级、列表样式、缩进格式。"
                })
                logger.info(f"[章节修改] 多轮对话，消息数: {len(chat_messages)}")

            # 从用户指令中提取目标字数（格式：本章节必须达到 XXXX 字左右）
            target_match = re.search(r'本章节必须达到\s*(\d+)\s*字', user_instruction)
            target_word_count = int(target_match.group(1)) if target_match else 0

            logger.info(f"[章节修改] 提取到目标字数: {target_word_count}")

            # 流式返回生成的文本
            logger.info(f"[章节修改] 开始调用模型...")
            chunk_count = 0

            if target_word_count > self.SINGLE_BATCH_CHAR_LIMIT:
                # 大字数修改：使用分批生成
                # 将多轮对话上下文合并为一个完整的 user prompt 供分批生成使用
                combined_prompt_parts = []
                for msg in chat_messages[1:]:  # 跳过 system prompt
                    role_label = "用户" if msg["role"] == "user" else "AI助手"
                    combined_prompt_parts.append(f"【{role_label}】\n{msg['content']}")
                combined_user_prompt = "\n\n".join(combined_prompt_parts)

                async for chunk in self._generate_long_content_stream(
                    system_prompt=chat_messages[0]["content"],
                    user_prompt=combined_user_prompt,
                    target_word_count=target_word_count,
                    temperature=0.7,
                ):
                    chunk_count += 1
                    yield chunk
            else:
                # 普通修改：直接单次生成
                async for chunk in self.stream_chat_completion(chat_messages, temperature=0.7):
                    chunk_count += 1
                    yield chunk
            
            logger.info(f"[章节修改] 模型调用完成，共 {chunk_count} 个chunk")

        except Exception as e:
            logger.error(f"[章节修改] 修改章节内容时出错: {str(e)}", exc_info=True)
            raise Exception(f"修改章节内容失败: {str(e)}")