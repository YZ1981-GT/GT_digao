"""测试国企单体利润表解析 - 排查"其他收益"提取为0的问题。

实际 Excel 结构（从截图确认）：
  Sheet名: 3-利润表（企业02表）
  行1: 利润表
  行2: （企业02表）
  行3: 编制单位：xxx    2024年度    金额单位：元
  行4: 项 目 | 附注 | 本期金额 | 上期金额
  行5: (空行或数据开始)
  ...
  行29: 加：其他收益 | 七、22 | 274,843.08 | 1,337.22
"""
import pytest
from app.models.audit_schemas import (
    CellData, ExcelParseResult, SheetData, StatementType,
)
from app.services.report_parser import ReportParser


@pytest.fixture
def parser():
    return ReportParser()


class TestSOEIncomeStatement:
    """测试国企单体利润表的科目提取。"""

    def test_single_entity_income_statement_basic(self, parser):
        """基本的单体利润表：项目/附注/本期金额/上期金额 四列结构。"""
        cells = [
            # 行1: 标题
            CellData(row=1, col=1, value='利润表'),
            # 行2: 副标题
            CellData(row=2, col=1, value='（企业02表）'),
            # 行3: 编制单位
            CellData(row=3, col=1, value='编制单位：xxx'),
            CellData(row=3, col=3, value='2024年度'),
            CellData(row=3, col=4, value='金额单位：元'),
            # 行4: 表头
            CellData(row=4, col=1, value='项 目'),
            CellData(row=4, col=2, value='附注'),
            CellData(row=4, col=3, value='本期金额'),
            CellData(row=4, col=4, value='上期金额'),
            # 行5: 营业收入
            CellData(row=5, col=1, value='一、营业收入'),
            CellData(row=5, col=2, value='七、1'),
            CellData(row=5, col=3, value=5000000.0),
            CellData(row=5, col=4, value=4500000.0),
            # 行6: 营业成本
            CellData(row=6, col=1, value='减：营业成本'),
            CellData(row=6, col=2, value='七、1'),
            CellData(row=6, col=3, value=3000000.0),
            CellData(row=6, col=4, value=2800000.0),
            # 行7: 其他收益
            CellData(row=7, col=1, value='加：其他收益'),
            CellData(row=7, col=2, value='七、22'),
            CellData(row=7, col=3, value=274843.08),
            CellData(row=7, col=4, value=1337.22),
        ]

        excel_result = ExcelParseResult(
            sheets=[SheetData(
                name='3-利润表（企业02表）',
                cells=cells,
                merged_ranges=[],
            )],
            sheet_names=['3-利润表（企业02表）'],
        )

        sheets = parser.extract_sheets(excel_result)
        assert len(sheets) == 1
        sheet = sheets[0]

        # 应识别为利润表
        assert sheet.statement_type == StatementType.INCOME_STATEMENT, \
            f"Should be income_statement, got {sheet.statement_type}"

        # 应为非合并报表
        assert sheet.is_consolidated is False, \
            f"Should NOT be consolidated, column_map={sheet.column_map}"

        # 表头应包含本期/上期
        print(f"headers={sheet.headers}")
        print(f"header_rows={sheet.header_rows}")
        print(f"raw_data first 3 rows={sheet.raw_data[:3]}")

        # 提取科目
        items = parser.extract_statement_items(sheet)
        print(f"All items: {[(i.account_name, i.closing_balance, i.opening_balance) for i in items]}")

        # 验证其他收益
        qita = [i for i in items if '其他收益' in i.account_name]
        assert len(qita) >= 1, f"Should find '其他收益', items={[i.account_name for i in items]}"
        item = qita[0]
        assert item.closing_balance == 274843.08, \
            f"其他收益 closing should be 274843.08, got {item.closing_balance}"
        assert item.opening_balance == 1337.22, \
            f"其他收益 opening should be 1337.22, got {item.opening_balance}"

    def test_single_entity_income_with_empty_row_after_header(self, parser):
        """表头后有空行的情况。"""
        cells = [
            # 行1: 标题
            CellData(row=1, col=1, value='利润表'),
            # 行2: 副标题
            CellData(row=2, col=1, value='（企业02表）'),
            # 行3: 编制单位
            CellData(row=3, col=1, value='编制单位：xxx'),
            # 行4: 表头
            CellData(row=4, col=1, value='项 目'),
            CellData(row=4, col=2, value='附注'),
            CellData(row=4, col=3, value='本期金额'),
            CellData(row=4, col=4, value='上期金额'),
            # 行5: 空行（无数据）
            # 行6: 营业收入
            CellData(row=6, col=1, value='一、营业收入'),
            CellData(row=6, col=3, value=5000000.0),
            CellData(row=6, col=4, value=4500000.0),
            # 行7: 其他收益
            CellData(row=7, col=1, value='加：其他收益'),
            CellData(row=7, col=2, value='七、22'),
            CellData(row=7, col=3, value=274843.08),
            CellData(row=7, col=4, value=1337.22),
        ]

        excel_result = ExcelParseResult(
            sheets=[SheetData(
                name='3-利润表（企业02表）',
                cells=cells,
                merged_ranges=[],
            )],
            sheet_names=['3-利润表（企业02表）'],
        )

        sheets = parser.extract_sheets(excel_result)
        sheet = sheets[0]
        items = parser.extract_statement_items(sheet)

        print(f"headers={sheet.headers}")
        print(f"raw_data={sheet.raw_data[:5]}")
        print(f"items={[(i.account_name, i.closing_balance, i.opening_balance) for i in items]}")

        qita = [i for i in items if '其他收益' in i.account_name]
        assert len(qita) >= 1
        assert qita[0].closing_balance == 274843.08
        assert qita[0].opening_balance == 1337.22
