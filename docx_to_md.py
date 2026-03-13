"""
DOCX 转 Markdown 脚本（增强版）
- 识别标题层级：Word Heading 样式 / outlineLvl / 加粗短段落 / 表格前描述行 / 模式匹配标题
- 单列表格转为普通文本块
- 多列表格正确转换（含合并单元格）
- 保留加粗、斜体等行内格式
"""
import re
import sys
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn


def iter_block_items(parent):
    """按文档顺序迭代段落和表格"""
    body = parent.element.body if hasattr(parent, 'element') else parent
    for child in body:
        if child.tag == qn('w:p'):
            yield Paragraph(child, parent)
        elif child.tag == qn('w:tbl'):
            yield Table(child, parent)


def get_heading_level(para):
    """判断段落的标题级别，返回 int 或 None"""
    style_name = (para.style.name or '').lower()
    text = para.text.strip()
    if not text:
        return None

    # 1. Word 内置 Heading 样式
    if style_name.startswith('heading'):
        try:
            level = int(style_name.replace('heading', '').strip())
            return level
        except ValueError:
            pass

    # 2. 中文标题样式名（精确匹配 + 模糊匹配如"标题3的样式"）
    cn_heading_map = {
        '标题 1': 1, '标题 2': 2, '标题 3': 3, '标题 4': 4, '标题 5': 5,
        '标题1': 1, '标题2': 2, '标题3': 3, '标题4': 4, '标题5': 5,
        # 自定义样式映射
        '样式2': 4,       # "同一控制下的企业合并"等子标题
        '附注三级': 3,    # 附注三级标题
    }
    raw_style = para.style.name or ''
    if raw_style in cn_heading_map:
        return cn_heading_map[raw_style]
    # 模糊匹配：样式名包含"标题"和数字，如"标题3的样式"
    cn_match = re.search(r'标题\s*([1-9])', raw_style)
    if cn_match:
        return int(cn_match.group(1))

    # 3. 通过 outlineLvl 判断
    pPr = para._element.find(qn('w:pPr'))
    if pPr is not None:
        outlineLvl = pPr.find(qn('w:outlineLvl'))
        if outlineLvl is not None:
            val = outlineLvl.get(qn('w:val'))
            if val is not None:
                level = int(val) + 1
                if 1 <= level <= 6:
                    return level

    return None


def is_bold_paragraph(para):
    """判断段落是否整体加粗（所有非空 run 都是粗体）"""
    runs = [r for r in para.runs if r.text.strip()]
    if not runs:
        return False
    return all(r.bold for r in runs)


def is_short_title_like(text):
    """判断文本是否像一个子标题（较短、无句号结尾等）"""
    text = text.strip()
    if not text or len(text) > 80:
        return False
    if text[-1] in '。；;':
        return False
    if text.startswith('（') and text.endswith('）'):
        return False
    if text.startswith('(') and text.endswith(')'):
        return False
    if text.startswith('【') and text.endswith('】'):
        return False
    return True


# 财务报表附注中常见的描述性标题行模式
_TITLE_PATTERNS = [
    # "按XX计提/分类/归集/划分"开头的
    r'^按.{1,20}(计提|分类|归集|划分|披露)',
    # "组合计提项目："
    r'^组合计提项目[：:]',
    # "期末本公司已..."
    r'^期末本公司',
    # "本期计提、收回或转回"
    r'^本期计提',
    # "转回或收回金额重要"
    r'^转回或收回',
    # "本期实际核销"
    r'^本期实际核销',
    # "重要的XX"（独立短行）
    r'^重要的.{2,30}$',
    # "按单项计提"
    r'^按单项计提',
    # "按组合计提"
    r'^按组合计提',
    # "按坏账计提方法"
    r'^按坏账计提',
    # "按预付/欠款方归集"
    r'^按(预付|欠款方)归集',
    # "作为承租人/出租人"
    r'^作为(承租人|出租人)',
    # "外币货币性项目"
    r'^外币货币性项目$',
    # "境外经营实体"
    r'^境外经营实体$',
]
_TITLE_RE = re.compile('|'.join(_TITLE_PATTERNS))


def is_pattern_title(text):
    """通过模式匹配判断是否为财务报表附注中的描述性标题行"""
    text = text.strip()
    if not text or len(text) > 80:
        return False
    # 不以句号等结尾（允许冒号结尾，如"按组合计提减值准备："）
    if text[-1] in '。；;':
        return False
    # 不以括号包裹
    if (text.startswith('（') and text.endswith('）')) or \
       (text.startswith('(') and text.endswith(')')) or \
       (text.startswith('【') and text.endswith('】')):
        return False
    return bool(_TITLE_RE.search(text))


def is_table_title_candidate(text):
    """判断文本是否可能是表格前的描述性标题行"""
    text = text.strip()
    if not text or len(text) > 60:
        return False
    if text[-1] in '。；;.':
        return False
    if (text.startswith('（') and text.endswith('）')) or \
       (text.startswith('(') and text.endswith(')')) or \
       (text.startswith('【') and text.endswith('】')):
        return False
    if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', text):
        return False
    # "续："不是标题
    if re.match(r'^续[（(：:]', text) or text == '续':
        return False
    return True


