"""审计底稿多维度复核引擎。

调用 OpenAIService.stream_chat_completion() 进行 LLM 推理，
复用其 429 重试、Token 估算、上下文截断等能力。
通过 KnowledgeService 检索审计准则和质控标准作为复核依据。
通过 PromptLibrary 获取用户选择的复核提示词。
支持复核过程中暂停等待用户补充材料（need_supplementary 事件）。
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Optional

from ..models.audit_schemas import (
    CrossReference,
    CrossReferenceAnalysis,
    FindingStatus,
    RequiredReference,
    ReviewFinding,
    ReviewReport,
    RiskLevel,
    SupplementaryMaterial,
    WorkpaperParseResult,
    WorkpaperType,
)
from .knowledge_service import knowledge_service
from .knowledge_retriever import knowledge_retriever
from .openai_service import OpenAIService, _get_context_limit, estimate_token_count, truncate_to_token_limit, OUTPUT_RESERVE_RATIO
from .prompt_library import PromptLibrary

logger = logging.getLogger(__name__)


class ReviewEngine:
    """审计底稿多维度复核引擎。"""

    # 复核维度定义
    REVIEW_DIMENSIONS: Dict[str, str] = {
        "format": "格式规范性",
        "data_reconciliation": "数据勾稽关系",
        "accounting_compliance": "会计准则合规性",
        "audit_procedure": "审计程序完整性",
        "evidence_sufficiency": "审计证据充分性",
    }

    # 底稿类型间的预期引用关系
    _REFERENCE_RULES: Dict[str, List[str]] = {
        "B": ["C"],          # B 类（穿行测试）应引用 C 类（控制测试）
        "C": ["B", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M"],  # C 类应引用 B 类和 D-M 类
        "D": ["C"],
        "E": ["C"],
        "F": ["C"],
        "G": ["C"],
        "H": ["C"],
        "I": ["C"],
        "J": ["C"],
        "K": ["C"],
        "L": ["C"],
        "M": ["C"],
    }

    # 业务循环映射（与 WorkpaperParser 保持一致）
    BUSINESS_CYCLE_MAP: Dict[str, str] = {
        "D": "销售循环",
        "E": "货币资金循环",
        "F": "存货循环",
        "G": "投资循环",
        "H": "固定资产循环",
        "I": "无形资产循环",
        "J": "职工薪酬循环",
        "K": "管理循环",
        "L": "债务循环",
        "M": "权益循环",
        "Q": "关联方循环",
    }

    # 风险等级关键词映射
    _HIGH_RISK_KEYWORDS = ["重大", "严重", "违规", "违反", "重大错报", "舞弊"]
    _MEDIUM_RISK_KEYWORDS = ["偏差", "不一致", "缺失", "遗漏", "不完整", "差异"]
    _LOW_RISK_KEYWORDS = ["建议", "优化", "改进", "完善", "规范", "提升"]

    def __init__(self) -> None:
        self.knowledge_service = knowledge_service
        self.prompt_library = PromptLibrary()

    @property
    def openai_service(self) -> OpenAIService:
        """每次访问时创建新实例，确保使用最新的 LLM 配置（热更新）。"""
        return OpenAIService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def review_workpaper_stream(
        self,
        workpaper: WorkpaperParseResult,
        dimensions: List[str],
        custom_dimensions: Optional[List[str]] = None,
        project_context: Optional[Dict] = None,
        prompt_id: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        supplementary_materials: Optional[List[SupplementaryMaterial]] = None,
    ) -> AsyncGenerator[str, None]:
        """流式执行底稿复核，逐维度分析并通过 SSE 输出进度和结果。

        Yields JSON-encoded SSE event strings.
        """
        review_id = str(uuid.uuid4())[:8]
        all_findings: List[ReviewFinding] = []

        yield json.dumps(
            {"status": "started", "message": f"开始复核底稿: {workpaper.filename}"},
            ensure_ascii=False,
        )

        # --- Resolve user prompt ---
        user_prompt_content: Optional[str] = custom_prompt
        if prompt_id and not user_prompt_content:
            detail = self.prompt_library.get_prompt(prompt_id)
            if detail:
                user_prompt_content = detail.content
                # Replace file placeholder
                uploaded_files = [
                    {"filename": workpaper.filename, "parse_status": workpaper.parse_status}
                ]
                user_prompt_content = self.prompt_library.resolve_file_placeholder(
                    user_prompt_content, uploaded_files
                )
                self.prompt_library.increment_usage_count(prompt_id)

        # --- Build supplementary context ---
        supplementary_context: Optional[str] = None
        if supplementary_materials:
            parts = []
            for mat in supplementary_materials:
                parts.append(mat.parsed_content)
            supplementary_context = "\n\n".join(parts)

        # --- Check required references (may yield need_supplementary) ---
        uploaded_ids = [workpaper.classification.workpaper_id or ""]
        missing_refs = await self.check_required_references(workpaper, uploaded_ids)
        if missing_refs and not supplementary_materials:
            yield json.dumps(
                {
                    "status": "need_supplementary",
                    "required_workpapers": [r.model_dump() for r in missing_refs],
                },
                ensure_ascii=False,
            )
            # The caller (router) decides whether to pause here.
            # We continue anyway so the engine can still produce partial results.

        # --- Iterate over standard dimensions ---
        all_dims = list(dimensions)
        if custom_dimensions:
            all_dims.extend(custom_dimensions)

        for dim in all_dims:
            dim_label = self.REVIEW_DIMENSIONS.get(dim, dim)
            yield json.dumps(
                {"status": "dimension_start", "dimension": dim_label},
                ensure_ascii=False,
            )

            # Retrieve knowledge context for this dimension
            knowledge_ctx = self._get_knowledge_context(workpaper, dim)

            findings = await self._review_dimension(
                workpaper=workpaper,
                dimension=dim,
                knowledge_context=knowledge_ctx,
                review_prompt=user_prompt_content,
                supplementary_context=supplementary_context,
            )
            all_findings.extend(findings)

            yield json.dumps(
                {
                    "status": "dimension_complete",
                    "dimension": dim_label,
                    "findings": [f.model_dump() for f in findings],
                },
                ensure_ascii=False,
            )

        # --- Build final report ---
        summary = {
            "high": sum(1 for f in all_findings if f.risk_level == RiskLevel.HIGH),
            "medium": sum(1 for f in all_findings if f.risk_level == RiskLevel.MEDIUM),
            "low": sum(1 for f in all_findings if f.risk_level == RiskLevel.LOW),
        }

        conclusion = self._generate_conclusion(all_findings, summary)

        report = ReviewReport(
            id=review_id,
            workpaper_ids=[workpaper.id],
            dimensions=[self.REVIEW_DIMENSIONS.get(d, d) for d in all_dims],
            findings=all_findings,
            summary=summary,
            conclusion=conclusion,
            reviewed_at=datetime.now().isoformat(),
            project_id=(project_context or {}).get("project_id"),
        )

        yield json.dumps(
            {"status": "completed", "report": report.model_dump()},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # Single-dimension review
    # ------------------------------------------------------------------

    async def _review_dimension(
        self,
        workpaper: WorkpaperParseResult,
        dimension: str,
        knowledge_context: str,
        review_prompt: Optional[str] = None,
        supplementary_context: Optional[str] = None,
    ) -> List[ReviewFinding]:
        """Execute a single dimension review via LLM and parse findings."""
        messages = await self._build_review_prompt(
            workpaper=workpaper,
            dimension=dimension,
            knowledge_context=knowledge_context,
            user_prompt=review_prompt,
            supplementary_context=supplementary_context,
        )

        # Collect streamed response
        full_response = ""
        try:
            logger.info(f"[复核] 开始调用 LLM，维度: {dimension}, 消息数: {len(messages)}")
            async for chunk in self.openai_service.stream_chat_completion(
                messages, temperature=0.3
            ):
                full_response += chunk
            logger.info(f"[复核] LLM 返回完成，维度: {dimension}, 响应长度: {len(full_response)}")
        except Exception as e:
            logger.error("LLM call failed for dimension %s: %s", dimension, e, exc_info=True)
            return []

        # Parse findings from LLM response
        return self._parse_findings(full_response, dimension)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    async def _build_review_prompt(
        self,
        workpaper: WorkpaperParseResult,
        dimension: str,
        knowledge_context: str,
        user_prompt: Optional[str] = None,
        supplementary_context: Optional[str] = None,
    ) -> List[dict]:
        """Build the messages list for a single-dimension review call.

        Injects audit context (business cycle, standards, QC standards),
        merges user-selected preset/custom prompts, and replaces the
        ``{{#sys.files#}}`` placeholder.
        """
        dim_label = self.REVIEW_DIMENSIONS.get(dimension, dimension)
        business_cycle = workpaper.classification.business_cycle or "未分类"
        workpaper_type = (
            workpaper.classification.workpaper_type.value
            if workpaper.classification.workpaper_type
            else "未知"
        )

        system_parts: List[str] = [
            "你是致同会计师事务所的资深审计复核专家。",
            f"当前复核维度：{dim_label}。",
            f"底稿类型：{workpaper_type} 类，所属业务循环：{business_cycle}。",
            "",
            "请对以下底稿内容进行专业复核，输出发现的问题列表。",
            "每个问题请按以下 JSON 数组格式输出（不要输出其他内容）：",
            '[{"location":"问题定位","description":"问题描述","reference":"参考依据","suggestion":"修改建议","risk_level":"high/medium/low"}]',
            "",
            "risk_level 判断标准：",
            "- high: 重大错报、违规、舞弊、严重偏差等可能导致审计意见变更的问题",
            "- medium: 数据不一致、信息缺失、程序遗漏等需要修正的问题",
            "- low: 格式优化、表述改进等建议性问题",
            "",
            "如果没有发现问题，请输出空数组 []。",
        ]

        # Inject knowledge context
        if knowledge_context.strip():
            system_parts.append("")
            system_parts.append("========== 审计准则与质控标准参考 ==========")
            system_parts.append(knowledge_context)
            system_parts.append("========== 参考结束 ==========")

        # Inject user prompt (preset or custom)
        if user_prompt:
            system_parts.append("")
            system_parts.append("========== 用户复核提示词 ==========")
            system_parts.append(user_prompt)
            system_parts.append("========== 提示词结束 ==========")

        system_content = "\n".join(system_parts)

        # Build user message with workpaper content (dynamic truncation based on model context)
        context_limit = _get_context_limit(self.openai_service.model_name)
        max_input_tokens = int(context_limit * (1 - OUTPUT_RESERVE_RATIO))
        system_tokens = estimate_token_count(system_content)
        overhead = 500  # supplementary + metadata overhead
        max_content_tokens = max(max_input_tokens - system_tokens - overhead, 2000)
        truncated_content = truncate_to_token_limit(workpaper.content_text, max_content_tokens)

        user_parts: List[str] = [
            f"底稿文件名：{workpaper.filename}",
            f"底稿编号：{workpaper.classification.workpaper_id or '未识别'}",
            "",
            "========== 底稿内容 ==========",
            truncated_content,
            "========== 底稿内容结束 ==========",
        ]

        if supplementary_context:
            supp_max_tokens = max(max_content_tokens // 3, 2000)
            truncated_supp = truncate_to_token_limit(supplementary_context, supp_max_tokens)
            user_parts.append("")
            user_parts.append("========== 补充材料 ==========")
            user_parts.append(truncated_supp)
            user_parts.append("========== 补充材料结束 ==========")

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    # ------------------------------------------------------------------
    # Reference checking
    # ------------------------------------------------------------------

    async def check_required_references(
        self,
        workpaper: WorkpaperParseResult,
        uploaded_workpaper_ids: List[str],
    ) -> List[RequiredReference]:
        """Check whether related workpapers required for review are uploaded.

        Based on the workpaper type, determine what related workpapers are
        needed (e.g. B-type needs C-type, C-type needs D-M types).
        Returns a list of missing references.
        """
        wp_type = workpaper.classification.workpaper_type
        if not wp_type:
            return []

        type_letter = wp_type.value
        required_types = self._REFERENCE_RULES.get(type_letter, [])
        if not required_types:
            return []

        # Normalise uploaded IDs for comparison
        uploaded_set = {uid.upper().strip() for uid in uploaded_workpaper_ids if uid}

        missing: List[RequiredReference] = []
        for req_type in required_types:
            # Check if any uploaded workpaper starts with the required type letter
            has_match = any(uid.startswith(req_type) for uid in uploaded_set)
            if not has_match:
                cycle_name = self.BUSINESS_CYCLE_MAP.get(req_type, "")
                desc = f"{wp_type.value} 类底稿复核需要参考 {req_type} 类底稿"
                if cycle_name:
                    desc += f"（{cycle_name}）"
                missing.append(
                    RequiredReference(
                        workpaper_ref=f"{req_type}-xx",
                        description=desc,
                        is_uploaded=False,
                    )
                )

        return missing

    # ------------------------------------------------------------------
    # Cross-reference analysis
    # ------------------------------------------------------------------

    async def analyze_cross_references(
        self,
        workpapers: List[WorkpaperParseResult],
    ) -> CrossReferenceAnalysis:
        """Analyze cross-references between workpapers.

        Verifies consistency between B/C/D-M type workpapers within the
        same business cycle.
        """
        references: List[CrossReference] = []
        missing_refs: List[CrossReference] = []
        consistency_findings: List[ReviewFinding] = []

        # Build lookup: type_letter -> list of workpapers
        type_map: Dict[str, List[WorkpaperParseResult]] = {}
        id_map: Dict[str, WorkpaperParseResult] = {}
        for wp in workpapers:
            if wp.classification.workpaper_type:
                letter = wp.classification.workpaper_type.value
                type_map.setdefault(letter, []).append(wp)
            id_map[wp.id] = wp

        # Detect references based on type rules
        for wp in workpapers:
            if not wp.classification.workpaper_type:
                continue
            src_letter = wp.classification.workpaper_type.value
            required_types = self._REFERENCE_RULES.get(src_letter, [])

            for req_type in required_types:
                targets = type_map.get(req_type, [])
                if targets:
                    for tgt in targets:
                        references.append(
                            CrossReference(
                                source_workpaper_id=wp.id,
                                source_workpaper_name=wp.filename,
                                target_workpaper_id=tgt.id,
                                target_workpaper_ref=tgt.classification.workpaper_id or tgt.filename,
                                is_missing=False,
                                reference_type=f"{src_letter}→{req_type} 引用",
                            )
                        )
                else:
                    ref = CrossReference(
                        source_workpaper_id=wp.id,
                        source_workpaper_name=wp.filename,
                        target_workpaper_id=None,
                        target_workpaper_ref=f"{req_type}-xx",
                        is_missing=True,
                        reference_type=f"{src_letter}→{req_type} 引用（缺失）",
                    )
                    references.append(ref)
                    missing_refs.append(ref)

                    # Missing reference → medium risk finding
                    consistency_findings.append(
                        ReviewFinding(
                            id=str(uuid.uuid4())[:8],
                            dimension="交叉引用",
                            risk_level=RiskLevel.MEDIUM,
                            location=wp.filename,
                            description=f"底稿 {wp.filename} 需要引用 {req_type} 类底稿，但未上传",
                            reference="审计底稿编制规范 - 交叉索引要求",
                            suggestion=f"请上传相关 {req_type} 类底稿以完善交叉引用",
                            status=FindingStatus.OPEN,
                        )
                    )

        # Verify B↔C consistency
        b_workpapers = type_map.get("B", [])
        c_workpapers = type_map.get("C", [])
        if b_workpapers and c_workpapers:
            finding = self._check_bc_consistency(b_workpapers, c_workpapers)
            if finding:
                consistency_findings.append(finding)

        # Verify C↔D-M consistency
        dm_types = ["D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]
        dm_workpapers = []
        for t in dm_types:
            dm_workpapers.extend(type_map.get(t, []))
        if c_workpapers and dm_workpapers:
            finding = self._check_cdm_consistency(c_workpapers, dm_workpapers)
            if finding:
                consistency_findings.append(finding)

        return CrossReferenceAnalysis(
            references=references,
            missing_references=missing_refs,
            consistency_findings=consistency_findings,
        )

    # ------------------------------------------------------------------
    # Risk classification
    # ------------------------------------------------------------------

    def classify_risk_level(self, finding: dict) -> RiskLevel:
        """Classify a review finding by risk level using keyword matching.

        Rules:
        - 重大/严重/违规 → HIGH
        - 偏差/不一致/缺失 → MEDIUM
        - 建议/优化/改进 → LOW
        """
        text = (
            finding.get("description", "")
            + " "
            + finding.get("suggestion", "")
            + " "
            + finding.get("location", "")
        )

        if any(kw in text for kw in self._HIGH_RISK_KEYWORDS):
            return RiskLevel.HIGH
        if any(kw in text for kw in self._MEDIUM_RISK_KEYWORDS):
            return RiskLevel.MEDIUM
        if any(kw in text for kw in self._LOW_RISK_KEYWORDS):
            return RiskLevel.LOW

        # Default to MEDIUM when no keywords match
        return RiskLevel.MEDIUM

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_knowledge_context(self, workpaper: WorkpaperParseResult, dimension: str) -> str:
        """Retrieve relevant knowledge from KnowledgeService for a dimension.

        优先使用 knowledge_retriever 的全量缓存进行检索，
        未预加载时回退到 knowledge_service.search_knowledge。
        """
        dim_label = self.REVIEW_DIMENSIONS.get(dimension, dimension)
        business_cycle = workpaper.classification.business_cycle or ""

        query = f"{dim_label} {business_cycle}"

        # 如果 knowledge_retriever 已预加载，优先使用检索
        if knowledge_retriever.is_loaded:
            result = knowledge_retriever.get_formatted_for_chapter(
                chapter_title=query,
                chapter_description="",
                max_tokens=10000,
            )
            if result:
                logger.info(f"[复核知识库] 维度 {dim_label} 从缓存检索到 {len(result)} 字符")
                return result

        # 回退到原有的 search_knowledge
        # Search across relevant knowledge libraries
        library_ids = []
        if dimension == "format":
            library_ids = ["workpaper_templates", "quality_standards"]
        elif dimension == "data_reconciliation":
            library_ids = ["accounting_standards", "workpaper_templates"]
        elif dimension == "accounting_compliance":
            library_ids = ["accounting_standards", "audit_regulations"]
        elif dimension == "audit_procedure":
            library_ids = ["audit_procedures", "quality_standards"]
        elif dimension == "evidence_sufficiency":
            library_ids = ["audit_procedures", "quality_standards"]
        else:
            # Custom dimension – search broadly
            library_ids = [
                "accounting_standards",
                "audit_procedures",
                "quality_standards",
            ]

        try:
            return self.knowledge_service.search_knowledge(
                library_ids=library_ids,
                query=query,
                max_chars=15000,
            )
        except Exception as e:
            logger.warning("Knowledge search failed: %s", e)
            return ""

    def _parse_findings(self, llm_response: str, dimension: str) -> List[ReviewFinding]:
        """Parse LLM response text into a list of ReviewFinding objects."""
        # Try to extract JSON array from the response
        findings: List[ReviewFinding] = []

        # Strip markdown code fences if present
        cleaned = llm_response.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (possibly ```json)
            first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
        cleaned = cleaned.strip()

        # Try to find a JSON array in the text
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            logger.warning("No JSON array found in LLM response for dimension %s", dimension)
            return findings

        try:
            items = json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from LLM response for dimension %s", dimension)
            return findings

        if not isinstance(items, list):
            return findings

        dim_label = self.REVIEW_DIMENSIONS.get(dimension, dimension)

        for item in items:
            if not isinstance(item, dict):
                continue
            # 优先使用 LLM 输出的 risk_level，回退到关键词分类
            llm_risk = (item.get("risk_level") or "").lower().strip()
            if llm_risk in ("high", "medium", "low"):
                risk_level = RiskLevel(llm_risk)
            else:
                risk_level = self.classify_risk_level(item)
            findings.append(
                ReviewFinding(
                    id=str(uuid.uuid4())[:8],
                    dimension=dim_label,
                    risk_level=risk_level,
                    location=item.get("location", "未指定"),
                    description=item.get("description", ""),
                    reference=item.get("reference", ""),
                    suggestion=item.get("suggestion", ""),
                    status=FindingStatus.OPEN,
                )
            )

        return findings

    def _generate_conclusion(
        self, findings: List[ReviewFinding], summary: Dict[str, int]
    ) -> str:
        """Generate a textual conclusion based on findings summary."""
        total = len(findings)
        if total == 0:
            return "本次复核未发现明显问题，底稿整体质量良好。"

        parts = [f"本次复核共发现 {total} 个问题"]
        detail_parts = []
        if summary["high"] > 0:
            detail_parts.append(f"高风险 {summary['high']} 个")
        if summary["medium"] > 0:
            detail_parts.append(f"中风险 {summary['medium']} 个")
        if summary["low"] > 0:
            detail_parts.append(f"低风险 {summary['low']} 个")
        if detail_parts:
            parts.append(f"（{'、'.join(detail_parts)}）")
        parts.append("。")

        if summary["high"] > 0:
            parts.append("存在高风险问题，建议优先处理后重新提交复核。")
        elif summary["medium"] > 0:
            parts.append("建议对中风险问题进行修正后确认。")
        else:
            parts.append("问题均为低风险改进建议，可酌情处理。")

        return "".join(parts)

    def _check_bc_consistency(
        self,
        b_workpapers: List[WorkpaperParseResult],
        c_workpapers: List[WorkpaperParseResult],
    ) -> Optional[ReviewFinding]:
        """Check if B-type (walkthrough) conclusions are consistent with C-type (control test) scope."""
        # Simple heuristic: if both exist, check for keyword overlap
        b_text = " ".join(wp.content_text[:2000] for wp in b_workpapers)
        c_text = " ".join(wp.content_text[:2000] for wp in c_workpapers)

        # Check for obvious inconsistency indicators
        b_has_effective = "有效" in b_text or "运行有效" in b_text
        c_has_ineffective = "无效" in c_text or "运行无效" in c_text or "偏差" in c_text

        if b_has_effective and c_has_ineffective:
            return ReviewFinding(
                id=str(uuid.uuid4())[:8],
                dimension="交叉引用",
                risk_level=RiskLevel.HIGH,
                location="B类与C类底稿",
                description="B类底稿（穿行测试）结论为控制运行有效，但C类底稿（控制测试）发现控制偏差或无效，结论不一致",
                reference="审计准则 - 穿行测试与控制测试结论一致性要求",
                suggestion="请核实B类底稿穿行测试结论是否需要修正，或C类底稿控制测试范围是否需要扩大",
                status=FindingStatus.OPEN,
            )
        return None

    def _check_cdm_consistency(
        self,
        c_workpapers: List[WorkpaperParseResult],
        dm_workpapers: List[WorkpaperParseResult],
    ) -> Optional[ReviewFinding]:
        """Check if C-type conclusions are consistent with D-M type test scope adjustments."""
        c_text = " ".join(wp.content_text[:2000] for wp in c_workpapers)
        dm_text = " ".join(wp.content_text[:2000] for wp in dm_workpapers)

        # If control tests show effective controls but substantive tests are extensive
        c_effective = "有效" in c_text and "无效" not in c_text
        dm_extensive = "扩大" in dm_text or "增加样本" in dm_text or "全面测试" in dm_text

        if c_effective and dm_extensive:
            return ReviewFinding(
                id=str(uuid.uuid4())[:8],
                dimension="交叉引用",
                risk_level=RiskLevel.MEDIUM,
                location="C类与D-M类底稿",
                description="C类底稿（控制测试）结论为控制有效，但D-M类底稿（实质性测试）仍采用扩大范围测试，测试范围调整可能不一致",
                reference="审计准则 - 控制测试结论与实质性测试范围调整一致性",
                suggestion="控制有效时实质性测试范围可适当缩小，请核实测试范围调整是否合理",
                status=FindingStatus.OPEN,
            )
        return None
