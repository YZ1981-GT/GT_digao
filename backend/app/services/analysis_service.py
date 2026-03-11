"""文档分析处理服务。

核心流程：
1. 用户上传一个或多个文档，解析并缓存内容
2. 用户选择分析模式（总结分析/整理汇总/生成汇总台账）
3. LLM 根据文档内容自动生成章节框架（带注释）
4. 用户确认框架后，逐章节生成内容（引用原文并标注出处）
5. 每个章节支持手动编辑和AI修改
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..models.analysis_schemas import (
    AnalysisChapter,
    AnalysisDocumentInfo,
    AnalysisMode,
    AnalysisProject,
    AnalysisSourceRef,
    ANALYSIS_MODE_CONFIG,
)
from .openai_service import OpenAIService, estimate_token_count, truncate_to_token_limit, _get_context_limit, OUTPUT_RESERVE_RATIO

logger = logging.getLogger(__name__)


_OUTLINE_SYSTEM_PROMPT = """你是一位资深审计文档分析专家。请根据用户上传的文档内容，生成一个结构化的章节框架。

【要求】
1. 根据分析模式（总结分析/整理汇总/生成汇总台账）确定合适的章节结构
2. 每个章节标题要准确反映该部分将涵盖的内容
3. 每个章节附带一段简短注释（annotation），说明该章节将包含哪些要点
4. 合理分配各章节的目标字数
5. 章节结构要有逻辑层次，支持嵌套子章节

请返回一个JSON数组，格式如下：
[
  {
    "id": "1",
    "title": "章节标题",
    "annotation": "该章节将涵盖的要点简述",
    "target_word_count": 800,
    "children": [
      {
        "id": "1.1",
        "title": "子章节标题",
        "annotation": "子章节要点简述",
        "target_word_count": 400,
        "children": []
      }
    ]
  }
]

只返回JSON数组，不要包含其他文字。"""

_CHAPTER_SYSTEM_PROMPT = """你是一位资深审计文档分析专家，正在根据上传的原始文档内容撰写分析报告的某个章节。

【核心规则】
1. 所有内容必须基于上传的原始文档，不得编造信息
2. 你的工作是总结提炼和汇总整理，不是创作新内容
3. 每段关键内容后必须标注引用来源，格式为：[来源：文档名称]
4. 引用原文时用「」括起来，并标注出处
5. 直接输出正文内容，不要输出章节标题
6. 使用专业的审计术语和规范的文档格式

【引用标注格式】
- 直接引用：「原文内容」[来源：文档名称]
- 间接引用/总结：内容描述 [来源：文档名称]
- 多文档综合：内容描述 [来源：文档A、文档B]

【写作风格】
- 客观、准确、专业
- 段落长短自然变化
- 内容要有实质性，紧扣原始文档
- 禁止使用：赋能、闭环、抓手、打通、全方位、多维度
"""


_FORMAT_MD_SYSTEM_PROMPT = """你是一位专业的文档排版专家。你的任务是将 OCR 识别后的原始文本整理为标准的 Markdown 格式文档。

【核心原则】
1. 严格保留原文所有内容，不得增加、删除或修改任何实质性信息
2. 只做格式整理和排版优化，不做内容改写

【排版规则】
1. 标题识别：根据内容层级关系，使用 # / ## / ### 等 Markdown 标题语法
2. 段落分割：合理分段，每段之间空一行
3. 表格还原：如果原文包含表格数据（如用 | 分隔或对齐的数据），转换为 Markdown 表格格式
4. 列表识别：将序号列表转为有序列表（1. 2. 3.），将项目符号转为无序列表（- ）
5. 去除噪声：删除明显的 OCR 噪声，如：
   - 重复的页眉页脚
   - 页码标记（如 "--- 第 X 页 ---"）
   - 乱码字符
   - 多余的空行和空格
6. 保留关键格式：日期、金额、编号等保持原样
7. 如果原文有明显的章节结构，用对应级别的标题标记

【输出要求】
- 直接输出整理后的 Markdown 文本
- 不要添加任何说明性文字（如"以下是整理后的内容"）
- 不要用代码块包裹整个输出"""


class AnalysisService:
    """文档分析处理服务"""

    def __init__(self):
        self._openai = OpenAIService()

    async def generate_outline(
        self,
        documents: List[AnalysisDocumentInfo],
        mode: AnalysisMode,
        target_word_count: int,
        custom_instruction: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """根据文档内容和分析模式，流式生成章节框架"""
        mode_config = ANALYSIS_MODE_CONFIG.get(mode.value, ANALYSIS_MODE_CONFIG["summary"])

        # 拼接所有文档内容摘要
        doc_summaries = []
        for doc in documents:
            text = doc.content_text[:6000] if doc.content_text else ""
            doc_summaries.append(f"【文档：{doc.filename}】\n{text}\n")

        all_docs_text = "\n".join(doc_summaries)

        # 构建用户提示
        user_prompt = f"""请为以下文档内容生成{mode_config['label']}的章节框架。

