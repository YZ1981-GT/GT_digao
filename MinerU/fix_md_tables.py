# -*- coding: utf-8 -*-
"""
MinerU Markdown 表格修复脚本
将 HTML <table> 转换为标准 Markdown 表格格式
支持 rowspan/colspan 合并单元格的展开
自动合并跨页拆分的表格、去除重复表头行、清理空列

用法:
  python fix_md_tables.py <输入文件.md> [输出文件.md]
  如果不指定输出文件，默认在同目录生成 _fixed.md 后缀文件
"""

import re
import sys
from pathlib import Path
from html.parser import HTMLParser


class TableParser(HTMLParser):
    """解析 HTML table 为二维数组"""

    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.current_cell = ""
        self.in_table = False
        self.in_cell = False
        self.current_colspan = 1
        self.current_rowspan = 1

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self.in_table = True
            self.current_table = []
        elif tag == "tr":
            self.current_row = []
        elif tag in ("td", "th"):
            self.in_cell = True
            self.current_cell = ""
            self.current_colspan = int(attrs_dict.get("colspan", 1))
            self.current_rowspan = int(attrs_dict.get("rowspan", 1))

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.in_cell = False
            text = self.current_cell.strip()
            self.current_row.append({
                "text": text,
                "colspan": self.current_colspan,
                "rowspan": self.current_rowspan,
            })
        elif tag == "tr":
            self.current_table.append(self.current_row)
        elif tag == "table":
            self.in_table = False
            self.tables.append(self.current_table)

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


def expand_spans(raw_rows):
    """将 rowspan/colspan 展开为完整的二维网格"""
    if not raw_rows:
        return []

    # 先算出最大列数
    max_cols = 0
    for row in raw_rows:
        cols = sum(cell["colspan"] for cell in row)
        max_cols = max(max_cols, cols)

    num_rows = len(raw_rows)
    grid = [[None] * max_cols for _ in range(num_rows)]

    for r, row in enumerate(raw_rows):
        c = 0
        cell_idx = 0
        while cell_idx < len(row) and c < max_cols:
            while c < max_cols and grid[r][c] is not None:
                c += 1
            if c >= max_cols:
                break

            cell = row[cell_idx]
            text = cell["text"]
            cs = cell["colspan"]
            rs = cell["rowspan"]

            for dr in range(rs):
                for dc in range(cs):
                    nr, nc = r + dr, c + dc
                    if nr < num_rows and nc < max_cols:
                        if dr == 0 and dc == 0:
                            grid[nr][nc] = text
                        else:
                            grid[nr][nc] = ""
            c += cs
            cell_idx += 1

    for r in range(num_rows):
        for c in range(max_cols):
            if grid[r][c] is None:
                grid[r][c] = ""

    return grid


def remove_empty_columns(grid):
    """删除所有行都为空的列"""
    if not grid or not grid[0]:
        return grid

    num_cols = len(grid[0])
    # 找出非空列（跳过表头行，只看数据行判断是否空列）
    non_empty_cols = []
    for c in range(num_cols):
        has_content = False
        for r in range(len(grid)):
            if grid[r][c].strip():
                has_content = True
                break
        if has_content:
            non_empty_cols.append(c)

    if len(non_empty_cols) == num_cols:
        return grid

    return [[row[c] for c in non_empty_cols] for row in grid]


def merge_colspan_header_columns(grid):
    """
    处理 colspan=2 导致的冗余列：如果表头中某列为空且与前一列属于同一个 colspan 展开，
    则合并这些列。具体策略：如果表头行中某列为空，且该列在所有数据行中也为空，则删除。
    """
    return remove_empty_columns(grid)


def normalize_header(row):
    """将表头行标准化用于比较（去空格、去特殊字符）"""
    return tuple(cell.strip().replace(" ", "") for cell in row)


def is_duplicate_header(row, header_norm):
    """判断某行是否是重复的表头行"""
    row_norm = normalize_header(row)
    if not header_norm:
        return False

    # 计算匹配度：表头中非空字段有多少在该行中也出现
    header_non_empty = [h for h in header_norm if h]
    if not header_non_empty:
        return False

    row_non_empty = [r for r in row_norm if r]
    if not row_non_empty:
        return False

    # 如果该行的非空字段数量少于表头的一半，可能不是表头
    # 但如果匹配度高，仍然认为是重复表头
    matches = 0
    for h in header_non_empty:
        for r in row_non_empty:
            if h == r or (len(h) > 1 and h in r) or (len(r) > 1 and r in h):
                matches += 1
                break

    # 超过60%的表头字段匹配，认为是重复表头
    return matches >= len(header_non_empty) * 0.6


