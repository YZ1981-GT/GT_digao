"""基于模板的审计文档生成服务。

核心流程参照现有审计文档程序的章节拆分和内容生成模式：
1. 用户上传模板文件（审计计划、审计小结、尽调报告等）
2. 调用 extract_template_outline() 通过LLM自动识别模板中的章节结构
3. 用户在前端确认/调整章节大纲
4. 逐章节调用 _generate_section_content() 流式生成内容
5. 每个章节支持手动编辑和AI对话式修改
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..models.audit_schemas import (
    DocumentExportRequest,
    FontSettings,
    GeneratedDocument,
    GeneratedSection,
    ProjectInfo,
    SectionRevisionRequest,
    TemplateOutlineItem,
)
from .knowledge_service import knowledge_service
from .knowledge_retriever import knowledge_retriever
from .openai_service import OpenAIService, estimate_token_count, truncate_to_token_limit, _get_context_limit, OUTPUT_RESERVE_RATIO
from .template_service import TemplateManager
from .word_service import WordExportService

logger = logging.getLogger(__name__)


# 审计文档生成系统提示词
_AUDIT_DOCUMENT_SYSTEM_PROMPT = """你是一位资深审计专家，正在为致同会计师事务所编写审计文档。

【核心规则】
1. 如果提供了知识库参考资料，优先使用其中的真实信息
2. 即使没有知识库资料，也必须根据项目信息（客户名称、审计期间等）和你的审计专业知识，生成完整、有实质内容的章节
3. 结合章节标题和上下文结构，输出符合该章节定位的专业审计内容
4. 只有确实需要具体数据的地方（如具体金额、具体日期、具体人员姓名、具体合同编号等）才标注【待补充】
5. 审计程序、方法论、风险评估框架、内控描述等专业内容不需要标【待补充】，应直接撰写
6. 使用专业的审计术语和规范的文档格式
7. 直接输出正文内容，不要输出章节标题或元信息

【写作风格】
- 像真正的审计从业者撰写文档，不要像AI生成文本
- 段落长短自然变化，避免机械化的分点结构
- 内容要有实质性，不要空泛地罗列原则，要结合客户行业特点展开
- 禁止使用：赋能、闭环、抓手、打通、全方位、多维度、深度融合、无缝衔接
- 不要使用Markdown标题格式（# ## ###），用中文序号组织层次
"""

# 大纲提取系统提示词
_OUTLINE_EXTRACTION_PROMPT = """你是一位审计文档结构分析专家。请分析以下模板文本，识别其中的章节结构。

请返回一个JSON数组，每个元素代表一个章节，格式如下：
[
  {
    "id": "1",
    "title": "章节标题",
    "description": "章节内容概述",
    "target_word_count": 1500,
    "fillable_fields": ["需要填充的字段1", "需要填充的字段2"],
    "children": [
      {
        "id": "1.1",
        "title": "子章节标题",
        "description": "子章节内容概述",
        "target_word_count": 800,
        "fillable_fields": [],
        "children": []
      }
    ]
  }
]

