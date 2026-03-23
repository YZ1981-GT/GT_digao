"""heading_utils 通用标题检测规则的单元测试。

覆盖所有中文编号模式、flat style 检测、层级修正等核心逻辑，
确保任何模板变体都能正确解析。
"""
import pytest
from app.services.heading_utils import (
    CHINESE_NUMBERING_PATTERNS,
    NOTE_TITLE_PATTERNS,
    infer_numbering_level,
    has_top_level_numbering,
    is_short_heading_candidate,
    detect_heading_level,
    correct_flat_style_level,
    detect_flat_style_mode,
)


class TestInferNumberingLevel:
    """中文编号模式 → 层级推断"""

    @pytest.mark.parametrize("text,expected", [
        # 一级：一、二、三...
        ("一、医院基本情况", 1),
        ("二、财务报表的编制基础", 1),
        ("七、财务报表重要项目说明", 1),
        ("十一、其他重要事项", 1),
        # 二级：（一）（二）...
        ("（一）医院历史沿革", 2),
        ("（二）母公司及组织架构", 2),
        ("(三)重要会计政策", 2),
        # 三级：1. 2. 或 1、2、（后面必须跟中文/字母）
        ("1、货币资金", 3),
        ("2.应收票据", 3),
        ("15、长期股权投资", 3),
        ("1. 货币资金", 3),
        ("1．按账龄披露应收账款", 3),
        ("2．按坏账准备计提方法分类披露", 3),
        # 四级：(1) (2)（限1-2位数字，后跟中文/字母）
        ("(1) 按坏账计提方法分类", 4),
        ("（2）按账龄分析", 4),
        # 无编号
        ("货币资金", None),
        ("", None),
        ("这是一段正文内容。", None),
        # 误匹配防护：数字开头但不是标题编号
        ("3.14 元的单价", None),
        ("1.5倍的标准", None),
        ("100、200、300", None),
        ("2023年度", None),
        ("(2023)年报", None),
        ("(100)号文件", None),
    ])
    def test_numbering_patterns(self, text, expected):
        assert infer_numbering_level(text) == expected


class TestHasTopLevelNumbering:
    @pytest.mark.parametrize("text,expected", [
        ("一、基本情况", True),
        ("七、财务报表重要项目说明", True),
        ("（一）历史沿革", False),
        ("1、货币资金", False),
        ("货币资金", False),
    ])
    def test_top_level(self, text, expected):
        assert has_top_level_numbering(text) == expected


class TestIsShortHeadingCandidate:
    def test_normal_heading(self):
        assert is_short_heading_candidate("货币资金") is True

    def test_too_long(self):
        assert is_short_heading_candidate("x" * 81) is False

    def test_ends_with_period(self):
        assert is_short_heading_candidate("这是一段话。") is False

    def test_wrapped_in_parens(self):
        assert is_short_heading_candidate("（删除不适用的内容）") is False

    def test_empty(self):
        assert is_short_heading_candidate("") is False