def remove_duplicate_headers(grid):
    """删除数据中混入的重复表头行（PDF跨页导致）"""
    if len(grid) < 2:
        return grid

    header_norm = normalize_header(grid[0])
    result = [grid[0]]

    for i in range(1, len(grid)):
        if not is_duplicate_header(grid[i], header_norm):
            result.append(grid[i])

    return result


def merge_split_rows(grid):
    """
    合并因PDF跨页断裂导致的拆分行。
    特征：某行的第一列（序号列）为空，且前一行的某些列内容被截断，
    且该行的大部分列也为空（只有少数列有续接内容）。
    """
    if len(grid) < 2:
        return grid

    result = [grid[0]]  # 表头

    i = 1
    while i < len(grid):
        row = grid[i]
        first_cell = row[0].strip() if row else ""

        if not first_cell and result and len(result) > 1:
            # 检查是否是续行：大部分列为空，只有少数列有内容
            non_empty_cells = [(c, row[c]) for c in range(len(row)) if row[c].strip()]
            total_cells = len(row)

            # 续行特征：非空单元格数量少于总列数的一半
            # 且不是"总计"之类的汇总行（汇总行通常有多个非空单元格）
            is_summary_row = any("总计" in row[c] or "合计" in row[c] or "小计" in row[c]
                                for c in range(len(row)) if row[c].strip())

            if not is_summary_row and non_empty_cells and len(non_empty_cells) < total_cells * 0.5:
                # 合并到上一行
                prev = result[-1]
                for c, val in non_empty_cells:
                    if c < len(prev):
                        if prev[c].strip():
                            prev[c] = prev[c].rstrip() + val.strip()
                        else:
                            prev[c] = val.strip()
                i += 1
                continue

        result.append(row)
        i += 1

    return result


def display_width(s):
    """计算字符串的显示宽度（中文字符算2）"""
    w = 0
    for ch in s:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef':
            w += 2
        else:
            w += 1
    return w


def grid_to_markdown(grid):
    """将二维网格转为 Markdown 表格字符串"""
    if not grid or not grid[0]:
        return ""

    num_cols = len(grid[0])

    col_widths = [3] * num_cols
    for row in grid:
        for c, cell in enumerate(row):
            if c < num_cols:
                col_widths[c] = max(col_widths[c], display_width(cell))

    max_col_width = 60
    col_widths = [min(w, max_col_width) for w in col_widths]

    def pad_cell(text, width):
        dw = display_width(text)
        padding = max(0, width - dw)
        return text + " " * padding

    def truncate_text(text, max_w):
        if display_width(text) <= max_w:
            return text
        truncated = ""
        w = 0
        for ch in text:
            cw = 2 if ('\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef') else 1
            if w + cw > max_w - 2:
                truncated += ".."
                break
            truncated += ch
            w += cw
        return truncated

    lines = []
    for i, row in enumerate(grid):
        cells = []
        for c in range(num_cols):
            cell_text = row[c] if c < len(row) else ""
            cell_text = truncate_text(cell_text, max_col_width)
            cells.append(pad_cell(cell_text, col_widths[c]))
        line = "| " + " | ".join(cells) + " |"
        lines.append(line)

        if i == 0:
            sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
            lines.append(sep)

    return "\n".join(lines)


def tables_share_structure(grid1, grid2):
    """判断两个表格是否具有相同的列结构（可合并）"""
    if not grid1 or not grid2:
        return False
    if not grid1[0] or not grid2[0]:
        return False

    # 先对两个网格去除空列后再比较
    clean1 = remove_empty_columns(grid1)
    clean2 = remove_empty_columns(grid2)

    cols1 = len(clean1[0]) if clean1 and clean1[0] else 0
    cols2 = len(clean2[0]) if clean2 and clean2[0] else 0

    if cols1 == 0 or cols2 == 0:
        return False

    # 允许列数差异在2以内
    if abs(cols1 - cols2) > 2:
        return False

    # 比较表头相似度（用去空列后的表头）
    h1 = normalize_header(clean1[0])
    h2 = normalize_header(clean2[0])

    # 提取非空表头字段
    h1_non_empty = [h for h in h1 if h]
    h2_non_empty = [h for h in h2 if h]

    if not h1_non_empty or not h2_non_empty:
        return False

    # 计算交集匹配度
    matches = 0
    for h in h1_non_empty:
        for h2_item in h2_non_empty:
            if h == h2_item or (len(h) > 1 and h in h2_item) or (len(h2_item) > 1 and h2_item in h):
                matches += 1
                break

    # 超过50%的非空表头字段匹配
    return matches >= len(h1_non_empty) * 0.5


