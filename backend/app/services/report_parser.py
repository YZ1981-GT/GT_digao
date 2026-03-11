"""审计报告文件解析服务。

继承 WorkpaperParser 的文件解析能力（Excel/Word），
新增审计报告专用的报表科目识别、附注表格提取、文件分类等功能。
"""
import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..models.audit_schemas import (
    NoteTable,
    ReportFileType,
    ReportReviewSession,
    ReportSheetData,
    ReportTemplateType,
    StatementItem,
    StatementType,
)
from .workpaper_parser import WorkpaperParser

logger = logging.getLogger(__name__)


class ReportParser(WorkpaperParser):
    """审计报告文件解析服务，继承 WorkpaperParser 的文件解析能力。"""

    # Sheet 名称 → 报表类型映射关键词
    STATEMENT_TYPE_KEYWORDS: Dict[StatementType, List[str]] = {
        StatementType.BALANCE_SHEET: ["资产负债", "balance sheet", "资产负债表"],
        StatementType.INCOME_STATEMENT: ["利润", "损益", "income", "profit", "利润表"],
        StatementType.CASH_FLOW: ["现金流量", "cash flow", "现金流量表"],
        StatementType.EQUITY_CHANGE: ["所有者权益变动", "权益变动", "equity", "股东权益变动"],
    }

    # 文件分类关键词
    FILE_CLASSIFY_KEYWORDS: Dict[ReportFileType, List[str]] = {
        ReportFileType.AUDIT_REPORT_BODY: ["审计报告", "审计意见", "独立审计"],
        ReportFileType.FINANCIAL_STATEMENT: ["财务报表", "资产负债表", "利润表", "现金流量表", "报表"],
        ReportFileType.NOTES_TO_STATEMENTS: ["附注", "财务报表附注", "报表附注", "notes"],
    }

    # 其中项识别关键词
    SUB_ITEM_KEYWORDS = ["其中：", "其中:", "其中", "  其中"]

    # ─── Public API ───

    async def parse_report_files(
        self,
        files: List[Tuple[str, str]],
        template_type: ReportTemplateType,
    ) -> ReportReviewSession:
        """多文件上传统一入口，解析所有文件并关联到同一复核会话。

        Args:
            files: [(file_path, filename), ...]
            template_type: 模板类型 soe/listed

        Returns:
            ReportReviewSession 包含解析后的所有数据
        """
        session_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        file_ids: List[str] = []
        file_classifications: Dict[str, ReportFileType] = {}
        all_sheet_data: Dict[str, List[ReportSheetData]] = {}
        all_statement_items: List[StatementItem] = []
        all_note_tables: List[NoteTable] = []

        for file_path, filename in files:
            file_id = str(uuid.uuid4())
            file_ids.append(file_id)
            ext = os.path.splitext(filename)[1].lower()

            # 基础校验
            if ext not in self.SUPPORTED_FORMATS:
                raise ValueError(
                    f"不支持的文件格式：{ext}，支持格式：{', '.join(sorted(self.SUPPORTED_FORMATS))}"
                )
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"文件不存在：{filename}")
            file_size = os.path.getsize(file_path)
            if file_size > self.MAX_FILE_SIZE:
                raise ValueError(f"文件大小超过限制（{self.MAX_FILE_SIZE // (1024 * 1024)}MB）：{filename}")

            # 解析文件
            if ext in ('.xlsx', '.xls'):
                excel_result = await self.parse_excel(file_path, ext)
                # 分类文件
                file_type = self.classify_report_file(filename, self._excel_to_text(excel_result))
                file_classifications[file_id] = file_type

                # 提取 Sheet 数据
                sheets = self.extract_sheets(excel_result)
                all_sheet_data[file_id] = sheets

                # 从每个 Sheet 提取科目
                for sheet in sheets:
                    items = self.extract_statement_items(sheet)
                    all_statement_items.extend(items)

            elif ext in ('.docx', '.doc'):
                word_result = await self.parse_word(file_path)
                content_text = self._word_to_text(word_result)
                file_type = self.classify_report_file(filename, content_text)
                file_classifications[file_id] = file_type

                # 从 Word 提取附注表格
                note_tables = self.extract_note_tables(word_result)
                all_note_tables.extend(note_tables)

            elif ext == '.pdf':
                pdf_result = await self.parse_pdf(file_path)
                file_type = self.classify_report_file(filename, pdf_result.text)
                file_classifications[file_id] = file_type

        return ReportReviewSession(
            id=session_id,
            template_type=template_type,
            file_ids=file_ids,
            file_classifications=file_classifications,
            sheet_data=all_sheet_data,
            statement_items=all_statement_items,
            note_tables=all_note_tables,
            status="parsed",
            created_at=now_iso,
        )

    def classify_report_file(self, filename: str, content: str) -> ReportFileType:
        """基于文件名和内容特征分类文件类型。

        Args:
            filename: 文件名
            content: 文件文本内容

        Returns:
            ReportFileType 枚举值
        """
        text = (filename + " " + content[:2000]).lower()

        # 按优先级匹配：附注 > 审计报告正文 > 财务报表
        # 附注通常包含"附注"关键词
        for keyword in self.FILE_CLASSIFY_KEYWORDS[ReportFileType.NOTES_TO_STATEMENTS]:
            if keyword.lower() in text:
                return ReportFileType.NOTES_TO_STATEMENTS

        for keyword in self.FILE_CLASSIFY_KEYWORDS[ReportFileType.AUDIT_REPORT_BODY]:
            if keyword.lower() in text:
                return ReportFileType.AUDIT_REPORT_BODY

        # Excel 文件默认归类为财务报表
        ext = os.path.splitext(filename)[1].lower()
        if ext in ('.xlsx', '.xls'):
            return ReportFileType.FINANCIAL_STATEMENT

        # Word/PDF 默认归类为附注
        return ReportFileType.NOTES_TO_STATEMENTS

    def extract_sheets(self, excel_result) -> List[ReportSheetData]:
        """从 Excel 解析结果中逐 Sheet 提取数据，自动识别报表类型。

        Args:
            excel_result: ExcelParseResult

        Returns:
            List[ReportSheetData]
        """
        sheets: List[ReportSheetData] = []

        for sheet_data in excel_result.sheets:
            sheet_name = sheet_data.name
            statement_type = self._identify_statement_type(sheet_name, sheet_data.cells)

            # 按行组织单元格数据
            rows_map: Dict[int, List[Tuple[int, Any]]] = {}
            for cell in sheet_data.cells:
                rows_map.setdefault(cell.row, []).append((cell.col, cell.value))

            if not rows_map:
                sheets.append(ReportSheetData(
                    sheet_name=sheet_name,
                    statement_type=statement_type,
                    row_count=0,
                    headers=[],
                    raw_data=[],
                ))
                continue

            sorted_rows = sorted(rows_map.keys())
            max_col = max(c for row_cells in rows_map.values() for c, _ in row_cells) if rows_map else 0

            # 第一行作为表头
            headers: List[str] = []
            raw_data: List[List[Any]] = []

            for idx, row_num in enumerate(sorted_rows):
                row_cells = sorted(rows_map[row_num], key=lambda x: x[0])
                # 构建完整行（填充空列）
                row_values: List[Any] = [None] * max_col
                for col, val in row_cells:
                    if 1 <= col <= max_col:
                        row_values[col - 1] = val

                if idx == 0:
                    headers = [str(v) if v is not None else "" for v in row_values]
                else:
                    raw_data.append(row_values)

            sheets.append(ReportSheetData(
                sheet_name=sheet_name,
                statement_type=statement_type,
                row_count=len(raw_data),
                headers=headers,
                raw_data=raw_data,
            ))

        return sheets

    def extract_statement_items(self, sheet_data: ReportSheetData) -> List[StatementItem]:
        """从单个 Sheet 中识别报表科目，含其中项明细和父子关系。

        Args:
            sheet_data: ReportSheetData

        Returns:
            List[StatementItem]
        """
        items: List[StatementItem] = []
        current_parent_id: Optional[str] = None
        in_sub_items = False

        for row_idx, row in enumerate(sheet_data.raw_data):
            if not row or all(v is None for v in row):
                continue

            # 第一列通常是科目名称
            account_name = self._extract_account_name(row)
            if not account_name:
                continue

            # 跳过表头行和合计行
            if self._is_header_or_total_row(account_name):
                in_sub_items = False
                continue

            # 检测是否为其中项
            is_sub = self._is_sub_item(account_name)
            if is_sub:
                in_sub_items = True
                account_name = self._clean_sub_item_name(account_name)
            else:
                in_sub_items = False

            item_id = str(uuid.uuid4())

            # 解析金额
            opening_balance, closing_balance, warnings = self._parse_amounts(
                row, sheet_data.statement_type
            )

            item = StatementItem(
                id=item_id,
                account_name=account_name.strip(),
                statement_type=sheet_data.statement_type,
                sheet_name=sheet_data.sheet_name,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                parent_id=current_parent_id if is_sub else None,
                is_sub_item=is_sub,
                row_index=row_idx,
                parse_warnings=warnings,
            )
            items.append(item)

            # 非其中项时更新当前父科目
            if not is_sub:
                current_parent_id = item_id

        return items

    def extract_note_tables(self, word_result) -> List[NoteTable]:
        """从 Word 解析结果中提取附注表格及其标题上下文。

        利用 table_contexts（按文档顺序记录每个表格前最近的段落文本）
        来准确关联表格与其所属的附注科目。

        Args:
            word_result: WordParseResult

        Returns:
            List[NoteTable]
        """
        note_tables: List[NoteTable] = []

        # 从段落中构建科目标题索引
        # 匹配 "1、货币资金" "2、应收票据" "(1) 应收票据分类" 等格式
        note_item_pattern = re.compile(
            r'^[（(]?\s*[\d一二三四五六七八九十]+\s*[）)、.\s]\s*(.+)'
        )

        # 当前科目上下文（从段落中追踪）
        current_note_account = ""
        current_section_title = ""

        for table_idx, table_data in enumerate(word_result.tables):
            if not table_data or len(table_data) < 2:
                continue

            # 使用 table_contexts 获取表格前最近的段落文本
            context_text = ""
            if table_idx < len(word_result.table_contexts):
                context_text = word_result.table_contexts[table_idx]

            # 从上下文推断科目名称
            section_title = context_text
            account_name = self._extract_account_from_heading(context_text)

            # 如果上下文是子标题（如 "(1) 应收票据分类"），向上查找主科目
            if not account_name and context_text:
                account_name = context_text

            # 表头和数据行
            headers = [str(h).strip() for h in table_data[0]] if table_data else []
            rows = table_data[1:] if len(table_data) > 1 else []

            note_tables.append(NoteTable(
                id=str(uuid.uuid4()),
                account_name=account_name or f"附注表格 {table_idx + 1}",
                section_title=section_title,
                headers=headers,
                rows=rows,
                source_location=f"表格 {table_idx + 1}",
            ))

        return note_tables

    # ─── Private helpers ───

    def _identify_statement_type(self, sheet_name: str, cells) -> StatementType:
        """根据 Sheet 名称和内容识别报表类型。"""
        name_lower = sheet_name.lower()

        for st_type, keywords in self.STATEMENT_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in name_lower:
                    return st_type

        # 从内容中识别（取前几行文本）
        content_text = ""
        for cell in cells[:50]:
            if cell.value and isinstance(cell.value, str):
                content_text += cell.value + " "

        content_lower = content_text.lower()
        for st_type, keywords in self.STATEMENT_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in content_lower:
                    return st_type

        # 默认归类为资产负债表
        return StatementType.BALANCE_SHEET

    @staticmethod
    def _extract_account_name(row: List[Any]) -> str:
        """从行数据中提取科目名称（通常在第一个非空文本列）。"""
        for val in row:
            if val is not None and isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    @staticmethod
    def _is_header_or_total_row(name: str) -> bool:
        """判断是否为表头行或合计行。"""
        # 先去除中间空格再匹配（Excel 中 "项 目" 等情况）
        name_normalized = re.sub(r'\s+', '', name.strip())
        skip_keywords = [
            "合计", "总计", "资产总计", "负债和所有者权益总计",
            "负债合计", "所有者权益合计", "项目", "科目",
            "期末余额", "期初余额", "本期金额", "上期金额",
            "流动资产：", "流动资产:", "非流动资产：", "非流动资产:",
            "流动负债：", "流动负债:", "非流动负债：", "非流动负债:",
            "所有者权益：", "所有者权益:", "所有者权益（或股东权益）：",
            # 表头标题行
            "资产负债表", "利润表", "现金流量表", "所有者权益变动表",
            "合并资产负债表", "合并利润表", "合并现金流量表", "合并所有者权益变动表",
            "编制单位", "单位：", "单位:", "币种：", "币种:",
            "审计", "会计期间",
        ]
        for kw in skip_keywords:
            kw_normalized = re.sub(r'\s+', '', kw)
            if name_normalized == kw_normalized or name_normalized.startswith(kw_normalized):
                return True
        # 跳过纯年份/日期行（如 "2025年" "2025年12月31日"）
        if re.match(r'^\d{4}年', name_normalized):
            return True
        return False

    def _is_sub_item(self, name: str) -> bool:
        """判断是否为其中项。"""
        for kw in self.SUB_ITEM_KEYWORDS:
            if name.strip().startswith(kw):
                return True
        return False

    @staticmethod
    def _clean_sub_item_name(name: str) -> str:
        """清理其中项名称前缀。"""
        cleaned = re.sub(r'^其中[：:]?\s*', '', name.strip())
        return cleaned.strip()

    def _parse_amounts(
        self, row: List[Any], statement_type: StatementType
    ) -> Tuple[Optional[float], Optional[float], List[str]]:
        """从行数据中解析期初/期末金额。

        策略：从行的右侧向左取最后两个数值列，因为报表格式通常为：
        科目名 | [附注编号] | ... | 期末余额 | 期初余额
        右侧最后一个数值列 = 期初余额，倒数第二个 = 期末余额。
        小整数（如附注编号 1-99）在左侧列中会被跳过。

        Returns:
            (opening_balance, closing_balance, parse_warnings)
        """
        warnings: List[str] = []

        # 收集所有列的 (col_index, parsed_value) 对
        col_values: List[Tuple[int, Optional[float]]] = []
        for col_idx, val in enumerate(row):
            parsed = self._try_parse_number(val)
            if parsed is not None:
                col_values.append((col_idx, parsed))
            elif val is not None and isinstance(val, str) and val.strip() and not self._is_text_value(val):
                stripped = val.strip()
                if stripped not in ('-', '—', '/', ''):
                    warnings.append(f"金额无法解析：'{val}'")

        # 过滤掉可能的附注编号：位于前半部分且为小整数（1-999）的值
        # 报表金额通常 >= 1000 或为 0 / 负数
        if len(col_values) >= 3:
            # 有3个以上数值时，排除前面的小整数（附注编号）
            half = len(row) // 2
            filtered = []
            for col_idx, val in col_values:
                # 前半部分的小正整数（1-999）很可能是附注编号
                if col_idx < half and val is not None and val == int(val) and 1 <= val <= 999:
                    continue
                filtered.append((col_idx, val))
            if len(filtered) >= 2:
                col_values = filtered

        # 从右侧取最后两个数值作为期末/期初
        closing_balance = None
        opening_balance = None

        if len(col_values) >= 2:
            # 倒数第一个 = 期初余额，倒数第二个 = 期末余额
            closing_balance = col_values[-2][1]
            opening_balance = col_values[-1][1]
        elif len(col_values) == 1:
            closing_balance = col_values[-1][1]

        return opening_balance, closing_balance, warnings

    @staticmethod
    def _try_parse_number(val: Any) -> Optional[float]:
        """尝试将值解析为数字。"""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            cleaned = val.strip().replace(',', '').replace('，', '').replace(' ', '')
            if not cleaned or cleaned in ('-', '—', '/', ''):
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @staticmethod
    def _is_text_value(val: str) -> bool:
        """判断值是否为纯文本（非数值）。"""
        text = val.strip()
        if not text:
            return True
        # 包含中文字符的视为文本
        if re.search(r'[\u4e00-\u9fff]', text):
            return True
        return False

    def _find_table_heading(self, paragraphs, table_idx: int, tables) -> str:
        """查找表格前最近的标题。

        简化策略：遍历段落，按表格出现顺序关联标题。
        """
        # 收集所有标题
        headings = []
        for para in paragraphs:
            text = para.get("text", "").strip()
            level = para.get("level")
            if level is not None and text:
                headings.append(text)
            elif text and re.match(r'^[（(]?\d+[）)]', text):
                # 匹配 "(1)" 或 "（一）" 等编号格式的标题
                headings.append(text)

        # 简单映射：第 N 个表格对应第 N 个标题（如果有）
        if table_idx < len(headings):
            return headings[table_idx]
        elif headings:
            return headings[-1]
        return f"附注表格 {table_idx + 1}"

    @staticmethod
    def _extract_account_from_heading(heading: str) -> str:
        """从标题中提取科目名称。"""
        if not heading:
            return ""
        # 去除编号前缀，如 "（一）" "1." "1、" 等
        cleaned = re.sub(r'^[（(]?[\d一二三四五六七八九十]+[）)、.\s]+', '', heading)
        # 去除常见后缀
        cleaned = re.sub(r'[（(]续[）)]$', '', cleaned)
        return cleaned.strip()


# 模块级单例
report_parser = ReportParser()
