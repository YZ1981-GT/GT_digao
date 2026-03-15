"""附注非科目注释内容复核服务（LLM 辅助）。

提取附注中的叙述性章节，检查表达通顺性和会计政策模板一致性。
LLM 失败时降级：跳过附注内容复核。
"""
import json
import logging
import re
import uuid
from typing import List, Optional

from ..models.audit_schemas import (
    FindingConfirmationStatus,
    FindingStatus,
    NarrativeSection,
    ReportReviewFinding,
    ReportReviewFindingCategory,
    ReportTemplateType,
    RiskLevel,
    TemplateCategory,
)
from .openai_service import OpenAIService
from .report_template_service import ReportTemplateService

logger = logging.getLogger(__name__)

# 章节类型关键词
SECTION_TYPE_KEYWORDS = {
    "basic_info": ["公司基本情况", "基本情况", "公司概况", "企业概况"],
    "accounting_policy": ["会计政策", "重要会计政策", "主要会计政策"],
    "tax": ["税项", "税种", "主要税项", "适用税率"],
    "related_party": ["关联方", "关联方关系", "关联方交易"],
    "report_item_note": ["报表项目注释", "报表项目", "财务报表项目"],
}

# 模板化章节类型（内容来自模板，不需要重点复核表达质量）
TEMPLATE_SECTION_TYPES = {"basic_info", "accounting_policy", "tax"}


