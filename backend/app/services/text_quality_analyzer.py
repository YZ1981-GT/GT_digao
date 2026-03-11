"""文本质量检查服务（LLM 辅助）。

检查标点符号使用规范性和可能的错别字。
LLM 失败时降级：跳过文本质量分析。
"""
import json
import logging
import re
import uuid
from typing import List, Optional

from ..models.audit_schemas import (
    FindingConfirmationStatus,
    FindingStatus,
    ReportReviewFinding,
    ReportReviewFindingCategory,
    RiskLevel,
)
from .openai_service import OpenAIService

logger = logging.getLogger(__name__)


class TextQualityAnalyzer:
    """文本质量检查服务。"""

    async def analyze_punctuation(
        self,
        text_content: str,
        openai_service: Optional[OpenAIService] = None,
    ) -> List[ReportReviewFinding]:
        """检查标点符号使用规范性。"""
        findings: List[ReportReviewFinding] = []
        if not text_content.strip():
            return findings

        # 本地规则：中英文标点混用检测
        findings.extend(self._check_mixed_punctuation(text_content))

        # LLM 辅助
        if openai_service:
            try:
                prompt = (
                    "请检查以下审计报告文本中的标点符号使用问题。\n"
                    "重点关注：中英文标点混用、缺失标点、多余标点。\n\n"
                    f"文本内容（前5000字）：\n{text_content[:5000]}\n\n"
                    "请以JSON数组格式返回，每项包含location/description/suggestion/risk_level。"
                )
                llm_findings = await self._call_llm(openai_service, prompt, "标点符号")
                findings.extend(llm_findings)
            except Exception as e:
                logger.warning("标点符号 LLM 检查失败: %s", e)

        return findings

    async def analyze_typos(
        self,
        text_content: str,
        openai_service: Optional[OpenAIService] = None,
    ) -> List[ReportReviewFinding]:
        """检查可能的错别字。"""
        findings: List[ReportReviewFinding] = []
        if not text_content.strip() or not openai_service:
            return findings

        try:
            prompt = (
                "请检查以下审计报告文本中可能的错别字。\n"
                "重点关注：审计专业术语、会计科目名称、常见易错字。\n\n"
                f"文本内容（前5000字）：\n{text_content[:5000]}\n\n"
                "请以JSON数组格式返回，每项包含location/description/suggestion/risk_level。"
            )
            findings = await self._call_llm(openai_service, prompt, "错别字")
        except Exception as e:
            logger.warning("错别字 LLM 检查失败: %s", e)

        return findings

    # ─── 本地规则 ───

    def _check_mixed_punctuation(self, text: str) -> List[ReportReviewFinding]:
        """检测中英文标点混用。"""
        findings = []
        # 中文语境中出现英文标点
        patterns = [
            (r'[\u4e00-\u9fff],[\u4e00-\u9fff]', "中文语境中使用了英文逗号"),
            (r'[\u4e00-\u9fff]\.[\u4e00-\u9fff]', "中文语境中使用了英文句号"),
            (r'[\u4e00-\u9fff];[\u4e00-\u9fff]', "中文语境中使用了英文分号"),
            (r'[\u4e00-\u9fff]\(', "中文语境中使用了英文左括号"),
        ]
        for pattern, desc in patterns:
            matches = list(re.finditer(pattern, text))
            if matches:
                locations = [f"位置{m.start()}" for m in matches[:3]]
                findings.append(ReportReviewFinding(
                    id=str(uuid.uuid4())[:8],
                    category=ReportReviewFindingCategory.TEXT_QUALITY,
                    risk_level=RiskLevel.LOW,
                    account_name="文本质量",
                    location=f"文本{', '.join(locations)}",
                    description=f"{desc}（共{len(matches)}处）",
                    suggestion="建议统一使用中文标点",
                    confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                    status=FindingStatus.OPEN,
                ))
        return findings

    # ─── LLM 调用 ───

    async def _call_llm(
        self,
        openai_service: OpenAIService,
        prompt: str,
        check_type: str,
    ) -> List[ReportReviewFinding]:
        messages = [
            {"role": "system", "content": "你是审计报告文本质量检查专家。请以JSON数组格式返回问题。"},
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
                    findings.append(ReportReviewFinding(
                        id=str(uuid.uuid4())[:8],
                        category=ReportReviewFindingCategory.TEXT_QUALITY,
                        risk_level=RiskLevel(item.get("risk_level", "low")),
                        account_name="文本质量",
                        location=item.get("location", "文本"),
                        description=item.get("description", ""),
                        suggestion=item.get("suggestion", ""),
                        confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                        status=FindingStatus.OPEN,
                    ))
        except Exception as e:
            logger.warning("解析 %s 结果失败: %s", check_type, e)

        return findings


# 模块级单例
text_quality_analyzer = TextQualityAnalyzer()