要求：
1. 准确识别标题层级关系（一级、二级、三级标题）
2. 为每个章节估算合理的目标字数
3. 识别需要填充的字段（如客户名称、审计期间等）
4. description 简要描述该章节应包含的内容
5. 只返回JSON数组，不要包含其他文字
"""


class DocumentGenerator:
    """基于模板的审计文档生成服务。"""

    def __init__(self):
        self.template_manager = TemplateManager()

    @property
    def openai_service(self) -> OpenAIService:
        """每次访问时创建新实例，确保使用最新的 LLM 配置（热更新）。"""
        return OpenAIService()

    # ── 大纲提取 ──

    async def extract_template_outline(
        self,
        template_id: str,
        force_llm: bool = False,
    ) -> List[Dict[str, Any]]:
        """从用户上传的模板文件中提取章节结构，生成树形大纲。

        优先使用模板文件中的标题样式（Heading 1/2/3）直接构建树形大纲，
        无需调用 LLM，速度快且结构准确。
        仅当模板没有标题样式或 force_llm=True 时才调用 LLM 识别。
        """
        import time
        start_time = time.time()
        
        template = self.template_manager.get_template(template_id)
        if not template:
            raise ValueError(f"模板不存在：{template_id}")

        # 优先使用模板上传时已解析的结构化标题信息
        if not force_llm and template.structure and template.structure.sections:
            sections = template.structure.sections
            # 检查是否有有效的标题层级
            has_levels = any(s.level >= 1 for s in sections)
            if has_levels and len(sections) >= 2:
                elapsed = time.time() - start_time
                logger.info(
                    f"[大纲提取] 模板 '{template.name}' 使用结构化标题构建大纲"
                    f"（{len(sections)} 个章节），耗时: {elapsed:.3f}秒"
                )
                return self._build_outline_from_sections(sections)
            else:
                logger.info(
                    f"[大纲提取] 模板 '{template.name}' 结构化标题不满足条件: "
                    f"has_levels={has_levels}, sections_count={len(sections)}"
                )
        else:
            has_structure = template.structure is not None
            has_sections = has_structure and template.structure.sections is not None and len(template.structure.sections) > 0
            logger.info(
                f"[大纲提取] 模板 '{template.name}' 无法使用快速路径: "
                f"force_llm={force_llm}, has_structure={has_structure}, has_sections={has_sections}"
            )

        # 回退：尝试重新解析模板文件，用文本模式检测标题
        if not force_llm:
            file_path = self.template_manager.get_template_file_path(template_id)
            if file_path:
                try:
                    structure = await self.template_manager.parse_template_structure(file_path)
                    if structure and structure.sections and len(structure.sections) >= 2:
                        has_levels = any(s.level >= 1 for s in structure.sections)
                        if has_levels:
                            elapsed = time.time() - start_time
                            logger.info(
                                f"[大纲提取] 模板 '{template.name}' 重新解析后使用结构化标题构建大纲"
                                f"（{len(structure.sections)} 个章节），耗时: {elapsed:.3f}秒"
                            )
                            return self._build_outline_from_sections(structure.sections)
                except Exception as e:
                    logger.warning(f"[大纲提取] 重新解析模板失败: {e}")

        # 回退到 LLM 识别
        logger.info(f"[大纲提取] 模板 '{template.name}' 使用 LLM 识别大纲结构")

        file_path = self.template_manager.get_template_file_path(template_id)
        if not file_path:
            raise ValueError(f"模板文件不存在：{template_id}")

        from .workpaper_parser import WorkpaperParser

        parser = WorkpaperParser()
        parse_result = await parser.parse_file(file_path, template.name + "." + template.file_format)
        template_text = parse_result.content_text

        if not template_text.strip():
            raise ValueError("模板文件内容为空，无法提取大纲")

        # 如果解析结果中有标题信息，附加到提示中帮助 LLM 理解结构
        heading_hint = ""
        if parse_result.structured_data:
            headings = parse_result.structured_data.get("headings", [])
            if headings:
                heading_lines = [
                    f"{'  ' * (h.get('level', 1) - 1)}[Heading {h.get('level', 1)}] {h.get('text', '')}"
                    for h in headings
                ]
                heading_hint = (
                    "\n\n【重要提示】以下是从文档样式中提取的标题层级信息，"
                    "请严格按照这些标题及其层级关系构建大纲：\n"
                    + "\n".join(heading_lines)
                )

        # 截断过长的模板文本
        context_limit = _get_context_limit(self.openai_service.model_name)
        max_input_tokens = int(context_limit * (1 - OUTPUT_RESERVE_RATIO))
        prompt_overhead = estimate_token_count(_OUTLINE_EXTRACTION_PROMPT) + estimate_token_count(heading_hint) + 500
        max_template_tokens = max(max_input_tokens - prompt_overhead, 2000)
        template_text = truncate_to_token_limit(template_text, max_template_tokens)

        messages = [
            {"role": "system", "content": _OUTLINE_EXTRACTION_PROMPT},
            {"role": "user", "content": f"请分析以下审计模板文本，识别章节结构并返回JSON大纲：\n\n{template_text}{heading_hint}"},
        ]

        full_content = ""
        async for chunk in self.openai_service.stream_chat_completion(
            messages, temperature=0.3
        ):
            full_content += chunk

        outline = self._parse_outline_json(full_content)
        
        # 统一使用层级数字编号
        DocumentGenerator._reindex_outline_smart(outline)
        
        elapsed = time.time() - start_time
        logger.info(f"[大纲提取] LLM识别完成，耗时: {elapsed:.3f}秒")
        
        return outline

    @staticmethod
    def _build_outline_from_sections(
        sections: list,
    ) -> List[Dict[str, Any]]:
        """从模板的结构化章节列表构建树形大纲（不依赖 LLM）。

        将扁平的 TemplateSection 列表（带 level）转换为嵌套的树形结构。
        使用栈算法，时间复杂度 O(n)，性能优化。

        序号处理：如果原标题中已包含中文序号（如"十二、""（一）""1."），
        则提取为 id 并从 title 中去除，保留原模板的序号风格。
        """
        if not sections:
            return []
        
        import time
        start_time = time.time()
        
        root: List[Dict[str, Any]] = []
        # 栈：(level, children_list) — 用于追踪当前层级的父节点
        stack: List[tuple] = [(0, root)]

        for section in sections:
            level = section.level if hasattr(section, 'level') else 1
            title = section.title if hasattr(section, 'title') else str(section)
            fillable = section.fillable_fields if hasattr(section, 'fillable_fields') else []

            # 弹出栈中层级 >= 当前层级的项（保持栈的层级递增性）
            while len(stack) > 1 and stack[-1][0] >= level:
                stack.pop()

            # 从标题中提取原始序号
            original_id, clean_title = DocumentGenerator._extract_original_id(title)

            # 根据层级估算目标字数
            if level == 1:
                target_words = 1500
            elif level == 2:
                target_words = 800
            else:
                target_words = 500

            item: Dict[str, Any] = {
                "id": original_id,  # 优先使用原始序号，空串则后续补编号
                "title": clean_title,
                "description": "",
                "target_word_count": target_words,
                "fillable_fields": fillable if fillable else [],
                "children": [],
            }

            # 添加到当前父节点的 children
            stack[-1][1].append(item)

            # 将当前节点压入栈，作为后续子节点的父节点
            stack.append((level, item["children"]))

        # 统一使用层级数字编号
        DocumentGenerator._reindex_outline_smart(root)
        
        elapsed = time.time() - start_time
        logger.info(
            f"[大纲构建] 从 {len(sections)} 个章节构建树形大纲，"
            f"根节点数: {len(root)}，耗时: {elapsed:.3f}秒"
        )
        
        return root

    @staticmethod
    def _extract_original_id(title: str) -> tuple:
        """从标题文本中提取原始序号和去除序号后的标题。

        支持的序号格式：
        - 中文数字：一、 二、 十二、
        - 中文括号：（一） (一) （二）
        - 阿拉伯数字：1. 1、 12.
        - 阿拉伯括号：(1) （1）
        - 章节格式：第一章 第二部分 第三节

        Returns:
            (original_id, clean_title)
            如果没有识别到序号，original_id 为空串。
        """
        title = title.strip()
        if not title:
            return ("", title)

        # 按优先级匹配各种序号模式
        patterns = [
            # 第X章/部分/节/篇
            (r'^(第[一二三四五六七八九十百零\d]+[章部分节篇])\s*', None),
            # 中文数字 + 顿号/点号：一、 二、 十二、
            (r'^([一二三四五六七八九十百零]+)[、.．]\s*', None),
            # 中文括号数字：（一） (一)
            (r'^[（(]([一二三四五六七八九十百零]+)[）)]\s*', lambda m: f'（{m.group(1)}）'),
            # 阿拉伯数字 + 点号/顿号：1. 1、 12.
            (r'^(\d+)[、.．]\s*', lambda m: f'{m.group(1)}.'),
            # 阿拉伯括号数字：(1) （1）
            (r'^[（(](\d+)[）)]\s*', lambda m: f'（{m.group(1)}）'),
        ]

        for pattern, id_formatter in patterns:
            m = re.match(pattern, title)
            if m:
                if id_formatter:
                    original_id = id_formatter(m)
                else:
                    original_id = m.group(0).strip()
                clean_title = title[m.end():].strip()
                # 如果去掉序号后标题为空，保留原标题
                if not clean_title:
                    return (original_id, title)
                return (original_id, clean_title)

        return ("", title)

    @staticmethod
    def _reindex_outline_smart(
        items: List[Dict[str, Any]], prefix: str = ""
    ) -> None:
        """智能编号：统一使用层级数字编号（1, 1.1, 1.1.1）。

        原始序号（中文序号等）已保存在 title 提取阶段，
        这里统一用阿拉伯数字层级编号，确保前端显示和后端引用一致。
        """
        for idx, item in enumerate(items, 1):
            item["id"] = f"{prefix}{idx}" if not prefix else f"{prefix}.{idx}"

            # 递归处理子节点
            if item.get("children"):
                DocumentGenerator._reindex_outline_smart(
                    item["children"], item["id"]
                )

    @staticmethod
    def _reindex_outline(
        items: List[Dict[str, Any]], prefix: str = ""
    ) -> List[Dict[str, Any]]:
        """递归重新编号大纲项的 ID。"""
        for idx, item in enumerate(items, 1):
            item["id"] = f"{prefix}{idx}" if not prefix else f"{prefix}.{idx}"
            if item.get("children"):
                DocumentGenerator._reindex_outline(item["children"], item["id"])
        return items

    def _parse_outline_json(self, content: str) -> List[Dict[str, Any]]:
        """从LLM响应中解析大纲JSON。"""
        # 尝试直接解析
        content = content.strip()

        # 移除可能的markdown代码块标记
        if content.startswith("```"):
            lines = content.split("\n")
            # 去掉首尾的 ``` 行
            start = 1
            end = len(lines)
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip().startswith("```"):
                    end = i
                    break
            content = "\n".join(lines[start:end]).strip()

        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "outline" in result:
                return result["outline"]
            return [result]
        except json.JSONDecodeError:
            # 尝试提取JSON数组
            import re
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

            logger.error("无法解析LLM返回的大纲JSON: %s", content[:500])
            raise ValueError("无法解析模板大纲结构，请重试")

    # ── 文档流式生成 ──

    async def generate_document_stream(
        self,
        template_id: str,
        outline: List[Dict[str, Any]],
        knowledge_library_ids: List[str],
        project_info: ProjectInfo,
    ) -> AsyncGenerator[str, None]:
        """逐章节流式生成审计文档内容。

        遍历大纲中的叶子章节，逐个调用 _generate_section_content()，
        每个章节生成时注入 parent 和 sibling 上下文。

        Yields:
            JSON-encoded SSE event strings.
        """
        yield json.dumps(
            {"status": "started", "message": "开始生成审计文档..."},
            ensure_ascii=False,
        )

        # 加载知识库内容（使用智能检索器，全量缓存不截断）
        yield json.dumps(
            {"status": "loading_knowledge", "message": "正在读取知识库..."},
            ensure_ascii=False,
        )

        knowledge_loaded = False
        if knowledge_library_ids:
            try:
                # 使用 knowledge_retriever 预加载全量知识库
                for evt in knowledge_retriever.preload(
                    knowledge_service,
                    library_ids=knowledge_library_ids,
                ):
                    yield json.dumps(
                        {"status": "loading_knowledge", "message": evt.get('message', '读取中...')},
                        ensure_ascii=False,
                    )
                knowledge_loaded = knowledge_retriever.is_loaded
                logger.info(f"[文档生成] 知识库预加载完成: {knowledge_retriever.stats}")
            except Exception as e:
                logger.warning("知识库读取失败: %s", e)

        # 收集所有叶子章节（扁平化）
        leaf_sections = []
        self._collect_leaf_sections(outline, leaf_sections, parent_path=[])

        # 逐章节生成
        generated_sections: List[GeneratedSection] = []
        for idx, leaf in enumerate(leaf_sections):
            section_info = leaf["section"]
            section_title = section_info.get("title", f"章节{idx + 1}")

            yield json.dumps(
                {"status": "section_start", "section": section_title, "index": idx},
                ensure_ascii=False,
            )

            # 构建上下文
            parent_sections = leaf.get("parents")
            sibling_sections = leaf.get("siblings")
            target_word_count = section_info.get("target_word_count", 1500)

            # 按章节内容智能检索相关知识库片段
            knowledge_context = ""
            if knowledge_loaded:
                knowledge_context = knowledge_retriever.get_formatted_for_chapter(
                    chapter_title=section_title,
                    chapter_description=section_info.get('description', ''),
                    max_tokens=8000,
                )

            # 流式生成单章节内容
            section_content = ""
            async for chunk in self._generate_section_content(
                section=section_info,
                parent_sections=parent_sections,
                sibling_sections=sibling_sections,
                project_info=project_info,
                knowledge_context=knowledge_context,
                target_word_count=target_word_count,
            ):
                section_content += chunk
                yield json.dumps(
                    {"status": "streaming", "content": chunk, "section_index": idx},
                    ensure_ascii=False,
                )

            is_placeholder = "【待补充】" in section_content

            generated_section = GeneratedSection(
                index=idx,
                title=section_title,
                content=section_content,
                is_placeholder=is_placeholder,
            )
            generated_sections.append(generated_section)

            yield json.dumps(
                {
                    "status": "section_complete",
                    "section": section_title,
                    "content": section_content,
                },
                ensure_ascii=False,
            )

        # 构建完整文档
        outline_items = self._dicts_to_outline_items(outline)
        document = GeneratedDocument(
            id=str(uuid.uuid4()),
            template_id=template_id,
            outline=outline_items,
            sections=generated_sections,
            project_info=project_info,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        yield json.dumps(
            {"status": "completed", "document": document.model_dump(mode="json")},
            ensure_ascii=False,
        )

    def _collect_leaf_sections(
        self,
        sections: List[Dict[str, Any]],
        result: List[Dict[str, Any]],
        parent_path: List[Dict[str, Any]],
    ) -> None:
        """递归收集叶子章节，附带 parent 和 sibling 上下文。"""
        for section in sections:
            children = section.get("children") or []
            if not children:
                # 叶子节点
                result.append({
                    "section": section,
                    "parents": parent_path[:] if parent_path else None,
                    "siblings": [
                        s for s in sections if s.get("id") != section.get("id")
                    ] or None,
                })
            else:
                # 递归处理子节点
                new_parent = parent_path + [{
                    "id": section.get("id", ""),
                    "title": section.get("title", ""),
                    "description": section.get("description", ""),
                }]
                self._collect_leaf_sections(children, result, new_parent)

    # ── 单章节内容生成 ──

    async def _generate_section_content(
        self,
        section: Dict[str, Any],
        parent_sections: Optional[List[Dict[str, Any]]],
        sibling_sections: Optional[List[Dict[str, Any]]],
        project_info: ProjectInfo,
        knowledge_context: str,
        target_word_count: int,
    ) -> AsyncGenerator[str, None]:
        """生成单个章节内容。

        注入 parent/sibling 上下文、知识库内容和项目信息，
        通过 stream_chat_completion() 流式输出。
        """
        section_title = section.get("title", "未命名章节")
        section_id = section.get("id", "")
        section_desc = section.get("description", "")
        fillable_fields = section.get("fillable_fields", [])

        # 构建上下文信息
        context_parts = []

        # 上级章节信息
        if parent_sections:
            context_parts.append("上级章节信息：")
            for parent in parent_sections:
                context_parts.append(
                    f"- {parent.get('id', '')} {parent.get('title', '')}: "
                    f"{parent.get('description', '')}"
                )

        # 同级章节信息
        if sibling_sections:
            context_parts.append("同级章节信息（请避免内容重复）：")
            for sibling in sibling_sections:
                if sibling.get("id") != section_id:
                    context_parts.append(
                        f"- {sibling.get('id', '')} {sibling.get('title', '')}: "
                        f"{sibling.get('description', '')}"
                    )

        context_info = "\n".join(context_parts) if context_parts else ""

        # 项目信息
        project_text = (
            f"客户名称：{project_info.client_name}\n"
            f"审计期间：{project_info.audit_period}\n"
        )
        if project_info.key_matters:
            project_text += f"重要事项：{project_info.key_matters}\n"
        if project_info.additional_info:
            for k, v in project_info.additional_info.items():
                project_text += f"{k}：{v}\n"

        # 知识库内容
        has_knowledge = bool(knowledge_context.strip())
        knowledge_section = ""
        if has_knowledge:
            knowledge_section = (
                "========== 知识库参考资料（必须严格遵守） ==========\n"
                "以下是致同会计师事务所的真实资料，生成内容时必须优先使用这些信息。\n"
                "严禁编造任何不存在于以下资料中的案例、人员、制度、流程等具体信息。\n\n"
                f"{knowledge_context}\n\n"
                "========== 知识库参考资料结束 ==========\n\n"
            )

        # 填充字段提示
        fillable_hint = ""
        if fillable_fields:
            fillable_hint = (
                f"\n本章节需要填充的字段：{', '.join(fillable_fields)}\n"
                "请使用项目信息中的对应数据填充，缺失的标注【待补充】。\n"
            )

        if has_knowledge:
            knowledge_rule = "优先使用知识库中的真实信息填充，知识库未覆盖的部分结合审计专业知识撰写，仅具体数据（金额、日期、人名等）标注【待补充】"
        else:
            knowledge_rule = (
                "虽然没有知识库参考资料，但你必须根据客户名称、审计期间和章节主题，"
                "结合你的审计专业知识生成完整的实质性内容。"
                "审计程序、方法论、风险评估、内控描述等专业内容应直接撰写，"
                "只有确实需要客户具体数据的地方（如具体金额、合同编号、人员姓名）才标注【待补充】"
            )

        user_prompt = f"""请为以下审计文档章节生成内容：

