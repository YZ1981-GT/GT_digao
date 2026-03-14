"""文本质量检查服务（LLM 辅助）。

检查标点符号使用规范性和可能的错别字。
LLM 失败时降级：跳过文本质量分析。
"""
import json
import logging
import re
import uuid
from typing import Dict, List, Optional

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
        source_file: str = "",
        body_char_count: int = 0,
    ) -> List[ReportReviewFinding]:
        """检查标点符号使用规范性。"""
        findings: List[ReportReviewFinding] = []
        if not text_content.strip():
            return findings

        # 本地规则：中英文标点混用检测
        findings.extend(self._check_mixed_punctuation(text_content, source_file, body_char_count))

        # LLM 辅助
        if openai_service:
            try:
                prompt = (
                    "请检查以下审计报告文本中的标点符号使用问题。\n"
                    "重点关注：中英文标点混用、缺失标点、多余标点。\n\n"
                    f"说明：文本前 {body_char_count} 个字符属于审计报告正文，之后属于附注内容。\n"
                    "请在 location 中用「正文-...」或「附注-...」前缀区分来源。\n\n"
                    f"文本内容（前5000字）：\n{text_content[:5000]}\n\n"
                    "请以JSON数组格式返回，每项必须包含以下字段：\n"
                    '{"location":"正文-第X行 或 附注-第X行（引用原文片段）","description":"问题描述，必须包含原文上下文片段","suggestion":"修改建议，给出具体的修改方式","risk_level":"low或medium"}\n'
                    "注意：location 和 description 中必须引用原文片段，让用户能定位到具体位置。\n"
                    "如果没有问题，返回空数组 []。"
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
        body_char_count: int = 0,
    ) -> List[ReportReviewFinding]:
        """检查可能的错别字。"""
        findings: List[ReportReviewFinding] = []
        if not text_content.strip() or not openai_service:
            return findings

        try:
            prompt = (
                "请检查以下审计报告文本中可能的错别字。\n"
                "重点关注：审计专业术语、会计科目名称、常见易错字。\n\n"
                f"说明：文本前 {body_char_count} 个字符属于审计报告正文，之后属于附注内容。\n"
                "请在 location 中用「正文-...」或「附注-...」前缀区分来源。\n\n"
                f"文本内容（前5000字）：\n{text_content[:5000]}\n\n"
                "请以JSON数组格式返回，每项必须包含以下字段：\n"
                '{"location":"正文-第X行 或 附注-第X行（引用原文片段）","description":"问题描述，必须包含原文上下文片段，如：「XX」应为「YY」","suggestion":"修改建议，给出具体的修改方式","risk_level":"low或medium"}\n'
                "注意：location 和 description 中必须引用原文片段，让用户能定位到具体位置。\n"
                "如果没有问题，返回空数组 []。"
            )
            findings = await self._call_llm(openai_service, prompt, "错别字")
        except Exception as e:
            logger.warning("错别字 LLM 检查失败: %s", e)

        return findings

    # ─── 本地规则 ───

    def _check_mixed_punctuation(self, text: str, source_file: str = "", body_char_count: int = 0) -> List[ReportReviewFinding]:
        """检测中英文标点混用，每处单独生成 finding 并附带上下文。"""
        findings = []
        lines = text.split('\n')
        # 构建字符偏移 → 行号映射
        line_offsets: List[int] = []
        offset = 0
        for line in lines:
            line_offsets.append(offset)
            offset += len(line) + 1  # +1 for '\n'

        # 构建行号 → 页码映射（从 "--- 第 N 页 ---" 标记提取）
        page_map: Dict[int, int] = {}  # line_index → page_number
        current_page = 0
        for i, line in enumerate(lines):
            pm = re.match(r'^---\s*第\s*(\d+)\s*页\s*---$', line.strip())
            if pm:
                current_page = int(pm.group(1))
            if current_page > 0:
                page_map[i] = current_page

        def _find_line(pos: int) -> int:
            for i in range(len(line_offsets) - 1, -1, -1):
                if pos >= line_offsets[i]:
                    return i
            return 0

        patterns = [
            (r'[\u4e00-\u9fff],[\u4e00-\u9fff]', "中文语境中使用了英文逗号", ",", "，"),
            (r'[\u4e00-\u9fff]\.[\u4e00-\u9fff]', "中文语境中使用了英文句号", ".", "。"),
            (r'[\u4e00-\u9fff];[\u4e00-\u9fff]', "中文语境中使用了英文分号", ";", "；"),
            (r'[\u4e00-\u9fff]\(', "中文语境中使用了英文左括号", "(", "（"),
        ]
        for pattern, desc, wrong_char, correct_char in patterns:
            matches = list(re.finditer(pattern, text))
            for m in matches:
                pos = m.start()
                # 提取上下文片段（前后各15字）
                ctx_start = max(0, pos - 15)
                ctx_end = min(len(text), pos + 20)
                snippet = text[ctx_start:ctx_end].replace('\n', ' ')
                # 在片段中标记问题字符
                rel_pos = pos - ctx_start
                marked = snippet[:rel_pos + 1] + '⟵' + snippet[rel_pos + 1:]
                # 定位到行
                line_no = _find_line(pos)
                line_text = lines[line_no].strip()[:50]
                # 获取页码
                page_no = page_map.get(line_no)

                # 根据字符位置判断属于正文还是附注
                source_prefix = "正文" if (body_char_count > 0 and pos < body_char_count) else "附注"
                location_str = f"{source_prefix}-第{line_no + 1}行"
                if page_no:
                    location_str = f"{source_prefix}-第{page_no}页-第{line_no + 1}行"
                location_str += f"：{line_text}"

                findings.append(ReportReviewFinding(
                    id=str(uuid.uuid4())[:8],
                    category=ReportReviewFindingCategory.TEXT_QUALITY,
                    risk_level=RiskLevel.LOW,
                    account_name="文本质量",
                    location=location_str,
                    description=f"{desc}：「{marked}」",
                    suggestion=f"将英文「{wrong_char}」改为中文「{correct_char}」",
                    source_page=page_no,
                    source_file=source_file or None,
                    confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                    status=FindingStatus.OPEN,
                ))
        return findings

    # ─── LLM 调用 ───

    @staticmethod
    def _extract_field(item: dict, primary: str, fallbacks: list) -> str:
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
                    desc = self._extract_field(item, "description", ["issue", "problem", "content", "错误描述", "问题"])
                    suggestion = self._extract_field(item, "suggestion", ["fix", "recommendation", "修改建议", "建议"])
                    if not desc:
                        continue
                    findings.append(ReportReviewFinding(
                        id=str(uuid.uuid4())[:8],
                        category=ReportReviewFindingCategory.TEXT_QUALITY,
                        risk_level=RiskLevel(item.get("risk_level", "low")),
                        account_name="文本质量",
                        location=item.get("location", "文本"),
                        description=desc,
                        suggestion=suggestion,
                        confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                        status=FindingStatus.OPEN,
                    ))
        except Exception as e:
            logger.warning("解析 %s 结果失败: %s", check_type, e)

        return findings


# 模块级单例
text_quality_analyzer = TextQualityAnalyzer()
