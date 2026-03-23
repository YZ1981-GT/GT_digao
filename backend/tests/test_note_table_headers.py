"""测试附注表格多行表头检测和对齐逻辑。"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.report_parser import ReportParser


@pytest.fixture
def parser():
    return ReportParser()


class TestDetectNoteTableHeaders:
    """测试 _detect_note_table_headers"""

    def test_single_row_header(self, parser):
        """普通单行表头"""
        table = [
            ["项目", "期初余额", "本期增加", "本期减少", "期末余额"],
            ["货币资金", "100,000.00", "50,000.00", "20,000.00", "130,000.00"],
            ["应收账款", "200,000.00", "80,000.00", "30,000.00", "250,000.00"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 1
        assert data_start == 1
        assert header_rows[0] == ["项目", "期初余额", "本期增加", "本期减少", "期末余额"]

    def test_merged_header_different_col_count(self, parser):
        """合并单元格导致行列数不同的多行表头
        
        Word 去重后：
        row0: ["票据种类", "期末余额", "上年年末余额"]  (3列)
        row1: ["账面余额", "坏账准备", "账面价值", "账面余额", "坏账准备", "账面价值"]  (6列)
        row2: ["银行承兑汇票", "112623142.41", "225246.28", "112397896.13", "86408004.95", "172816.01", "86235188.94"]  (7列)
        
        _align_header_rows 智能展开：票据种类独占1列，期末余额展开3列，上年年末余额展开3列。
        前端通过相同值检测来渲染 colSpan。
        """
        table = [
            ["票据种类", "期末余额", "上年年末余额"],
            ["账面余额", "坏账准备", "账面价值", "账面余额", "坏账准备", "账面价值"],
            ["银行承兑汇票", "112623142.41", "225246.28", "112397896.13", "86408004.95", "172816.01", "86235188.94"],
            ["商业承兑汇票", "", "", "", "281595.00", "563.19", "281031.81"],
            ["合计", "112623142.41", "225246.28", "112397896.13", "86689599.95", "173379.20", "86516220.75"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        
        assert len(header_rows) == 2, f"Expected 2 header rows, got {len(header_rows)}"
        assert data_start == 2, f"Expected data_start=2, got {data_start}"
        
        # 所有行应该对齐到 7 列
        for i, row in enumerate(header_rows):
            assert len(row) == 7, f"Header row {i} has {len(row)} cols, expected 7: {row}"
        
        # 第一行：智能展开 — 票据种类(1) + 期末余额(3) + 上年年末余额(3)
        assert header_rows[0][0] == "票据种类"
        assert header_rows[0][1] == "期末余额"
        assert header_rows[0][2] == "期末余额"
        assert header_rows[0][3] == "期末余额"
        assert header_rows[0][4] == "上年年末余额"
        assert header_rows[0][5] == "上年年末余额"
        assert header_rows[0][6] == "上年年末余额"
        
        # 第二行：前插1个空列（独占列对齐）+ 原始6列
        assert header_rows[1][0] == ""
        assert header_rows[1][1] == "账面余额"
        assert header_rows[1][2] == "坏账准备"

    def test_merged_header_same_col_count(self, parser):
        """所有行列数相同的多行表头（第二行第一列为空或重复）"""
        table = [
            ["种类", "期末余额", "", "", "上年年末余额", "", ""],
            ["", "账面余额", "坏账准备", "账面价值", "账面余额", "坏账准备", "账面价值"],
            ["银行承兑汇票", "112623142.41", "225246.28", "112397896.13", "86408004.95", "172816.01", "86235188.94"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 2
        assert data_start == 2

    def test_no_merge_normal_data(self, parser):
        """第二行是数据行（有大数字），不是子表头"""
        table = [
            ["项目", "金额"],
            ["货币资金", "1500000.00"],
            ["应收账款", "2000000.00"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 1
        assert data_start == 1

    def test_three_col_to_five_col(self, parser):
        """3列展开到5列的场景"""
        table = [
            ["项目", "期末数", "期初数"],
            ["账面余额", "坏账准备", "账面余额", "坏账准备"],
            ["应收账款", "500000", "10000", "400000", "8000"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 2
        assert data_start == 2
        for row in header_rows:
            assert len(row) == 5, f"Row has {len(row)} cols, expected 5: {row}"

    def test_single_row_table(self, parser):
        """只有一行的表格"""
        table = [
            ["项目", "金额"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 1
        assert data_start == 1

    def test_empty_table(self, parser):
        """空表格"""
        header_rows, data_start = parser._detect_note_table_headers([])
        assert header_rows == []
        assert data_start == 0

    def test_aging_table_with_merge(self, parser):
        """账龄分析表 - 合并表头
        
        Word 去重后：
        row0: ["账龄", "期末余额", "上年年末余额"]  (3列)
        row1: ["金额", "比例(%)", "金额", "比例(%)"]  (4列，缺第一列)
        row2: ["1年以内", "500000", "50.00", "400000", "40.00"]  (5列)
        """
        table = [
            ["账龄", "期末余额", "上年年末余额"],
            ["金额", "比例(%)", "金额", "比例(%)"],
            ["1年以内", "500000", "50.00", "400000", "40.00"],
            ["1-2年", "300000", "30.00", "350000", "35.00"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 2
        assert data_start == 2
        for row in header_rows:
            assert len(row) == 5, f"Row has {len(row)} cols: {row}"

    def test_aging_table_with_gap_column(self, parser):
        """账龄分析表 - 子行有空列分隔符
        
        Word 去重后：
        row0: ["账龄", "期末余额", "上年年末余额"]  (3列)
        row1: ["金额", "比例(%)", "", "金额", "比例(%)"]  (5列，中间有空列分隔)
        row2: ["1年以内", "16029217.98", "89.42", "", "18152612.23", "100.00"]  (6列)
        
        期末余额应展开2列，上年年末余额应展开2列，中间保留空列分隔符。
        """
        table = [
            ["账龄", "期末余额", "上年年末余额"],
            ["金额", "比例(%)", "", "金额", "比例(%)"],
            ["1年以内", "16029217.98", "89.42", "", "18152612.23", "100.00"],
            ["1至2年", "1895686.38", "10.58", "", "", ""],
            ["合计", "17924904.36", "100.00", "", "18152612.23", "100.00"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 2
        assert data_start == 2
        for row in header_rows:
            assert len(row) == 6, f"Row has {len(row)} cols: {row}"
        
        # 第一行：账龄(1) + 期末余额(2) + 空列(1) + 上年年末余额(2)
        assert header_rows[0][0] == "账龄"
        assert header_rows[0][1] == "期末余额"
        assert header_rows[0][2] == "期末余额"
        assert header_rows[0][3] == ""  # 空列分隔符
        assert header_rows[0][4] == "上年年末余额"
        assert header_rows[0][5] == "上年年末余额"
        
        # 第二行：空(1) + 金额 + 比例(%) + 空 + 金额 + 比例(%)
        assert header_rows[1][0] == ""
        assert header_rows[1][1] == "金额"
        assert header_rows[1][2] == "比例(%)"
        assert header_rows[1][3] == ""
        assert header_rows[1][4] == "金额"
        assert header_rows[1][5] == "比例(%)"

    def test_simple_two_col_table(self, parser):
        """简单两列表格不应误判"""
        table = [
            ["项目", "金额"],
            ["现金", "100.50"],
            ["银行存款", "999.99"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 1
        assert data_start == 1

    def test_vertical_merge_header(self, parser):
        """纵向合并单元格的表头
        
        Word 去重后：
        row0: ["合资企业名称", "主要经营地", "注册地", "业务性质", "持股比例(%)", "对合资企业投资的会计处理方法"]  (6列)
        row1: ["直接", "间接"]  (2列，纵向合并去重掉了4列)
        row2: ["一、联营企业", "", "", "", "", "", ""]  (7列)
        row3: ["XX公司", "西安", "西安", "快递", "23.33", "", "权益法"]  (7列)
        
        _align_header_rows 智能展开：row0 6列补齐到7列，row1 2列补齐到7列。
        """
        table = [
            ["合资企业名称", "主要经营地", "注册地", "业务性质", "持股比例(%)", "对合资企业投资的会计处理方法"],
            ["直接", "间接"],
            ["一、联营企业", "", "", "", "", "", ""],
            ["XX公司", "西安", "西安", "快递", "23.33", "", "权益法"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 2
        assert data_start == 2
        for i, row in enumerate(header_rows):
            assert len(row) == 7, f"Header row {i} has {len(row)} cols, expected 7: {row}"
        
        # 第一行：原始6列 + 1个空补齐
        assert header_rows[0][0] == "合资企业名称"
        assert header_rows[0][4] == "持股比例(%)"
        assert header_rows[0][5] == "对合资企业投资的会计处理方法"
        assert header_rows[0][6] == ""  # 补齐的空列
        
        # 第二行：原始2列 + 5个空补齐
        assert header_rows[1][0] == "直接"
        assert header_rows[1][1] == "间接"
        assert header_rows[1][2] == ""  # 补齐
        """三行表头场景
        
        row0: ["项目", "本期金额"]  (2列)
        row1: ["归属于母公司", "少数股东权益"]  (2列，缺第一列)
        row2: ["实收资本", "资本公积", "盈余公积", "未分配利润", ""]  (5列，缺第一列)
        row3: ["XX公司", "100000", "200000", "50000", "300000", "80000"]  (6列)
        """
        table = [
            ["项目", "本期金额"],
            ["归属于母公司", "少数股东权益"],
            ["实收资本", "资本公积", "盈余公积", "未分配利润", ""],
            ["XX公司", "100000", "200000", "50000", "300000", "80000"],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert data_start == 3
        assert len(header_rows) == 3
        for row in header_rows:
            assert len(row) == 6, f"Row has {len(row)} cols: {row}"


class TestAlignHeaderRows:
    """测试 _align_header_rows（简单补齐模式，不做展开）"""

    def test_three_row_header_bad_debt_classification(self):
        """三行表头：坏账准备分类表（截图中的场景）

        Word 去重后（合并单元格展开为空）：
        row0: ["类 别", "期末余数", "", "", "", "", ""]  (7列)
        row1: ["", "账面余额", "", "坏账准备", "", "账面价值"]  (6列 or 7列)
        row2: ["类 别", "金额", "比例(%)", "金额", "预期信用损失率(%)", "账面价值"]  (6列 or 7列)
        row3: ["单项计提坏账准备的其他应收款项", "", "", "", "", "", ""]  (7列，数据行)
        """
        parser = ReportParser()
        table = [
            ["类 别", "期末余数", "", "", "", "", ""],
            ["", "账面余额", "", "坏账准备", "", "账面价值", ""],
            ["类 别", "金额", "比例(%)", "金额", "预期信用损失率(%)", "账面价值", ""],
            ["单项计提坏账准备的其他应收款项", "", "", "", "", "", ""],
            ["按信用风险特征组合计提坏账准备的其他应收款项", "3764954.04", "100.00", "", "", "3764954.04", ""],
        ]
        header_rows, data_start = parser._detect_note_table_headers(table)
        assert len(header_rows) == 3, f"Expected 3 header rows, got {len(header_rows)}: {header_rows}"
        assert data_start == 3

    def test_pad_short_rows(self):
        """智能展开：票据种类独占1列，期末余额展开3列，上年年末余额展开3列"""
        rows = [
            ["票据种类", "期末余额", "上年年末余额"],
            ["", "账面余额", "坏账准备", "账面价值", "账面余额", "坏账准备", "账面价值"],
        ]
        result = ReportParser._align_header_rows(rows, 7)
        assert len(result) == 2
        assert len(result[0]) == 7
        assert len(result[1]) == 7
        # 第一行：智能展开 — 票据种类(1) + 期末余额(3) + 上年年末余额(3)
        assert result[0][0] == "票据种类"
        assert result[0][1] == "期末余额"
        assert result[0][2] == "期末余额"
        assert result[0][3] == "期末余额"
        assert result[0][4] == "上年年末余额"
        assert result[0][5] == "上年年末余额"
        assert result[0][6] == "上年年末余额"
        # 第二行：前插1个空列 + 原始6列
        assert result[1][0] == ""
        assert result[1][1] == "账面余额"

    def test_pad_missing_first_col(self):
        """子表头缺少第一列（垂直合并去重），简单补齐到末尾"""
        rows = [
            ["票据种类", "期末余额", "", "", "上年年末余额", "", ""],
            ["账面余额", "坏账准备", "账面价值", "账面余额", "坏账准备", "账面价值"],
        ]
        result = ReportParser._align_header_rows(rows, 7)
        # 第一行已经7列
        assert len(result[0]) == 7
        # 第二行6列 + 1个空补齐
        assert len(result[1]) == 7
        assert result[1][0] == "账面余额"  # 简单补齐不会前插空列
        assert result[1][6] == ""  # 末尾补空

    def test_already_aligned(self):
        """已经对齐的行"""
        rows = [
            ["项目", "期初", "", "期末", ""],
            ["", "余额", "准备", "余额", "准备"],
        ]
        result = ReportParser._align_header_rows(rows, 5)
        assert all(len(r) == 5 for r in result)

    def test_truncate_long_rows(self):
        """超长行截断到目标列数"""
        rows = [
            ["a", "b", "c", "d", "e"],
        ]
        result = ReportParser._align_header_rows(rows, 3)
        assert len(result[0]) == 3
        assert result[0] == ["a", "b", "c"]


class TestMergeNoteHeaderRows:
    """测试 _merge_note_header_rows"""

    def test_single_row(self):
        headers = [["项目", "期初余额", "期末余额"]]
        result = ReportParser._merge_note_header_rows(headers)
        assert result == ["项目", "期初余额", "期末余额"]

    def test_two_rows_merge(self):
        headers = [
            ["票据种类", "期末余额", "", "", "上年年末余额", "", ""],
            ["", "账面余额", "坏账准备", "账面价值", "账面余额", "坏账准备", "账面价值"],
        ]
        result = ReportParser._merge_note_header_rows(headers)
        assert len(result) == 7
        assert result[0] == "票据种类"
        assert result[1] == "期末余额-账面余额"
        assert result[2] == "坏账准备"  # 只有第二行有值
        assert result[4] == "上年年末余额-账面余额"

    def test_empty(self):
        assert ReportParser._merge_note_header_rows([]) == []
