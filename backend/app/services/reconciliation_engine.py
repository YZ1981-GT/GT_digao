"""勾稽校验引擎（本地规则为主）。

基于 Table_Structure_Analyzer 输出的结构化信息执行确定性数值校验：
- 科目名称模糊匹配构建对照映射
- 金额一致性校验（报表 vs 附注合计值）
- 附注表格内部勾稽（横纵加总）
- 余额变动公式校验（期初+增加-减少=期末）
- 其中项校验（子项之和 ≤ 父项）
"""
import logging
import uuid
from typing import Dict, List, Optional, Tuple

from ..models.audit_schemas import (
    FindingConfirmationStatus,
    FindingStatus,
    MatchingEntry,
    MatchingMap,
    NoteTable,
    ReportReviewFinding,
    ReportReviewFindingCategory,
    RiskLevel,
    StatementItem,
    TableStructure,
)

logger = logging.getLogger(__name__)

# 浮点容差
TOLERANCE = 0.01


def _safe_float(val) -> Optional[float]:
    """安全转换为浮点数。"""
    if val is None:
        return None
    try:
        v = float(val)
        return v
    except (ValueError, TypeError):
        return None


def _amounts_equal(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < TOLERANCE


class ReconciliationEngine:
    """勾稽校验引擎，所有数值校验为纯函数。"""

    # ─── 科目匹配 ───

    def build_matching_map(
        self,
        items: List[StatementItem],
        notes: List[NoteTable],
    ) -> MatchingMap:
        """基于标准科目映射模板构建对照映射，模板未命中时回退到模糊匹配。"""
        from .account_mapping_template import account_mapping_template

        entries: List[MatchingEntry] = []
        matched_note_ids: set = set()
        unmatched_items: List[str] = []

        for item in items:
            # 1) 优先使用模板映射
            template_notes: List[Tuple[str, float]] = []
            for note in notes:
                if account_mapping_template.match_note(
                    item.account_name, note.account_name, note.section_title
                ):
                    template_notes.append((note.id, 1.0))

            if template_notes:
                note_ids = [n[0] for n in template_notes[:3]]
                entries.append(MatchingEntry(
                    statement_item_id=item.id,
                    note_table_ids=note_ids,
                    match_confidence=1.0,
                ))
                matched_note_ids.update(note_ids)
                continue

            # 2) 回退到模糊匹配
            best_notes: List[Tuple[str, float]] = []
            for note in notes:
                score = self._match_score(item.account_name, note.account_name)
                if score >= 0.5:
                    best_notes.append((note.id, score))

            best_notes.sort(key=lambda x: x[1], reverse=True)

            if best_notes:
                note_ids = [n[0] for n in best_notes[:3]]
                confidence = best_notes[0][1]
                entries.append(MatchingEntry(
                    statement_item_id=item.id,
                    note_table_ids=note_ids,
                    match_confidence=confidence,
                ))
                matched_note_ids.update(note_ids)
            else:
                unmatched_items.append(item.id)

        unmatched_notes = [n.id for n in notes if n.id not in matched_note_ids]

        return MatchingMap(
            entries=entries,
            unmatched_items=unmatched_items,
            unmatched_notes=unmatched_notes,
        )

    # ─── 金额一致性校验 ───

    def check_amount_consistency(
        self,
        matching_map: MatchingMap,
        items: List[StatementItem],
        notes: List[NoteTable],
        table_structures: Dict[str, TableStructure],
    ) -> List[ReportReviewFinding]:
        """基于 TableStructure 定位附注合计值，与报表余额比对。"""
        findings: List[ReportReviewFinding] = []
        item_map = {i.id: i for i in items}
        note_map = {n.id: n for n in notes}

        for entry in matching_map.entries:
            item = item_map.get(entry.statement_item_id)
            if not item:
                continue

            for note_id in entry.note_table_ids:
                note = note_map.get(note_id)
                ts = table_structures.get(note_id)
                if not note or not ts:
                    continue

                # 获取附注合计值
                note_closing = self._get_cell_value(note, ts.closing_balance_cell)
                note_opening = self._get_cell_value(note, ts.opening_balance_cell)

                # 期末余额比对
                if item.closing_balance is not None and note_closing is not None:
                    if not _amounts_equal(item.closing_balance, note_closing):
                        diff = round(item.closing_balance - note_closing, 2)
                        findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                            account_name=item.account_name,
                            statement_amount=item.closing_balance,
                            note_amount=note_closing,
                            difference=diff,
                            location=f"附注-{item.account_name}-{note.section_title}-期末余额",
                            description=f"报表期末余额{item.closing_balance}与附注合计{note_closing}不一致，差异{diff}",
                            risk_level=self._assess_risk(abs(diff), item.closing_balance),
                            reasoning=f"校验公式: 报表期末余额({item.closing_balance}) - 附注合计({note_closing}) = {diff}",
                            note_table_ids=[note_id],
                        ))

                # 期初余额比对
                if item.opening_balance is not None and note_opening is not None:
                    if not _amounts_equal(item.opening_balance, note_opening):
                        diff = round(item.opening_balance - note_opening, 2)
                        findings.append(self._make_finding(
                            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,
                            account_name=item.account_name,
                            statement_amount=item.opening_balance,
                            note_amount=note_opening,
                            difference=diff,
                            location=f"附注-{item.account_name}-{note.section_title}-期初余额",
                            description=f"报表期初余额{item.opening_balance}与附注合计{note_opening}不一致，差异{diff}",
                            risk_level=self._assess_risk(abs(diff), item.opening_balance),
                            reasoning=f"校验公式: 报表期初余额({item.opening_balance}) - 附注合计({note_opening}) = {diff}",
                            note_table_ids=[note_id],
                        ))

        return findings

    # ─── 附注表格内部勾稽 ───

    def check_note_table_integrity(
        self,
        note_table: NoteTable,
        table_structure: TableStructure,
    ) -> List[ReportReviewFinding]:
        """基于 LLM 识别的合计行/列结构校验横纵加总。"""
        findings: List[ReportReviewFinding] = []

        # 纵向加总校验：数据行之和 == 合计行
        for total_idx in table_structure.total_row_indices:
            data_indices = self._get_data_rows_for_total(table_structure, total_idx)
            if not data_indices:
                continue

            for col in table_structure.columns:
                if col.semantic in ("label", "other"):
                    continue

                total_val = self._get_row_col_value(note_table, total_idx, col.col_index)
                if total_val is None:
                    continue

                data_sum = 0.0
                has_data = False
                for di in data_indices:
                    v = self._get_row_col_value(note_table, di, col.col_index)
                    if v is not None:
                        data_sum += v
                        has_data = True

                if has_data and not _amounts_equal(data_sum, total_val):
                    diff = round(data_sum - total_val, 2)
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=note_table.account_name,
                        statement_amount=total_val,
                        note_amount=data_sum,
                        difference=diff,
                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{total_idx + 1}行合计-列{col.col_index + 1}",
                        description=f"纵向加总不平：数据行合计{data_sum}，合计行{total_val}，差异{diff}",
                        risk_level=RiskLevel.MEDIUM,
                        reasoning=f"校验: sum(数据行)={data_sum}, 合计行={total_val}, 差异={diff}",
                        note_table_ids=[note_table.id],
                    ))

        return findings

    # ─── 余额变动公式校验 ───

    def check_balance_formula(
        self,
        note_table: NoteTable,
        table_structure: TableStructure,
    ) -> List[ReportReviewFinding]:
        """校验 期初+增加-减少=期末 余额变动公式。"""
        findings: List[ReportReviewFinding] = []
        if not table_structure.has_balance_formula:
            return findings

        col_map = {c.semantic: c.col_index for c in table_structure.columns}
        opening_col = col_map.get("opening_balance")
        closing_col = col_map.get("closing_balance")
        increase_col = col_map.get("current_increase")
        decrease_col = col_map.get("current_decrease")

        if opening_col is None or closing_col is None:
            return findings

        for row_struct in table_structure.rows:
            if row_struct.role in ("header",):
                continue

            opening = self._get_row_col_value(note_table, row_struct.row_index, opening_col)
            closing = self._get_row_col_value(note_table, row_struct.row_index, closing_col)
            increase = self._get_row_col_value(note_table, row_struct.row_index, increase_col) if increase_col is not None else 0.0
            decrease = self._get_row_col_value(note_table, row_struct.row_index, decrease_col) if decrease_col is not None else 0.0

            if opening is None or closing is None:
                continue
            increase = increase or 0.0
            decrease = decrease or 0.0

            expected = opening + increase - decrease
            if not _amounts_equal(expected, closing):
                diff = round(expected - closing, 2)
                findings.append(self._make_finding(
                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                    account_name=note_table.account_name,
                    location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_struct.row_index + 1}行'{row_struct.label}'",
                    description=f"余额变动公式不平：期初{opening}+增加{increase}-减少{decrease}={expected}，期末{closing}，差异{diff}",
                    difference=diff,
                    statement_amount=expected,
                    note_amount=closing,
                    risk_level=RiskLevel.MEDIUM,
                    reasoning=f"公式: {opening}+{increase}-{decrease}={expected}, 实际期末={closing}",
                    note_table_ids=[note_table.id],
                ))

        return findings

    # ─── 其中项校验 ───

    def check_sub_items(
        self,
        note_table: NoteTable,
        table_structure: TableStructure,
    ) -> List[ReportReviewFinding]:
        """验证各 sub_item 之和 ≤ 父项金额。"""
        findings: List[ReportReviewFinding] = []

        # 按 parent 分组
        parent_children: Dict[int, List[int]] = {}
        for row in table_structure.rows:
            if row.role == "sub_item" and row.parent_row_index is not None:
                parent_children.setdefault(row.parent_row_index, []).append(row.row_index)

        for parent_idx, child_indices in parent_children.items():
            for col in table_structure.columns:
                if col.semantic in ("label", "other"):
                    continue

                parent_val = self._get_row_col_value(note_table, parent_idx, col.col_index)
                if parent_val is None:
                    continue

                child_sum = 0.0
                has_child = False
                for ci in child_indices:
                    v = self._get_row_col_value(note_table, ci, col.col_index)
                    if v is not None:
                        child_sum += v
                        has_child = True

                if has_child and child_sum > parent_val + TOLERANCE:
                    diff = round(child_sum - parent_val, 2)
                    parent_label = ""
                    for r in table_structure.rows:
                        if r.row_index == parent_idx:
                            parent_label = r.label
                            break
                    findings.append(self._make_finding(
                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,
                        account_name=note_table.account_name,
                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{parent_idx + 1}行'{parent_label}'",
                        description=f"其中项之和{child_sum}超过父项{parent_val}，差异{diff}",
                        difference=diff,
                        statement_amount=parent_val,
                        note_amount=child_sum,
                        risk_level=RiskLevel.LOW,
                        reasoning=f"其中项校验: sum(子项)={child_sum} > 父项={parent_val}",
                        note_table_ids=[note_table.id],
                    ))

        return findings

    # ─── 统计汇总 ───

    def get_reconciliation_summary(
        self, findings: List[ReportReviewFinding]
    ) -> Dict[str, int]:
        """生成匹配/不匹配/未检查统计。"""
        matched = sum(1 for f in findings if f.difference is not None and abs(f.difference) < TOLERANCE)
        mismatched = sum(1 for f in findings if f.difference is not None and abs(f.difference) >= TOLERANCE)
        return {
            "matched": matched,
            "mismatched": mismatched,
            "unchecked": 0,
        }

    # ─── 内部工具 ───

    @staticmethod
    def _match_score(name1: str, name2: str) -> float:
        """科目名称匹配评分。"""
        if not name1 or not name2:
            return 0.0
        if name1 == name2:
            return 1.0
        if name1 in name2 or name2 in name1:
            return 0.8
        # Jaccard
        s1, s2 = set(name1), set(name2)
        inter = s1 & s2
        union = s1 | s2
        return len(inter) / len(union) if union else 0.0

    @staticmethod
    def _get_cell_value(note: NoteTable, cell_ref: Optional[str]) -> Optional[float]:
        """从 RxCy 格式引用获取单元格值。"""
        if not cell_ref:
            return None
        try:
            parts = cell_ref.upper().replace("R", "").split("C")
            row_idx = int(parts[0])
            col_idx = int(parts[1])
            if row_idx < len(note.rows) and col_idx < len(note.rows[row_idx]):
                return _safe_float(note.rows[row_idx][col_idx])
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def _get_row_col_value(note: NoteTable, row_idx: int, col_idx: int) -> Optional[float]:
        """获取指定行列的浮点值。"""
        try:
            if row_idx < len(note.rows) and col_idx < len(note.rows[row_idx]):
                return _safe_float(note.rows[row_idx][col_idx])
        except (IndexError, TypeError):
            pass
        return None

    def _get_data_rows_for_total(
        self, ts: TableStructure, total_idx: int
    ) -> List[int]:
        """获取某合计行对应的顶层数据行索引（排除其中项明细，避免重复计算）。"""
        data_rows = []
        for r in ts.rows:
            if r.row_index >= total_idx:
                break
            if r.role == "data":
                data_rows.append(r.row_index)
            # sub_item 不参与合计行加总（它们已包含在父项中）
        return data_rows

    @staticmethod
    def _assess_risk(abs_diff: float, base_amount: Optional[float]) -> RiskLevel:
        """基于差异金额评估风险等级。"""
        if base_amount and abs(base_amount) > 0:
            ratio = abs_diff / abs(base_amount)
            if ratio > 0.05:
                return RiskLevel.HIGH
            elif ratio > 0.01:
                return RiskLevel.MEDIUM
        if abs_diff > 10000:
            return RiskLevel.HIGH
        elif abs_diff > 100:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _make_finding(
        category: ReportReviewFindingCategory,
        account_name: str,
        location: str,
        description: str,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        statement_amount: Optional[float] = None,
        note_amount: Optional[float] = None,
        difference: Optional[float] = None,
        reasoning: str = "",
        note_table_ids: Optional[List[str]] = None,
    ) -> ReportReviewFinding:
        return ReportReviewFinding(
            id=str(uuid.uuid4())[:8],
            category=category,
            risk_level=risk_level,
            account_name=account_name,
            statement_amount=statement_amount,
            note_amount=note_amount,
            difference=difference,
            location=location,
            description=description,
            suggestion="请核实数据并修正",
            analysis_reasoning=reasoning,
            note_table_ids=note_table_ids or [],
            confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,
            status=FindingStatus.OPEN,
        )



# 模块级单例
reconciliation_engine = ReconciliationEngine()
