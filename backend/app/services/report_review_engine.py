"""审计报告复核引擎（整合五层复核）。

流式执行：结构识别 → 数值校验 → 正文复核 → 附注内容复核 → 文本质量检查。
所有 Finding 统一标记为 pending_confirmation。
"""
import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Optional

from ..models.audit_schemas import (
    ChangeAnalysis,
    FindingConfirmationStatus,
    FindingConversation,
    FindingConversationMessage,
    FindingStatus,
    MatchingMap,
    NoteTable,
    ReportReviewConfig,
    ReportReviewFinding,
    ReportReviewFindingCategory,
    ReportReviewResult,
    ReportReviewSession,
    RiskLevel,
    StatementItem,
    TableStructure,
    TemplateCategory,
)
from .openai_service import OpenAIService
from .reconciliation_engine import ReconciliationEngine
from .report_body_reviewer import ReportBodyReviewer
from .report_template_service import ReportTemplateService
from .note_content_reviewer import NoteContentReviewer
from .text_quality_analyzer import TextQualityAnalyzer
from .table_structure_analyzer import TableStructureAnalyzer

logger = logging.getLogger(__name__)


class ReportReviewEngine:
    """审计报告复核引擎。"""

    def __init__(self):
        self.reconciliation = ReconciliationEngine()
        self.table_analyzer = TableStructureAnalyzer()
        self.template_service = ReportTemplateService()
        self.body_reviewer = ReportBodyReviewer(self.template_service)
        self.note_reviewer = NoteContentReviewer(self.template_service)
        self.text_analyzer = TextQualityAnalyzer()

    @property
    def openai_service(self) -> OpenAIService:
        return OpenAIService()

    # ─── 主流程 ───

    async def review_stream(
        self,
        session: ReportReviewSession,
        config: ReportReviewConfig,
    ) -> AsyncGenerator[str, None]:
        """流式执行五层复核。"""
        all_findings: List[ReportReviewFinding] = []
        oai = self.openai_service

        yield json.dumps({"status": "started", "message": "开始审计报告复核"}, ensure_ascii=False)

        # 1. 结构识别
        yield json.dumps({"status": "phase", "phase": "structure_analysis", "message": "正在识别附注表格结构..."}, ensure_ascii=False)
        table_structures: Dict[str, TableStructure] = {}
        for note in session.note_tables:
            try:
                ts = await self.table_analyzer.analyze_table_structure(note, oai)
                table_structures[note.id] = ts
            except Exception as e:
                logger.warning("表格结构识别失败 %s: %s", note.id, e)

        # 2. 数值校验
        yield json.dumps({"status": "phase", "phase": "reconciliation", "message": "正在执行数值校验..."}, ensure_ascii=False)
        if session.matching_map:
            amount_findings = self.reconciliation.check_amount_consistency(
                session.matching_map, session.statement_items, session.note_tables, table_structures
            )
            all_findings.extend(amount_findings)

            for note in session.note_tables:
                ts = table_structures.get(note.id)
                if ts:
                    all_findings.extend(self.reconciliation.check_note_table_integrity(note, ts))
                    all_findings.extend(self.reconciliation.check_balance_formula(note, ts))
                    all_findings.extend(self.reconciliation.check_sub_items(note, ts))

        # 变动分析
        changes = self.calculate_changes(session.statement_items)
        abnormal = self.flag_abnormal_changes(changes, config.change_threshold)
        for item in abnormal:
            try:
                change_findings = await self.analyze_change_reasonableness(item, oai, config.custom_prompt)
                all_findings.extend(change_findings)
            except Exception as e:
                logger.warning("变动分析失败 %s: %s", item.account_name, e)

        # 逐科目发送进度
        for item in session.statement_items:
            item_findings = [f for f in all_findings if f.account_name == item.account_name]
            yield json.dumps({
                "status": "account_complete",
                "account_name": item.account_name,
                "findings_count": len(item_findings),
            }, ensure_ascii=False)

        # 3. 正文复核
        yield json.dumps({"status": "phase", "phase": "body_review", "message": "正在复核审计报告正文..."}, ensure_ascii=False)
        report_body = session.file_classifications.get("report_body_text", "")
        if isinstance(report_body, str) and report_body:
            try:
                body_findings = await self.body_reviewer.check_entity_name_consistency(
                    report_body, session.statement_items, session.note_tables, oai
                )
                all_findings.extend(body_findings)
                body_findings2 = await self.body_reviewer.check_abbreviation_consistency(report_body, "", oai)
                all_findings.extend(body_findings2)
                body_findings3 = await self.body_reviewer.check_template_compliance(
                    report_body, config.template_type, oai
                )
                all_findings.extend(body_findings3)
            except Exception as e:
                logger.warning("正文复核失败: %s", e)

        # 4. 附注内容复核
        yield json.dumps({"status": "phase", "phase": "note_review", "message": "正在复核附注内容..."}, ensure_ascii=False)
        try:
            notes_text = " ".join(n.section_title for n in session.note_tables)
            sections = self.note_reviewer.extract_narrative_sections(notes_text)
            for section in sections:
                expr_findings = await self.note_reviewer.check_expression_quality(section, oai)
                all_findings.extend(expr_findings)
                if section.section_type == "accounting_policy":
                    policy_findings = await self.note_reviewer.check_policy_template_compliance(
                        section, config.template_type, oai
                    )
                    all_findings.extend(policy_findings)
        except Exception as e:
            logger.warning("附注内容复核失败: %s", e)

        # 5. 文本质量检查
        yield json.dumps({"status": "phase", "phase": "text_quality", "message": "正在检查文本质量..."}, ensure_ascii=False)
        try:
            all_text = report_body if isinstance(report_body, str) else ""
            punct_findings = await self.text_analyzer.analyze_punctuation(all_text, oai)
            all_findings.extend(punct_findings)
            typo_findings = await self.text_analyzer.analyze_typos(all_text, oai)
            all_findings.extend(typo_findings)
        except Exception as e:
            logger.warning("文本质量检查失败: %s", e)

        # 确保所有 Finding 为 pending_confirmation
        for f in all_findings:
            f.confirmation_status = FindingConfirmationStatus.PENDING_CONFIRMATION

        # 生成结果
        summary = self._build_summary(all_findings)
        recon_summary = self.reconciliation.get_reconciliation_summary(all_findings)

        result = ReportReviewResult(
            id=str(uuid.uuid4())[:8],
            session_id=session.id,
            findings=all_findings,
            category_summary=summary["category"],
            risk_summary=summary["risk"],
            reconciliation_summary=recon_summary,
            confirmation_summary={"pending": len(all_findings), "confirmed": 0, "dismissed": 0},
            conclusion=self._generate_conclusion(all_findings),
            reviewed_at=datetime.now().isoformat(),
        )

        yield json.dumps({"status": "completed", "result": result.model_dump()}, ensure_ascii=False)

    # ─── 变动分析 ───

    def calculate_changes(self, items: List[StatementItem]) -> List[ChangeAnalysis]:
        """计算各科目变动金额和百分比。"""
        changes = []
        for item in items:
            if item.is_sub_item:
                continue
            opening = item.opening_balance
            closing = item.closing_balance
            change_amount = None
            change_pct = None
            exceeds = False

            if opening is not None and closing is not None:
                change_amount = closing - opening
                if abs(opening) > 0.01:
                    change_pct = change_amount / abs(opening)

            changes.append(ChangeAnalysis(
                statement_item_id=item.id,
                account_name=item.account_name,
                opening_balance=opening,
                closing_balance=closing,
                change_amount=change_amount,
                change_percentage=change_pct,
                exceeds_threshold=False,
            ))
        return changes

    def flag_abnormal_changes(
        self, changes: List[ChangeAnalysis], threshold: float = 0.3
    ) -> List[StatementItem]:
        """标记超阈值科目。返回需要 LLM 分析的 StatementItem 列表。"""
        abnormal_ids = []
        for c in changes:
            if c.change_percentage is not None and abs(c.change_percentage) > threshold:
                c.exceeds_threshold = True
                abnormal_ids.append(c.statement_item_id)
        # 返回空列表（实际需要从 session 获取 items，这里简化）
        return []

    async def analyze_change_reasonableness(
        self,
        item: StatementItem,
        openai_service: OpenAIService,
        custom_prompt: Optional[str] = None,
    ) -> List[ReportReviewFinding]:
        """LLM 辅助分析超阈值科目变动合理性。"""
        prompt = f"请分析科目'{item.account_name}'的变动合理性。"
        if item.opening_balance and item.closing_balance:
            change = item.closing_balance - item.opening_balance
            prompt += f"\n期初: {item.opening_balance}, 期末: {item.closing_balance}, 变动: {change}"
        if custom_prompt:
            prompt += f"\n用户要求: {custom_prompt}"

        messages = [
            {"role": "system", "content": "你是审计变动分析专家。请以JSON数组格式返回分析结果。"},
            {"role": "user", "content": prompt},
        ]

        response = ""
        try:
            async for chunk in openai_service.stream_chat_completion(messages, temperature=0.3):
                if isinstance(chunk, str):
                    response += chunk
        except Exception:
            return []

        # 简化：返回空列表（实际应解析 LLM 响应）
        return []

    # ─── Finding 交互 ───

    async def chat_about_finding(
        self,
        finding: ReportReviewFinding,
        user_message: str,
        conversation: FindingConversation,
        openai_service: Optional[OpenAIService] = None,
    ) -> AsyncGenerator[str, None]:
        """用户追问，流式回复。"""
        if not openai_service:
            yield json.dumps({"error": "LLM 服务不可用"}, ensure_ascii=False)
            return

        # 构建上下文
        messages = [
            {"role": "system", "content": f"你是审计复核助手。当前问题：{finding.description}\n建议：{finding.suggestion}"},
        ]
        for msg in conversation.messages[-10:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        # 记录用户消息
        user_msg = FindingConversationMessage(
            id=str(uuid.uuid4())[:8],
            role="user",
            content=user_message,
            message_type="chat",
            created_at=datetime.now().isoformat(),
        )
        conversation.messages.append(user_msg)

        # 流式回复
        assistant_content = ""
        try:
            async for chunk in openai_service.stream_chat_completion(messages, temperature=0.5):
                if isinstance(chunk, str):
                    assistant_content += chunk
                    yield json.dumps({"status": "streaming", "content": chunk}, ensure_ascii=False)
        except Exception as e:
            yield json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
            return

        # 记录助手回复
        assistant_msg = FindingConversationMessage(
            id=str(uuid.uuid4())[:8],
            role="assistant",
            content=assistant_content,
            message_type="chat",
            created_at=datetime.now().isoformat(),
        )
        conversation.messages.append(assistant_msg)
        yield json.dumps({"status": "done"}, ensure_ascii=False)

    async def trace_finding(
        self,
        finding: ReportReviewFinding,
        trace_type: str,
        conversation: FindingConversation,
        openai_service: Optional[OpenAIService] = None,
    ) -> AsyncGenerator[str, None]:
        """溯源分析。"""
        if not openai_service:
            yield json.dumps({"error": "LLM 服务不可用"}, ensure_ascii=False)
            return

        trace_prompts = {
            "cross_reference": f"请对问题'{finding.description}'进行跨文档交叉引用分析。",
            "template_compare": f"请对问题'{finding.description}'进行模板详细比对分析。",
            "data_drill_down": f"请对问题'{finding.description}'进行数据下钻分析。",
        }
        prompt = trace_prompts.get(trace_type, f"请分析问题：{finding.description}")

        messages = [
            {"role": "system", "content": "你是审计溯源分析专家。"},
            {"role": "user", "content": prompt},
        ]

        content = ""
        try:
            async for chunk in openai_service.stream_chat_completion(messages, temperature=0.3):
                if isinstance(chunk, str):
                    content += chunk
                    yield json.dumps({"status": "streaming", "content": chunk}, ensure_ascii=False)
        except Exception as e:
            yield json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
            return

        # 记录溯源消息
        trace_msg = FindingConversationMessage(
            id=str(uuid.uuid4())[:8],
            role="assistant",
            content=content,
            message_type="trace",
            trace_type=trace_type,
            created_at=datetime.now().isoformat(),
        )
        conversation.messages.append(trace_msg)
        yield json.dumps({"status": "done"}, ensure_ascii=False)

    # ─── 内部工具 ───

    @staticmethod
    def _build_summary(findings: List[ReportReviewFinding]) -> Dict:
        category_summary = {}
        risk_summary = {"high": 0, "medium": 0, "low": 0}
        for f in findings:
            cat = f.category.value if hasattr(f.category, 'value') else str(f.category)
            category_summary[cat] = category_summary.get(cat, 0) + 1
            risk_summary[f.risk_level.value] = risk_summary.get(f.risk_level.value, 0) + 1
        return {"category": category_summary, "risk": risk_summary}

    @staticmethod
    def _generate_conclusion(findings: List[ReportReviewFinding]) -> str:
        total = len(findings)
        if total == 0:
            return "本次复核未发现明显问题。"
        high = sum(1 for f in findings if f.risk_level == RiskLevel.HIGH)
        medium = sum(1 for f in findings if f.risk_level == RiskLevel.MEDIUM)
        low = sum(1 for f in findings if f.risk_level == RiskLevel.LOW)
        parts = [f"本次复核共发现 {total} 个待确认问题"]
        details = []
        if high:
            details.append(f"高风险 {high} 个")
        if medium:
            details.append(f"中风险 {medium} 个")
        if low:
            details.append(f"低风险 {low} 个")
        if details:
            parts.append(f"（{'、'.join(details)}）")
        parts.append("。所有问题需经用户确认后纳入最终报告。")
        return "".join(parts)


# 模块级单例
report_review_engine = ReportReviewEngine()