分析模式：{mode_config['label']}
模式说明：{mode_config['description']}
目标总字数：约{target_word_count}字
文档数量：{len(documents)}个

"""
        if custom_instruction:
            user_prompt += f"用户额外要求：{custom_instruction}\n\n"

        user_prompt += f"文档内容：\n{all_docs_text}"

        # Token 限制处理
        context_limit = _get_context_limit(self._openai.model_name)
        reserve = int(context_limit * OUTPUT_RESERVE_RATIO)
        available = context_limit - reserve
        user_prompt = truncate_to_token_limit(user_prompt, available - 500)

        messages = [
            {"role": "system", "content": _OUTLINE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        collected = ""
        async for chunk in self._openai.stream_chat_completion(messages):
            collected += chunk
            yield f'data: {json.dumps({"status": "streaming", "content": chunk}, ensure_ascii=False)}\n\n'

        # 尝试解析JSON
        try:
            # 提取JSON数组
            json_match = re.search(r'\[[\s\S]*\]', collected)
            if json_match:
                outline_data = json.loads(json_match.group())
                yield f'data: {json.dumps({"status": "completed", "outline": outline_data}, ensure_ascii=False)}\n\n'
            else:
                yield f'data: {json.dumps({"status": "error", "message": "无法解析章节框架，请重试"}, ensure_ascii=False)}\n\n'
        except json.JSONDecodeError:
            yield f'data: {json.dumps({"status": "error", "message": "章节框架格式错误，请重试"}, ensure_ascii=False)}\n\n'

    async def generate_chapter_content(
        self,
        documents: List[AnalysisDocumentInfo],
        chapter: AnalysisChapter,
        mode: AnalysisMode,
        outline: List[AnalysisChapter],
        custom_instruction: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """流式生成单个章节的内容，引用原始文档并标注出处"""
        mode_config = ANALYSIS_MODE_CONFIG.get(mode.value, ANALYSIS_MODE_CONFIG["summary"])

        # 拼接文档内容
        doc_contents = []
        for doc in documents:
            text = doc.content_text or ""
            doc_contents.append(f"【文档：{doc.filename}（ID: {doc.id}）】\n{text}\n")

        all_docs_text = "\n".join(doc_contents)

        # 构建章节上下文
        outline_summary = "\n".join(
            f"  {ch.id}. {ch.title} - {ch.annotation}" for ch in outline
        )

        user_prompt = f"""请撰写以下章节的内容：

章节编号：{chapter.id}
章节标题：{chapter.title}
章节说明：{chapter.annotation}
目标字数：约{chapter.target_word_count}字
分析模式：{mode_config['label']}

完整章节框架：
{outline_summary}

"""
        if custom_instruction:
            user_prompt += f"用户额外要求：{custom_instruction}\n\n"

        user_prompt += f"""原始文档内容：
{all_docs_text}

