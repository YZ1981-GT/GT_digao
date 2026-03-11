"""审计报告正文复核服务（LLM 辅助）。

检查正文中的单位名称一致性、简称统一性、与致同报告模板的表述规范性比对。
LLM 失败时降级：跳过正文复核，不影响数值校验。
"""
import logging
import re
import uuid
from typing import List, Optional

from ..models.audit_schemas import (
    FindingConfirmationStatus,
    FindingStatus,
    NoteTable,
    ReportReviewFinding,
    ReportReviewFindingCategory,
    ReportTemplateType,
    RiskLevel,
    StatementItem,
    TemplateCategory,
)
from .openai_service import OpenAIService
from .report_template_service import ReportTemplateService

logger = logging.getLogger(__name__)


class ReportBodyReviewer:
    """审计报告正文复核服务。"""

    def __init__(self, template_service: Optional[ReportTemplateService] = None):
        self.template_service = template_service

    # ─── Public API ───

    async def check_entity_name_consistency(
        self,
        report_body_text: str,
        statement_items: List[StatementItem],
        note_tables: List[NoteTable],
        openai_service: Optional[OpenAIService] = None,
    ) -> List[ReportReviewFinding]:
        """检查正文中的单位名称是否与报表和附注一致。"""
        findings: List[ReportReviewFinding] = []
        if not report_body_text.strip():
            return findings

        try:
            if openai_service:
                prompt = self._build_name_check_prompt(report_body_text, statement_items, note_tables)
                findings = await self._call_llm_for_findings(
                    openai_service, prompt,
                    ReportReviewFindingCategory.REPORT_BODY_COMPLIANCE,
                    "单位名称一致性",
                )
        except Exception as e:
            logger.warning("单位名称一致性检查 LLM 调用失败: %s", e)

        return findings

    async def check_abbreviation_consistency(
        self,
        report_body_text: str,
        notes_text: str,
        openai_service: Optional[OpenAIService] = None,
    ) -> List[ReportReviewFinding]:
        """跨文档检查简称统一性。"""
        findings: List[ReportReviewFinding] = []
        if not report_body_text.strip():
            return findings

        try:
            if openai_service:
                prompt = (
                    "请检查以下审计报告正文和附注中的简称使用是否统一。\n"
                    "规则：首次出现应使用全称并注明简称，后续统一使用简称。\n\n"
                    f"正文内容（前3000字）：\n{report_body_text[:3000]}\n\n"
                    f"附注内容（前3000字）：\n{notes_text[:3000]}\n\n"
                    "请以JSON数组格式返回发现的问题。"
                )
                findings = await self._call_llm_for_findings(
                    openai_service, prompt,
                    ReportReviewFindingCategory.REPORT_BODY_COMPLIANCE,
                    "简称统一性",
                )
        except Exception as e:
            logger.warning("简称统一性检查 LLM 调用失败: %s", e)

        return findings

    async def check_template_compliance(
        self,
        report_body_text: str,
        template_type: ReportTemplateType,
        openai_service: Optional[OpenAIService] = None,
    ) -> List[ReportReviewFinding]:
        """正文与致同报告正文模板逐段比对。"""
        findings: List[ReportReviewFinding] = []
        if not report_body_text.strip():
            return findings

        template_content = None
        if self.template_service:
            try:
                doc = self.template_service.get_template(template_type, TemplateCategory.REPORT_BODY)
                if doc:
                    template_content = doc.full_content
            except Exception as e:
                logger.warning("模板加载失败: %s", e)

        if not template_content:
            logger.info("模板未加载，跳过模板比对")
            return findings

        try:
            if openai_service:
                prompt = (
                    "请将以下审计报告正文与模板逐段比对，识别表述偏差。\n\n"
                    f"模板内容：\n{template_content[:5000]}\n\n"
                    f"实际正文：\n{report_body_text[:5000]}\n\n"
                    "对于每个偏差，请返回JSON数组，每项包含：\n"
                    '{"location":"位置","description":"问题描述","template_reference":"模板原文","suggestion":"修改建议","risk_level":"low/medium/high"}'
                )
                findings = await self._call_llm_for_findings(
                    openai_service, prompt,
                    ReportReviewFindingCategory.REPORT_BODY_COMPLIANCE,
                    "模板比对",
                )
        except Exception as e:
            logger.warning("模板比对 LLM 调用失败: %s", e)

        return findings

    # ─── 内部工具 ───

    def _build_name_check_prompt(
        self, body: str, items: List[StatementItem], notes: List[NoteTable]
    ) -> str:
        item_names = list(set(i.account_name for i in items[:20]))
        note_names = list(set(n.account_name for n in notes[:20]))
        return (
            "请检查以下审计报告正文中的单位名称是否与报表和附注中的名称一致。\n\n"
            f"正文内容（前3000字）：\n{body[:3000]}\n\n"
            f"报表科目名称：{', '.join(item_names)}\n"
            f"附注科目名称：{', '.join(note_names)}\n\n"
            "请以JSON数组格式返回发现的不一致问题。"
        )

    async def _call_llm_for_findings(
        self,
        openai_service: OpenAIService,
        prompt: str,
        category: ReportReviewFindingCategory,
        check_type: str,
    ) -> List[ReportReviewFinding]:
        """调用 LLM 并解析 findings。"""
        import json

        messages = [
            {"role": "system", "content": "你是审计报告复核专家。请分析问题并以JSON数组格式返回。"},
            {"role": "user", "content": prompt},
        ]

        response = ""
        async for chunk in openai_service.stream_chat_completion(messages, temperature=0.3):
            if isinstance(chunk, str):
                response += chunk
            elif isinstance(chunk, dict) and "content" in chunk:
                response += chunk["content"]

        findings = []
        try:
            match = re.search(r'\[[\s\S]*\]', response)
            if match:
                items = json.loads(match.group())
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    findings.append(ReportReviewFinding(
                        id=str(uuid.uuid4())[:8],
                        category=category,
                        risk_level=RiskLevel(item.get("risk_level", "low")),
                        account_name=item.get("account_name", check_type),
                        location=item.get("location", "审计报告正文"),
                        description=item.get("description", ""),
                        template_reference=item.get("template_reference"),
                        suggestion=item.get("suggestion", ""),
                        analysis_reasoning=item.get("reasoning", ""),
                        confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                        status=FindingStatus.OPEN,
                    ))
        except Exception as e:
            logger.warning("解析 LLM 返回的 %s 结果失败: %s", check_type, e)

        return findings


# 模块级单例
report_body_reviewer = ReportBodyReviewer()