def process_grid(grid):
    """对展开后的网格进行后处理优化"""
    grid = remove_empty_columns(grid)
    grid = remove_duplicate_headers(grid)
    grid = merge_split_rows(grid)
    return grid


def convert_html_tables_in_md(content):
    """将 Markdown 内容中的所有 HTML table 替换为 Markdown 表格"""
    table_pattern = re.compile(r'<table>.*?</table>', re.DOTALL)

    # 找到所有表格及其位置
    matches = list(table_pattern.finditer(content))
    if not matches:
        return content

    # 解析所有表格
    parsed = []
    for m in matches:
        parser = TableParser()
        parser.feed(m.group(0))
        if parser.tables:
            grid = expand_spans(parser.tables[0])
            parsed.append({
                'match': m,
                'grid': grid,
            })
        else:
            parsed.append({
                'match': m,
                'grid': None,
            })

    # 合并相邻的同结构表格（PDF跨页拆分）
    merged_groups = []
    i = 0
    while i < len(parsed):
        if parsed[i]['grid'] is None:
            merged_groups.append(parsed[i])
            i += 1
            continue

        group = [parsed[i]]
        j = i + 1

        while j < len(parsed):
            if parsed[j]['grid'] is None:
                break

            # 检查两个表格之间的文本是否只有空白
            between_start = group[-1]['match'].end()
            between_end = parsed[j]['match'].start()
            between_text = content[between_start:between_end].strip()

            # 如果中间只有空白或换行，且表格结构相似，则合并
            if not between_text and tables_share_structure(group[-1]['grid'], parsed[j]['grid']):
                group.append(parsed[j])
                j += 1
            else:
                break

        merged_groups.append(group if len(group) > 1 else group[0])
        i = j

    # 从后往前替换，避免位置偏移
    result = content
    for item in reversed(merged_groups):
        if isinstance(item, list):
            # 合并组：将多个表格合并为一个
            first_match = item[0]['match']
            last_match = item[-1]['match']

            # 先对每个子表格去空列，统一列数后再合并
            grids = [remove_empty_columns(sub['grid']) for sub in item]
            max_cols = max(len(g[0]) for g in grids if g and g[0])

            # 统一列数（不足的补空列）
            for g in grids:
                for row in g:
                    while len(row) < max_cols:
                        row.append("")

            # 合并网格：第一个表格完整保留，后续表格去掉表头
            combined_grid = list(grids[0])
            for sub_grid in grids[1:]:
                if sub_grid and len(sub_grid) > 1:
                    combined_grid.extend(sub_grid[1:])
                elif sub_grid:
                    combined_grid.extend(sub_grid)

            combined_grid = remove_duplicate_headers(combined_grid)
            combined_grid = merge_split_rows(combined_grid)
            combined_grid = remove_empty_columns(combined_grid)
            md = grid_to_markdown(combined_grid)

            start = first_match.start()
            end = last_match.end()
            result = result[:start] + "\n\n" + md + "\n\n" + result[end:]
        else:
            # 单个表格
            m = item['match']
            grid = item['grid']
            if grid is None:
                continue
            grid = process_grid(grid)
            md = grid_to_markdown(grid)
            result = result[:m.start()] + "\n\n" + md + "\n\n" + result[m.end():]

    return result


def fix_md_file(input_path, output_path=None):
    """修复单个 Markdown 文件"""
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.parent / (input_path.stem + "_fixed.md")
    else:
        output_path = Path(output_path)

    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    fixed = convert_html_tables_in_md(content)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(fixed)

    original_count = len(re.findall(r'<table>', content))
    print(f"✓ 转换完成！")
    print(f"  输入: {input_path}")
    print(f"  输出: {output_path}")
    print(f"  转换表格数: {original_count}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python fix_md_tables.py <输入文件.md> [输出文件.md]")
        print("  如果不指定输出文件，默认生成 _fixed.md 后缀文件")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    fix_md_file(input_file, output_file)
