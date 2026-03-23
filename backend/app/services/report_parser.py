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
    NoteSection,
    NoteTable,
    ReportFileType,
    ReportReviewSession,
    ReportSheetData,
    ReportTemplateType,
    StatementItem,
    StatementType,
)
from .workpaper_parser import WorkpaperParser
from .heading_utils import (
    infer_numbering_level,
    detect_heading_level as _unified_detect_heading,
    detect_flat_style_mode,
)

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

    # 辅助性 Sheet 名称关键词 — 这些 Sheet 不是正式报表，应跳过科目提取
    SKIP_SHEET_KEYWORDS: List[str] = [
        "横纵加", "校验", "辅助", "参数", "配置", "勾稽",
        "custom", "config", "setting", "template",
        "目录", "封面", "说明", "备注",
        "增加额", "调整",
    ]

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

        # ── 去重：同名科目保留来自正式报表 Sheet 的版本 ──
        # 国企版 Excel 常含辅助 Sheet（增加额、横纵加等），可能产生重复科目
        FORMAL_SHEET_KW = ["资产负债", "利润", "损益", "现金流量", "权益变动"]
        def _is_formal_sheet(name: str) -> bool:
            return any(kw in name for kw in FORMAL_SHEET_KW)

        seen: Dict[str, StatementItem] = {}  # key = (account_name, statement_type)
        deduped_items: List[StatementItem] = []
        for item in all_statement_items:
            key = f"{item.account_name}|{item.statement_type}|{item.is_sub_item}"
            existing = seen.get(key)
            if existing is None:
                seen[key] = item
                deduped_items.append(item)
            else:
                # 优先保留来自正式报表 Sheet 的科目
                new_formal = _is_formal_sheet(item.sheet_name)
                old_formal = _is_formal_sheet(existing.sheet_name)
                if new_formal and not old_formal:
                    # 替换：从 deduped 中移除旧的，加入新的
                    deduped_items = [x for x in deduped_items if x.id != existing.id]
                    deduped_items.append(item)
                    seen[key] = item
                    logger.info("[parse_report_files] 去重：'%s' 保留 Sheet '%s'，丢弃 Sheet '%s'",
                                item.account_name, item.sheet_name, existing.sheet_name)
                elif new_formal == old_formal and (
                    (existing.closing_balance is None and existing.opening_balance is None)
                    and (item.closing_balance is not None or item.opening_balance is not None)
                ):
                    # 都是正式/非正式时，保留有余额的
                    deduped_items = [x for x in deduped_items if x.id != existing.id]
                    deduped_items.append(item)
                    seen[key] = item
                # 否则保留已有的（先到先得）

        if len(deduped_items) < len(all_statement_items):
            logger.info("[parse_report_files] 科目去重：%d → %d",
                        len(all_statement_items), len(deduped_items))
        all_statement_items = deduped_items

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

        # 先按文件名精确匹配
        fn_lower = filename.lower()

        # 文件名包含"附注"且不包含"审计报告" -> 附注
        if any(kw.lower() in fn_lower for kw in ['附注', 'notes']):
            return ReportFileType.NOTES_TO_STATEMENTS

        # 文件名包含"审计报告" -> 审计报告正文
        if any(kw.lower() in fn_lower for kw in ['审计报告', '审计意见', '独立审计']):
            return ReportFileType.AUDIT_REPORT_BODY

        # 文件名无法判断时，按内容特征分类
        # 审计报告正文特征：包含"审计意见""我们审计了""注册会计师"等
        audit_body_signals = ['审计意见', '我们审计了', '注册会计师', '审计报告', '独立审计']
        # 附注特征：包含"会计政策""报表附注""财务报表主要项目"等
        notes_signals = ['会计政策', '报表附注', '财务报表主要项目', '会计估计']

        body_score = sum(1 for kw in audit_body_signals if kw in text)
        notes_score = sum(1 for kw in notes_signals if kw in text)

        if body_score > notes_score:
            return ReportFileType.AUDIT_REPORT_BODY
        if notes_score > 0:
            return ReportFileType.NOTES_TO_STATEMENTS

        # Excel 文件默认归类为财务报表
        ext = os.path.splitext(filename)[1].lower()
        if ext in ('.xlsx', '.xls'):
            return ReportFileType.FINANCIAL_STATEMENT

        # Word/PDF 默认归类为附注
        return ReportFileType.NOTES_TO_STATEMENTS

    # 合并/公司列关键词
    CONSOLIDATED_KW = ['合并', '合并数']
    COMPANY_KW = ['公司', '母公司', '公司数']

    def extract_sheets(self, excel_result) -> List[ReportSheetData]:
        """从 Excel 解析结果中逐 Sheet 提取数据，自动识别报表类型。

        支持合并财务报表的多行表头（2行结构），识别合并/公司列。
        典型结构：
          行1: 项目 | 附注 | 期末余额(合并单元格) |       | 上年年末余额(合并单元格) |
          行2:      |      | 合并                | 公司   | 合并                    | 公司

        Args:
            excel_result: ExcelParseResult

        Returns:
            List[ReportSheetData]
        """
        sheets: List[ReportSheetData] = []

        for sheet_data in excel_result.sheets:
            sheet_name = sheet_data.name
            statement_type = self._identify_statement_type(sheet_name, sheet_data.cells)

            # 跳过辅助性 Sheet
            if statement_type is None:
                logger.info("[extract_sheets] Skipping auxiliary sheet: %s", sheet_name)
                continue

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

            # 构建所有行的值数组
            all_row_values: List[List[Any]] = []
            for row_num in sorted_rows:
                row_cells = sorted(rows_map[row_num], key=lambda x: x[0])
                row_values: List[Any] = [None] * max_col
                for col, val in row_cells:
                    if 1 <= col <= max_col:
                        row_values[col - 1] = val
                all_row_values.append(row_values)

            # 调试日志：输出前10行的内容，帮助排查表头识别问题
            logger.info(f"[extract_sheets] Sheet '{sheet_name}': {len(all_row_values)} rows, max_col={max_col}")
            for dbg_i, dbg_row in enumerate(all_row_values[:10]):
                non_none = [(ci, v) for ci, v in enumerate(dbg_row) if v is not None]
                logger.info(f"  Row[{dbg_i}] (excel_row={sorted_rows[dbg_i]}): {non_none}")
            if sheet_data.merged_ranges:
                logger.info(f"  Merged ranges: {sheet_data.merged_ranges[:20]}")

            # ── 识别表头行：找到"项目"行及其后续的合并/公司子表头行 ──
            header_start_idx, header_end_idx = self._detect_header_rows(
                all_row_values, sheet_data.merged_ranges, sorted_rows
            )

            header_rows_raw: List[List[str]] = []
            for i in range(header_start_idx, header_end_idx + 1):
                header_rows_raw.append(
                    [str(v) if v is not None else "" for v in all_row_values[i]]
                )

            # ── 检测合并/公司列结构 ──
            # 传入表头行对应的 Excel 实际行号，用于匹配合并单元格范围
            header_excel_rows = [sorted_rows[i] for i in range(header_start_idx, header_end_idx + 1)]
            is_consolidated, column_map, data_col_end = self._detect_consolidated_columns(
                header_rows_raw, sheet_data.merged_ranges, max_col, header_excel_rows
            )

            # 如果检测到合并报表但只有单行表头，自动生成2行表头（补充合并/公司标签）
            if is_consolidated and len(header_rows_raw) == 1 and column_map:
                sub_row = [''] * len(header_rows_raw[0])
                for key, ci in column_map.items():
                    if ci < len(sub_row):
                        if 'consolidated' in key:
                            sub_row[ci] = '合并'
                        elif 'company' in key:
                            sub_row[ci] = '公司'
                header_rows_raw.append(sub_row)
                logger.info(f"[extract_sheets] Auto-generated sub-header row for consolidated sheet: {sub_row}")

            # 合并多行表头为单行语义表头
            merged_headers = self._merge_header_rows(header_rows_raw, data_col_end)

            # 数据行 = 表头之后的行
            raw_data = all_row_values[header_end_idx + 1:]

            # 如果检测到右边界，截断数据列
            if data_col_end is not None and data_col_end < max_col:
                raw_data = [row[:data_col_end] for row in raw_data]
                merged_headers = merged_headers[:data_col_end]
                header_rows_raw = [row[:data_col_end] for row in header_rows_raw]

            sheets.append(ReportSheetData(
                sheet_name=sheet_name,
                statement_type=statement_type,
                row_count=len(raw_data),
                headers=merged_headers,
                header_rows=header_rows_raw,
                raw_data=raw_data,
                is_consolidated=is_consolidated,
                column_map=column_map,
                data_col_end=data_col_end,
            ))

        # ── 续表继承：如果续表未检测到合并列结构，从同类型主表继承 ──
        main_sheet_map: Dict[str, ReportSheetData] = {}
        for sd in sheets:
            # 主表：非续表、有合并列结构
            name_norm = sd.sheet_name.replace(' ', '')
            if '续' not in name_norm and sd.is_consolidated and sd.column_map:
                main_sheet_map[sd.statement_type] = sd

        for sd in sheets:
            name_norm = sd.sheet_name.replace(' ', '')
            if '续' in name_norm and not sd.is_consolidated:
                main = main_sheet_map.get(sd.statement_type)
                if main and main.column_map:
                    # 检查续表的列数是否与主表兼容
                    max_col_idx = max(main.column_map.values()) if main.column_map else 0
                    data_cols = len(sd.headers) if sd.headers else (len(sd.raw_data[0]) if sd.raw_data else 0)
                    if data_cols > max_col_idx:
                        sd.is_consolidated = True
                        sd.column_map = dict(main.column_map)
                        sd.data_col_end = main.data_col_end
                        logger.info(
                            f"[extract_sheets] Continuation sheet '{sd.sheet_name}' "
                            f"inherited column_map from '{main.sheet_name}': {sd.column_map}"
                        )

        return sheets

    def _detect_header_rows(
        self, all_rows: List[List[Any]], merged_ranges: List[str],
        sorted_excel_rows: Optional[List[int]] = None
    ) -> Tuple[int, int]:
        """检测表头的起止行索引（支持多行表头）。

        策略：
        0. (向上扫描) "项目"行上方若有第一列为空、含非空文本的行，视为父表头行
        1. 找到包含"项目"的行作为表头起始行
        2. 检查下一行是否包含"合并"/"公司"等子表头关键词
        3. 或者检查表头行是否有跨行的合并单元格（如 C3:D4 表示2行表头）
        4. 或者检查下一行第一列为空但有其他非空文本列（子表头特征）

        Args:
            all_rows: 所有行的值数组
            merged_ranges: 合并单元格范围字符串列表
            sorted_excel_rows: all_rows 中每行对应的 Excel 实际行号

        Returns:
            (header_start_idx, header_end_idx) 基于 all_rows 的索引
        """
        header_kw = ['项目', '项 目']
        header_start = 0

        # 解析合并单元格范围，用于后续判断
        # merged_ranges 格式如 ['C3:D4', 'E3:F4'] 或 ['C1:D1']
        parsed_merges = self._parse_merged_ranges(merged_ranges)

        for ri, row in enumerate(all_rows[:10]):
            first_cell = str(row[0] if row[0] is not None else '').replace(' ', '')
            if any(kw.replace(' ', '') == first_cell for kw in header_kw):
                header_start = ri
                break

        # ── 策略0：向上扫描，检查"项目"行上方是否有父表头行 ──
        # 典型场景：行4="期末余额|期初余额"，行5="项目|附注|合并|公司|合并|公司"
        # "项目"在行5，但行4也是表头的一部分
        while header_start > 0:
            prev_row = all_rows[header_start - 1]
            prev_first = str(prev_row[0] if prev_row[0] is not None else '').strip()
            prev_texts = [
                str(v).strip() for v in prev_row if v is not None and str(v).strip()
            ]
            # 上一行第一列为空，且有非空文本列，且不含大数字 → 父表头行
            if prev_first:
                break
            if len(prev_texts) < 1:
                break
            has_large_nums = any(
                self._try_parse_number(v) is not None and abs(self._try_parse_number(v)) >= 1000
                for v in prev_row if v is not None
            )
            if has_large_nums:
                break
            header_start -= 1
            logger.info(f"[_detect_header_rows] Strategy 0: extended header_start upward to idx {header_start}, texts={prev_texts}")

        header_end = header_start
        # 找到"项目"行的索引（可能因向上扫描而不再是 header_start）
        project_row_idx = header_start
        for ri in range(header_start, min(header_start + 5, len(all_rows))):
            first_cell = str(all_rows[ri][0] if all_rows[ri][0] is not None else '').replace(' ', '')
            if any(kw.replace(' ', '') == first_cell for kw in header_kw):
                project_row_idx = ri
                header_end = ri  # 至少包含到"项目"行
                break
        # 对应的 Excel 实际行号（sorted_rows 中的索引 → 实际行号）
        # 注意：all_rows 的索引和 Excel 行号可能不一致，但 merged_ranges 用的是 Excel 行号
        # 我们需要通过 all_rows 的内容来判断

        if project_row_idx + 1 < len(all_rows):
            next_row = all_rows[project_row_idx + 1]
            next_row_texts = [
                str(v).strip() for v in next_row if v is not None and str(v).strip()
            ]
            logger.info(f"[_detect_header_rows] header_start={header_start}, project_row_idx={project_row_idx}, next_row_texts={next_row_texts}")

            # 策略1：下一行包含"合并"/"公司"关键词
            has_consolidated = any(
                any(kw in t for kw in self.CONSOLIDATED_KW) for t in next_row_texts
            )
            has_company = any(
                any(kw in t for kw in self.COMPANY_KW) for t in next_row_texts
            )
            logger.info(f"[_detect_header_rows] has_consolidated={has_consolidated}, has_company={has_company}")

            if has_consolidated or has_company:
                header_end = project_row_idx + 1
            else:
                # 策略2：检查是否有跨行的合并单元格覆盖了表头行
                # 需要知道 all_rows 索引对应的 Excel 实际行号
                if sorted_excel_rows and project_row_idx < len(sorted_excel_rows):
                    excel_header_row = sorted_excel_rows[project_row_idx]
                    for mr in parsed_merges:
                        if mr['row_span'] > 1 and mr['min_row'] <= excel_header_row <= mr['max_row']:
                            extra_rows = mr['max_row'] - excel_header_row
                            if extra_rows > 0 and project_row_idx + extra_rows < len(all_rows):
                                header_end = max(header_end, project_row_idx + extra_rows)
                                logger.info(f"[_detect_header_rows] Strategy 2: multi-row merge {mr}, extending header to idx {header_end}")

                # 策略3：下一行第一列为空，但有其他非空文本（子表头特征）
                if header_end == project_row_idx and next_row_texts:
                    first_of_next = next_row[0] if next_row[0] is not None else ''
                    first_of_next_str = str(first_of_next).strip()
                    has_large_numbers = any(
                        self._try_parse_number(v) is not None and abs(self._try_parse_number(v)) >= 1000
                        for v in next_row if v is not None
                    )
                    if not first_of_next_str and len(next_row_texts) >= 2 and not has_large_numbers:
                        header_end = project_row_idx + 1
                        logger.info(f"[_detect_header_rows] Strategy 3: sub-header detected (empty first col, {len(next_row_texts)} text cols)")

        # ── 继续向下扫描更多表头行（权益变动表等可能有3行以上表头） ──
        # 判断标准：下一行第一列为空，且有多个非空文本列，且不含大数字
        while header_end + 1 < len(all_rows) and header_end < header_start + 5:
            candidate_row = all_rows[header_end + 1]
            candidate_first = str(candidate_row[0] if candidate_row[0] is not None else '').strip()
            candidate_texts = [
                str(v).strip() for v in candidate_row if v is not None and str(v).strip()
            ]
            # 如果第一列有文本内容（非空），说明已经是数据行了
            if candidate_first:
                break
            # 如果没有非空文本列，说明是空行
            if len(candidate_texts) < 2:
                break
            # 如果包含大数字，说明是数据行
            has_large_nums = any(
                self._try_parse_number(v) is not None and abs(self._try_parse_number(v)) >= 1000
                for v in candidate_row if v is not None
            )
            if has_large_nums:
                break
            # 通过了所有检查，这是一个子表头行
            header_end += 1
            logger.info(f"[_detect_header_rows] Extended header to idx {header_end}, texts={candidate_texts}")

        logger.info(f"[_detect_header_rows] result: header_start={header_start}, header_end={header_end}")
        return header_start, header_end

    @staticmethod
    def _parse_merged_ranges(merged_ranges: List[str]) -> List[Dict[str, int]]:
        """解析合并单元格范围字符串为结构化数据。

        Args:
            merged_ranges: ['A1:B2', 'C3:D4'] 格式的合并范围

        Returns:
            [{'min_row': 1, 'max_row': 2, 'min_col': 1, 'max_col': 2, 'row_span': 2, 'col_span': 2}, ...]
        """
        result = []
        pattern = re.compile(r'([A-Z]+)(\d+):([A-Z]+)(\d+)')
        for mr_str in merged_ranges:
            m = pattern.match(mr_str)
            if m:
                min_col = 0
                for ch in m.group(1):
                    min_col = min_col * 26 + (ord(ch) - ord('A') + 1)
                min_row = int(m.group(2))
                max_col = 0
                for ch in m.group(3):
                    max_col = max_col * 26 + (ord(ch) - ord('A') + 1)
                max_row = int(m.group(4))
                result.append({
                    'min_row': min_row, 'max_row': max_row,
                    'min_col': min_col, 'max_col': max_col,
                    'row_span': max_row - min_row + 1,
                    'col_span': max_col - min_col + 1,
                })
        return result

    # 期末/期初关键词（用于判断表头列组归属）
    _CLOSING_HEADER_KW = ['期末', '年末', '本期', '本年']
    _OPENING_HEADER_KW = ['期初', '年初', '上期', '上年']

    def _detect_consolidated_columns(
        self,
        header_rows: List[List[str]],
        merged_ranges: List[str],
        max_col: int,
        header_excel_rows: Optional[List[int]] = None,
    ) -> Tuple[bool, Dict[str, int], Optional[int]]:
        """检测合并/公司列结构，返回列映射和数据右边界。

        对于合并财务报表，典型的表头结构为：
          行1: 项目 | 附注 | 期末余额 |      | 上年年末余额 |
          行2:      |      | 合并     | 公司  | 合并         | 公司

        Returns:
            (is_consolidated, column_map, data_col_end)
            column_map: {
                'closing_consolidated': col_idx,
                'closing_company': col_idx,
                'opening_consolidated': col_idx,
                'opening_company': col_idx,
            }
            data_col_end: 最右侧公司列的索引+1（用于截断），None表示不截断
        """
        column_map: Dict[str, int] = {}
        is_consolidated = False
        data_col_end: Optional[int] = None

        def _is_opening_text(text: str) -> bool:
            """判断文本是否为期初/上期类关键词。"""
            return any(kw in text for kw in self._OPENING_HEADER_KW)

        def _is_closing_text(text: str) -> bool:
            """判断文本是否为期末/本期类关键词（排除同时含期初关键词的情况）。"""
            return (any(kw in text for kw in self._CLOSING_HEADER_KW)
                    and not _is_opening_text(text))

        # 即使只有单行表头，也尝试通过合并单元格范围推断列结构
        if len(header_rows) >= 1:
            parent_row = header_rows[0]
            parsed_merges = self._parse_merged_ranges(merged_ranges)
            parent_excel_row = header_excel_rows[0] if header_excel_rows else None

            logger.info(
                f"[_detect_consolidated_columns] parent_row[0..5]={parent_row[:6]}, "
                f"parent_excel_row={parent_excel_row}, "
                f"header_rows_count={len(header_rows)}"
            )

            # 找到表头行中跨2列的合并单元格组
            span2_groups: List[Tuple[int, int, str]] = []
            for mr in parsed_merges:
                if mr['col_span'] == 2:
                    if parent_excel_row is not None:
                        if not (mr['min_row'] <= parent_excel_row <= mr['max_row']):
                            continue
                    col_0 = mr['min_col'] - 1
                    col_1 = mr['max_col'] - 1
                    if col_0 < len(parent_row):
                        text = parent_row[col_0].strip()
                        if text:
                            span2_groups.append((col_0, col_1, text))

            if len(span2_groups) >= 2:
                # 有2组以上跨2列的合并单元格，推断为合并报表
                is_consolidated = True

                # 根据合并单元格文本判断哪组是期末、哪组是期初
                closing_group = None
                opening_group = None
                for g in span2_groups:
                    if closing_group is None and _is_closing_text(g[2]):
                        closing_group = g
                    elif opening_group is None and _is_opening_text(g[2]):
                        opening_group = g
                # 回退：无法通过关键词判断时，按位置顺序（第一组=期末）
                if closing_group is None and opening_group is None:
                    closing_group = span2_groups[0]
                    opening_group = span2_groups[1]
                elif closing_group is None:
                    closing_group = [g for g in span2_groups if g != opening_group][0]
                elif opening_group is None:
                    opening_group = [g for g in span2_groups if g != closing_group][0]

                column_map['closing_consolidated'] = closing_group[0]
                column_map['closing_company'] = closing_group[1]
                column_map['opening_consolidated'] = opening_group[0]
                column_map['opening_company'] = opening_group[1]
                rightmost = max(g[1] for g in span2_groups)
                data_col_end = rightmost + 1
                logger.info(f"[_detect_consolidated_columns] Inferred from parent row merged ranges: {span2_groups}, column_map={column_map}")
                return is_consolidated, column_map, data_col_end

        if len(header_rows) < 2:
            return is_consolidated, column_map, data_col_end

        sub_header = header_rows[-1]  # 子表头行（第2行）
        parent_row = header_rows[0]

        logger.info(f"[_detect_consolidated_columns] sub_header branch: sub_header={sub_header}")

        # 收集所有"合并"和"公司"列的位置
        consolidated_cols: List[int] = []
        company_cols: List[int] = []

        for ci, cell_text in enumerate(sub_header):
            text = cell_text.strip()
            if not text:
                continue
            if any(kw == text or kw in text for kw in self.CONSOLIDATED_KW):
                consolidated_cols.append(ci)
            elif any(kw == text or kw in text for kw in self.COMPANY_KW):
                company_cols.append(ci)

        # 需要同时有合并和公司列才算合并报表
        if consolidated_cols and company_cols:
            is_consolidated = True
            logger.info(f"[_detect_consolidated_columns] FOUND consolidated_cols={consolidated_cols}, company_cols={company_cols}")

            # 根据第一行表头的期末/期初关键词判断每组合并/公司列的归属
            def _parent_label_of(col_idx: int) -> str:
                """回溯第一行表头，找到 col_idx 所属的父列标签。"""
                for ci in range(col_idx, -1, -1):
                    if ci < len(parent_row):
                        h = parent_row[ci].strip()
                        if h:
                            return h
                return ""

            # 对合并列分组：哪个是期末、哪个是期初
            closing_cons = None
            opening_cons = None
            for ci in consolidated_cols:
                parent = _parent_label_of(ci)
                if closing_cons is None and _is_closing_text(parent):
                    closing_cons = ci
                elif opening_cons is None and _is_opening_text(parent):
                    opening_cons = ci
            # 回退到位置顺序
            if closing_cons is None and opening_cons is None:
                if len(consolidated_cols) >= 1:
                    closing_cons = consolidated_cols[0]
                if len(consolidated_cols) >= 2:
                    opening_cons = consolidated_cols[1]
            elif closing_cons is None and len(consolidated_cols) >= 2:
                closing_cons = [ci for ci in consolidated_cols if ci != opening_cons][0]
            elif opening_cons is None and len(consolidated_cols) >= 2:
                opening_cons = [ci for ci in consolidated_cols if ci != closing_cons][0]

            # 对公司列分组
            closing_comp = None
            opening_comp = None
            for ci in company_cols:
                parent = _parent_label_of(ci)
                if closing_comp is None and _is_closing_text(parent):
                    closing_comp = ci
                elif opening_comp is None and _is_opening_text(parent):
                    opening_comp = ci
            if closing_comp is None and opening_comp is None:
                if len(company_cols) >= 1:
                    closing_comp = company_cols[0]
                if len(company_cols) >= 2:
                    opening_comp = company_cols[1]
            elif closing_comp is None and len(company_cols) >= 2:
                closing_comp = [ci for ci in company_cols if ci != opening_comp][0]
            elif opening_comp is None and len(company_cols) >= 2:
                opening_comp = [ci for ci in company_cols if ci != closing_comp][0]

            if closing_cons is not None:
                column_map['closing_consolidated'] = closing_cons
            if closing_comp is not None:
                column_map['closing_company'] = closing_comp
            if opening_cons is not None:
                column_map['opening_consolidated'] = opening_cons
            if opening_comp is not None:
                column_map['opening_company'] = opening_comp

            # 最右侧的公司列就是数据右边界
            rightmost_company = max(company_cols)
            data_col_end = rightmost_company + 1  # +1 因为是切片用
        else:
            logger.info(f"[_detect_consolidated_columns] sub_header: no consolidated/company keywords found. consolidated_cols={consolidated_cols}, company_cols={company_cols}")

        return is_consolidated, column_map, data_col_end

    def _merge_header_rows(
        self, header_rows: List[List[str]], data_col_end: Optional[int]
    ) -> List[str]:
        """将多行表头合并为单行语义表头。

        支持2行、3行甚至更多行的表头结构（如权益变动表）。
        合并策略：逐层向下合并，每层的值会继承上层的合并单元格值。
        最终每列的表头 = 各层非空值用"-"拼接。
        """
        if len(header_rows) == 1:
            return header_rows[0]

        col_count = max(len(row) for row in header_rows)

        # 对每一行，向右传播值（处理合并单元格导致的空值）
        propagated_rows: List[List[str]] = []
        for row in header_rows:
            propagated: List[str] = []
            last_val = ""
            for ci in range(col_count):
                v = row[ci].strip() if ci < len(row) else ""
                if v:
                    last_val = v
                propagated.append(last_val if v else "")
            propagated_rows.append(propagated)

        # 逐列合并：取每行中该列的非空值，用"-"拼接
        # 但要避免重复（如果子行值和父行值相同则不重复）
        merged: List[str] = []
        for ci in range(col_count):
            parts: List[str] = []
            for row in propagated_rows:
                val = row[ci] if ci < len(row) else ""
                if val and (not parts or val != parts[-1]):
                    parts.append(val)
            merged.append("-".join(parts) if parts else "")

        return merged

    def extract_statement_items(self, sheet_data: ReportSheetData) -> List[StatementItem]:
        """从单个 Sheet 中识别报表科目，含其中项明细和父子关系。

        支持合并财务报表的合并/公司列结构。

        Args:
            sheet_data: ReportSheetData

        Returns:
            List[StatementItem]
        """
        items: List[StatementItem] = []
        current_parent_id: Optional[str] = None
        in_sub_items = False

        logger.info(
            "[extract_statement_items] Sheet '%s' type=%s, is_consolidated=%s, "
            "column_map=%s, headers=%s, rows=%d",
            sheet_data.sheet_name, sheet_data.statement_type,
            sheet_data.is_consolidated, sheet_data.column_map,
            sheet_data.headers[:8] if sheet_data.headers else [],
            len(sheet_data.raw_data),
        )

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

            # 清理利润表/现金流量表科目名称中的格式前缀
            # 如 "一、营业收入" → "营业收入"，"加：其他收益" → "其他收益"
            account_name = self._clean_account_prefix(account_name)

            item_id = str(uuid.uuid4())

            # 解析金额 - 根据是否为合并报表使用不同策略
            if sheet_data.is_consolidated and sheet_data.column_map:
                opening_balance, closing_balance, company_opening, company_closing, warnings = (
                    self._parse_amounts_consolidated(row, sheet_data.column_map)
                )
            else:
                opening_balance, closing_balance, warnings = self._parse_amounts(
                    row, sheet_data.statement_type, sheet_data.headers
                )
                company_opening = None
                company_closing = None

            item = StatementItem(
                id=item_id,
                account_name=account_name.strip(),
                statement_type=sheet_data.statement_type,
                sheet_name=sheet_data.sheet_name,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                company_opening_balance=company_opening,
                company_closing_balance=company_closing,
                is_consolidated=sheet_data.is_consolidated,
                parent_id=current_parent_id if is_sub else None,
                is_sub_item=is_sub,
                row_index=row_idx,
                parse_warnings=warnings,
            )
            items.append(item)

            # 前10个科目输出详细日志，帮助排查金额提取问题
            if len(items) <= 10:
                logger.info(
                    "[extract_statement_items]   #%d '%s': closing=%s, opening=%s, "
                    "co_closing=%s, co_opening=%s, row_data=%s, warnings=%s",
                    len(items), account_name.strip(),
                    closing_balance, opening_balance,
                    company_closing if sheet_data.is_consolidated else '-',
                    company_opening if sheet_data.is_consolidated else '-',
                    [v for v in row[:8] if v is not None],
                    warnings,
                )

            # 非其中项时更新当前父科目
            if not is_sub:
                current_parent_id = item_id

        return items

    def extract_note_tables(self, word_result) -> List[NoteTable]:
        """从 Word 解析结果中提取附注表格及其标题上下文。

        利用 table_after_para_idx（按文档顺序记录每个表格前最近的段落索引）
        向上回溯段落列表，找到真正的科目标题（而非紧邻的描述性段落）。

        Args:
            word_result: WordParseResult

        Returns:
            List[NoteTable]
        """
        note_tables: List[NoteTable] = []

        # 从段落中构建科目标题索引
        # 匹配 "1、货币资金" "2、应收票据" "(1) 应收票据分类" 等格式
        # 数字编号后必须跟中文/字母，避免误匹配 "3.14 元" "100、200" 等正文
        note_item_pattern = re.compile(
            r'^[（(]?\s*[\d一二三四五六七八九十]+\s*[）)、.\s]\s*([\u4e00-\u9fffa-zA-Z].+)'
        )

        # ── 预构建段落级别索引，用于向上回溯查找科目标题 ──
        para_levels: List[Optional[int]] = []
        for para_info in word_result.paragraphs:
            para_levels.append(para_info.get('level'))

        def _find_account_title(table_idx: int) -> tuple:
            """向上回溯段落列表，找到表格所属的科目标题。

            返回 (account_name, section_title, sub_title)
            - account_name: 科目名称（如"货币资金"）
            - section_title: 紧邻表格的段落文本（可能是子标题或描述）
            - sub_title: 子标题（如"按坏账计提方法分类"）
            """
            # 确定起始段落索引
            start_pi = -1
            if (hasattr(word_result, 'table_after_para_idx') and
                    word_result.table_after_para_idx and
                    table_idx < len(word_result.table_after_para_idx)):
                start_pi = word_result.table_after_para_idx[table_idx]
            elif table_idx < len(word_result.table_contexts):
                # 旧方式：通过 table_contexts 文本匹配段落索引
                ctx = word_result.table_contexts[table_idx]
                if ctx:
                    for pi, p in enumerate(word_result.paragraphs):
                        if p.get('text', '').strip() == ctx:
                            start_pi = pi
                            break

            if start_pi < 0:
                # 无法定位段落索引，直接从 table_contexts 提取
                ctx = ""
                if (hasattr(word_result, 'table_contexts') and
                        word_result.table_contexts and
                        table_idx < len(word_result.table_contexts)):
                    ctx = word_result.table_contexts[table_idx]
                extracted = self._extract_account_from_heading(ctx) if ctx else ""
                return (extracted or ctx, ctx, "")

            # 紧邻表格的段落文本（用作 section_title）
            immediate_text = word_result.paragraphs[start_pi].get('text', '').strip() if start_pi < len(word_result.paragraphs) else ""

            # 向上回溯，找到最近的有编号的科目标题
            # 优先找 level=3 的标题（如 "1、货币资金"），其次 level=2（如 "（一）流动资产"）
            account_name = ""
            sub_title = ""
            found_level3 = False

            for pi in range(start_pi, -1, -1):
                text = word_result.paragraphs[pi].get('text', '').strip()
                if not text:
                    continue
                level = para_levels[pi]

                # 如果没有 level 字段，通过编号模式推断
                if level is None:
                    level = infer_numbering_level(text)

                # 检查是否是编号标题
                m = note_item_pattern.match(text)
                if m and level is not None:
                    extracted = self._extract_account_from_heading(text)
                    if level <= 3 and not found_level3:
                        # 这是科目级标题（如 "1、货币资金"）
                        account_name = extracted
                        found_level3 = True
                        break
                    elif level >= 4 and not sub_title:
                        # 这是子标题（如 "(1) 按坏账计提方法分类"）
                        sub_title = extracted
                elif m and not account_name:
                    # 有编号但无法推断层级，保守处理：继续向上找
                    extracted = self._extract_account_from_heading(text)
                    if not sub_title:
                        sub_title = extracted

            # 如果没找到编号标题，用紧邻段落文本
            if not account_name:
                account_name = self._extract_account_from_heading(immediate_text) or immediate_text

            return (account_name, immediate_text, sub_title)

        for table_idx, table_data in enumerate(word_result.tables):
            if not table_data:
                continue

            account_name, section_title, sub_title = _find_account_title(table_idx)

            # section_title 优先用紧邻段落，如果紧邻段落为空则用科目名
            if not section_title:
                section_title = account_name

            # 单行表格：直接作为 headers，无数据行
            if len(table_data) == 1:
                headers = table_data[0]
                header_rows_raw = [table_data[0]]
                rows = []
            else:
                # 表头和数据行 — 检测多行表头
                header_rows_raw, data_start = self._detect_note_table_headers(table_data)
                headers = self._merge_note_header_rows(header_rows_raw)
                rows = table_data[data_start:] if data_start < len(table_data) else []

            logger.info(f"[extract_note_tables] table {table_idx}: account={account_name}, "
                        f"section_title={section_title[:30]}, "
                        f"header_rows={len(header_rows_raw)}, "
                        f"row0_cols={len(table_data[0]) if table_data else 0}, "
                        f"headers={headers[:4]}...")

            note_tables.append(NoteTable(
                id=str(uuid.uuid4()),
                account_name=account_name or f"附注表格 {table_idx + 1}",
                section_title=section_title,
                headers=headers,
                header_rows=header_rows_raw,
                rows=rows,
                source_location=f"表格 {table_idx + 1}",
            ))

        return note_tables

    def extract_note_sections(self, word_result, note_tables: List[NoteTable]) -> List[NoteSection]:
        """从 Word 解析结果中构建附注层级结构树。

        按附注文档的标题层级（一、二、三...  (一)(二)...  1. 2. ...）
        组织为树形结构，每个节点关联其下的正文段落和附注表格。
        """
        paragraphs = word_result.paragraphs

        # 指示性关键词：出现在括号中说明这是编辑指引而非标题内容
        _INSTRUCTION_KW = [
            '删除', '不适用', '披露', '填列', '除外', '格式', '描述',
            '可选', '续', '注：', '注:', '如无', '仅限', '不包括',
            '参考', '划分为持有待售',
        ]

        def _is_instruction(inner: str) -> bool:
            return any(kw in inner for kw in _INSTRUCTION_KW)

        def clean_heading_title(title: str) -> str:
            """清理标题中的括号注释/使用说明"""
            result = title
            for pat in [r'（([^（）]+)）', r'\(([^()]+)\)']:
                parts = []
                last = 0
                for m in re.finditer(pat, result):
                    inner = m.group(1)
                    if _is_instruction(inner):
                        parts.append(result[last:m.start()])
                        last = m.end()
                    else:
                        parts.append(result[last:m.end()])
                        last = m.end()
                parts.append(result[last:])
                result = ''.join(parts)
            return result.strip()

        def detect_heading_level(para_info: Dict) -> Optional[int]:
            """检测段落的标题级别（委托给 heading_utils 统一处理）。"""
            text = para_info.get('text', '').strip()
            word_level = para_info.get('level')
            return _unified_detect_heading(
                text=text,
                word_style_level=word_level,
                flat_style_mode=flat_style_mode,
            )

        # ── 预扫描：检测 Word 样式 level 是否全部相同（flat mode） ──
        flat_style_mode = detect_flat_style_mode(paragraphs)
        if flat_style_mode:
            logger.info(f"[extract_note_sections] flat_style_mode detected")

        # 使用精确的段落索引关联表格（优先使用 table_after_para_idx）
        table_after_para: Dict[int, List[int]] = {}
        used_tables: set = set()

        if hasattr(word_result, 'table_after_para_idx') and word_result.table_after_para_idx:
            # 新方式：直接使用段落索引
            for ti, pi in enumerate(word_result.table_after_para_idx):
                if pi >= 0:
                    table_after_para.setdefault(pi, []).append(ti)
                    used_tables.add(ti)
        else:
            # 旧方式兼容：通过 table_contexts 文本匹配
            table_context_to_idx: Dict[str, List[int]] = {}
            for ti, ctx in enumerate(word_result.table_contexts):
                if ctx:
                    table_context_to_idx.setdefault(ctx, []).append(ti)

            for pi, para_info in enumerate(paragraphs):
                text = para_info.get('text', '').strip()
                if text in table_context_to_idx:
                    for ti in table_context_to_idx[text]:
                        if ti not in used_tables:
                            table_after_para.setdefault(pi, []).append(ti)
                            used_tables.add(ti)

        # 构建树（含层级归一化，防止 H1→H3 跳级）
        root_sections: List[NoteSection] = []
        stack: List[tuple] = []  # [(raw_level, NoteSection)]
        heading_stack: List[int] = []  # 用于归一化的原始层级栈

        def normalize_level(raw_level: int) -> int:
            """归一化标题层级，防止跳级（如 H1→H3 归一化为 H1→H2）"""
            while heading_stack and heading_stack[-1] >= raw_level:
                heading_stack.pop()
            normalized = len(heading_stack) + 1
            heading_stack.append(raw_level)
            return min(normalized, 6)

        def current_section() -> Optional[NoteSection]:
            return stack[-1][1] if stack else None

        def add_table_to_current(table_idx: int):
            if table_idx < len(note_tables):
                sec = current_section()
                if sec:
                    sec.note_table_ids.append(note_tables[table_idx].id)
                    sec.content_order.append({'type': 'table', 'index': len(sec.note_table_ids) - 1})

        for pi, para_info in enumerate(paragraphs):
            text = para_info.get('text', '').strip()
            if not text:
                # 即使空段落，也要检查是否有表格跟在后面
                if pi in table_after_para:
                    for ti in table_after_para[pi]:
                        add_table_to_current(ti)
                continue

            level = detect_heading_level(para_info)

            if level is not None:
                norm_level = normalize_level(level)
                section = NoteSection(
                    id=str(uuid.uuid4())[:8],
                    title=clean_heading_title(text),
                    level=norm_level,
                )
                while stack and stack[-1][0] >= norm_level:
                    stack.pop()
                if stack:
                    stack[-1][1].children.append(section)
                else:
                    root_sections.append(section)
                stack.append((norm_level, section))

                if '货币资金' in text:
                    parent_title = stack[-2][1].title if len(stack) >= 2 else 'ROOT'
                    logger.info(f"[extract_note_sections] 货币资金 found: level={level}, norm={norm_level}, parent={parent_title}")
            else:
                sec = current_section()
                if sec:
                    sec.content_paragraphs.append(text)
                    sec.content_order.append({'type': 'para', 'index': len(sec.content_paragraphs) - 1})

            if pi in table_after_para:
                for ti in table_after_para[pi]:
                    add_table_to_current(ti)

        # 未匹配的表格添加到最后一个节点
        for ti in range(len(word_result.tables)):
            if ti not in used_tables:
                add_table_to_current(ti)

        # 调试日志：输出根节点及其子节点
        for sec in root_sections:
            child_titles = [c.title[:20] for c in sec.children[:10]]
            logger.info(f"[extract_note_sections] ROOT: '{sec.title[:30]}' level={sec.level}, children={len(sec.children)}, first_children={child_titles}")

        return root_sections

    # ─── Private helpers ───

    def _identify_statement_type(self, sheet_name: str, cells) -> Optional[StatementType]:
        """根据 Sheet 名称识别报表类型，名称无法识别时回退到内容检测。

        优先级：
        1. 辅助性 Sheet 关键词 → 跳过
        2. Sheet 名称关键词匹配 → 确定类型
        3. 内容回退：检查前 10 行单元格中是否包含报表标题关键词

        Returns:
            StatementType 或 None（非正式报表 Sheet 应跳过）
        """
        name_clean = re.sub(r'\s+', '', sheet_name)

        # 先检查是否为辅助性 Sheet（应跳过）
        is_skip = False
        skip_matched = ''
        for kw in self.SKIP_SHEET_KEYWORDS:
            if kw in name_clean or kw.lower() in sheet_name.lower():
                is_skip = True
                skip_matched = kw
                break

        # 按 Sheet 名称匹配报表类型
        name_lower = sheet_name.lower()
        matched_type: Optional[StatementType] = None
        for st_type, keywords in self.STATEMENT_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in name_lower:
                    matched_type = st_type
                    break
            if matched_type:
                break

        if is_skip:
            if matched_type:
                # 名称同时含辅助关键词和报表关键词 → 辅助优先跳过
                # （如"利润及利润分配表增加额"、"现金流量表调整"）
                logger.info(
                    "[_identify_statement_type] Skipping auxiliary sheet: %s (matched skip '%s', also matched '%s')",
                    sheet_name, skip_matched, matched_type.value,
                )
            else:
                logger.info("[_identify_statement_type] Skipping auxiliary sheet: %s (matched '%s')", sheet_name, skip_matched)
            return None

        if matched_type:
            return matched_type

        # ── 内容回退：名称无法识别时，检查前 10 行单元格内容 ──
        if cells:
            early_texts: list[str] = []
            for cell in cells:
                if cell.row <= 10 and cell.value is not None:
                    cell_str = re.sub(r'\s+', '', str(cell.value))
                    if cell_str:
                        early_texts.append(cell_str)
            combined = ''.join(early_texts)
            for st_type, keywords in self.STATEMENT_TYPE_KEYWORDS.items():
                for kw in keywords:
                    if kw in combined or kw.lower() in combined.lower():
                        logger.info(
                            "[_identify_statement_type] Content fallback: sheet '%s' → %s (matched '%s')",
                            sheet_name, st_type.value, kw,
                        )
                        return st_type

        # 名称和内容均无法识别 → 跳过
        logger.info("[_identify_statement_type] Skipping unrecognized sheet: %s", sheet_name)
        return None

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

    @staticmethod
    def _clean_account_prefix(name: str) -> str:
        """清理报表科目名称中的格式前缀。

        利润表和现金流量表的科目名称常带有序号和加减标记：
        - "一、营业收入" → "营业收入"
        - "加：其他收益" → "其他收益"
        - "减：营业成本" → "营业成本"
        - "加：营业外收入" → "营业外收入"
        - "二、营业利润" → "营业利润"
        """
        cleaned = name.strip()
        # 去掉中文序号前缀：一、二、三、...
        cleaned = re.sub(r'^[一二三四五六七八九十]+[、.]\s*', '', cleaned)
        # 去掉 加：/减：/加:/减: 前缀
        cleaned = re.sub(r'^[加减][：:]\s*', '', cleaned)
        return cleaned.strip()

    def _parse_amounts_consolidated(
        self, row: List[Any], column_map: Dict[str, int]
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], List[str]]:
        """从合并报表行中按列映射精确提取金额。

        Args:
            row: 数据行
            column_map: 列语义映射 {closing_consolidated: idx, closing_company: idx, ...}

        Returns:
            (opening_balance, closing_balance, company_opening, company_closing, warnings)
        """
        warnings: List[str] = []

        def _get_val(key: str) -> Optional[float]:
            idx = column_map.get(key)
            if idx is None or idx >= len(row):
                return None
            val = row[idx]
            parsed = self._try_parse_number(val)
            if parsed is None and val is not None and isinstance(val, str) and val.strip():
                stripped = val.strip()
                if stripped not in ('-', '—', '/', ''):
                    warnings.append(f"金额无法解析：'{val}'")
            return parsed

        closing_balance = _get_val('closing_consolidated')
        opening_balance = _get_val('opening_consolidated')
        company_closing = _get_val('closing_company')
        company_opening = _get_val('opening_company')

        return opening_balance, closing_balance, company_opening, company_closing, warnings

    def _parse_amounts(
        self, row: List[Any], statement_type: StatementType,
        headers: Optional[List[str]] = None,
    ) -> Tuple[Optional[float], Optional[float], List[str]]:
        """从行数据中解析期初/期末金额。

        优先使用表头关键词（期末/期初）精确定位列；
        回退策略：从行的右侧向左取最后两个数值列，
        倒数第二个 = 期末余额，最后一个 = 期初余额。
        小整数（如附注编号 1-99）在左侧列中会被跳过。

        Returns:
            (opening_balance, closing_balance, parse_warnings)
        """
        warnings: List[str] = []

        # ── 策略1：通过表头关键词精确定位期末/期初列 ──
        if headers:
            closing_col: Optional[int] = None
            opening_col: Optional[int] = None
            for ci, h in enumerate(headers):
                h_text = h.strip() if h else ''
                if not h_text:
                    continue
                is_opening = any(kw in h_text for kw in self._OPENING_HEADER_KW)
                is_closing = (any(kw in h_text for kw in self._CLOSING_HEADER_KW)
                              and not is_opening)
                if is_closing and closing_col is None:
                    closing_col = ci
                elif is_opening and opening_col is None:
                    opening_col = ci

            if closing_col is not None or opening_col is not None:
                def _get(ci: Optional[int]) -> Optional[float]:
                    if ci is None or ci >= len(row):
                        return None
                    val = row[ci]
                    parsed = self._try_parse_number(val)
                    if parsed is None and val is not None and isinstance(val, str) and val.strip():
                        stripped = val.strip()
                        if stripped not in ('-', '—', '/', '') and not self._is_text_value(val):
                            warnings.append(f"金额无法解析：'{val}'")
                    return parsed

                closing_balance = _get(closing_col)
                opening_balance = _get(opening_col)
                return opening_balance, closing_balance, warnings

        # ── 策略2（回退）：按位置取最后两个数值列 ──
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

        # 过滤掉可能的附注编号：
        # 附注编号通常是紧跟科目名称之后的第一个小整数（1-999），
        # 位于金额列之前。当第一个数值列是小整数且后面还有其他数值列时，
        # 将其视为附注编号并跳过。
        if len(col_values) >= 2:
            first_ci, first_val = col_values[0]
            if (first_val is not None
                    and first_val == int(first_val)
                    and 1 <= first_val <= 999):
                col_values = col_values[1:]

        closing_balance = None
        opening_balance = None

        if len(col_values) >= 2:
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

    def _detect_note_table_headers(self, table_data: List[List[Any]]) -> tuple:
        """检测附注表格的多行表头。

        Word 表格中合并单元格保留所有列位置（合并位置填空），
        所以各行列数通常一致。但仍需处理列数不同的边缘情况。

        检测策略：逐行扫描，如果行无大数字、有足够非空单元格、
        且第一列与首行相同或为空（纵向合并），则视为表头行。
        对齐策略：短行在前面补空列使所有行列数一致。

        返回 (header_rows, data_start_index)。
        """
        if not table_data:
            return [], 0

        row0 = [str(h).strip() for h in table_data[0]]
        if len(table_data) < 2:
            return [row0], 1

        # 找到数据行的最大列数
        max_cols = len(row0)
        for ri in range(1, min(len(table_data), 6)):
            max_cols = max(max_cols, len(table_data[ri]))

        # 统一逻辑：逐行扫描，判断是否为表头行
        header_rows_raw: List[List[str]] = [row0]
        data_start = 1

        for ri in range(1, min(len(table_data), 4)):
            row_raw = table_data[ri]
            row = [str(c).strip() if c is not None else '' for c in row_raw]
            # 有大数字 → 数据行
            if self._row_has_large_number(row_raw):
                break
            non_empty = [v for v in row if v]
            # 非空单元格太少 → 不是表头
            if len(non_empty) < 2:
                break
            first_cell = row[0] if row else ''
            # 第一列与首行不同且非空 → 可能是数据行
            if first_cell and first_cell != row0[0]:
                # 再检查是否全是文本（子表头特征：数字少于 1/3）
                num_count = 0
                for c in row:
                    s = c.replace(',', '').replace(' ', '')
                    try:
                        float(s)
                        num_count += 1
                    except (ValueError, TypeError):
                        pass
                if num_count > len(row) // 3:
                    break  # 数字太多，是数据行
            header_rows_raw.append(row)
            data_start = ri + 1

        # 对齐所有表头行到 max_cols
        aligned = self._align_header_rows(header_rows_raw, max_cols)
        return aligned, data_start

    @staticmethod
    def _row_has_large_number(row: List[Any]) -> bool:
        """检查行中是否有大数字（>1000），用于区分表头和数据行。"""
        for c in row:
            if c is None:
                continue
            s = str(c).replace(',', '').replace(' ', '').strip()
            try:
                if abs(float(s)) > 1000:
                    return True
            except (ValueError, TypeError):
                pass
        return False

    @staticmethod
    def _align_header_rows(header_rows: List[List[str]], target_cols: int) -> List[List[str]]:
        """对齐多行表头到相同列数（智能展开）。

        对于父表头行（最短行），根据子行信息推断独占列和展开列：
        - 独占列（纵向合并）保持1列宽度
        - 展开列（有子列的父列）重复填充以覆盖子列范围
        前端通过相同值检测来渲染 rowSpan/colSpan。
        """
        if not header_rows:
            return header_rows
        if len(header_rows) == 1:
            row = header_rows[0]
            if len(row) >= target_cols:
                return [row[:target_cols]]
            return [row + [''] * (target_cols - len(row))]

        first_row = header_rows[0]
        first_len = len(first_row)
        sub_rows = header_rows[1:]
        sub_row_max = max(len(r) for r in sub_rows)

        # 第一行不需要展开的情况
        if first_len >= target_cols or first_len >= sub_row_max:
            result: List[List[str]] = []
            r0 = list(first_row[:target_cols]) if first_len >= target_cols else list(first_row) + [''] * (target_cols - first_len)
            result.append(r0)
            for row in sub_rows:
                if len(row) >= target_cols:
                    result.append(list(row[:target_cols]))
                else:
                    result.append(list(row) + [''] * (target_cols - len(row)))
            return result

        # ── 第一行比子行短，需要智能展开 ──
        # 策略：第一列通常是独占列（项目/科目名），其余列是展开列
        # 展开列的宽度基于子行列数均分，而不是基于 target_cols
        # 这样即使数据行有额外空列，展开也是正确的

        # 确定独占列：默认第一列独占，其余展开
        # 但如果有关键词匹配，优先使用关键词
        expand_kw = ['变动', '增减', '明细', '调整', '余额', '金额', '数']
        is_expand = [False] * first_len

        # 先用关键词标记展开列
        for i, val in enumerate(first_row):
            v = (val or '').replace(' ', '')
            if any(kw in v for kw in expand_kw):
                is_expand[i] = True

        n_marked = sum(is_expand)
        if n_marked == 0:
            # 没有关键词匹配，用位置启发式：第一列独占，其余展开
            for i in range(1, first_len):
                is_expand[i] = True
        elif n_marked == first_len:
            # 所有列都被标记为展开，第一列改为独占
            is_expand[0] = False

        n_expand = sum(is_expand)
        head_solo_count = 0
        for i in range(first_len):
            if not is_expand[i]:
                head_solo_count += 1
            else:
                break

        if n_expand <= 0:
            # 所有列都是独占的，简单补齐
            r0 = list(first_row) + [''] * (target_cols - first_len)
            subs = []
            for row in sub_rows:
                subs.append(list(row) + [''] * (target_cols - len(row)) if len(row) < target_cols else list(row[:target_cols]))
            return [r0[:target_cols]] + subs

        # 展开列的总子列数 = 子行列数 - 子行中对应独占列的空位数
        # 如果子行前面有空列，说明是独占列的纵向合并空位
        ref_sub = sub_rows[0] if sub_rows else []
        sub_leading_empty = 0
        for c in ref_sub:
            if not (c and str(c).strip()):
                sub_leading_empty += 1
            else:
                break
        # 子行前导空列数不超过独占列数
        solo_offset = min(sub_leading_empty, head_solo_count)
        child_total = sub_row_max - solo_offset
        if child_total <= 0:
            child_total = sub_row_max

        # ── 尝试按子行内容分组来确定每个展开列的宽度 ──
        # 子行中可能存在空列作为分隔符（如 "金额 | 比例% | [空] | 金额 | 比例%"）
        # 将子行按空列分割成组，如果组数等于展开列数，则按组大小分配宽度
        sub_content = list(ref_sub[solo_offset:])
        # 将子行分割成非空组（被空列分隔）
        groups: list = []
        current_group: list = []
        for ci, c in enumerate(sub_content):
            if c and str(c).strip():
                current_group.append(ci)
            else:
                if current_group:
                    groups.append(current_group)
                    current_group = []
        if current_group:
            groups.append(current_group)

        if len(groups) == n_expand and all(len(g) > 0 for g in groups):
            # 组数匹配展开列数 — 按每组实际列数分配宽度
            # 同时在组之间插入空列（分隔符），保持与子行/数据行的对齐
            # 构建 r0：独占列 + (展开列重复 * 组宽) + 组间空列 + ...
            r0_parts: List[str] = []
            expand_idx = 0
            for i in range(first_len):
                if is_expand[i]:
                    if expand_idx < len(groups):
                        group = groups[expand_idx]
                        group_size = len(group)
                        r0_parts.extend([first_row[i]] * group_size)
                        # 在组之间插入空列（如果不是最后一组）
                        if expand_idx + 1 < len(groups):
                            next_group = groups[expand_idx + 1]
                            gap_size = next_group[0] - (group[-1] + 1)
                            r0_parts.extend([''] * gap_size)
                    expand_idx += 1
                else:
                    r0_parts.append(first_row[i])

            # 补齐或截断到 target_cols
            if len(r0_parts) > target_cols:
                r0 = r0_parts[:target_cols]
            elif len(r0_parts) < target_cols:
                r0 = r0_parts + [''] * (target_cols - len(r0_parts))
            else:
                r0 = r0_parts

            # 子行对齐：直接前插独占列空位，保持原始结构（含空列分隔符）
            aligned_subs: List[List[str]] = []
            for row in sub_rows:
                if len(row) >= target_cols:
                    aligned_subs.append(list(row[:target_cols]))
                else:
                    padded = [''] * head_solo_count + list(row) + [''] * max(target_cols - len(row) - head_solo_count, 0)
                    aligned_subs.append(padded[:target_cols])

            return [r0[:target_cols]] + aligned_subs
        else:
            # 无法按组分配，使用均分策略
            base_w = child_total // n_expand
            rem = child_total % n_expand
            widths = [1] * first_len
            expand_idx = 0
            for i in range(first_len):
                if is_expand[i]:
                    widths[i] = base_w + (1 if expand_idx < rem else 0)
                    expand_idx += 1

        r0: List[str] = []
        for i, val in enumerate(first_row):
            r0.extend([val] * widths[i])
        # 补齐或截断到 target_cols
        if len(r0) > target_cols:
            r0 = r0[:target_cols]
        elif len(r0) < target_cols:
            r0.extend([''] * (target_cols - len(r0)))

        # ── 对齐子行：前面插入 head_solo_count 个空列 ──
        aligned_subs: List[List[str]] = []
        for row in sub_rows:
            if len(row) >= target_cols:
                aligned_subs.append(list(row[:target_cols]))
            else:
                padded = [''] * head_solo_count + list(row) + [''] * max(target_cols - len(row) - head_solo_count, 0)
                aligned_subs.append(padded[:target_cols])

        return [r0[:target_cols]] + aligned_subs


    @staticmethod
    def _merge_note_header_rows(header_rows: List[List[str]]) -> List[str]:
        """将附注表格的多行表头合并为单行语义表头。"""
        if not header_rows:
            return []
        if len(header_rows) == 1:
            return header_rows[0]

        col_count = max(len(row) for row in header_rows)
        merged = []
        for ci in range(col_count):
            parts = []
            for row in header_rows:
                val = row[ci].strip() if ci < len(row) else ''
                if val and val not in parts:
                    parts.append(val)
            merged.append('-'.join(parts) if parts else '')
        return merged

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

    @staticmethod
    def _extract_pdf_table_titles(pdf_text: str) -> List[str]:
        """从 PDF 文本中提取每个 [表格 N] 标记前的上下文标题。

        扫描 [表格 N] 标记前的非空行，向上回溯找到可能的科目标题。
        """
        titles: List[str] = []
        lines = pdf_text.splitlines()
        # 编号标题模式（数字后必须跟中文/字母，避免误匹配正文数字）
        note_item_pat = re.compile(
            r'^[（(]?\s*[\d一二三四五六七八九十]+\s*[）)、.\s]\s*([\u4e00-\u9fffa-zA-Z].+)'
        )
        table_marker_pat = re.compile(r'^\[表格\s*\d+\]')

        for i, line in enumerate(lines):
            if not table_marker_pat.match(line.strip()):
                continue
            # 向上回溯找标题
            title = ""
            for j in range(i - 1, max(i - 10, -1), -1):
                prev = lines[j].strip()
                if not prev or prev.startswith('[表格结束]') or prev.startswith('---'):
                    continue
                # 跳过纯数字行（表格数据残留）
                if re.match(r'^[\d,.\-\s]+$', prev):
                    continue
                m = note_item_pat.match(prev)
                if m:
                    title = m.group(1).strip()
                    break
                # 短文本行可能是标题
                if len(prev) <= 40 and not prev.endswith('。'):
                    title = prev
                    break
            titles.append(title)
        return titles


# 模块级单例
report_parser = ReportParser()
