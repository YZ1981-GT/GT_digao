"""统一的标题层级检测工具模块。

所有标题检测逻辑集中在此，避免在 workpaper_parser / report_parser 中重复定义。
核心规则：
  - 中文编号模式是最可靠的层级信号，优先级最高
  - Word 样式 / OutlineLevel 作为辅助信号
  - 加粗短段落、模式匹配标题、表格前描述行作为兜底
"""
import re
from typing import List, Optional, Tuple

# ─── 中文编号模式 → 层级映射（唯一定义，全局复用） ───
# 按优先级排列：先匹配更具体的模式
# 注意：正则需要足够精确，避免误匹配正文中的数字
CHINESE_NUMBERING_PATTERNS: List[Tuple[re.Pattern, int]] = [
    (re.compile(r'^[一二三四五六七八九十百]+、'), 1),                        # 一、二、三、...十一、
    (re.compile(r'^[（(][一二三四五六七八九十百]+[）)]'), 2),                # （一）（二）...
    (re.compile(r'^\d{1,3}[、.．]\s*[\u4e00-\u9fff(（a-zA-Z]'), 3),        # 1、货币资金 / 2.应收票据 / 1．按账龄（含全角句点）
    (re.compile(r'^[（(]\d{1,2}[）)]\s*[\u4e00-\u9fff a-zA-Z]'), 4),      # (1) 按坏账计提（限1-2位数字）
    (re.compile(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]'), 4),                # ① ② ③ ...
]

# 财务报表附注中常见的描述性标题行模式（兜底检测）
NOTE_TITLE_PATTERNS = re.compile('|'.join([
    r'^按.{1,20}(计提|分类|归集|划分|披露)',
    r'^组合计提项目[：:]',
    r'^期末本公司',
    r'^本期计提',
    r'^转回或收回',
    r'^本期实际核销',
    r'^重要的.{2,30}',
    r'^按单项计提',
    r'^按组合计提',
    r'^按坏账计提',
    r'^按(预付|欠款方)归集',
    r'^作为(承租人|出租人)',
    r'^外币货币性项目',
    r'^境外经营实体',
]))


def infer_numbering_level(text: str) -> Optional[int]:
    """通过中文编号模式推断标题层级。

    这是最可靠的层级信号，适用于所有文档模板。
    Returns:
        层级 1-4，或 None（无编号）
    """
    if not text:
        return None
    for pattern, level in CHINESE_NUMBERING_PATTERNS:
        if pattern.match(text):
            return level
    return None


def has_top_level_numbering(text: str) -> bool:
    """判断文本是否以一级编号开头（一、二、三...）"""
    return bool(re.match(r'^[一二三四五六七八九十百]+、', text))


def is_short_heading_candidate(text: str) -> bool:
    """判断文本是否符合短标题的基本特征（长度、结尾、不被括号包裹）"""
    if not text or len(text) > 80:
        return False
    if text[-1] in '。；;':
        return False
    if (text.startswith('（') and text.endswith('）')) or \
       (text.startswith('(') and text.endswith(')')):
        return False
    return True


def detect_heading_level(
    text: str,
    word_style_level: Optional[int] = None,
    is_bold: bool = False,
    is_before_table: bool = False,
    current_heading_level: int = 0,
    flat_style_mode: bool = False,
) -> Optional[int]:
    """统一的标题层级检测函数。

    检测优先级：
    1. 中文编号模式（最可靠）
    2. Word 样式 / OutlineLevel（受 flat_style_mode 约束）
    3. 加粗短段落 → 子标题
    4. 附注模式匹配标题 → 子标题
    5. 表格前描述性短段落 → 子标题

    Args:
        text: 段落文本（已 strip）
        word_style_level: Word 样式或 OutlineLevel 给出的层级（1-9），None 表示无
        is_bold: 段落是否全部加粗
        is_before_table: 下一个非空元素是否为表格
        current_heading_level: 当前上下文中最近的标题层级
        flat_style_mode: 是否处于 flat 模式（所有 Word 样式 level 相同）

    Returns:
        标题层级 1-6，或 None（非标题）
    """
    if not text:
        return word_style_level if word_style_level and not flat_style_mode else None

    # ── 1. 中文编号模式（最高优先级） ──
    numbering_level = infer_numbering_level(text)
    if numbering_level is not None:
        # 编号模式始终优先，但如果 Word 样式给出了更细的层级，取更细的
        if word_style_level is not None and word_style_level > numbering_level:
            return word_style_level
        return numbering_level

    # ── 2. Word 样式 / OutlineLevel ──
    if word_style_level is not None:
        if flat_style_mode:
            # flat 模式下，无编号标题不信任 Word 样式
            pass
        else:
            return word_style_level

    # ── 3-5. 兜底检测（仅对短标题候选） ──
    if not is_short_heading_candidate(text):
        return None

    sub_level = min(current_heading_level + 1, 6) if current_heading_level else 4

    # 3. 加粗短段落
    if is_bold:
        return sub_level

    # 4. 附注模式匹配
    if NOTE_TITLE_PATTERNS.search(text):
        return sub_level

    # 5. 表格前描述性短段落
    if is_before_table and len(text) <= 60:
        if not re.match(r'^续[（(：:]', text) and text != '续':
            return sub_level

    return None


def correct_flat_style_level(
    level: Optional[int],
    text: str,
    current_heading_level: int,
) -> Optional[int]:
    """修正 flat style 场景下的层级。

    当 Word 样式给出 level=1 但文本没有一级编号时，
    说明 Word 样式不准确（所有标题都设为 Heading 1），降级为子标题。
    修正为 level=2（固定），避免随 current_heading_level 递增导致
    同级科目（如货币资金、应收账款）被错误嵌套。
    """
    if level is None or not text:
        return level
    if level <= current_heading_level and current_heading_level >= 1:
        if not has_top_level_numbering(text) and level == 1:
            # 固定修正为 level=2，不随 current_heading_level 递增
            return 2
    return level


def detect_flat_style_mode(paragraphs: list) -> bool:
    """预扫描段落列表，检测是否所有 Word 样式 level 都相同（flat mode）。

    如果所有有 level 的段落都是同一个 level（如全是 Heading 1），
    说明 Word 样式不可靠。
    """
    style_levels = set()
    for p in paragraphs:
        lvl = p.get('level')
        if lvl is not None:
            style_levels.add(lvl)
    return len(style_levels) == 1
