"""变动金额阈值过滤测试。

验证 flag_abnormal_changes 和明细行变动分析中的金额阈值过滤逻辑。
"""
import uuid
import pytest

from app.models.audit_schemas import (
    ChangeAnalysis,
    MatchingEntry,
    MatchingMap,
    NoteTable,
    ReportReviewConfig,
    ReportReviewFindingCategory,
    ReportTemplateType,
    StatementItem,
    StatementType,
    TableStructure,
    TableStructureColumn,
    TableStructureRow,
)
from app.services.report_review_engine import ReportReviewEngine

engine = ReportReviewEngine()


class TestFlagAbnormalChanges:
    """flag_abnormal_changes 金额阈值过滤测试。"""

    def _make_changes(self):
        """构造一组变动分析结果。"""
        return [
            ChangeAnalysis(
                statement_item_id="1", account_name="其他应收款",
                opening_balance=17170568.45, closing_balance=28547388.90,
                change_amount=11376820.45,  # ~1137万元
                change_percentage=0.663,  # 66.3%
            ),
            ChangeAnalysis(
                statement_item_id="2", account_name="货币资金",
                opening_balance=100000000, closing_balance=800000000,
                change_amount=700000000,  # 7亿 = 70000万元
                change_percentage=7.0,  # 700%
            ),
            ChangeAnalysis(
                statement_item_id="3", account_name="应收账款",
                opening_balance=50000000, closing_balance=70000000,
                change_amount=20000000,  # 2000万元
                change_percentage=0.4,  # 40%
            ),
        ]

    def test_no_amount_threshold(self):
        """不设金额阈值时，所有超比率阈值的科目都应报出。"""
        changes = self._make_changes()
        abnormal = engine.flag_abnormal_changes(changes, threshold=0.3, amount_threshold=0)
        assert len(abnormal) == 3

    def test_amount_threshold_filters_small_changes(self):
        """设金额阈值 55900万元 = 559000000元，变动金额 < 阈值的应被过滤。"""
        changes = self._make_changes()
        # 55900万元 = 559000000元
        abnormal = engine.flag_abnormal_changes(
            changes, threshold=0.3, amount_threshold=559000000,
        )
        # 其他应收款: 11376820 < 559000000 → 过滤
        # 货币资金: 700000000 > 559000000 → 保留
        # 应收账款: 20000000 < 559000000 → 过滤
        assert len(abnormal) == 1
        assert abnormal[0].account_name == "货币资金"

    def test_amount_threshold_100wan(self):
        """设金额阈值 100万元 = 1000000元。"""
        changes = self._make_changes()
        abnormal = engine.flag_abnormal_changes(
            changes, threshold=0.3, amount_threshold=1000000,
        )
        # 其他应收款: 11376820 > 1000000 → 保留
        # 货币资金: 700000000 > 1000000 → 保留
        # 应收账款: 20000000 > 1000000 → 保留
        assert len(abnormal) == 3

    def test_amount_threshold_exact_boundary(self):
        """变动金额恰好等于阈值时不应被过滤（只过滤严格小于的）。"""
        changes = [
            ChangeAnalysis(
                statement_item_id="1", account_name="测试科目",
                opening_balance=100, closing_balance=200,
                change_amount=100,
                change_percentage=1.0,
            ),
        ]
        abnormal = engine.flag_abnormal_changes(
            changes, threshold=0.3, amount_threshold=100,
        )
        # abs(100) < 100 is False → 不过滤
        assert len(abnormal) == 1