项目信息：
{project_text}

{knowledge_section}{context_info + chr(10) if context_info else ""}当前章节信息：
章节编号: {section_id}
章节标题: {section_title}
章节描述: {section_desc}
{fillable_hint}
【生成要求】
1. {knowledge_rule}
2. 不要编造具体数字、具体案例、具体人员姓名，但审计方法、程序、框架等专业内容必须完整撰写
3. 确保与上级章节逻辑相承，避免与同级章节内容重复
4. 本章节目标字数约{target_word_count}字
5. 直接输出正文，不要输出章节标题或元信息
6. 不要使用Markdown标题格式（# ## ###），用中文序号组织层次
7. 内容要有实质性和针对性，结合客户所在行业特点展开，不要空泛罗列"""

        messages = [
            {"role": "system", "content": _AUDIT_DOCUMENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Token限制检查与截断
        context_limit = _get_context_limit(self.openai_service.model_name)
        max_input_tokens = int(context_limit * (1 - OUTPUT_RESERVE_RATIO))
        total_tokens = sum(estimate_token_count(m["content"]) for m in messages)

        if total_tokens > max_input_tokens:
            logger.warning(
                "[Token限制] 章节 %s 输入约 %d tokens，超过限制 %d，将截断知识库内容",
                section_title, total_tokens, max_input_tokens,
            )
            overflow = total_tokens - max_input_tokens
            if knowledge_context:
                kb_tokens = estimate_token_count(knowledge_context)
                new_kb_max = max(kb_tokens - overflow - 500, 1000)
                truncated_kb = truncate_to_token_limit(knowledge_context, new_kb_max)
                # 重建 user_prompt with truncated knowledge
                knowledge_section = (
                    "========== 知识库参考资料（必须严格遵守） ==========\n"
                    f"{truncated_kb}\n"
                    "========== 知识库参考资料结束 ==========\n\n"
                )
                user_prompt = f"""请为以下审计文档章节生成内容：

