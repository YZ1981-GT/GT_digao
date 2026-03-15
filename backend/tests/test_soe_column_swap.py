"""测试国企报表期末/期初列映射是否正确。

实际国企报表 Excel 结构（从截图确认）：
  行1: 合并及公司资产负债表
  行2: 2025年12月31日
  行3: 编制单位：xxx                          金额单位：元
  行4:                | 期末余额(C4:D4合并) | 期初余额(E4:F4合并)
  行5: 项 目 | 附注  | 合并 | 公司 | 合并 | 公司
  行6: 流动资产：
  行7: 货币资金 | 八、1 | 172,056.52 |  | 225,611.66 |

关键问题：
  "项目"在行5，"期末余额"/"期初余额"在行4（上方）。
  _detect_header_rows 必须向上扫描把行4也包含进表头。
"""
import pytest
from app.models.audit_schemas import (
    CellData, ExcelParseResult, SheetData, StatementType,
)
from app.services.report_parser import ReportParser


@pytest.fixture
def parser():
    return ReportParser()


class TestSOEColumnMapping:
    """测试国企合并报表的列映射。"""

    def test_detect_header_rows_upward_scan(self, parser):
        """行4=期末/期初，行5=项目/合并/公司 → 表头应包含行4和行5。"""
        all_rows = [
            # idx=0 (Excel row 1): 标题
            ['合并及公司资产负债表', None, None, None, None, None],
            # idx=1 (Excel row 2): 日期
            ['2025年12月31日', None, None, None, None, None],
            # idx=2 (Excel row 3): 编制单位
            ['编制单位：xxx', None, None, None, None, '金额单位：元'],
            # idx=3 (Excel row 4): 期末/期初（第一列为空）
            [None, None, '期末余额', None, '期初余额', None],
            # idx=4 (Excel row 5): 项目/合并/公司
            ['项 目', '附注', '合并', '公司', '合并', '公司'],
            # idx=5 (Excel row 6): 流动资产
            ['流动资产：', None, None, None, None, None],
            # idx=6 (Excel row 7): 货币资金
            ['货币资金', '八、1', 172056.52, None, 225611.66, None],
        ]
        sorted_excel_rows = [1, 2, 3, 4, 5, 6, 7]
        merged_ranges = ['C4:D4', 'E4:F4']

        header_start, header_end = parser._detect_header_rows(
            all_rows, merged_ranges, sorted_excel_rows
        )

        # 表头应从 idx=3（行4）到 idx=4（行5）
        assert header_start == 3, f"header_start should be 3 (row 4), got {header_start}"
        assert header_end == 4, f"header_end should be 4 (row 5), got {header_end}"

    def test_full_soe_extract_sheets(self, parser):
        """端到端测试：模拟实际国企报表 Excel → extract_sheets → extract_statement_items。"""
        cells = [
            # 行1: 标题
            CellData(row=1, col=1, value='合并及公司资产负债表'),
            # 行2: 日期
            CellData(row=2, col=1, value='2025年12月31日'),
            # 行3: 编制单位
            CellData(row=3, col=1, value='编制单位：xxx'),
            CellData(row=3, col=6, value='金额单位：元'),
            # 行4: 期末/期初（A4为空，C4=期末余额，E4=期初余额）
            CellData(row=4, col=3, value='期末余额'),
            CellData(row=4, col=5, value='期初余额'),
            # 行5: 项目/附注/合并/公司
            CellData(row=5, col=1, value='项 目'),
            CellData(row=5, col=2, value='附注'),
            CellData(row=5, col=3, value='合并'),
            CellData(row=5, col=4, value='公司'),
            CellData(row=5, col=5, value='合并'),
            CellData(row=5, col=6, value='公司'),
            # 行6: 流动资产
            CellData(row=6, col=1, value='流动资产：'),
            # 行7: 货币资金
            CellData(row=7, col=1, value='货币资金'),
            CellData(row=7, col=2, value='八、1'),
            CellData(row=7, col=3, value=172056.52),
            CellData(row=7, col=5, value=225611.66),
            # 行8: 应收票据
            CellData(row=8, col=1, value='应收票据'),
            CellData(row=8, col=2, value='八、2'),
            CellData(row=8, col=3, value=1392177.19),
            CellData(row=8, col=5, value=773499.21),
        ]
        merged_ranges = ['C4:D4', 'E4:F4']

        excel_result = ExcelParseResult(
            sheets=[SheetData(
                name='资产负债表(企业01表)',
                cells=cells,
                merged_ranges=merged_ranges,
            )],
            sheet_names=['资产负债表(企业01表)'],
        )

        sheets = parser.extract_sheets(excel_result)
        assert len(sheets) == 1
        sheet = sheets[0]

        # 应检测为合并报表
        assert sheet.is_consolidated is True, \
            f"Should be consolidated, column_map={sheet.column_map}"
        assert sheet.column_map is not None

        # 验证 column_map 正确
        assert sheet.column_map.get('closing_consolidated') == 2, \
            f"closing_consolidated should be 2, got {sheet.column_map.get('closing_consolidated')}"
        assert sheet.column_map.get('opening_consolidated') == 4, \
            f"opening_consolidated should be 4, got {sheet.column_map.get('opening_consolidated')}"

        # 提取科目
        items = parser.extract_statement_items(sheet)
        huobi = [i for i in items if '货币资金' in i.account_name]
        assert len(huobi) == 1
        item = huobi[0]

        # 关键断言：期末=172056.52，期初=225611.66
        assert item.closing_balance == 172056.52, \
            f"货币资金 closing should be 172056.52, got {item.closing_balance}"
        assert item.opening_balance == 225611.66, \
            f"货币资金 opening should be 225611.66, got {item.opening_balance}"

        # 验证应收票据
        yingshou = [i for i in items if '应收票据' in i.account_name]
        assert len(yingshou) == 1
        assert yingshou[0].closing_balance == 1392177.19
        assert yingshou[0].opening_balance == 773499.21

    def test_soe_reversed_column_order_in_excel(self, parser):
        """测试期初在前、期末在后的 Excel 结构。"""
        cells = [
            CellData(row=4, col=3, value='期初余额'),
            CellData(row=4, col=5, value='期末余额'),
            CellData(row=5, col=1, value='项 目'),
            CellData(row=5, col=2, value='附注'),
            CellData(row=5, col=3, value='合并'),
            CellData(row=5, col=4, value='公司'),
            CellData(row=5, col=5, value='合并'),
            CellData(row=5, col=6, value='公司'),
            CellData(row=6, col=1, value='货币资金'),
            CellData(row=6, col=3, value=225611.66),
            CellData(row=6, col=5, value=172056.52),
        ]
        merged_ranges = ['C4:D4', 'E4:F4']

        excel_result = ExcelParseResult(
            sheets=[SheetData(
                name='资产负债表',
                cells=cells,
                merged_ranges=merged_ranges,
            )],
            sheet_names=['资产负债表'],
        )

        sheets = parser.extract_sheets(excel_result)
        sheet = sheets[0]
        items = parser.extract_statement_items(sheet)
        huobi = [i for i in items if '货币资金' in i.account_name]
        assert len(huobi) == 1
        # 期初在C列=225611.66，期末在E列=172056.52
        assert huobi[0].opening_balance == 225611.66, \
            f"opening should be 225611.66, got {huobi[0].opening_balance}"
        assert huobi[0].closing_balance == 172056.52, \
            f"closing should be 172056.52, got {huobi[0].closing_balance}"

    def test_detect_consolidated_columns_with_span2_groups(self, parser):
        """模拟2行表头：行4=期末/期初，行5=合并/公司。"""
        header_rows = [
            ['', '', '期末余额', '', '期初余额', ''],
            ['项 目', '附注', '合并', '公司', '合并', '公司'],
        ]
        merged_ranges = ['C4:D4', 'E4:F4']
        header_excel_rows = [4, 5]

        is_consolidated, column_map, data_col_end = parser._detect_consolidated_columns(
            header_rows, merged_ranges, 6, header_excel_rows
        )

        assert is_consolidated is True
        assert column_map.get('closing_consolidated') == 2
        assert column_map.get('closing_company') == 3
        assert column_map.get('opening_consolidated') == 4
        assert column_map.get('opening_company') == 5

    def test_existing_format_still_works(self, parser):
        """确保原有格式（项目和期末在同一行）仍然正确。"""
        cells = [
            CellData(row=3, col=1, value='项目'),
            CellData(row=3, col=2, value='附注'),
            CellData(row=3, col=3, value='期末余额'),
            CellData(row=3, col=5, value='期初余额'),
            CellData(row=4, col=3, value='合并'),
            CellData(row=4, col=4, value='公司'),
            CellData(row=4, col=5, value='合并'),
            CellData(row=4, col=6, value='公司'),
            CellData(row=5, col=1, value='货币资金'),
            CellData(row=5, col=3, value=100000.0),
            CellData(row=5, col=5, value=80000.0),
        ]
        merged_ranges = ['C3:D3', 'E3:F3']

        excel_result = ExcelParseResult(
            sheets=[SheetData(
                name='资产负债表',
                cells=cells,
                merged_ranges=merged_ranges,
            )],
            sheet_names=['资产负债表'],
        )

        sheets = parser.extract_sheets(excel_result)
        sheet = sheets[0]
        assert sheet.is_consolidated is True

        items = parser.extract_statement_items(sheet)
        huobi = [i for i in items if '货币资金' in i.account_name]
        assert len(huobi) == 1
        assert huobi[0].closing_balance == 100000.0
        assert huobi[0].opening_balance == 80000.0

    def test_non_consolidated_simple_sheet(self, parser):
        """非合并报表（无合并/公司列）仍然正确。"""
        cells = [
            CellData(row=1, col=1, value='项目'),
            CellData(row=1, col=2, value='期末余额'),
            CellData(row=1, col=3, value='期初余额'),
            CellData(row=2, col=1, value='货币资金'),
            CellData(row=2, col=2, value=100000.0),
            CellData(row=2, col=3, value=80000.0),
        ]

        excel_result = ExcelParseResult(
            sheets=[SheetData(
                name='资产负债表',
                cells=cells,
                merged_ranges=[],
            )],
            sheet_names=['资产负债表'],
        )

        sheets = parser.extract_sheets(excel_result)
        sheet = sheets[0]
        assert sheet.is_consolidated is False

        items = parser.extract_statement_items(sheet)
        huobi = [i for i in items if '货币资金' in i.account_name]
        assert len(huobi) == 1
        assert huobi[0].closing_balance == 100000.0
        assert huobi[0].opening_balance == 80000.0