class NoteContentReviewer:
    """附注非科目注释内容复核服务。"""

    def __init__(self, template_service: Optional[ReportTemplateService] = None):
        self.template_service = template_service

    # ─── Public API ───

    def extract_narrative_sections(
        self, notes_parsed_data: str
    ) -> List[NarrativeSection]:
        """从附注中提取非表格叙述性内容。"""
        sections: List[NarrativeSection] = []
        if not notes_parsed_data.strip():
            return sections

        # 按标题分割
        parts = re.split(r'\n(?=[一二三四五六七八九十\d]+[、.．])', notes_parsed_data)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # 提取标题
            title_match = re.match(r'^([一二三四五六七八九十\d]+[、.．]\s*\S+)', part)
            title = title_match.group(1) if title_match else part[:30]
            content = part[len(title):].strip() if title_match else part

            # 跳过纯表格内容（简单启发式）
            if content.count("|") > content.count("\n") * 2:
                continue

            section_type = self._classify_section(title)
            sections.append(NarrativeSection(
                id=str(uuid.uuid4())[:8],
                section_type=section_type,
                title=title,
                content=content,
                source_location=f"附注-{title}",
            ))

        return sections

    async def check_expression_quality(
        self,
        section: NarrativeSection,
        openai_service: Optional[OpenAIService] = None,
    ) -> List[ReportReviewFinding]:
        """检查叙述性内容的表达通顺性。"""
        findings: List[ReportReviewFinding] = []
        if not section.content.strip() or not openai_service:
            return findings

        try:
            prompt = (
                f"请检查以下审计报告附注中报表项目注释的正文内容。\n"
                f"这些内容是项目组自行编写的，请重点关注：\n"
                f"1. 表达是否通顺、逻辑是否连贯\n"
                f"2. 专业术语使用是否准确\n"
                f"3. 数据描述是否与上下文一致\n"
                f"4. 是否有遗漏或多余的内容\n"
                f"注意：不要检查标点符号使用和错别字问题（由文本质量检查模块负责）。\n\n"
                f"章节标题：{section.title}\n"
                f"章节类型：{section.section_type}\n\n"
                f"内容：\n{section.content[:5000]}\n\n"
                "如果发现问题，请以JSON数组格式返回，每项必须包含以下字段：\n"
                '{"location":"问题所在的具体段落或句子（引用原文片段）","description":"问题描述，必须包含原文上下文片段，如：「原文内容」存在XX问题","suggestion":"修改建议，给出具体的修改方式","risk_level":"low或medium"}\n'
                "注意：location 和 description 中必须引用原文片段，让用户能定位到具体位置。\n"
                "如果内容表达合理、无明显问题，返回空数组 []。不要对模板化的标准表述提出问题。"
            )
            findings = await self._call_llm(openai_service, prompt, "表达通顺性", section.title)
        except Exception as e:
            logger.warning("表达通顺性检查失败: %s", e)

        return findings

    async def check_policy_template_compliance(
        self,
        policy_section: NarrativeSection,
        template_type: ReportTemplateType,
        openai_service: Optional[OpenAIService] = None,
    ) -> List[ReportReviewFinding]:
        """会计政策与致同附注模板逐条比对。"""
        findings: List[ReportReviewFinding] = []
        if not policy_section.content.strip() or not openai_service:
            return findings

        template_content = None
        if self.template_service:
            try:
                # 尝试按章节路径加载
                template_content = self.template_service.get_template_section(
                    template_type, TemplateCategory.NOTES, "会计政策"
                )
                if not template_content:
                    doc = self.template_service.get_template(template_type, TemplateCategory.NOTES)
                    if doc:
                        template_content = doc.full_content[:8000]
            except Exception as e:
                logger.warning("附注模板加载失败: %s", e)

        if not template_content:
            logger.info("附注模板未加载，跳过政策比对")
            return findings

        try:
            prompt = (
                "请将以下会计政策内容与模板逐条比对，识别政策措辞不一致。\n\n"
                f"模板内容：\n{template_content[:5000]}\n\n"
                f"实际内容：\n{policy_section.content[:5000]}\n\n"
                "对于每个偏差，返回JSON数组，每项包含：\n"
                '{"location":"问题所在的具体段落（引用原文片段）","description":"问题描述，引用实际内容原文","template_reference":"模板中对应的原文","suggestion":"修改建议","risk_level":"low/medium"}\n'
                "注意：location 和 description 中必须引用原文片段，让用户能定位到具体位置。"
            )
            findings = await self._call_llm(openai_service, prompt, "会计政策比对", policy_section.title)
        except Exception as e:
            logger.warning("会计政策比对失败: %s", e)

        return findings

    # ─── 内部工具 ───

    @staticmethod
    def _classify_section(title: str) -> str:
        for stype, keywords in SECTION_TYPE_KEYWORDS.items():
            if any(kw in title for kw in keywords):
                return stype
        return "other"

    @staticmethod
    def _extract_field(item: dict, primary: str, fallbacks: List[str]) -> str:
        """从 LLM 返回的 dict 中提取字段，支持多个备选字段名。"""
        val = item.get(primary, "")
        if val:
            return str(val).strip()
        for fb in fallbacks:
            val = item.get(fb, "")
            if val:
                return str(val).strip()
        return ""

    async def _call_llm(
        self,
        openai_service: OpenAIService,
        prompt: str,
        check_type: str,
        section_title: str = "",
    ) -> List[ReportReviewFinding]:
        messages = [
            {"role": "system", "content": "你是审计报告附注复核专家。请以JSON数组格式返回发现的问题。"},
            {"role": "user", "content": prompt},
        ]

        response = ""
        async for chunk in openai_service.stream_chat_completion(messages, temperature=0.3):
            if isinstance(chunk, str):
                response += chunk

        findings = []
        try:
            match = re.search(r'\[[\s\S]*\]', response)
            if match:
                items = json.loads(match.group())
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    desc = self._extract_field(item, "description", ["issue", "problem", "content", "错误描述", "问题"])
                    suggestion = self._extract_field(item, "suggestion", ["fix", "recommendation", "修改建议", "建议"])
                    if not desc:
                        continue
                    # 确保 location 有"附注-章节标题"前缀
                    raw_loc = item.get("location", "")
                    if section_title and raw_loc and not raw_loc.startswith("附注"):
                        location = f"附注-{section_title}-{raw_loc}"
                    elif section_title and not raw_loc:
                        location = f"附注-{section_title}"
                    elif raw_loc:
                        location = raw_loc if raw_loc.startswith("附注") else f"附注-{raw_loc}"
                    else:
                        location = "附注"
                    findings.append(ReportReviewFinding(
                        id=str(uuid.uuid4())[:8],
                        category=ReportReviewFindingCategory.NOTE_CONTENT,
                        risk_level=RiskLevel(item.get("risk_level", "low")),
                        account_name=item.get("account_name", section_title or check_type),
                        location=location,
                        description=desc,
                        template_reference=item.get("template_reference"),
                        suggestion=suggestion,
                        confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                        status=FindingStatus.OPEN,
                    ))
        except Exception as e:
            logger.warning("解析 %s 结果失败: %s", check_type, e)

        return findings


# 模块级单例
note_content_reviewer = NoteContentReviewer()
