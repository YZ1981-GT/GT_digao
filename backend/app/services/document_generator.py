"""基于模板的审计文档生成服务。

核心流程参照现有审计文档程序的章节拆分和内容生成模式：
1. 用户上传模板文件（审计计划、审计小结、尽调报告等）
2. 调用 extract_template_outline() 通过LLM自动识别模板中的章节结构
3. 用户在前端确认/调整章节大纲
4. 逐章节调用 _generate_section_content() 流式生成内容
5. 每个章节支持手动编辑和AI对话式修改
"""
import io
import json
import logging
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
from .openai_service import OpenAIService, estimate_token_count, truncate_to_token_limit, _get_context_limit, OUTPUT_RESERVE_RATIO
from .template_service import TemplateManager
from .word_service import (
    DEFAULT_FONT_NAME,
    WordExportService,
    set_paragraph_font,
    set_run_font,
)

logger = logging.getLogger(__name__)


# 审计文档生成系统提示词
_AUDIT_DOCUMENT_SYSTEM_PROMPT = """你是一位资深审计专家，正在为会计师事务所编写审计文档。

【核心规则】
1. 优先使用知识库中的真实信息，缺失标注【待补充】，严禁编造事实性信息
2. 不要编造具体数字、具体案例、具体人员姓名等事实性内容
3. 所有事实性内容必须来源于知识库或用户填写的项目信息
4. 使用专业的审计术语和规范的文档格式
5. 直接输出正文内容，不要输出章节标题或元信息

【写作风格】
- 像真正的审计从业者撰写文档，不要像AI生成文本
- 段落长短自然变化，避免机械化的分点结构
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
    ) -> List[Dict[str, Any]]:
        """从用户上传的模板文件中自动识别章节结构，生成树形大纲。

        将模板解析后的文本内容发送给LLM，要求其识别章节标题层级、
        表格结构和需要填充的内容区域，返回OutlineItem格式的JSON大纲。
        """
        # 获取模板信息和文件路径
        template = self.template_manager.get_template(template_id)
        if not template:
            raise ValueError(f"模板不存在：{template_id}")

        file_path = self.template_manager.get_template_file_path(template_id)
        if not file_path:
            raise ValueError(f"模板文件不存在：{template_id}")

        # 解析模板文件获取文本内容
        from .workpaper_parser import WorkpaperParser

        parser = WorkpaperParser()
        parse_result = await parser.parse_file(file_path, template.name + "." + template.file_format)
        template_text = parse_result.content_text

        if not template_text.strip():
            raise ValueError("模板文件内容为空，无法提取大纲")

        # 截断过长的模板文本
        context_limit = _get_context_limit(self.openai_service.model_name)
        max_input_tokens = int(context_limit * (1 - OUTPUT_RESERVE_RATIO))
        prompt_overhead = estimate_token_count(_OUTLINE_EXTRACTION_PROMPT) + 500
        max_template_tokens = max(max_input_tokens - prompt_overhead, 2000)
        template_text = truncate_to_token_limit(template_text, max_template_tokens)

        # 调用LLM识别章节结构
        messages = [
            {"role": "system", "content": _OUTLINE_EXTRACTION_PROMPT},
            {"role": "user", "content": f"请分析以下审计模板文本，识别章节结构并返回JSON大纲：\n\n{template_text}"},
        ]

        full_content = ""
        async for chunk in self.openai_service.stream_chat_completion(
            messages, temperature=0.3
        ):
            full_content += chunk

        # 解析JSON响应
        outline = self._parse_outline_json(full_content)
        return outline

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

        # 加载知识库内容
        yield json.dumps(
            {"status": "loading_knowledge", "message": "正在读取知识库..."},
            ensure_ascii=False,
        )

        knowledge_context = ""
        if knowledge_library_ids:
            try:
                knowledge_context = knowledge_service.search_knowledge(
                    knowledge_library_ids,
                    f"{project_info.client_name} {project_info.audit_period} 审计",
                    max_chars=50000,
                )
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

        user_prompt = f"""请为以下审计文档章节生成内容：

项目信息：
{project_text}

{knowledge_section}{context_info + chr(10) if context_info else ""}当前章节信息：
章节编号: {section_id}
章节标题: {section_title}
章节描述: {section_desc}
{fillable_hint}
【生成要求】
1. {"优先使用知识库中的真实信息填充，知识库未覆盖的部分标注【待补充】" if has_knowledge else "由于没有相关参考资料，请用【待补充】标注需要填写真实信息的地方"}
2. 严禁编造具体数字、案例、人员姓名等事实性信息
3. 确保与上级章节逻辑相承，避免与同级章节内容重复
4. 本章节目标字数约{target_word_count}字
5. 直接输出正文，不要输出章节标题或元信息
6. 不要使用Markdown标题格式（# ## ###），用中文序号组织层次"""

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
1. 优先使用知识库中的真实信息填充，缺失标注【待补充】
2. 严禁编造具体数字、案例、人员姓名等事实性信息
3. 确保与上级章节逻辑相承，避免与同级章节内容重复
4. 本章节目标字数约{target_word_count}字
5. 直接输出正文，不要输出章节标题或元信息"""
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
        若 font_settings 非空，使用用户指定的字体设置。
        """
        # 确定字体
        font_name = DEFAULT_FONT_NAME
        if font_settings and font_settings.chinese_font:
            font_name = font_settings.chinese_font

        # 将 GeneratedDocument 的 sections 转换为 outline_items 格式
        # WordExportService 期望的是带 id/title/content/children 属性的对象
        outline_data = self._build_export_outline(document)

        # 使用 WordExportService 构建文档
        word_service = WordExportService()

        # 如果有自定义字体，覆盖默认字体设置
        if font_settings and font_settings.chinese_font:
            self._apply_font_to_styles(word_service.doc, font_name)

        buffer = word_service.build_document(
            outline_data,
            project_name=f"{document.project_info.client_name} 审计文档",
        )

        # 如果有自定义字体，对整个文档应用字体
        if font_settings:
            self._apply_font_settings(word_service.doc, font_settings)
            # 重新保存
            new_buffer = io.BytesIO()
            word_service.doc.save(new_buffer)
            new_buffer.seek(0)
            return new_buffer.read()

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

    def _apply_font_to_styles(self, doc, font_name: str) -> None:
        """将字体应用到文档样式。"""
        from docx.oxml.ns import qn as docx_qn

        try:
            for style_name in ["Normal", "Heading 1", "Heading 2", "Heading 3"]:
                if style_name in doc.styles:
                    style = doc.styles[style_name]
                    style.font.name = font_name
                    if style._element.rPr is None:
                        style._element._add_rPr()
                    style._element.rPr.rFonts.set(docx_qn("w:eastAsia"), font_name)
        except Exception as e:
            logger.warning("应用字体样式失败: %s", e)

    def _apply_font_settings(self, doc, font_settings: FontSettings) -> None:
        """对整个文档应用用户自定义字体设置。"""
        cn_font = font_settings.chinese_font or DEFAULT_FONT_NAME
        en_font = font_settings.english_font or "Times New Roman"

        for paragraph in doc.paragraphs:
            for run in paragraph.runs:
                # 设置中文字体
                set_run_font(run, cn_font)
                # 设置英文字体
                run.font.name = en_font

                # 应用字号
                if font_settings.body_font_size:
                    from docx.shared import Pt
                    run.font.size = Pt(font_settings.body_font_size)

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
