"""审计报告复核引擎（整合五层复核）。

流式执行：结构识别 → 数值校验 → 正文复核 → 附注内容复核 → 文本质量检查。
所有 Finding 统一标记为 pending_confirmation。
"""
import asyncio
import json
import logging
import re
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
    NarrativeSection,
    NoteSection,
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

    def _find_template_section_for_account(
        self,
        account_name: str,
        template_type: str,
        template_toc: Optional[list] = None,
    ) -> Optional[str]:
        """模糊匹配科目名到模板章节路径，返回章节内容。

        优先匹配精确标题，其次匹配包含关系（要求至少2个字重叠）。
        如果匹配到的章节有子章节含表格，优先返回含表格的子章节。
        """
        if not template_toc or not account_name:
            return None
        best_path = None
        best_score = 0
        for toc_entry in template_toc:
            title = toc_entry.title
            clean_title = re.sub(r'[（(].*?[）)]', '', title).strip()
            if not clean_title:
                continue
            if account_name == clean_title:
                best_path = toc_entry.path
                best_score = 100
                break
            if account_name in clean_title and len(account_name) >= 2:
                score = len(account_name) / max(len(clean_title), 1) * 50
                if score > best_score:
                    best_score = score
                    best_path = toc_entry.path
            elif clean_title in account_name and len(clean_title) >= 2:
                score = len(clean_title) / max(len(account_name), 1) * 40
                if score > best_score:
                    best_score = score
                    best_path = toc_entry.path
        if not best_path or best_score < 10:
            return None

        content = self.template_service.get_template_section(
            template_type, TemplateCategory.NOTES, best_path,
        )
        if content is not None and len(content) < 200:
            child_prefix = best_path + "/"
            child_parts = []
            for toc_entry in template_toc:
                if toc_entry.path.startswith(child_prefix):
                    child_content = self.template_service.get_template_section(
                        template_type, TemplateCategory.NOTES, toc_entry.path,
                    )
                    if child_content and "|" in child_content:
                        child_parts.append(f"### {toc_entry.title}\n{child_content}")
            if child_parts:
                content = content + "\n\n" + "\n\n".join(child_parts)

        if content and len(content) > 2000:
            content = content[:2000] + "\n...(截断)"
        return content


    # ─── 主流程 ───

    async def review_stream(
        self,
        session: ReportReviewSession,
        config: ReportReviewConfig,
    ) -> AsyncGenerator[str, None]:
        """流式执行五层复核。每次 yield 后用 asyncio.sleep(0) 确保事件及时 flush。"""
        all_findings: List[ReportReviewFinding] = []
        oai = self.openai_service

        yield json.dumps({"status": "started", "message": "开始审计报告复核"}, ensure_ascii=False)
        await asyncio.sleep(0)

        # ── 预加载模板 TOC 和 note_id → StatementItem 映射（Phase 1 & 2 共用）──
        _template_toc = self.template_service.get_template_toc(
            config.template_type, TemplateCategory.NOTES,
        )
        _item_map = {i.id: i for i in session.statement_items}
        _note_id_to_item: Dict[str, StatementItem] = {}
        if session.matching_map:
            for entry in session.matching_map.entries:
                itm = _item_map.get(entry.statement_item_id)
                if itm:
                    for nid_tmp in entry.note_table_ids:
                        _note_id_to_item[nid_tmp] = itm

        def _build_hints_for_note(nid: str):
            """为指定附注表格构建 template_hint 和 statement_amount_hint。"""
            template_hint = None
            statement_amount_hint = None
            item = _note_id_to_item.get(nid)
            if item:
                parts = []
                if item.closing_balance is not None:
                    parts.append(f"期末余额={item.closing_balance:,.2f}")
                if item.opening_balance is not None:
                    parts.append(f"期初余额={item.opening_balance:,.2f}")
                if parts:
                    statement_amount_hint = f"报表科目'{item.account_name}'的{', '.join(parts)}"
                template_hint = self._find_template_section_for_account(
                    item.account_name, config.template_type, _template_toc,
                )
            return template_hint, statement_amount_hint

        # 1. 结构识别（优先复用 session 中已有的结果，仅补充缺失的）
        table_structures: Dict[str, TableStructure] = dict(session.table_structures)
        missing_notes = [n for n in session.note_tables if n.id not in table_structures]
        total_tables = len(session.note_tables)

        if missing_notes:
            yield json.dumps({"status": "phase", "phase": "structure_analysis", "message": f"正在识别附注表格结构（{len(missing_notes)} 个待识别，{total_tables - len(missing_notes)} 个已缓存）..."}, ensure_ascii=False)
            await asyncio.sleep(0)

            async def _analyze_one(note: NoteTable) -> tuple:
                try:
                    t_hint, s_hint = _build_hints_for_note(note.id)
                    ts = await self.table_analyzer.analyze_table_structure(
                        note, oai,
                        template_hint=t_hint,
                        statement_amount_hint=s_hint,
                    )
                    return (note.id, ts, None)
                except Exception as e:
                    logger.warning("表格结构识别失败 %s: %s", note.id, e)
                    return (note.id, None, e)

            semaphore = asyncio.Semaphore(5)

            async def _analyze_with_limit(note: NoteTable) -> tuple:
                async with semaphore:
                    return await _analyze_one(note)

            results = await asyncio.gather(
                *[_analyze_with_limit(note) for note in missing_notes],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    continue
                note_id, ts, err = r
                if ts:
                    table_structures[note_id] = ts

            yield json.dumps({
                "status": "phase_progress",
                "phase": "structure_analysis",
                "message": f"表格结构识别完成（{len(table_structures)}/{total_tables}）",
            }, ensure_ascii=False)
            await asyncio.sleep(0)
        else:
            yield json.dumps({"status": "phase", "phase": "structure_analysis", "message": f"复用已有表格结构（{total_tables} 个）"}, ensure_ascii=False)
            await asyncio.sleep(0)

        # 统计结构识别详情
        high_conf = sum(1 for ts in table_structures.values() if ts.structure_confidence == "high")
        med_conf = sum(1 for ts in table_structures.values() if ts.structure_confidence == "medium")
        low_conf = sum(1 for ts in table_structures.values() if ts.structure_confidence == "low")
        has_total_count = sum(1 for ts in table_structures.values() if ts.total_row_indices)
        has_formula_count = sum(1 for ts in table_structures.values() if ts.has_balance_formula)
        struct_details = [
            f"共识别 {len(table_structures)} 个附注表格",
            f"识别置信度：高 {high_conf} 个、中 {med_conf} 个、低 {low_conf} 个",
            f"含合计行的表格 {has_total_count} 个，含余额变动结构的表格 {has_formula_count} 个",
        ]
        yield json.dumps({
            "status": "phase_complete", "phase": "structure_analysis",
            "message": f"结构识别完成，共识别 {len(table_structures)} 个表格",
            "findings_count": 0,
            "details": struct_details,
        }, ensure_ascii=False)
        await asyncio.sleep(0)

        # 2. 数值校验
        yield json.dumps({"status": "phase", "phase": "reconciliation", "message": "正在执行数值校验..."}, ensure_ascii=False)
        await asyncio.sleep(0)

        # 统计变量
        amount_check_count = 0  # 报表vs附注比对的科目数
        amount_match_count = 0  # 金额一致的科目数
        integrity_check_count = 0  # 表内加总校验的表格数
        integrity_match_count = 0  # 加总无误的表格数
        formula_check_count = 0  # 余额变动公式校验的表格数
        formula_match_count = 0  # 公式无误的表格数
        sub_item_check_count = 0  # 其中项校验的表格数
        sub_item_match_count = 0  # 其中项无误的表格数
        cross_table_check_count = 0  # 跨表交叉核对发现的问题数
        wide_table_check_count = 0  # 宽表横向公式校验的表格数
        wide_table_match_count = 0  # 宽表横向公式相符的表格数
        llm_reanalyzed_count = 0  # LLM 二次校验的表格数
        llm_fixed_count = 0  # LLM 修正结构的表格数

        if session.matching_map:
            # 跟踪已被 LLM 重新分析过的表格 ID（避免重复调用）
            _llm_reanalyzed_ids: set = set()

            amount_findings = self.reconciliation.check_amount_consistency(
                session.matching_map, session.statement_items, session.note_tables, table_structures,
                note_sections=session.note_sections,
            )

            # ── LLM 二次校验：金额不一致或未提取到值时，调用 LLM 重新识别表格结构 ──
            if amount_findings and oai:
                # 收集不一致 finding 涉及的附注表格 ID（包括"未找到值"的 finding）
                mismatch_note_ids: set = set()
                not_found_tag = self.reconciliation.NOTE_VALUE_NOT_FOUND_TAG
                not_found_count = sum(1 for f in amount_findings if not_found_tag in (f.description or ""))
                mismatch_count = len(amount_findings) - not_found_count
                for f in amount_findings:
                    if f.note_table_ids:
                        mismatch_note_ids.update(f.note_table_ids)

                if mismatch_note_ids:
                    msg_parts = []
                    if mismatch_count > 0:
                        msg_parts.append(f"{mismatch_count} 个金额不一致")
                    if not_found_count > 0:
                        msg_parts.append(f"{not_found_count} 个未提取到附注合计值")
                    yield json.dumps({
                        "status": "phase_progress", "phase": "reconciliation",
                        "message": f"初步校验发现 {'、'.join(msg_parts)}，正在调用 LLM 校验 {len(mismatch_note_ids)} 个表格结构...",
                    }, ensure_ascii=False)
                    await asyncio.sleep(0)

                    note_map_for_recheck = {n.id: n for n in session.note_tables}
                    updated_note_ids: set = set()
                    recheck_semaphore = asyncio.Semaphore(3)

                    async def _reanalyze_one(nid: str):
                        note = note_map_for_recheck.get(nid)
                        if not note:
                            return (nid, None)
                        t_hint, s_hint = _build_hints_for_note(nid)
                        async with recheck_semaphore:
                            new_ts = await self.table_analyzer.reanalyze_with_llm(
                                note, oai,
                                template_hint=t_hint,
                                statement_amount_hint=s_hint,
                            )
                            return (nid, new_ts)

                    recheck_results = await asyncio.gather(
                        *[_reanalyze_one(nid) for nid in mismatch_note_ids],
                        return_exceptions=True,
                    )

                    for r in recheck_results:
                        if isinstance(r, Exception):
                            continue
                        nid, new_ts = r
                        llm_reanalyzed_count += 1
                        _llm_reanalyzed_ids.add(nid)
                        if new_ts is not None:
                            # LLM 返回了不同的结构，更新并标记
                            table_structures[nid] = new_ts
                            updated_note_ids.add(nid)
                            llm_fixed_count += 1

                    if updated_note_ids:
                        # 用更新后的结构重新核对金额
                        new_amount_findings = self.reconciliation.check_amount_consistency(
                            session.matching_map, session.statement_items,
                            session.note_tables, table_structures,
                            note_sections=session.note_sections,
                        )
                        # 替换原始 findings
                        amount_findings = new_amount_findings
                        logger.info(
                            "LLM 二次校验完成：重新分析 %d 个表格，修正 %d 个，"
                            "金额不一致从 %d 个变为 %d 个",
                            llm_reanalyzed_count, llm_fixed_count,
                            len(amount_findings) + llm_fixed_count,  # 原始数量近似
                            len(new_amount_findings),
                        )

                        yield json.dumps({
                            "status": "phase_progress", "phase": "reconciliation",
                            "message": f"LLM 校验完成：修正 {llm_fixed_count} 个表格结构，重新核对后剩余 {len(new_amount_findings)} 个不一致",
                        }, ensure_ascii=False)
                        await asyncio.sleep(0)
                    else:
                        yield json.dumps({
                            "status": "phase_progress", "phase": "reconciliation",
                            "message": f"LLM 校验完成：{llm_reanalyzed_count} 个表格结构确认无误",
                        }, ensure_ascii=False)
                        await asyncio.sleep(0)

            # 统计报表vs附注比对
            amount_check_count = len(session.matching_map.entries)
            # 统计有不一致 finding 的科目数（一个科目可能有期末+期初两个 finding）
            amount_mismatch_accounts = len(set(f.account_name for f in amount_findings))
            amount_match_count = amount_check_count - amount_mismatch_accounts
            all_findings.extend(amount_findings)

            note_map_tmp_recheck = {n.id: n for n in session.note_tables}

            # ── 第一轮本地校验 ──
            local_error_note_ids: set = set()  # 本地校验发现问题的表格 ID
            _first_pass_findings: List[ReportReviewFinding] = []
            # 记录每个表格在第一轮中各类校验是否通过（用于反馈循环回退计数）
            _first_pass_match: Dict[str, Dict[str, bool]] = {}

            for note in session.note_tables:
                ts = table_structures.get(note.id)
                if ts:
                    note_findings: List[ReportReviewFinding] = []
                    note_match: Dict[str, bool] = {}

                    if ts.total_row_indices:
                        integrity_check_count += 1
                        integrity_f = self.reconciliation.check_note_table_integrity(note, ts)
                        if not integrity_f:
                            integrity_match_count += 1
                            note_match["integrity"] = True
                        else:
                            note_match["integrity"] = False
                        note_findings.extend(integrity_f)

                    if ts.has_balance_formula:
                        formula_check_count += 1
                        formula_f = self.reconciliation.check_balance_formula(note, ts)
                        if not formula_f:
                            formula_match_count += 1
                            note_match["formula"] = True
                        else:
                            note_match["formula"] = False
                        note_findings.extend(formula_f)

                    has_sub = any(r.role == "sub_item" for r in ts.rows)
                    if has_sub:
                        sub_item_check_count += 1
                        sub_f = self.reconciliation.check_sub_items(note, ts)
                        if not sub_f:
                            sub_item_match_count += 1
                            note_match["sub_item"] = True
                        else:
                            note_match["sub_item"] = False
                        note_findings.extend(sub_f)

                    ratio_f = self.reconciliation.check_ratio_columns(note, ts)
                    note_findings.extend(ratio_f)

                    # 未分配利润专用校验
                    if self.reconciliation._is_undistributed_profit_table(note):
                        udp_f = self.reconciliation.check_undistributed_profit(note, ts)
                        note_findings.extend(udp_f)

                    _first_pass_match[note.id] = note_match
                    if note_findings:
                        local_error_note_ids.add(note.id)
                    _first_pass_findings.extend(note_findings)

            # ── LLM 反馈循环：对本地校验失败且未被 LLM 重新分析过的表格，触发 LLM 重新识别 ──
            retry_note_ids = local_error_note_ids - _llm_reanalyzed_ids
            if retry_note_ids and oai:
                logger.info(
                    "本地校验发现 %d 个表格有问题，其中 %d 个未经 LLM 重新分析，触发反馈循环",
                    len(local_error_note_ids), len(retry_note_ids),
                )
                yield json.dumps({
                    "status": "phase_progress", "phase": "reconciliation",
                    "message": f"本地校验发现 {len(local_error_note_ids)} 个表格有差异，正在对 {len(retry_note_ids)} 个表格进行 LLM 结构复核...",
                }, ensure_ascii=False)
                await asyncio.sleep(0)

                retry_semaphore = asyncio.Semaphore(3)

                async def _retry_reanalyze(nid: str):
                    note = note_map_tmp_recheck.get(nid)
                    if not note:
                        return (nid, None)
                    t_hint, s_hint = _build_hints_for_note(nid)
                    async with retry_semaphore:
                        new_ts = await self.table_analyzer.reanalyze_with_llm(
                            note, oai,
                            template_hint=t_hint,
                            statement_amount_hint=s_hint,
                        )
                        return (nid, new_ts)

                retry_results = await asyncio.gather(
                    *[_retry_reanalyze(nid) for nid in retry_note_ids],
                    return_exceptions=True,
                )

                retry_updated_ids: set = set()
                for r in retry_results:
                    if isinstance(r, Exception):
                        continue
                    nid, new_ts = r
                    llm_reanalyzed_count += 1
                    _llm_reanalyzed_ids.add(nid)
                    if new_ts is not None:
                        table_structures[nid] = new_ts
                        retry_updated_ids.add(nid)
                        llm_fixed_count += 1

                if retry_updated_ids:
                    # 结构已更新，重新运行本地校验（仅对更新的表格）
                    # 先移除第一轮中这些表格产生的 findings
                    new_first_pass = []
                    for f in _first_pass_findings:
                        if f.note_table_ids and set(f.note_table_ids) & retry_updated_ids:
                            continue  # 移除旧 finding
                        new_first_pass.append(f)
                    _first_pass_findings = new_first_pass

                    for nid in retry_updated_ids:
                        note = note_map_tmp_recheck.get(nid)
                        ts = table_structures.get(nid)
                        if not note or not ts:
                            continue

                        # 回退第一轮的 match 计数
                        old_match = _first_pass_match.get(nid, {})
                        if old_match.get("integrity"):
                            integrity_match_count -= 1
                        if old_match.get("formula"):
                            formula_match_count -= 1
                        if old_match.get("sub_item"):
                            sub_item_match_count -= 1

                        # 用新结构重新校验
                        if ts.total_row_indices:
                            integrity_f = self.reconciliation.check_note_table_integrity(note, ts)
                            if not integrity_f:
                                integrity_match_count += 1
                            _first_pass_findings.extend(integrity_f)

                        if ts.has_balance_formula:
                            formula_f = self.reconciliation.check_balance_formula(note, ts)
                            if not formula_f:
                                formula_match_count += 1
                            _first_pass_findings.extend(formula_f)

                        has_sub = any(r.role == "sub_item" for r in ts.rows)
                        if has_sub:
                            sub_f = self.reconciliation.check_sub_items(note, ts)
                            if not sub_f:
                                sub_item_match_count += 1
                            _first_pass_findings.extend(sub_f)

                        ratio_f = self.reconciliation.check_ratio_columns(note, ts)
                        _first_pass_findings.extend(ratio_f)

                        # 未分配利润专用校验
                        if self.reconciliation._is_undistributed_profit_table(note):
                            udp_f = self.reconciliation.check_undistributed_profit(note, ts)
                            _first_pass_findings.extend(udp_f)

                    logger.info(
                        "反馈循环完成：LLM 修正 %d 个表格结构，重新校验后剩余 %d 个本地校验问题",
                        len(retry_updated_ids), len(_first_pass_findings),
                    )
                    yield json.dumps({
                        "status": "phase_progress", "phase": "reconciliation",
                        "message": f"LLM 结构复核完成：修正 {len(retry_updated_ids)} 个表格，重新校验后剩余 {len(_first_pass_findings)} 个差异",
                    }, ensure_ascii=False)
                    await asyncio.sleep(0)

            all_findings.extend(_first_pass_findings)

            # ── 宽表横向公式校验（LLM 识别列语义 + 本地数值验证）──
            wide_table_check_count = 0
            wide_table_match_count = 0
            wide_table_candidates = [
                n for n in session.note_tables
                if self.table_analyzer.is_wide_table_candidate(n, table_structures.get(n.id))
            ]
            if wide_table_candidates and oai:
                yield json.dumps({
                    "status": "phase_progress", "phase": "reconciliation",
                    "message": f"正在对 {len(wide_table_candidates)} 个宽表进行横向公式分析...",
                }, ensure_ascii=False)
                await asyncio.sleep(0)

                wide_semaphore = asyncio.Semaphore(3)

                async def _analyze_wide(note: NoteTable):
                    t_hint, _ = _build_hints_for_note(note.id)
                    async with wide_semaphore:
                        try:
                            formula = await self.table_analyzer.analyze_wide_table_formula(
                                note, oai, template_hint=t_hint,
                            )
                            return (note.id, formula, None)
                        except Exception as e:
                            logger.warning("宽表公式分析失败 %s: %s", note.id, e)
                            return (note.id, None, e)

                wide_results = await asyncio.gather(
                    *[_analyze_wide(n) for n in wide_table_candidates],
                    return_exceptions=True,
                )

                wide_table_findings: List[ReportReviewFinding] = []
                for r in wide_results:
                    if isinstance(r, Exception):
                        continue
                    nid, formula, err = r
                    if formula is None:
                        continue
                    wide_table_check_count += 1
                    note = note_map_tmp_recheck.get(nid)
                    if not note:
                        continue
                    wf = self.reconciliation.check_wide_table_formula(note, formula)
                    if not wf:
                        wide_table_match_count += 1
                    wide_table_findings.extend(wf)

                all_findings.extend(wide_table_findings)

                if wide_table_check_count > 0:
                    yield json.dumps({
                        "status": "phase_progress", "phase": "reconciliation",
                        "message": f"宽表横向公式校验完成：共分析 {wide_table_check_count} 个表格，"
                                   f"相符 {wide_table_match_count} 个，发现 {len(wide_table_findings)} 个差异",
                    }, ensure_ascii=False)
                    await asyncio.sleep(0)

            # ── 跨表交叉核对（同科目下多表之间的一致性校验）──
            cross_table_findings = self.reconciliation.check_cross_table_consistency(
                session.note_tables, table_structures,
            )
            cross_table_check_count = len(cross_table_findings)  # 发现的问题数即为校验点数的近似
            all_findings.extend(cross_table_findings)

            # ── 现金流量表补充资料 vs 利润表/现金流量表 跨报表校验 ──
            cashflow_supp_findings = self.reconciliation.check_cashflow_supplement_consistency(
                session.statement_items, session.note_tables, table_structures,
            )
            cross_table_check_count += len(cashflow_supp_findings)
            all_findings.extend(cashflow_supp_findings)

            # ── 应交所得税本期增加 vs 当期所得税费用 ──
            income_tax_findings = self.reconciliation.check_income_tax_consistency(
                session.note_tables,
            )
            cross_table_check_count += len(income_tax_findings)
            all_findings.extend(income_tax_findings)

            # ── 权益法投资损益跨科目交叉核对 ──
            equity_income_findings = self.reconciliation.check_equity_method_income_consistency(
                session.statement_items, session.note_tables, table_structures,
            )
            cross_table_check_count += len(equity_income_findings)
            all_findings.extend(equity_income_findings)

            # ── 受限资产交叉披露验证（LLM 辅助）──
            try:
                restricted_findings = await self.reconciliation.check_restricted_asset_disclosure(
                    session.note_tables, session.note_sections, oai,
                )
                cross_table_check_count += len(restricted_findings)
                all_findings.extend(restricted_findings)
            except Exception as e:
                logger.warning("受限资产交叉披露验证失败: %s", e)

        # 变动分析：1级报表科目 + 2级附注明细行
        changes = self.calculate_changes(session.statement_items)
        abnormal = self.flag_abnormal_changes(changes, config.change_threshold)
        threshold_pct = int(config.change_threshold * 100)

        # 排除不需要变动分析的科目
        # 1. 未分配利润等权益类科目（变动由利润表决定，不属于异常变动）
        # 2. 所有者权益变动表的结构行（如"一、上年年末余额"等）
        # 3. 利润表中由其他科目计算得出的汇总行（如营业利润、利润总额、净利润等）
        #    只要直接科目的变动有合理解释，汇总行的变动自然可解释
        CHANGE_EXCLUDE_KEYWORDS = [
            "未分配利润", "盈余公积", "实收资本", "股本",
            "上年年末余额", "本年年初余额", "本年增减变动", "本年年末余额",
            "年初余额", "年末余额", "期初余额", "期末余额",
            "本期增减", "本期变动", "综合收益总额",
        ]
        # 利润表汇总行（由其他直接科目加减计算得出）
        COMPUTED_ROW_NAMES = [
            "营业利润", "利润总额", "净利润",
            "归属于母公司所有者的净利润", "归属于母公司股东的净利润",
            "少数股东损益",
            "归属于母公司所有者的综合收益总额", "归属于母公司股东的综合收益总额",
            "归属于少数股东的综合收益总额",
            # 利润表拆分项（由净利润拆分，非独立科目）
            "持续经营净利润", "终止经营净利润",
            # 资产负债表汇总行
            "流动资产合计", "非流动资产合计", "资产总计", "资产合计",
            "流动负债合计", "非流动负债合计", "负债合计",
            "所有者权益合计", "股东权益合计",
            "负债和所有者权益总计", "负债和股东权益总计",
            "归属于母公司所有者权益合计", "归属于母公司股东权益合计",
            # 现金流量表汇总行/小计行
            "经营活动现金流入小计", "经营活动现金流出小计", "经营活动产生的现金流量净额",
            "投资活动现金流入小计", "投资活动现金流出小计", "投资活动产生的现金流量净额",
            "筹资活动现金流入小计", "筹资活动现金流出小计", "筹资活动产生的现金流量净额",
            "现金及现金等价物净增加额", "期末现金及现金等价物余额", "期初现金及现金等价物余额",
            "汇率变动对现金及现金等价物的影响",
        ]
        def _is_computed_row(name: str) -> bool:
            """判断是否为计算得出的汇总行，兼容带序号前缀（如'1.持续经营净利润'）。"""
            # 去掉数字序号前缀：1. 2. (1) (2) 等
            import re
            cleaned = re.sub(r'^[\d]+[.、]\s*', '', name)
            cleaned = re.sub(r'^[（(][\d]+[）)]\s*', '', cleaned)
            return any(cleaned.startswith(cn) for cn in COMPUTED_ROW_NAMES)

        abnormal = [
            chg for chg in abnormal
            if not any(kw in chg.account_name for kw in CHANGE_EXCLUDE_KEYWORDS)
            and not _is_computed_row(chg.account_name)
        ]

        # 构建 account_name → note_table_ids 映射
        acct_note_map: Dict[str, List[str]] = {}
        if session.matching_map:
            item_map_tmp = {i.id: i for i in session.statement_items}
            for entry in session.matching_map.entries:
                itm = item_map_tmp.get(entry.statement_item_id)
                if itm and entry.note_table_ids:
                    acct_note_map.setdefault(itm.account_name, []).extend(entry.note_table_ids)

        note_map_tmp = {n.id: n for n in session.note_tables}
        change_findings: List[ReportReviewFinding] = []
        detail_analyzed_accounts: set = set()  # 已通过明细分析的1级科目
        detail_change_count = 0  # 明细行变动分析数
        detail_abnormal_count = 0  # 明细行超阈值数

        for chg in abnormal:
            note_ids = acct_note_map.get(chg.account_name, [])
            detail_rows_found = False

            # 尝试从附注表格中提取明细行变动
            for nid in note_ids:
                note = note_map_tmp.get(nid)
                ts = table_structures.get(nid)
                if not note or not ts:
                    continue

                # 找到 opening_balance 和 closing_balance 列
                opening_col = None
                closing_col = None
                for col in ts.columns:
                    if col.semantic == "opening_balance" and opening_col is None:
                        opening_col = col.col_index
                    elif col.semantic == "closing_balance" and closing_col is None:
                        closing_col = col.col_index
                if opening_col is None or closing_col is None:
                    continue

                # 遍历 data 行（非 total/subtotal/sub_item_header）
                for row_s in ts.rows:
                    if row_s.role not in ("data",):
                        continue
                    label = row_s.label.strip() if row_s.label else ""
                    if not label:
                        continue

                    opening_v = self.reconciliation._get_row_col_value(note, row_s.row_index, opening_col)
                    closing_v = self.reconciliation._get_row_col_value(note, row_s.row_index, closing_col)
                    if opening_v is None or closing_v is None:
                        continue
                    if abs(opening_v) < 0.01 and abs(closing_v) < 0.01:
                        continue

                    detail_change_count += 1
                    change_amt = closing_v - opening_v
                    change_pct_val = (change_amt / abs(opening_v)) if abs(opening_v) > 0.01 else None

                    if change_pct_val is not None and abs(change_pct_val) > config.change_threshold:
                        detail_abnormal_count += 1
                        detail_rows_found = True
                        pct_str = f"{change_pct_val * 100:.1f}%"
                        # 位置：附注-科目-表格名称-具体行
                        loc = f"附注-{chg.account_name}-{note.section_title}-第{row_s.row_index + 1}行'{label}'"
                        change_findings.append(ReportReviewFinding(
                            id=str(uuid.uuid4())[:8],
                            category=ReportReviewFindingCategory.CHANGE_ABNORMAL,
                            risk_level=RiskLevel.MEDIUM if abs(change_pct_val) > 1.0 else RiskLevel.LOW,
                            account_name=chg.account_name,
                            location=loc,
                            description=f"明细项'{label}'变动 {pct_str}（期初 {opening_v:,.2f} → 期末 {closing_v:,.2f}，变动 {change_amt:,.2f}），超过阈值 {threshold_pct}%",
                            suggestion=f"请关注'{label}'大幅变动的原因，核实变动合理性",
                            statement_amount=opening_v,
                            note_amount=closing_v,
                            difference=round(change_amt, 2),
                            analysis_reasoning=f"变动率 {pct_str} 超过阈值 {threshold_pct}%",
                            note_table_ids=[nid],
                            confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                            status=FindingStatus.OPEN,
                        ))

            if detail_rows_found:
                detail_analyzed_accounts.add(chg.account_name)
            else:
                # 没有明细行可分析，对1级科目本身生成 finding
                if chg.change_percentage is not None:
                    pct_str = f"{chg.change_percentage * 100:.1f}%"
                    # 位置：尝试关联附注表格名称
                    nids = acct_note_map.get(chg.account_name, [])
                    if nids:
                        note_names = [note_map_tmp[nid].section_title for nid in nids if nid in note_map_tmp]
                        loc = f"附注-{chg.account_name}-{'、'.join(note_names[:2])}"
                    else:
                        loc = f"报表-{chg.account_name}"
                    change_findings.append(ReportReviewFinding(
                        id=str(uuid.uuid4())[:8],
                        category=ReportReviewFindingCategory.CHANGE_ABNORMAL,
                        risk_level=RiskLevel.MEDIUM if abs(chg.change_percentage) > 1.0 else RiskLevel.LOW,
                        account_name=chg.account_name,
                        location=loc,
                        description=f"'{chg.account_name}'整体变动 {pct_str}（期初 {chg.opening_balance:,.2f} → 期末 {chg.closing_balance:,.2f}，变动 {chg.change_amount:,.2f}），超过阈值 {threshold_pct}%",
                        suggestion=f"请关注'{chg.account_name}'大幅变动的原因，核实变动合理性",
                        statement_amount=chg.opening_balance,
                        note_amount=chg.closing_balance,
                        difference=round(chg.change_amount, 2),
                        analysis_reasoning=f"变动率 {pct_str} 超过阈值 {threshold_pct}%",
                        note_table_ids=nids,
                        confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
                        status=FindingStatus.OPEN,
                    ))

        all_findings.extend(change_findings)

        change_finding_count = len(change_findings)
        recon_finding_count = len(all_findings) - change_finding_count

        # 统计报表中有数据的科目数（排除余额为0的科目）
        items_with_data = sum(
            1 for item in session.statement_items
            if (item.closing_balance is not None and item.closing_balance != 0)
            or (item.opening_balance is not None and item.opening_balance != 0)
        )

        # 构建数值校验详情
        recon_details = []
        if amount_check_count > 0:
            match_str = "全部相符" if amount_match_count == amount_check_count else f"相符 {amount_match_count} 个，不符 {amount_check_count - amount_match_count} 个"
            recon_details.append(f"报表中有数据的科目 {items_with_data} 个，与附注共校验 {amount_check_count} 个科目，{match_str}")
            if llm_reanalyzed_count > 0:
                if llm_fixed_count > 0:
                    recon_details.append(f"LLM 二次校验：重新分析 {llm_reanalyzed_count} 个表格，修正 {llm_fixed_count} 个结构识别错误")
                else:
                    recon_details.append(f"LLM 二次校验：重新分析 {llm_reanalyzed_count} 个表格，结构确认无误")
        if integrity_check_count > 0:
            if integrity_match_count == integrity_check_count:
                recon_details.append(f"表内纵向加总校验：共校验 {integrity_check_count} 个表格，全部相符")
            else:
                recon_details.append(f"表内纵向加总校验：共校验 {integrity_check_count} 个表格，相符 {integrity_match_count} 个，不符 {integrity_check_count - integrity_match_count} 个")
        if formula_check_count > 0:
            if formula_match_count == formula_check_count:
                recon_details.append(f"余额变动公式校验：共校验 {formula_check_count} 个表格，全部相符")
            else:
                recon_details.append(f"余额变动公式校验：共校验 {formula_check_count} 个表格，相符 {formula_match_count} 个，不符 {formula_check_count - formula_match_count} 个")
        if sub_item_check_count > 0:
            if sub_item_match_count == sub_item_check_count:
                recon_details.append(f"其中项明细校验：共校验 {sub_item_check_count} 个表格，全部相符")
            else:
                recon_details.append(f"其中项明细校验：共校验 {sub_item_check_count} 个表格，相符 {sub_item_match_count} 个，不符 {sub_item_check_count - sub_item_match_count} 个")
        if wide_table_check_count > 0:
            if wide_table_match_count == wide_table_check_count:
                recon_details.append(f"宽表横向公式校验（LLM辅助）：共校验 {wide_table_check_count} 个表格，全部相符")
            else:
                recon_details.append(f"宽表横向公式校验（LLM辅助）：共校验 {wide_table_check_count} 个表格，相符 {wide_table_match_count} 个，不符 {wide_table_check_count - wide_table_match_count} 个")
        if cross_table_check_count > 0:
            recon_details.append(f"跨表交叉核对：发现 {cross_table_check_count} 个不一致")
        elif session.matching_map:
            recon_details.append("跨表交叉核对：未发现不一致")
        if len(abnormal) > 0:
            # 变动分析详情
            level1_only = len(abnormal) - len(detail_analyzed_accounts)
            parts = []
            parts.append(f"报表科目变动超过阈值 {threshold_pct}% 的共 {len(abnormal)} 个")
            if detail_analyzed_accounts:
                parts.append(f"其中 {len(detail_analyzed_accounts)} 个已深入附注明细行分析（共分析 {detail_change_count} 个明细行，超阈值 {detail_abnormal_count} 个）")
            if level1_only > 0:
                parts.append(f"{level1_only} 个仅在报表层级标记变动")
            recon_details.append("；".join(parts))

        for item in session.statement_items:
            item_findings = [f for f in all_findings if f.account_name == item.account_name]
            yield json.dumps({
                "status": "account_complete",
                "account_name": item.account_name,
                "findings_count": len(item_findings),
            }, ensure_ascii=False)
            await asyncio.sleep(0)

        yield json.dumps({
            "status": "phase_complete", "phase": "reconciliation",
            "message": f"数值校验完成，发现 {recon_finding_count} 个问题" + (f"，变动提示 {change_finding_count} 个" if change_finding_count > 0 else ""),
            "findings_count": recon_finding_count,
            "change_findings_count": change_finding_count,
            "details": recon_details,
        }, ensure_ascii=False)
        await asyncio.sleep(0)

        # 3. 正文复核（并发执行多项检查）
        yield json.dumps({"status": "phase", "phase": "body_review", "message": "正在复核审计报告正文..."}, ensure_ascii=False)
        await asyncio.sleep(0)
        report_body = "\n".join(
            p.get("text", "") for p in session.audit_report_content if p.get("text")
        ) if session.audit_report_content else ""
        if isinstance(report_body, str) and report_body:
            try:
                body_results = await asyncio.gather(
                    self.body_reviewer.check_entity_name_consistency(
                        report_body, session.statement_items, session.note_tables, oai
                    ),
                    self.body_reviewer.check_abbreviation_consistency(report_body, "", oai),
                    self.body_reviewer.check_template_compliance(
                        report_body, config.template_type, oai
                    ),
                    return_exceptions=True,
                )
                for r in body_results:
                    if isinstance(r, list):
                        all_findings.extend(r)
                    elif isinstance(r, Exception):
                        logger.warning("正文复核子任务失败: %s", r)
            except Exception as e:
                logger.warning("正文复核失败: %s", e)

        body_finding_count = len(all_findings) - recon_finding_count - change_finding_count
        body_details = []
        body_content_len = len(report_body) if isinstance(report_body, str) else 0
        if body_content_len > 0:
            body_details.append(f"审计报告正文共 {body_content_len} 字")
            body_details.append("已检查：主体名称一致性、简称使用规范性、模板合规性")
        else:
            body_details.append("未检测到审计报告正文内容，跳过正文复核")
        yield json.dumps({
            "status": "phase_complete", "phase": "body_review",
            "message": f"正文复核完成，发现 {body_finding_count} 个问题",
            "findings_count": body_finding_count,
            "details": body_details,
        }, ensure_ascii=False)
        await asyncio.sleep(0)

        # 4. 附注内容复核（并发处理各章节，带进度反馈）
        yield json.dumps({"status": "phase", "phase": "note_review", "message": "正在复核附注内容..."}, ensure_ascii=False)
        await asyncio.sleep(0)
        total_sections = 0
        total_paragraphs = 0
        skipped_template_sections = 0
        try:
            # 从 session.note_sections 树中提取有正文内容的叙述性章节
            sections: List[NarrativeSection] = []

            # 报表项目注释的关键词（这些章节下的内容是项目组自己写的，重点复核）
            REPORT_ITEM_KEYWORDS = ["报表项目注释", "报表项目", "财务报表项目"]
            # 模板化章节类型（内容来自模板，表达质量不需要重点复核）
            TEMPLATE_SECTION_TYPES = {"basic_info", "accounting_policy", "tax"}

            def _is_report_item_parent(title: str) -> bool:
                return any(kw in title for kw in REPORT_ITEM_KEYWORDS)

            def _flatten_note_sections(node_list: List[NoteSection], parent_title: str = "", under_report_item: bool = False):
                """递归遍历附注层级树，将含正文段落的节点转为 NarrativeSection。
                under_report_item: 是否在"报表项目注释"节点下（项目组自写内容）
                """
                for node in node_list:
                    is_ri = under_report_item or _is_report_item_parent(node.title)
                    if node.content_paragraphs:
                        content = "\n".join(node.content_paragraphs)
                        section_type = self.note_reviewer._classify_section(node.title)
                        # 如果在报表项目注释下，标记为 report_item_note
                        if is_ri and section_type == "other":
                            section_type = "report_item_note"
                        sections.append(NarrativeSection(
                            id=node.id,
                            section_type=section_type,
                            title=node.title,
                            content=content,
                            source_location=f"附注-{parent_title + '/' if parent_title else ''}{node.title}",
                        ))
                    if node.children:
                        _flatten_note_sections(node.children, node.title, is_ri)

            if session.note_sections:
                _flatten_note_sections(session.note_sections)
            else:
                # 降级：如果 note_sections 为空，尝试从 note_tables 标题拼接
                notes_text = "\n".join(
                    f"{n.section_title}\n" for n in session.note_tables if n.section_title
                )
                sections = self.note_reviewer.extract_narrative_sections(notes_text)

            total_sections = len(sections)
            total_paragraphs = sum(len(s.content.split("\n")) for s in sections)

            if total_sections > 0:
                yield json.dumps({
                    "status": "phase_progress", "phase": "note_review",
                    "message": f"共 {total_sections} 个叙述性章节（{total_paragraphs} 个段落）待复核",
                }, ensure_ascii=False)
                await asyncio.sleep(0)

            async def _review_section(section):
                results = []
                try:
                    # 模板化章节（会计政策、基本情况、税项）跳过表达质量检查
                    # 这些内容来自模板，与模板相同或大体相同不需要作为问题
                    if section.section_type in TEMPLATE_SECTION_TYPES:
                        nonlocal skipped_template_sections
                        skipped_template_sections += 1
                        # 仅对会计政策做模板比对（检查是否偏离模板）
                        if section.section_type == "accounting_policy":
                            policy_findings = await self.note_reviewer.check_policy_template_compliance(
                                section, config.template_type, oai
                            )
                            results.extend(policy_findings)
                        return results

                    # 报表项目注释及其他项目组自写内容：重点复核表达质量
                    expr_findings = await self.note_reviewer.check_expression_quality(section, oai)
                    results.extend(expr_findings)
                except Exception as e:
                    logger.warning("附注章节复核失败 %s: %s", section.title, e)
                return results

            if sections:
                section_results = await asyncio.gather(
                    *[_review_section(s) for s in sections],
                    return_exceptions=True,
                )
                # 收集数值校验阶段已覆盖的科目名（去重：避免附注复核重复报告同一科目的问题）
                recon_covered_accounts: set = set()
                for f in all_findings:
                    if f.category in (
                        ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                        ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    ):
                        # 清洗科目名：去除编号、标点、空白
                        clean = re.sub(r'[\s\d（()）、.．一二三四五六七八九十]+', '', f.account_name)
                        if clean:
                            recon_covered_accounts.add(clean)

                def _is_recon_covered(acct_name: str) -> bool:
                    """检查附注复核的科目是否已被数值校验覆盖。"""
                    clean = re.sub(r'[\s\d（()）、.．一二三四五六七八九十]+', '', acct_name)
                    if not clean:
                        return False
                    for covered in recon_covered_accounts:
                        if clean in covered or covered in clean:
                            return True
                    return False

                for r in section_results:
                    if isinstance(r, list):
                        for f in r:
                            if _is_recon_covered(f.account_name):
                                logger.info("附注复核去重：跳过 '%s'（数值校验已覆盖）", f.account_name)
                                continue
                            all_findings.append(f)

                yield json.dumps({
                    "status": "phase_progress", "phase": "note_review",
                    "message": f"附注内容复核完成（{total_sections}/{total_sections}）",
                }, ensure_ascii=False)
                await asyncio.sleep(0)
        except Exception as e:
            logger.warning("附注内容复核失败: %s", e)

        pre_text_count = len(all_findings)
        note_finding_count = pre_text_count - recon_finding_count - change_finding_count - body_finding_count
        note_details = []
        if total_sections > 0:
            report_item_count = sum(1 for s in sections if s.section_type == "report_item_note")
            template_count = sum(1 for s in sections if s.section_type in TEMPLATE_SECTION_TYPES)
            other_count = total_sections - report_item_count - template_count
            note_details.append(f"共提取 {total_sections} 个叙述性章节（{total_paragraphs} 个正文段落）")
            review_parts = []
            if report_item_count > 0:
                review_parts.append(f"报表项目注释 {report_item_count} 个（重点复核）")
            if other_count > 0:
                review_parts.append(f"其他章节 {other_count} 个")
            if template_count > 0:
                review_parts.append(f"模板化章节 {template_count} 个（跳过表达检查）")
            note_details.append(f"复核范围：{', '.join(review_parts)}")
            # 统计章节类型分布
            type_counts: Dict[str, int] = {}
            for s in sections:
                type_counts[s.section_type] = type_counts.get(s.section_type, 0) + 1
            type_labels = {
                "accounting_policy": "会计政策",
                "basic_info": "基本情况",
                "tax": "税项",
                "related_party": "关联方",
                "report_item_note": "报表项目注释",
                "other": "其他",
            }
            type_parts = [f"{type_labels.get(k, k)} {v} 个" for k, v in type_counts.items()]
            note_details.append(f"章节分布：{', '.join(type_parts)}")
        else:
            note_details.append("未提取到附注叙述性章节内容")
        unique_accounts = len(set(n.account_name for n in session.note_tables))
        note_details.append(f"附注表格共 {len(session.note_tables)} 个，涉及 {unique_accounts} 个报表科目")
        # 表内数值校验关系汇总
        table_check_lines = []
        if integrity_check_count > 0:
            status = "全部相符" if integrity_match_count == integrity_check_count else f"相符 {integrity_match_count} 个，不符 {integrity_check_count - integrity_match_count} 个"
            table_check_lines.append(f"涉及小计/合计纵向加总校验的表格 {integrity_check_count} 个，{status}")
        if formula_check_count > 0:
            status = "全部相符" if formula_match_count == formula_check_count else f"相符 {formula_match_count} 个，不符 {formula_check_count - formula_match_count} 个"
            table_check_lines.append(f"涉及期初±增减变动=期末横向校验的表格 {formula_check_count} 个，{status}")
        if sub_item_check_count > 0:
            status = "全部相符" if sub_item_match_count == sub_item_check_count else f"相符 {sub_item_match_count} 个，不符 {sub_item_check_count - sub_item_match_count} 个"
            table_check_lines.append(f"涉及其中项明细校验的表格 {sub_item_check_count} 个，{status}")
        if wide_table_check_count > 0:
            status = "全部相符" if wide_table_match_count == wide_table_check_count else f"相符 {wide_table_match_count} 个，不符 {wide_table_check_count - wide_table_match_count} 个"
            table_check_lines.append(f"涉及宽表横向公式校验（LLM辅助）的表格 {wide_table_check_count} 个，{status}")
        # 统计无校验关系的表格（既无合计行也无余额变动也无其中项）
        no_check_count = sum(
            1 for n in session.note_tables
            if n.id in table_structures
            and not table_structures[n.id].total_row_indices
            and not table_structures[n.id].has_balance_formula
            and not any(r.role == "sub_item" for r in table_structures[n.id].rows)
        )
        if no_check_count > 0:
            table_check_lines.append(f"无数值校验关系的表格 {no_check_count} 个（仅含明细数据）")
        note_details.extend(table_check_lines)
        yield json.dumps({
            "status": "phase_complete", "phase": "note_review",
            "message": f"附注复核完成，发现 {note_finding_count} 个问题",
            "findings_count": note_finding_count,
            "details": note_details,
        }, ensure_ascii=False)
        await asyncio.sleep(0)

        # 5. 文本质量检查（并发执行）
        yield json.dumps({"status": "phase", "phase": "text_quality", "message": "正在检查文本质量..."}, ensure_ascii=False)
        await asyncio.sleep(0)
        try:
            # 拼接报告正文 + 附注叙述性内容，作为全文检查范围
            text_parts = []
            body_char_count = 0
            note_text_char_count = 0

            if isinstance(report_body, str) and report_body:
                text_parts.append(report_body)
                body_char_count = len(report_body)

            # 附注叙述性段落
            note_text_parts = []
            if session.note_sections:
                def _collect_paragraphs(nodes: list):
                    for node in nodes:
                        for p in node.content_paragraphs:
                            if p.strip():
                                note_text_parts.append(p)
                        if node.children:
                            _collect_paragraphs(node.children)
                _collect_paragraphs(session.note_sections)
            if note_text_parts:
                note_text = "\n".join(note_text_parts)
                text_parts.append(note_text)
                note_text_char_count = len(note_text)

            all_text = "\n\n".join(text_parts)

            if all_text.strip():
                quality_results = await asyncio.gather(
                    self.text_analyzer.analyze_punctuation(all_text, oai, body_char_count=body_char_count),
                    self.text_analyzer.analyze_typos(all_text, oai, body_char_count=body_char_count),
                    return_exceptions=True,
                )
                for r in quality_results:
                    if isinstance(r, list):
                        all_findings.extend(r)
                    elif isinstance(r, Exception):
                        logger.warning("文本质量子任务失败: %s", r)
        except Exception as e:
            logger.warning("文本质量检查失败: %s", e)

        text_finding_count = len(all_findings) - pre_text_count
        text_details = []
        checked_parts = []
        if body_char_count > 0:
            checked_parts.append(f"审计报告正文 {body_char_count} 字")
        if note_text_char_count > 0:
            checked_parts.append(f"附注叙述性内容 {note_text_char_count} 字")
        if checked_parts:
            text_details.append(f"检查范围：{'、'.join(checked_parts)}，合计 {body_char_count + note_text_char_count} 字")
            text_details.append("已检查：中英文标点混用、标点符号规范、错别字检测")
        else:
            text_details.append("未检测到正文或附注文本，跳过文本质量检查")
        yield json.dumps({
            "status": "phase_complete", "phase": "text_quality",
            "message": f"文本质量检查完成，发现 {text_finding_count} 个问题",
            "findings_count": text_finding_count,
            "details": text_details,
        }, ensure_ascii=False)
        await asyncio.sleep(0)

        # ── 去重：按 (category, account_name, location) 去除重复 finding ──
        seen_keys: set = set()
        deduped_findings: List[ReportReviewFinding] = []
        for f in all_findings:
            key = (f.category, f.account_name, f.location)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_findings.append(f)
        if len(deduped_findings) < len(all_findings):
            logger.info("去重：%d 个 finding 去重后剩余 %d 个", len(all_findings), len(deduped_findings))
        all_findings = deduped_findings

        # 确保所有 Finding 为 pending_confirmation
        for f in all_findings:
            f.confirmation_status = FindingConfirmationStatus.PENDING_CONFIRMATION

        # 补充 note_table_ids：对于没有 note_table_ids 的 finding，从 matching_map 反查
        if session.matching_map:
            # 构建 account_name → note_table_ids 映射
            item_map = {i.id: i for i in session.statement_items}
            acct_to_notes: Dict[str, List[str]] = {}
            for entry in session.matching_map.entries:
                item = item_map.get(entry.statement_item_id)
                if item and entry.note_table_ids:
                    acct_to_notes.setdefault(item.account_name, []).extend(entry.note_table_ids)
            for f in all_findings:
                if not f.note_table_ids and f.account_name in acct_to_notes:
                    f.note_table_ids = list(dict.fromkeys(acct_to_notes[f.account_name]))  # 去重保序

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
    ) -> List[ChangeAnalysis]:
        """标记超阈值科目，返回超阈值的 ChangeAnalysis 列表。"""
        abnormal = []
        for c in changes:
            if c.change_percentage is not None and abs(c.change_percentage) > threshold:
                c.exceeds_threshold = True
                abnormal.append(c)
        return abnormal

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