项目信息：
{project_text}

{knowledge_section}{context_info + chr(10) if context_info else ""}当前章节信息：
章节编号: {section_id}
章节标题: {section_title}
章节描述: {section_desc}
{fillable_hint}
【生成要求】
1. 优先使用知识库中的真实信息填充，知识库未覆盖的部分结合审计专业知识撰写，仅具体数据标注【待补充】
2. 不要编造具体数字、具体案例、具体人员姓名，但审计方法、程序、框架等专业内容必须完整撰写
3. 确保与上级章节逻辑相承，避免与同级章节内容重复
4. 本章节目标字数约{target_word_count}字
5. 直接输出正文，不要输出章节标题或元信息
6. 内容要有实质性和针对性，结合客户所在行业特点展开"""
                messages[1]["content"] = user_prompt

        async for chunk in self.openai_service.stream_chat_completion(
            messages, temperature=0.7
        ):
            yield chunk

    # ── 章节修改 ──

    async def revise_section_stream(
        self,
        section_index: int,
        current_content: str,
        user_instruction: str,
        document_context: Optional[Dict[str, Any]] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        selected_text: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """AI对话式修改章节内容。

        支持全文修改和选中文本局部修改。
        若 selected_text 非空，仅对选中部分进行修改，其余内容保持不变。
        """
        if messages is None:
            messages = []

        system_prompt = _AUDIT_DOCUMENT_SYSTEM_PROMPT

        if selected_text:
            # 局部修改模式：仅修改选中文本
            revision_prompt = (
                f"以下是当前章节的完整内容：\n\n{current_content}\n\n"
                f"用户选中了以下文本要求修改：\n「{selected_text}」\n\n"
                f"用户的修改指令：{user_instruction}\n\n"
                "请仅输出修改后的选中部分文本（不要输出完整章节内容），"
                "保持与上下文的连贯性。"
            )
        else:
            # 全文修改模式
            revision_prompt = (
                f"以下是当前章节的完整内容：\n\n{current_content}\n\n"
                f"用户的修改指令：{user_instruction}\n\n"
                "请根据用户指令修改章节内容，输出修改后的完整章节内容。"
                "保持专业的审计文档风格，严禁编造事实性信息。"
            )

        # 构建对话消息列表
        chat_messages = [{"role": "system", "content": system_prompt}]

        # 添加历史对话
        for msg in messages:
            chat_messages.append(msg)

        # 添加当前修改请求
        chat_messages.append({"role": "user", "content": revision_prompt})

        async for chunk in self.openai_service.stream_chat_completion(
            chat_messages, temperature=0.7
        ):
            yield chunk

    # ── Word 导出 ──

    async def export_to_word(
        self,
        document: GeneratedDocument,
        template_id: str,
        font_settings: Optional[FontSettings] = None,
    ) -> bytes:
        """导出为Word格式。

        将 GeneratedDocument 的章节结构转换为 OutlineItem 格式，
        调用 WordExportService.build_document() 生成Word文档。
        字体设置统一由 WordExportService 处理，避免重复应用。
        """
        outline_data = self._build_export_outline(document)

        word_service = WordExportService()
        buffer = word_service.build_document(
            outline_data,
            project_name=f"{document.project_info.client_name} 审计文档",
            font_settings=font_settings,
        )

        return buffer.read()

    def _build_export_outline(
        self, document: GeneratedDocument
    ) -> List[TemplateOutlineItem]:
        """将 GeneratedDocument 转换为 WordExportService 可用的大纲格式。

        将 sections 的内容填充到 outline 的叶子节点中。
        """
        if document.outline:
            # 使用原始大纲结构，填充生成的内容
            outline_copy = [item.model_copy(deep=True) for item in document.outline]
            section_map = {s.title: s.content for s in document.sections}
            self._fill_outline_content(outline_copy, section_map)
            return outline_copy

        # 没有大纲结构时，直接从 sections 构建扁平大纲
        items = []
        for section in document.sections:
            items.append(
                TemplateOutlineItem(
                    id=str(section.index + 1),
                    title=section.title,
                    description="",
                    content=section.content,
                    children=[],
                )
            )
        return items

    def _fill_outline_content(
        self,
        items: List[TemplateOutlineItem],
        section_map: Dict[str, str],
    ) -> None:
        """递归将生成的内容填充到大纲叶子节点。"""
        for item in items:
            if item.children:
                self._fill_outline_content(item.children, section_map)
            else:
                # 叶子节点：尝试匹配 section 内容
                if item.title in section_map:
                    item.content = section_map[item.title]

    # ── 序列化 / 反序列化 ──

    def parse_document_to_structured(self, document: GeneratedDocument) -> dict:
        """将文档解析为结构化数据格式。"""
        return document.model_dump(mode="json")

    def structured_to_document(self, data: dict) -> GeneratedDocument:
        """从结构化数据重建文档对象。"""
        return GeneratedDocument.model_validate(data)

    # ── 辅助方法 ──

    def _dicts_to_outline_items(
        self, dicts: List[Dict[str, Any]]
    ) -> List[TemplateOutlineItem]:
        """将字典列表转换为 TemplateOutlineItem 列表。"""
        items = []
        for d in dicts:
            children = None
            if d.get("children"):
                children = self._dicts_to_outline_items(d["children"])
            items.append(
                TemplateOutlineItem(
                    id=d.get("id", ""),
                    title=d.get("title", ""),
                    description=d.get("description", ""),
                    target_word_count=d.get("target_word_count"),
                    fillable_fields=d.get("fillable_fields"),
                    children=children,
                    content=d.get("content"),
                )
            )
        return items