def runs_to_md(para):
    """将段落的 runs 转为 Markdown 行内格式"""
    parts = []
    for run in para.runs:
        text = run.text
        if not text:
            continue
        if run.bold:
            text = f'**{text}**'
        if run.italic:
            text = f'*{text}*'
        parts.append(text)
    result = ''.join(parts)
    result = re.sub(r'\*\*\*\*', '', result)
    result = re.sub(r'\*\*\s*\*\*', ' ', result)
    return result.strip()


def get_actual_column_count(table):
    """获取表格的实际列数（去重合并单元格后）"""
    if not table.rows:
        return 0
    unique_counts = set()
    for row in table.rows:
        seen = set()
        unique_cells = 0
        for cell in row.cells:
            cell_id = id(cell._tc)
            if cell_id not in seen:
                seen.add(cell_id)
                unique_cells += 1
        unique_counts.add(unique_cells)
    return max(unique_counts) if unique_counts else 0


def table_to_md(table):
    """将 Word 表格转为 Markdown 表格，处理合并单元格。
    单列表格转为普通文本块。"""
    rows = table.rows
    if not rows:
        return ''

    actual_cols = get_actual_column_count(table)

    grid = []
    for row in rows:
        row_data = []
        seen = set()
        for cell in row.cells:
            cell_id = id(cell._tc)
            if cell_id in seen:
                continue
            seen.add(cell_id)
            cell_text = cell.text.strip().replace('\n', '<br/>')
            cell_text = cell_text.replace('|', '\\|')
            row_data.append(cell_text)
        grid.append(row_data)

    if not grid:
        return ''

    if actual_cols <= 1:
        lines = []
        for row_data in grid:
            text = row_data[0] if row_data else ''
            if text:
                text = text.replace('<br/>', '\n')
                lines.append(text)
        return '\n\n'.join(lines)

    max_cols = max(len(r) for r in grid)
    for r in grid:
        while len(r) < max_cols:
            r.append('')

    lines = []
    header = grid[0]
    lines.append('| ' + ' | '.join(header) + ' |')
    lines.append('| ' + ' | '.join(['---'] * max_cols) + ' |')
    for row_data in grid[1:]:
        lines.append('| ' + ' | '.join(row_data) + ' |')

    return '\n'.join(lines)


def determine_sub_heading_level(current_heading_level):
    """在当前标题级别下确定子标题级别"""
    return min(current_heading_level + 1, 6) if current_heading_level else 4


def _next_is_table(blocks, current_index):
    """检查当前段落之后（跳过空段落）是否紧跟表格"""
    for j in range(current_index + 1, min(current_index + 3, len(blocks))):
        next_block = blocks[j]
        if isinstance(next_block, Table):
            return True
        if isinstance(next_block, Paragraph):
            if next_block.text.strip():
                return False
    return False


def convert_docx_to_md(docx_path, output_path=None):
    """主转换函数"""
    doc = Document(docx_path)

    if output_path is None:
        output_path = re.sub(r'\.docx$', '.md', docx_path, flags=re.IGNORECASE)

    blocks = list(iter_block_items(doc))
    md_lines = []
    current_heading_level = 0

    # 层级归一化：记录已出现的层级，防止跳级
    # 例如 H1 -> H3 应该归一化为 H1 -> H2
    heading_stack = []  # 记录当前的标题层级栈

    def normalize_heading_level(raw_level):
        """归一化标题层级，防止跳级"""
        nonlocal heading_stack
        # 弹出栈中 >= raw_level 的层级
        while heading_stack and heading_stack[-1] >= raw_level:
            heading_stack.pop()
        # 归一化后的层级 = 栈深度 + 1
        normalized = len(heading_stack) + 1
        heading_stack.append(raw_level)
        return min(normalized, 6)

    for i, block in enumerate(blocks):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                md_lines.append('')
                continue

            heading_level = get_heading_level(block)

            if heading_level:
                # Word 标题样式 -> 归一化层级
                normalized = normalize_heading_level(heading_level)
                current_heading_level = normalized
                prefix = '#' * normalized
                md_lines.append(f'{prefix} {text}')
                md_lines.append('')
            elif is_bold_paragraph(block) and is_short_title_like(text):
                # 整体加粗的短段落 -> 子标题
                level = determine_sub_heading_level(current_heading_level)
                prefix = '#' * level
                md_lines.append(f'{prefix} {text}')
                md_lines.append('')
            elif is_pattern_title(text):
                # 模式匹配的描述性标题行 -> 子标题
                level = determine_sub_heading_level(current_heading_level)
                prefix = '#' * level
                md_lines.append(f'{prefix} {text}')
                md_lines.append('')
            elif is_table_title_candidate(text) and _next_is_table(blocks, i):
                # 紧跟表格的描述性短段落 -> 子标题
                level = determine_sub_heading_level(current_heading_level)
                prefix = '#' * level
                md_lines.append(f'{prefix} {text}')
                md_lines.append('')
            else:
                content = runs_to_md(block)
                if not content:
                    content = text
                md_lines.append(content)
                md_lines.append('')

        elif isinstance(block, Table):
            md_lines.append('')
            md_lines.append(table_to_md(block))
            md_lines.append('')

    result = '\n'.join(md_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = result.strip() + '\n'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)

    print(f'转换完成: {docx_path} -> {output_path}')
    print(f'共 {len(result.splitlines())} 行')
    return output_path


if __name__ == '__main__':
    input_file = sys.argv[1] if len(sys.argv) > 1 else '3.2025年度上市公司财务报表附注模板-2026.01.15.docx'
    convert_docx_to_md(input_file)