class TestDetectHeadingLevel:
    """统一标题检测函数"""

    def test_numbering_overrides_word_style(self):
        """编号模式优先于 Word 样式"""
        # Word 说 level=1，但文本是（一）→ 应该是 level=2
        assert detect_heading_level("（一）历史沿革", word_style_level=1) == 2

    def test_word_style_when_no_numbering(self):
        """无编号时使用 Word 样式"""
        assert detect_heading_level("货币资金", word_style_level=2) == 2

    def test_flat_mode_ignores_word_style(self):
        """flat mode 下无编号标题不信任 Word 样式"""
        assert detect_heading_level("货币资金", word_style_level=1, flat_style_mode=True) is None

    def test_flat_mode_still_uses_numbering(self):
        """flat mode 下编号模式仍然有效"""
        assert detect_heading_level("一、基本情况", word_style_level=1, flat_style_mode=True) == 1
        assert detect_heading_level("（一）历史沿革", word_style_level=1, flat_style_mode=True) == 2

    def test_bold_short_paragraph(self):
        """加粗短段落 → 子标题"""
        assert detect_heading_level("货币资金", is_bold=True, current_heading_level=1) == 2
        assert detect_heading_level("货币资金", is_bold=True, current_heading_level=0) == 4

    def test_note_title_pattern(self):
        """附注模式匹配标题"""
        assert detect_heading_level("按坏账计提方法分类", current_heading_level=3) == 4

    def test_before_table_short_paragraph(self):
        """表格前描述性短段落"""
        assert detect_heading_level("应收账款账龄分析", is_before_table=True, current_heading_level=3) == 4
        assert detect_heading_level("按单项计提坏账准备", is_before_table=True, current_heading_level=3) == 4
        # 长文本不会被当作表格前标题
        long_text = "本公司根据相关会计准则的规定，对应收账款按照预期信用损失模型计提坏账准备。"
        assert detect_heading_level(long_text, is_before_table=True, current_heading_level=3) is None

    def test_long_text_not_heading(self):
        """长文本不是标题"""
        assert detect_heading_level("这是一段很长的正文内容，描述了公司的基本情况和历史沿革，包括成立时间、注册资本、经营范围等信息。") is None

    def test_empty_text(self):
        assert detect_heading_level("") is None
        assert detect_heading_level("", word_style_level=1) == 1
        assert detect_heading_level("", word_style_level=1, flat_style_mode=True) is None

    def test_word_style_finer_than_numbering(self):
        """Word 样式给出更细的层级时，取更细的"""
        # 编号说 level=3，Word 说 level=4 → 取 4
        assert detect_heading_level("1、货币资金", word_style_level=4) == 4


class TestCorrectFlatStyleLevel:
    def test_no_correction_needed(self):
        """正常情况不修正"""
        assert correct_flat_style_level(2, "（一）历史沿革", 1) == 2

    def test_downgrade_level1_without_top_numbering(self):
        """level=1 但无一级编号 → 降级为固定 level=2"""
        assert correct_flat_style_level(1, "货币资金", 1) == 2

    def test_no_downgrade_with_top_numbering(self):
        """level=1 且有一级编号 → 不降级"""
        assert correct_flat_style_level(1, "七、财务报表重要项目说明", 1) == 1

    def test_none_level(self):
        assert correct_flat_style_level(None, "货币资金", 1) is None

    def test_sibling_accounts_same_level(self):
        """连续无编号科目应保持同级（level=2），不随 current_heading_level 递增"""
        # 货币资金后 current_heading_level=2，应收账款也应得到 level=2
        assert correct_flat_style_level(1, "应收账款", 2) == 2
        assert correct_flat_style_level(1, "其他应收款", 2) == 2
        assert correct_flat_style_level(1, "固定资产", 3) == 2
        assert correct_flat_style_level(1, "无形资产", 4) == 2


class TestDetectFlatStyleMode:
    def test_all_same_level(self):
        paras = [{"level": 1}, {"level": 1}, {"level": 1}]
        assert detect_flat_style_mode(paras) is True

    def test_mixed_levels(self):
        paras = [{"level": 1}, {"level": 2}, {"level": 3}]
        assert detect_flat_style_mode(paras) is False

    def test_no_levels(self):
        paras = [{"text": "abc"}, {"text": "def"}]
        assert detect_flat_style_mode(paras) is False

    def test_single_paragraph_with_level(self):
        paras = [{"level": 1}]
        assert detect_flat_style_mode(paras) is True

    def test_mixed_with_and_without_level(self):
        """有些段落有 level，有些没有，但有 level 的都相同"""
        paras = [{"level": 1}, {"text": "no level"}, {"level": 1}]
        assert detect_flat_style_mode(paras) is True


class TestNoteTitlePatterns:
    """附注模式匹配"""

    @pytest.mark.parametrize("text", [
        "按坏账计提方法分类",
        "按单项计提坏账准备",
        "按组合计提坏账准备",
        "按预付归集",
        "重要的在建工程项目变动情况",
        "作为承租人的租赁情况",
        "外币货币性项目",
        "境外经营实体",
    ])
    def test_matches(self, text):
        assert NOTE_TITLE_PATTERNS.search(text) is not None

    @pytest.mark.parametrize("text", [
        "货币资金",
        "应收账款",
        "这是一段正文。",
    ])
    def test_no_match(self, text):
        assert NOTE_TITLE_PATTERNS.search(text) is None