请严格基于以上文档内容撰写该章节，所有关键信息必须标注引用来源。"""

        # Token 限制
        context_limit = _get_context_limit(self._openai.model_name)
        reserve = int(context_limit * OUTPUT_RESERVE_RATIO)
        available = context_limit - reserve
        user_prompt = truncate_to_token_limit(user_prompt, available - 800)

        messages = [
            {"role": "system", "content": _CHAPTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        collected = ""
        sources: List[Dict[str, Any]] = []

        async for chunk in self._openai.stream_chat_completion(messages):
            collected += chunk
            yield f'data: {json.dumps({"status": "streaming", "content": chunk}, ensure_ascii=False)}\n\n'

        # 从生成内容中提取引用来源（每个标注独立提取 excerpt）
        source_tag_pattern = r'\[来源[：:]\s*([^\]]+)\]'
        doc_map: Dict[str, 'AnalysisDocumentInfo'] = {}
        for doc in documents:
            doc_map[doc.filename] = doc

        for tag_match in re.finditer(source_tag_pattern, collected):
            src_text = tag_match.group(1)
            doc_names = [n.strip() for n in re.split(r'[、,，]', src_text)]
            for name in doc_names:
                # 匹配文档
                matched_doc = None
                for doc in documents:
                    if name in doc.filename or doc.filename in name:
                        matched_doc = doc
                        break
                if matched_doc:
                    excerpt = self._find_excerpt_at(
                        matched_doc.content_text, collected, tag_match.start()
                    )
                    sources.append({
                        "doc_id": matched_doc.id,
                        "doc_name": matched_doc.filename,
                        "excerpt": excerpt,
                        "location": None,
                    })

        yield f'data: {json.dumps({"status": "completed", "content": collected, "sources": sources}, ensure_ascii=False)}\n\n'

    async def revise_chapter_content(
        self,
        documents: List[AnalysisDocumentInfo],
        current_content: str,
        user_instruction: str,
        selected_text: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """AI修改章节内容"""
        doc_context = "\n".join(
            f"【{doc.filename}】\n{doc.content_text[:3000]}" for doc in documents
        )

        system_msg = _CHAPTER_SYSTEM_PROMPT + "\n\n你正在修改已有的章节内容。保持引用标注格式不变。"

        user_msg = f"当前章节内容：\n{current_content}\n\n"
        if selected_text:
            user_msg += f"用户选中的文本：\n{selected_text}\n\n注意：只修改选中的部分。\n\n"
        user_msg += f"修改要求：{user_instruction}\n\n原始文档参考：\n{doc_context}"

        chat_messages = [{"role": "system", "content": system_msg}]
        if messages:
            chat_messages.extend(messages)
        chat_messages.append({"role": "user", "content": user_msg})

        # Token 限制
        context_limit = _get_context_limit(self._openai.model_name)
        reserve = int(context_limit * OUTPUT_RESERVE_RATIO)

        collected = ""
        async for chunk in self._openai.stream_chat_completion(chat_messages):
            collected += chunk
            yield f'data: {json.dumps({"status": "streaming", "content": chunk}, ensure_ascii=False)}\n\n'

        yield f'data: {json.dumps({"status": "completed", "content": collected}, ensure_ascii=False)}\n\n'

    async def format_document_to_markdown(
        self,
        content_text: str,
        filename: str,
        custom_instruction: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """将 OCR 识别后的原始文本整理为标准 Markdown 格式。

        策略：
        1. 先用本地脚本做基础清洗排版
        2. 按章节/段落智能切分为多个块
        3. 逐块调用 LLM 做精细化整理，块间停顿 3-5 秒避免限流
        4. 流式拼接返回完整结果
        """
        import asyncio

        yield f'data: {json.dumps({"status": "streaming", "content": ""}, ensure_ascii=False)}\n\n'

        # ─── 第一步：本地脚本清洗 ───
        try:
            cleaned = self._local_format_to_markdown(content_text)
            yield f'data: {json.dumps({"status": "phase", "phase": "local_done", "message": "本地排版处理完成，正在进行 AI 精细化整理..."}, ensure_ascii=False)}\n\n'
        except Exception as e:
            logger.warning("本地排版处理异常，跳过: %s", e)
            cleaned = content_text

        # ─── 第二步：智能切分 ───
        context_limit = _get_context_limit(self._openai.model_name)
        # 排版任务：输出长度 ≈ 输入长度，所以输入+输出要一起算进上下文
        # 留 system prompt 开销，剩余空间对半分给输入和输出
        system_tokens = estimate_token_count(_FORMAT_MD_SYSTEM_PROMPT) + 800
        usable = context_limit - system_tokens
        # 每块输入最多占可用空间的 45%（留 55% 给输出，因为排版可能略增加长度）
        chunk_token_budget = int(usable * 0.45)
        # 输出 max_tokens 设为输入预算的 1.2 倍（排版可能略增加）
        # 但不能超过 API 限制的 65536
        MAX_OUTPUT_TOKENS = 65536
        output_max_tokens = min(int(chunk_token_budget * 1.2), MAX_OUTPUT_TOKENS)
        # 反向约束：输入块不能超过输出上限，否则输出会被截断
        if chunk_token_budget > output_max_tokens:
            chunk_token_budget = int(output_max_tokens * 0.85)  # 留余量

        chunks = self._split_into_chunks(cleaned, chunk_token_budget)
        total_chunks = len(chunks)

        logger.info("AI排版: 文档 %s 共 %d 字符, 切分为 %d 块 (输入≤%d tokens, 输出≤%d tokens)",
                     filename, len(cleaned), total_chunks, chunk_token_budget, output_max_tokens)

        if total_chunks == 1:
            # 单块，直接处理（不需要分块提示）
            yield f'data: {json.dumps({"status": "phase", "phase": "ai_start", "message": f"文档较短，整体 AI 排版中..."}, ensure_ascii=False)}\n\n'

            user_prompt = f"请将以下经过初步清洗的文档内容进一步整理为标准 Markdown 格式：\n\n文档名称：{filename}\n\n"
            if custom_instruction:
                user_prompt += f"额外排版要求：{custom_instruction}\n\n"
            user_prompt += f"文档内容：\n{chunks[0]}"

            messages = [
                {"role": "system", "content": _FORMAT_MD_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            collected = ""
            async for chunk_text in self._openai.stream_chat_completion(messages, temperature=0.3, max_tokens=output_max_tokens):
                collected += chunk_text
                yield f'data: {json.dumps({"status": "streaming", "content": chunk_text}, ensure_ascii=False)}\n\n'

            yield f'data: {json.dumps({"status": "completed", "content": collected}, ensure_ascii=False)}\n\n'
            return

        # ─── 多块逐块处理 ───
        collected_all = ""
        for idx, chunk_content in enumerate(chunks):
            chunk_num = idx + 1
            progress_msg = f"正在处理第 {chunk_num}/{total_chunks} 段..."
            yield f'data: {json.dumps({"status": "phase", "phase": "chunk_progress", "message": progress_msg, "chunk": chunk_num, "total": total_chunks}, ensure_ascii=False)}\n\n'

            # 构建分块提示
            user_prompt = (
                f"请将以下文档片段整理为标准 Markdown 格式。"
                f"这是文档「{filename}」的第 {chunk_num}/{total_chunks} 段。\n"
                f"请严格保留原文内容，只做格式整理。直接输出整理后的 Markdown，不要添加说明文字。\n\n"
            )
            if custom_instruction:
                user_prompt += f"额外排版要求：{custom_instruction}\n\n"
            user_prompt += f"文档片段内容：\n{chunk_content}"

            messages = [
                {"role": "system", "content": _FORMAT_MD_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            chunk_result = ""
            async for chunk_text in self._openai.stream_chat_completion(messages, temperature=0.3, max_tokens=output_max_tokens):
                chunk_result += chunk_text
                yield f'data: {json.dumps({"status": "streaming", "content": chunk_text}, ensure_ascii=False)}\n\n'

            # 块间分隔（非最后一块时加换行）
            if chunk_num < total_chunks:
                separator = "\n\n"
                collected_all += chunk_result + separator
                yield f'data: {json.dumps({"status": "streaming", "content": separator}, ensure_ascii=False)}\n\n'

                # 块间停顿 5 秒，避免 API 限流
                pause_msg = f"第 {chunk_num}/{total_chunks} 段完成，等待 5 秒后继续..."
                yield f'data: {json.dumps({"status": "phase", "phase": "chunk_pause", "message": pause_msg}, ensure_ascii=False)}\n\n'
                await asyncio.sleep(5)
            else:
                collected_all += chunk_result

        yield f'data: {json.dumps({"status": "completed", "content": collected_all}, ensure_ascii=False)}\n\n'

    @staticmethod
    def _split_into_chunks(text: str, max_tokens_per_chunk: int) -> list[str]:
        """智能切分文档为多个块，尽量在章节/段落边界切分。

        切分优先级：
        1. 一级标题（# ）
        2. 二级标题（## ）
        3. 三级标题（### ）
        4. 空行（段落边界）
        5. 硬切（按 token 预算强制切分）
        """
        total_tokens = estimate_token_count(text)
        if total_tokens <= max_tokens_per_chunk:
            return [text]

        lines = text.split('\n')
        chunks: list[str] = []
        current_lines: list[str] = []
        current_tokens = 0

        for line in lines:
            line_tokens = estimate_token_count(line + '\n')

            # 如果当前块加上这行会超限
            if current_tokens + line_tokens > max_tokens_per_chunk and current_lines:
                # 检查是否在好的切分点
                is_good_break = (
                    line.startswith('# ')
                    or line.startswith('## ')
                    or line.startswith('### ')
                    or line.strip() == ''
                )

                if is_good_break or current_tokens > max_tokens_per_chunk * 0.8:
                    # 在此处切分
                    chunks.append('\n'.join(current_lines))
                    current_lines = []
                    current_tokens = 0

            current_lines.append(line)
            current_tokens += line_tokens

            # 安全阀：如果单块已经远超预算（1.2倍），强制切分
            if current_tokens > max_tokens_per_chunk * 1.2 and len(current_lines) > 1:
                chunks.append('\n'.join(current_lines))
                current_lines = []
                current_tokens = 0

        # 最后一块
        if current_lines:
            chunks.append('\n'.join(current_lines))

        # 如果切出来的块太小（< 500 tokens），合并到前一块
        merged_chunks: list[str] = []
        for chunk in chunks:
            if merged_chunks and estimate_token_count(chunk) < 500:
                merged_chunks[-1] += '\n' + chunk
            else:
                merged_chunks.append(chunk)

        return merged_chunks if merged_chunks else [text]

    @staticmethod
    def _local_format_to_markdown(text: str) -> str:
        """本地脚本：对 OCR / docx 提取的原始文本做基础清洗和 Markdown 排版。

        处理内容：
        1. 预处理 [表格内容]...[表格结束] 块：合并连续同结构表格行、拆分段落
        2. 去除页码标记（--- 第 X 页 ---）
        3. 清理多余空格：中文之间的空格、行首缩进空格、连续空格
        4. 合并多余空行（连续 2+ 空行合并为 1 行）
        5. 识别标题行（短行、无标点结尾、编号前缀、Markdown 标题）
        6. 识别列表项（数字序号、字母序号、项目符号）
        7. 表格行保留原格式
        8. HTML 表格转 Markdown 表格
        """
        if not text:
            return ""

        # ─── 空格清理辅助函数 ───
        def _clean_spaces(s: str) -> str:
            """清理行内多余空格。"""
            s = s.strip()
            if not s:
                return ''
            s = re.sub(r'[ \t]+', ' ', s)
            # 去除两个中文字符/标点之间的空格（多轮）
            for _ in range(3):
                s = re.sub(
                    r'([\u4e00-\u9fff，。；：、！？""''（）【】《》])\s+'
                    r'([\u4e00-\u9fff，。；：、！？""''（）【】《》])',
                    r'\1\2', s)
            return s

        # ─── 第 0 步：预处理 [表格内容]...[表格结束] 块 ───
        text = AnalysisService._preprocess_table_blocks(text, _clean_spaces)

        lines = text.split('\n')
        result_lines: list[str] = []

        # ─── 逐行处理 ───
        for line in lines:
            stripped = line.strip()

            # 去除页码标记
            if re.match(r'^-{2,}\s*第\s*\d+\s*页\s*-{2,}$', stripped):
                continue
            if re.match(r'^\d{1,4}$', stripped) and len(stripped) <= 4:
                continue
            # 去除 OCR 噪声行
            if stripped and len(stripped) <= 2 and re.match(r'^[^\w\u4e00-\u9fff]+$', stripped):
                continue

            if not stripped:
                result_lines.append('')
                continue

            # Markdown 表格行（含 |）保留
            if '|' in stripped and stripped.count('|') >= 2:
                result_lines.append(stripped)
                continue

            # 清理空格
            cleaned = _clean_spaces(stripped)
            if not cleaned:
                continue

            # ─── 已有 Markdown 标题标记 ───
            md_heading = re.match(r'^(#{1,6})\s+(.+)', cleaned)
            if md_heading:
                level = md_heading.group(1)
                title_text = _clean_spaces(md_heading.group(2))
                result_lines.append(f'\n{level} {title_text}')
                continue

            # ─── 识别标题行 ───
            is_title = False
            if len(cleaned) <= 80 and not cleaned.endswith(('。', '；', '，', '、', '：', ':', '.', ',', ';')):
                if re.match(r'^第[一二三四五六七八九十百]+[章节篇部]\s*', cleaned):
                    result_lines.append(f'\n# {cleaned}')
                    is_title = True
                elif re.match(r'^[（(][一二三四五六七八九十]+[）)]\s*', cleaned):
                    result_lines.append(f'\n## {cleaned}')
                    is_title = True
                elif re.match(r'^[一二三四五六七八九十]+[、.]\s*', cleaned):
                    result_lines.append(f'\n## {cleaned}')
                    is_title = True
                elif re.match(r'^\d{1,2}[、.．]\s*\S', cleaned) and len(cleaned) <= 50:
                    result_lines.append(f'\n### {cleaned}')
                    is_title = True
                elif re.match(r'^[（(]\d{1,2}[）)]\s*\S', cleaned) and len(cleaned) <= 50:
                    result_lines.append(f'\n#### {cleaned}')
                    is_title = True
            if is_title:
                continue

            # ─── 识别有序列表项 ───
            list_match = re.match(r'^(\d{1,2})[、.．]\s+(.+)', cleaned)
            if list_match and len(cleaned) > 50:
                result_lines.append(cleaned)
                continue
            if list_match:
                result_lines.append(f'{list_match.group(1)}. {list_match.group(2)}')
                continue

            paren_list = re.match(r'^[（(](\d{1,2})[）)]\s*(.+)', cleaned)
            if paren_list and len(cleaned) > 50:
                result_lines.append(cleaned)
                continue
            if paren_list:
                result_lines.append(f'{paren_list.group(1)}. {paren_list.group(2)}')
                continue

            # 无序列表项
            bullet_match = re.match(r'^[·•●◆◇▪▸►-]\s*(.+)', cleaned)
            if bullet_match:
                result_lines.append(f'- {bullet_match.group(1)}')
                continue

            # 普通文本行
            result_lines.append(cleaned)

        # ─── 合并多余空行：连续空行最多保留 1 行 ───
        merged: list[str] = []
        blank_count = 0
        for line in result_lines:
            if line == '':
                blank_count += 1
                if blank_count <= 1:
                    merged.append('')
            else:
                blank_count = 0
                merged.append(line)

        text_out = '\n'.join(merged).strip()

        # ─── HTML 表格转 Markdown ───
        if '<table>' in text_out.lower():
            try:
                from pathlib import Path
                import sys
                project_root = Path(__file__).resolve().parent.parent.parent.parent
                mineru_dir = project_root / "MinerU"
                if mineru_dir.exists():
                    sys.path.insert(0, str(mineru_dir))
                    try:
                        from fix_md_tables import convert_html_tables_in_md
                        text_out = convert_html_tables_in_md(text_out)
                    finally:
                        sys.path.pop(0)
            except Exception as e:
                logger.warning("HTML 表格转换失败: %s", e)

        return text_out

    @staticmethod
    def _preprocess_table_blocks(text: str, clean_fn) -> str:
        """预处理 [表格内容]...[表格结束] 块。

        docx2python 经常把 Word 文档中的每一行都包装成独立的 [表格内容]...[表格结束]，
        导致：
        - 空块（无内容）
        - 单行文本被包在表格标记里（实际是段落）
        - 连续多个同列数的单行块（实际是一个表格的多行）
        - 段落文本用 | 分隔（实际是 docx2python 对单元格的拼接）

        本方法：
        1. 解析所有 [表格内容]...[表格结束] 块
        2. 删除空块
        3. 单行无 | 的块 → 还原为普通段落
        4. 单行有 | 但内容是长段落文本 → 按 | 拆分为多个段落
        5. 连续多个同列数的块 → 合并为一个 Markdown 表格
        """
        TAG_START = '[表格内容]'
        TAG_END = '[表格结束]'

        if TAG_START not in text:
            return text

        lines = text.split('\n')
        # 解析为 segments: 每个 segment 是 ('text', [...lines]) 或 ('table', [...lines])
        segments: list = []
        current_text_lines: list[str] = []
        in_table = False
        table_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped == TAG_START:
                # 把之前积累的文本行存起来
                if current_text_lines:
                    segments.append(('text', current_text_lines))
                    current_text_lines = []
                in_table = True
                table_lines = []
            elif stripped == TAG_END and in_table:
                in_table = False
                segments.append(('table', table_lines))
                table_lines = []
            elif in_table:
                table_lines.append(stripped)
            else:
                current_text_lines.append(line)

        if current_text_lines:
            segments.append(('text', current_text_lines))
        if in_table and table_lines:
            # 未闭合的表格块，当文本处理
            segments.append(('text', table_lines))

        # ─── 处理 table segments ───
        processed_segments: list = []

        def _col_count(line: str) -> int:
            """计算 | 分隔的列数。"""
            return line.count('|') + 1 if '|' in line else 0

        def _is_paragraph_line(line: str) -> bool:
            """判断一行是否更像段落而非表格行。
            长文本中的 | 通常是 docx2python 拼接段落的分隔符。
            """
            if '|' not in line:
                return True
            # 如果 | 分隔的各段都很长（平均 > 40 字符），更可能是段落拼接
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if not parts:
                return True
            avg_len = sum(len(p) for p in parts) / len(parts)
            # 段落特征：段数少且平均长度大
            if len(parts) <= 3 and avg_len > 40:
                return True
            # 如果某段包含句号等段落标点，也是段落
            if any(p.endswith(('。', '；', '：', '）', '】')) for p in parts):
                if avg_len > 25:
                    return True
            return False

        i = 0
        while i < len(segments):
            seg_type, seg_lines = segments[i]

            if seg_type == 'text':
                processed_segments.append(('text', seg_lines))
                i += 1
                continue

            # table segment
            # 过滤空行
            content_lines = [l for l in seg_lines if l.strip()]

            if not content_lines:
                # 空块，跳过
                i += 1
                continue

            # 单行块
            if len(content_lines) == 1:
                line = content_lines[0]

                if _is_paragraph_line(line):
                    # 按 | 拆分为多个段落（如果有 |）
                    if '|' in line:
                        parts = [clean_fn(p) for p in line.split('|') if p.strip()]
                        processed_segments.append(('text', parts))
                    else:
                        processed_segments.append(('text', [line]))
                    i += 1
                    continue

                # 看后续是否有同列数的连续单行表格块，合并为一个表格
                cols = _col_count(line)
                table_rows = [line]
                j = i + 1
                while j < len(segments):
                    next_type, next_lines = segments[j]
                    if next_type == 'text':
                        # 跳过空行 text segment
                        if all(not l.strip() for l in next_lines):
                            j += 1
                            continue
                        break
                    # next is table
                    next_content = [l for l in next_lines if l.strip()]
                    if not next_content:
                        j += 1
                        continue
                    if len(next_content) == 1:
                        nc = _col_count(next_content[0])
                        # 同列数或无 | 的行（可能是表格中的纯文本行）
                        if nc == cols or nc == 0:
                            table_rows.append(next_content[0])
                            j += 1
                            continue
                    break

                if len(table_rows) >= 2:
                    # 合并为 Markdown 表格
                    md_table = AnalysisService._rows_to_md_table(table_rows, cols)
                    processed_segments.append(('text', md_table))
                    i = j
                else:
                    # 单行表格行，保留为文本
                    processed_segments.append(('text', [line]))
                    i += 1
            else:
                # 多行块 → 真正的表格
                cols = max(_col_count(l) for l in content_lines)
                if cols >= 2:
                    md_table = AnalysisService._rows_to_md_table(content_lines, cols)
                    processed_segments.append(('text', md_table))
                else:
                    # 无 | 的多行 → 段落
                    processed_segments.append(('text', content_lines))
                i += 1

        # 重新拼接
        output_lines: list[str] = []
        for seg_type, seg_lines in processed_segments:
            output_lines.extend(seg_lines)
            output_lines.append('')  # 段间空行

        return '\n'.join(output_lines)

    @staticmethod
    def _rows_to_md_table(rows: list[str], expected_cols: int) -> list[str]:
        """将多行文本转换为 Markdown 表格格式。"""
        if not rows or expected_cols < 2:
            return rows

        md_lines: list[str] = []
        for idx, row in enumerate(rows):
            if '|' in row:
                cells = [c.strip() for c in row.split('|')]
            else:
                cells = [row.strip()]

            # 补齐列数
            while len(cells) < expected_cols:
                cells.append('')

            md_line = '| ' + ' | '.join(cells[:expected_cols]) + ' |'
            md_lines.append(md_line)

            # 第一行后加分隔行
            if idx == 0:
                sep = '| ' + ' | '.join(['---'] * expected_cols) + ' |'
                md_lines.append(sep)

        return md_lines

    @staticmethod
    def _find_excerpt_at(doc_text: str, generated_text: str, tag_pos: int) -> str:
        """根据来源标注在生成文本中的位置，精准定位原文中的对应片段。

        策略（按优先级）：
        1. 「」直接引用 → 在原文中精确/模糊查找
        2. 提取标注前最近的完整句子 → 用自然词组（非单字拼接）在原文中搜索
        3. 多粒度关键词组合匹配
        4. 兜底返回文档开头
        """
        if not doc_text:
            return ""

        # 清理原文中的页码标记，便于匹配
        clean_doc = re.sub(r'\n*---\s*第\s*\d+\s*页[^-]*---\s*\n*', '\n', doc_text)

        # 取标注前 400 字符（多取一些以覆盖更长的引用段落）
        before = generated_text[max(0, tag_pos - 400):tag_pos]

        # ─── 1. 检查「」直接引用 ───
        quotes = re.findall(r'「([^」]{4,300})」', before)
        if quotes:
            quoted = quotes[-1]  # 取最靠近标注的
            # 精确查找
            idx = clean_doc.find(quoted)
            if idx >= 0:
                start = max(0, idx - 20)
                end = min(len(clean_doc), idx + len(quoted) + 20)
                return clean_doc[start:end]
            # 前半段匹配（LLM 可能略有改写后半部分）
            for try_len in [min(30, len(quoted)), min(20, len(quoted)), min(12, len(quoted))]:
                if try_len < 6:
                    break
                idx = clean_doc.find(quoted[:try_len])
                if idx >= 0:
                    start = max(0, idx - 10)
                    end = min(len(clean_doc), idx + len(quoted) + 30)
                    return clean_doc[start:end]

        # ─── 2. 提取标注前最近的完整句子 ───
        # 先按句号/换行分割，取最后一个有意义的句子
        sentences = re.split(r'[。！？\n]', before)
        last_sentences = []
        for s in reversed(sentences):
            s = re.sub(r'\[来源[：:][^\]]*\]', '', s).strip()
            s = re.sub(r'[「」]', '', s).strip()
            if len(s) >= 6:
                last_sentences.append(s)
                if len(last_sentences) >= 2:
                    break

        if not last_sentences:
            return clean_doc[:150] + "..."

        best_pos = -1
        best_len = 0
        best_excerpt = ""

        for sentence in last_sentences:
            # ─── 2a. 提取自然词组（保留标点分隔的完整短语） ───
            # 按标点/空格分割为自然词组，保留原始形态
            natural_phrases = re.findall(
                r'[\u4e00-\u9fff\da-zA-Z\.\%\-]{3,}',
                sentence
            )
            # 按长度降序
            natural_phrases.sort(key=len, reverse=True)

            # ─── 2b. 尝试用较长的自然词组直接在原文中查找 ───
            for phrase in natural_phrases:
                if len(phrase) < 4:
                    continue
                pos = clean_doc.find(phrase)
                if pos >= 0 and len(phrase) > best_len:
                    best_pos = pos
                    best_len = len(phrase)
                    # 找到 >= 8 字的匹配就足够可信了
                    if best_len >= 8:
                        break
            if best_len >= 8:
                break

            # ─── 2c. 滑动窗口：从句子中取连续子串在原文中搜索 ───
            if best_pos < 0:
                for window_size in [18, 14, 10, 7]:
                    if len(sentence) < window_size:
                        continue
                    for start_i in range(len(sentence) - window_size + 1):
                        substr = sentence[start_i:start_i + window_size]
                        # 跳过纯标点/空格开头的子串
                        if not re.search(r'[\u4e00-\u9fffa-zA-Z\d]', substr[:2]):
                            continue
                        pos = clean_doc.find(substr)
                        if pos >= 0:
                            best_pos = pos
                            best_len = window_size
                            break
                    if best_pos >= 0:
                        break

            if best_pos >= 0:
                break

        if best_pos >= 0:
            # 返回匹配位置所在的完整句子上下文
            # 向前找到句子开头（句号/换行之后）
            ctx_start = best_pos
            for boundary in ['\n', '。', '！', '？']:
                bp = clean_doc.rfind(boundary, max(0, best_pos - 100), best_pos)
                if bp >= 0:
                    ctx_start = min(ctx_start, bp + 1)
                    break
            else:
                ctx_start = max(0, best_pos - 40)

            # 向后找到句子结尾
            ctx_end = best_pos + best_len
            for boundary in ['。', '！', '？', '\n']:
                ep = clean_doc.find(boundary, ctx_end, min(len(clean_doc), ctx_end + 150))
                if ep >= 0:
                    ctx_end = ep + 1
                    break
            else:
                ctx_end = min(len(clean_doc), ctx_end + 100)

            excerpt = clean_doc[ctx_start:ctx_end].strip()
            # 限制长度
            if len(excerpt) > 250:
                excerpt = excerpt[:250] + "..."
            return excerpt

        # ─── 3. 兜底 ───
        return clean_doc[:150] + "..."

    @staticmethod
    def _find_excerpt(doc_text: str, generated_text: str, doc_name: str) -> str:
        """兼容旧调用"""
        escaped_name = re.escape(doc_name)
        tag_pattern = r'\[来源[：:][^\]]*?' + escaped_name + r'[^\]]*\]'
        m = re.search(tag_pattern, generated_text)
        if m:
            return AnalysisService._find_excerpt_at(doc_text, generated_text, m.start())
        return doc_text[:150] + "..."


# 单例
analysis_service = AnalysisService()
