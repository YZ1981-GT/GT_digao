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

        策略：先用本地脚本做基础清洗排版，再用 LLM 做精细化整理。
        """
        yield f'data: {json.dumps({"status": "streaming", "content": ""}, ensure_ascii=False)}\n\n'

        # ─── 第一步：本地脚本清洗 ───
        try:
            cleaned = self._local_format_to_markdown(content_text)
            yield f'data: {json.dumps({"status": "phase", "phase": "local_done", "message": "本地排版处理完成，正在进行 AI 精细化整理..."}, ensure_ascii=False)}\n\n'
        except Exception as e:
            logger.warning("本地排版处理异常，跳过: %s", e)
            cleaned = content_text

        # ─── 第二步：LLM 精细化整理 ───
        user_prompt = f"请将以下经过初步清洗的文档内容进一步整理为标准 Markdown 格式：\n\n文档名称：{filename}\n\n"
        if custom_instruction:
            user_prompt += f"额外排版要求：{custom_instruction}\n\n"
        user_prompt += f"文档内容：\n{cleaned}"

        context_limit = _get_context_limit(self._openai.model_name)
        reserve = int(context_limit * OUTPUT_RESERVE_RATIO)
        available = context_limit - reserve
        user_prompt = truncate_to_token_limit(user_prompt, available - 500)

        messages = [
            {"role": "system", "content": _FORMAT_MD_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        collected = ""
        async for chunk in self._openai.stream_chat_completion(messages, temperature=0.3):
            collected += chunk
            yield f'data: {json.dumps({"status": "streaming", "content": chunk}, ensure_ascii=False)}\n\n'

        yield f'data: {json.dumps({"status": "completed", "content": collected}, ensure_ascii=False)}\n\n'

    @staticmethod
    def _local_format_to_markdown(text: str) -> str:
        """本地脚本：对 OCR 原始文本做基础清洗和 Markdown 排版。

        处理内容：
        1. 去除页码标记（--- 第 X 页 ---）
        2. 去除多余空行（连续 3+ 空行合并为 2 行）
        3. 去除行首行尾多余空格
        4. 识别标题行（短行、无标点结尾、可能有编号前缀）
        5. 识别列表项（数字序号、字母序号、项目符号）
        6. 表格行保留原格式
        7. HTML 表格转 Markdown 表格（复用 fix_md_tables 逻辑）
        """
        if not text:
            return ""

        lines = text.split('\n')
        result_lines: list[str] = []

        # ─── 逐行处理 ───
        for line in lines:
            stripped = line.strip()

            # 去除页码标记
            if re.match(r'^-{2,}\s*第\s*\d+\s*页\s*-{2,}$', stripped):
                continue

            # 去除纯页码行
            if re.match(r'^\d{1,4}$', stripped) and len(stripped) <= 4:
                continue

            # 去除 OCR 噪声行（纯符号/极短乱码）
            if stripped and len(stripped) <= 2 and re.match(r'^[^\w\u4e00-\u9fff]+$', stripped):
                continue

            # 空行保留（后面统一合并）
            if not stripped:
                result_lines.append('')
                continue

            # 识别标题行：短行 + 无标点结尾 + 可能有编号前缀
            is_title = False
            if len(stripped) <= 60 and not stripped.endswith(('。', '；', '，', '、', '：', ':', '.', ',', ';')):
                # 一级标题：如 "第一章 xxx"、"一、xxx"
                if re.match(r'^(第[一二三四五六七八九十百]+[章节篇部])\s*', stripped):
                    result_lines.append(f'\n# {stripped}')
                    is_title = True
                # 二级标题：如 "（一）xxx"、"一、xxx"
                elif re.match(r'^[（(][一二三四五六七八九十]+[）)]\s*', stripped):
                    result_lines.append(f'\n## {stripped}')
                    is_title = True
                elif re.match(r'^[一二三四五六七八九十]+[、.]\s*', stripped):
                    result_lines.append(f'\n## {stripped}')
                    is_title = True
                # 三级标题：如 "1. xxx"、"1、xxx"（短行）
                elif re.match(r'^\d{1,2}[、.．]\s*\S', stripped) and len(stripped) <= 40:
                    result_lines.append(f'\n### {stripped}')
                    is_title = True

            if is_title:
                continue

            # 识别有序列表项：如 "1. xxx"、"（1）xxx"
            list_match = re.match(r'^(\d{1,2})[、.．]\s+(.+)', stripped)
            if list_match and len(stripped) > 40:
                # 长行当正文段落，不做列表处理
                result_lines.append(stripped)
                continue
            if list_match:
                result_lines.append(f'{list_match.group(1)}. {list_match.group(2)}')
                continue

            paren_list = re.match(r'^[（(](\d{1,2})[）)]\s*(.+)', stripped)
            if paren_list:
                result_lines.append(f'{paren_list.group(1)}. {paren_list.group(2)}')
                continue

            # 识别无序列表项
            bullet_match = re.match(r'^[·•●◆◇▪▸►]\s*(.+)', stripped)
            if bullet_match:
                result_lines.append(f'- {bullet_match.group(1)}')
                continue

            # 表格行保留
            if '|' in stripped and stripped.count('|') >= 2:
                result_lines.append(stripped)
                continue

            # 普通文本行
            result_lines.append(stripped)

        # ─── 合并多余空行 ───
        merged: list[str] = []
        blank_count = 0
        for line in result_lines:
            if line == '':
                blank_count += 1
                if blank_count <= 2:
                    merged.append('')
            else:
                blank_count = 0
                merged.append(line)

        text_out = '\n'.join(merged).strip()

        # ─── HTML 表格转 Markdown（如果有） ───
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
