"""勾稽校验引擎（本地规则为主）。





基于 Table_Structure_Analyzer 输出的结构化信息执行确定性数值校验：


- 科目名称模糊匹配构建对照映射


- 金额一致性校验（报表 vs 附注合计值）


- 附注表格内部勾稽（横纵加总）


- 余额变动公式校验（期初+增加-减少=期末）


- 其中项校验（子项之和 ≤ 父项）


"""


import json


import logging


import re


import uuid


from typing import Dict, List, Optional, Tuple





from ..models.audit_schemas import (


    FindingConfirmationStatus,


    FindingStatus,


    MatchingEntry,


    MatchingMap,


    NoteSection,


    NoteTable,


    ReportReviewFinding,


    ReportReviewFindingCategory,


    RiskLevel,


    StatementItem,


    StatementType,


    TableStructure,


)





logger = logging.getLogger(__name__)





# 浮点容差


TOLERANCE = 0.5

# 比例列校验容差（百分点）：比金额容差更严格
RATIO_TOLERANCE = 0.15





# 预编译常用正则（避免在循环中反复编译）


_SECTION_PATTERN = re.compile(r'^[一二三四五六七八九十]+[、.]')


_PARENTHETICAL_PATTERN = re.compile(r'[（(][^）)]*[）)]')


_TRAILING_PAREN_PATTERN = re.compile(r'[（(].+[）)]$')


_NOTE_NUMBER_PREFIX = re.compile(r'^[（(]\d+[）)]')


_NOTE_DOT_PREFIX = re.compile(r'^\d+[.、．]')








def _safe_float(val) -> Optional[float]:


    """安全转换为浮点数，支持千分位逗号格式和括号负数格式。





    支持格式：


    - 普通数字：123.45


    - 千分位逗号：38,444,572.98


    - 括号负数（中国财务报表常见）：(1,234.56) → -1234.56


    - 中文负号：-1,234.56


    """


    if val is None:


        return None


    try:


        v = float(val)


        return v


    except (ValueError, TypeError):


        pass


    try:


        s = str(val).strip()


        if not s:


            return None


        # 中文财务报表中，"—"、"－"、"-" 常表示零或无数据


        if s in ('-', '—', '－', '─', '--', '——'):


            return None


        # 括号负数格式：(1,234.56) 或 （1,234.56）


        neg = False


        if (s.startswith('(') and s.endswith(')')) or (s.startswith('（') and s.endswith('）')):


            s = s[1:-1].strip()


            neg = True


        # 百分号格式：12.5% → 12.5（保留原始百分比数值，不除以100）

        is_percent = False

        if s.endswith("%") or s.endswith("％"):

            s = s[:-1].strip()

            is_percent = True

        s = s.replace(",", "").replace("，", "")


        if s:


            v = float(s)


            return -v if neg else v


    except (ValueError, TypeError):


        pass


    return None








def _amounts_equal(a: Optional[float], b: Optional[float]) -> bool:


    if a is None or b is None:


        return a is None and b is None


    return abs(a - b) < TOLERANCE








class ReconciliationEngine:


    """勾稽校验引擎，所有数值校验为纯函数。"""





    # ─── 科目匹配 ───





    def build_matching_map(


        self,


        items: List[StatementItem],


        notes: List[NoteTable],


    ) -> MatchingMap:


        """基于标准科目映射模板构建对照映射，模板未命中时回退到模糊匹配。"""


        from .account_mapping_template import account_mapping_template





        entries: List[MatchingEntry] = []


        matched_note_ids: set = set()


        unmatched_items: List[str] = []





        # 上市版报表一个科目可能有：合并附注 + 多个明细子表 + 母公司附注，


        # 限制过小会导致母公司附注被截断，无法进行母公司口径的金额校验。


        MAX_NOTES_PER_ITEM = 10





        for item in items:


            # 1) 优先使用模板映射


            template_notes: List[Tuple[str, float]] = []


            for note in notes:


                if account_mapping_template.match_note(


                    item.account_name, note.account_name, note.section_title


                ):


                    template_notes.append((note.id, 1.0))





            if template_notes:


                note_ids = [n[0] for n in template_notes[:MAX_NOTES_PER_ITEM]]


                entries.append(MatchingEntry(


                    statement_item_id=item.id,


                    note_table_ids=note_ids,


                    match_confidence=1.0,


                ))


                matched_note_ids.update(note_ids)


                continue





            # 2) 回退到模糊匹配


            best_notes: List[Tuple[str, float]] = []


            for note in notes:


                score = self._match_score(item.account_name, note.account_name)


                if score >= 0.5:


                    best_notes.append((note.id, score))





            best_notes.sort(key=lambda x: x[1], reverse=True)





            if best_notes:


                note_ids = [n[0] for n in best_notes[:MAX_NOTES_PER_ITEM]]


                confidence = best_notes[0][1]


                entries.append(MatchingEntry(


                    statement_item_id=item.id,


                    note_table_ids=note_ids,


                    match_confidence=confidence,


                ))


                matched_note_ids.update(note_ids)


            else:


                unmatched_items.append(item.id)





        unmatched_notes = [n.id for n in notes if n.id not in matched_note_ids]





        return MatchingMap(


            entries=entries,


            unmatched_items=unmatched_items,


            unmatched_notes=unmatched_notes,


        )





    # ─── 金额一致性校验 ───





    # 报表中的汇总行关键词 — 这些行是多个科目的合计，不对应具体附注披露，跳过金额核对


    STATEMENT_SUBTOTAL_KEYWORDS = [


        "合计", "总计", "总额", "小计", "净额", "净值",


    ]





    # 不应做金额核对的特殊科目名称关键词（包含即跳过）


    SKIP_AMOUNT_CHECK_KEYWORDS = [


        "相抵后净额", "抵销后净额",  # 递延所得税资产和负债相抵后净额


    ]





    # 现金流量表中有附注披露的科目关键词（仅"其他与XX活动有关的现金"等有明细表）


    # 其余现金流量表科目（如"处置固定资产收回的现金净额"、"投资支付的现金"等）无附注披露


    CASH_FLOW_NOTE_KEYWORDS = [


        "其他与经营活动有关",


        "其他与投资活动有关",


        "其他与筹资活动有关",


        "重要的投资活动有关",


        "重要的筹资活动有关",


    ]





    # 现金流量表科目名称特征（用于 statement_type 未正确标记时的兜底识别）


    CASH_FLOW_NAME_INDICATORS = [


        "收到的现金", "支付的现金", "收回的现金", "现金净额",


        "经营活动", "投资活动", "筹资活动",


        "现金及现金等价物",


    ]





    def _should_skip_amount_check(self, item: StatementItem) -> bool:


        """判断报表科目是否应跳过金额一致性核对。"""


        name = item.account_name


        # 所有者权益变动表：结构行/过程行，不对应具体附注披露表格


        if item.statement_type == StatementType.EQUITY_CHANGE:


            return True


        # 汇总行（如"非流动负债合计"）


        if any(name.endswith(kw) for kw in self.STATEMENT_SUBTOTAL_KEYWORDS):


            return True


        # 特殊科目（如"递延所得税资产和递延所得税负债相抵后净额"）


        if any(kw in name for kw in self.SKIP_AMOUNT_CHECK_KEYWORDS):


            return True


        # 报表中的"其中"子项（如"应付职工薪酬-短期薪酬"、"当期所得税费用"等）：


        # 子项没有独立的附注披露表格，其金额包含在父科目的附注表格中，


        # 不应单独与附注合计值比对（否则会用父科目的合计值来比对子项金额，必然不一致）。


        if item.is_sub_item:


            return True


        # 附注编号格式的科目名（如"(1) 固定资产情况"、"4.递延所得税"等）：


        # 这些是附注章节标题被误解析为报表科目，不是真正的报表行


        if _NOTE_NUMBER_PREFIX.match(name) or _NOTE_DOT_PREFIX.match(name):


            return True


        # 附注章节标题特征词：科目名以"情况"/"说明"/"明细"/"详情"结尾，


        # 如"固定资产情况"、"在建工程情况"等，是附注章节标题被误解析为报表科目


        if any(name.endswith(kw) for kw in self.NOTE_SECTION_TITLE_SUFFIXES):


            return True


        # 括号内含子项说明的科目名（如"应付职工薪酬（短期薪酬）"、"长期借款（1年内到期）"等）：


        # 即使 is_sub_item 未被标记，通过名称模式也能识别为子项


        if _TRAILING_PAREN_PATTERN.search(name):


            return True


        # 现金流量表科目：仅白名单内的科目有附注披露


        is_cash_flow = (


            item.statement_type == StatementType.CASH_FLOW


            or any(kw in name for kw in self.CASH_FLOW_NAME_INDICATORS)


        )


        if is_cash_flow:


            if not any(kw in name for kw in self.CASH_FLOW_NOTE_KEYWORDS):


                return True


        # 现金流量表补充资料项目：这些项目的名称来自补充资料表格，


        # 不是独立的报表科目，不应与附注表格核对


        if any(kw in name for kw in self.CASHFLOW_SUPPLEMENT_ITEM_KEYWORDS):


            return True


        return False





    # 附注章节标题后缀词 — 真正的报表科目不会以这些词结尾


    NOTE_SECTION_TITLE_SUFFIXES = [


        "情况", "说明", "明细", "详情",


    ]





    # 现金流量表补充资料中的项目名称关键词


    # 这些项目出现在补充资料中，不是独立的报表科目，不应与附注表格做金额核对


    CASHFLOW_SUPPLEMENT_ITEM_KEYWORDS = [


        "固定资产折旧", "油气资产折耗", "生产性生物资产折旧",


        "无形资产摊销", "长期待摊费用摊销",


        "处置固定资产", "固定资产报废",


        "公允价值变动损失", "财务费用",


        "投资损失", "递延所得税资产减少", "递延所得税负债增加",


        "存货的减少", "经营性应收项目", "经营性应付项目",


        "商誉减值损失", "资产减值准备",


        "现金的期末余额", "现金的期初余额",


        "现金等价物的期末余额", "现金等价物的期初余额",


        "现金及现金等价物净增加额",


    ]





    # 附注表格标题中含这些关键词时，表示仅披露重要/主要项目，


    # 报表金额应 ≥ 附注合计（附注是部分明细，不是全部）


    PARTIAL_DISCLOSURE_KEYWORDS = [


        "重要", "主要", "重大",


    ]





    def _is_partial_disclosure(self, note: NoteTable) -> bool:


        """判断附注表格是否仅披露部分项目（如"重要在建工程项目变动情况"）。"""


        combined = (note.section_title or "") + (note.account_name or "")


        return any(kw in combined for kw in self.PARTIAL_DISCLOSURE_KEYWORDS)





    # 资产组成部分子表关键词（国企报表中固定资产/无形资产等科目的附注


    # 常拆分为多张独立表格：原价表、累计折旧表、减值准备表、账面价值表。


    # 原价/累计折旧/减值准备表的合计值仅代表资产的某一组成部分，


    # 不应直接与报表余额（账面价值）比对。）


    _COMPONENT_SUBTABLE_KW = [


        "原价", "原值", "账面原值",


        "累计折旧", "累计摊销",


        "减值准备",


    ]





    @staticmethod


    def _is_component_subtable(note: NoteTable) -> bool:


        """判断附注表格是否为资产组成部分子表（原价/累计折旧/减值准备）。





        国企报表中，固定资产等科目的附注常拆分为多张独立表格，


        其中原价表、累计折旧表、减值准备表的合计值仅代表资产的某一组成部分，


        不应直接与报表余额（账面价值）比对。





        仅对长期资产类科目生效（固定资产、无形资产、投资性房地产等），


        避免误匹配非资产科目（如"合同资产减值准备"应由 _is_detail_subtable 处理）。


        """


        acct = (note.account_name or "").replace(" ", "").replace("\u3000", "")


        if not any(kw in acct for kw in ReconciliationEngine._SECTION_EXTRACT_ACCOUNTS):


            return False


        title = (note.section_title or "").replace(" ", "").replace("\u3000", "")


        return any(kw in title for kw in ReconciliationEngine._COMPONENT_SUBTABLE_KW)





    # 国企版资产负债表中，固定资产/无形资产等科目拆分为子行项目：


    # "固定资产原价"、"累计折旧"、"固定资产减值准备"、"固定资产净值"等。


    # 这些子行项目需要从合并附注表格的对应段落中提取值。


    _COMPONENT_ITEM_TO_SECTION = {


        "原价": "cost", "原值": "cost", "账面原值": "cost",


        "累计折旧": "amort", "累计摊销": "amort",


        "减值准备": "impair",


    }


    # 需要做子行段落提取的资产科目


    _SECTION_EXTRACT_ACCOUNTS = [


        "固定资产", "无形资产", "投资性房地产",


        "使用权资产", "油气资产", "生产性生物资产",


    ]





    # ─── 合并小计表格（同一张表包含多个科目各自的段落小计行） ───


    # 每个配置项：


    #   table_markers: 表格标题必须同时包含的关键词（用于识别合并表）


    #   section_markers: 段落标题关键词列表（用于识别段落边界）


    #   item_section_map: 报表科目关键词 → 段落标识关键词列表


    _COMBINED_SUBTOTAL_CONFIGS: List[Dict] = [


        {


            # 递延所得税资产和递延所得税负债


            "table_markers": ["递延所得税资产", "递延所得税负债"],


            "section_markers": ["递延所得税资产", "递延所得税负债"],


            "item_section_map": {


                "递延所得税资产": ["递延所得税资产"],


                "递延所得税负债": ["递延所得税负债"],


            },


        },


        {


            # 其他综合收益（不能重分类 / 将重分类）


            "table_markers": ["其他综合收益"],


            "section_markers": ["不能重分类进损益的其他综合收益",


                                "将重分类进损益的其他综合收益"],


            "item_section_map": {


                "不能重分类": ["不能重分类进损益的其他综合收益"],


                "将重分类": ["将重分类进损益的其他综合收益"],


            },


        },


    ]





    @staticmethod


    def _find_combined_config(note: NoteTable, item_name: str) -> Optional[Tuple[Dict, List[str]]]:


        """查找匹配的合并小计表格配置，返回 (config, section_keywords) 或 None。"""


        title = (note.account_name or "") + (note.section_title or "")


        title = title.replace(" ", "").replace("\u3000", "")


        norm_item = item_name.replace(" ", "").replace("\u3000", "")


        for cfg in ReconciliationEngine._COMBINED_SUBTOTAL_CONFIGS:


            if not all(kw in title for kw in cfg["table_markers"]):


                continue


            for item_kw, sec_kws in cfg["item_section_map"].items():


                if item_kw in norm_item:


                    return cfg, sec_kws


        return None





    @staticmethod


    def _extract_combined_subtotal(


        note: NoteTable,


        section_keywords: List[str],


        section_markers: Optional[List[str]] = None,


    ) -> Tuple[Optional[float], Optional[float]]:


        """从合并小计表格中提取指定段落的小计行期末/期初值。





        表格结构示例（递延所得税）：


          项目 | 期末余额-暂时性差异 | 期末余额-递延所得税 | 期初余额-暂时性差异 | 期初余额-递延所得税


          递延所得税资产:


            ...明细行...


            小计 | 6,645,328.04 | 1,861,632.01 | 9,670,760.85 | 2,419,049.17


          递延所得税负债:


            ...明细行...


            小计 | 163,431,416.60 | 40,120,854.15 | 8,265,217.92 | 2,066,304.48





        本方法找到 section_keywords 匹配的段落，然后提取该段落内"小计"行的值。


        对于有多个同期列的表格（如暂时性差异+递延所得税），取最后一个匹配列


        （即"递延所得税"列，而非"暂时性差异"列）。


        """


        # 如果未传入 section_markers，从配置中查找


        if section_markers is None:


            title = (note.account_name or "") + (note.section_title or "")


            title_n = title.replace(" ", "").replace("\u3000", "")


            for cfg in ReconciliationEngine._COMBINED_SUBTOTAL_CONFIGS:


                if all(kw in title_n for kw in cfg["table_markers"]):


                    section_markers = cfg["section_markers"]


                    break


            if section_markers is None:


                section_markers = []





        closing_kw = ReconciliationEngine._CLOSING_COL_KW


        opening_kw = ReconciliationEngine._OPENING_COL_KW


        is_move = ReconciliationEngine._is_movement_col


        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]





        # ── 识别期末/期初列索引 ──


        # 递延所得税合并表的表头有两种风格：


        #   风格A: "期末余额-暂时性差异" | "期末余额-递延所得税" | "期初余额-暂时性差异" | "期初余额-递延所得税"


        #          → 每列都带期间关键词，直接取最后一个期末/期初列即可


        #   风格B: "期末余额-可抵扣暂时性差异" | "递延所得税资产/负债" | "上年年末余额-暂时性差异" | "递延所得税资产/负债"


        #          → "递延所得税"列不带期间关键词，需要从前一列继承期间属性


        # 策略：先标记每列的期间属性（closing/opening/none），


        #       然后对无期间属性的列从左邻列继承，最后取最后一个 closing/opening 列。


        col_period: List[Optional[str]] = [None] * len(norm_h)  # "closing" | "opening" | None


        for ci, h in enumerate(norm_h):


            if ci == 0 or is_move(h):


                continue


            has_open = any(kw in h for kw in opening_kw)


            has_close = any(kw in h for kw in closing_kw) and not has_open


            if has_close:


                col_period[ci] = "closing"


            elif has_open:


                col_period[ci] = "opening"





        # 无期间属性的列从左邻列继承（处理风格B）


        for ci in range(1, len(col_period)):


            if col_period[ci] is None and not is_move(norm_h[ci]) and norm_h[ci]:


                if ci > 0 and col_period[ci - 1] is not None:


                    col_period[ci] = col_period[ci - 1]





        # 取最后一个 closing/opening 列索引（递延所得税列在暂时性差异列之后）


        hdr_closing_idx = -1


        hdr_opening_idx = -1


        for ci in range(len(col_period)):


            if col_period[ci] == "closing":


                hdr_closing_idx = ci


            elif col_period[ci] == "opening":


                hdr_opening_idx = ci





        if hdr_closing_idx <= 0 and hdr_opening_idx <= 0:


            # 尝试从 header_rows 中查找


            for hr in (getattr(note, "header_rows", None) or []):


                for ci, cell in enumerate(hr):


                    h = str(cell or "").replace(" ", "").replace("\u3000", "")


                    has_open = any(kw in h for kw in opening_kw)


                    if any(kw in h for kw in closing_kw) and not has_open:


                        hdr_closing_idx = ci


                    if has_open:


                        hdr_opening_idx = ci





        in_target = False


        closing_val: Optional[float] = None


        opening_val: Optional[float] = None





        # 收集目标段落内的数据行（用于没有"小计"行时的兜底）


        target_data_rows: List[list] = []


        # 保存目标段落的标题行（带序号的行，如"一、递延所得税资产"），


        # 当段落内没有"小计"行时，标题行本身可能就包含小计值


        target_section_header_row: Optional[list] = None


        found_subtotal = False





        for row in note.rows:


            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()





            # 检测段落标题行（包含段落关键词的行，如"递延所得税负债："或"一、递延所得税资产"）


            # 注意：如果行同时包含所有标记词（如"递延所得税资产和递延所得税负债"），


            # 则是表格标题行而非段落标题行，应跳过。


            # 段落标题行的特征：去掉序号后，剩余部分应精确等于标记词（可带冒号/标点后缀）


            # 不应匹配：包含标记词但有额外内容的行（如"递延所得税资产净额"、"减：递延所得税资产抵销"）


            is_section_header = False


            markers = section_markers or []


            matched_markers = [kw for kw in markers if kw in first]


            if matched_markers and len(matched_markers) < len(markers):


                # 去掉中文序号前缀（如"一、"）


                _stripped = _SECTION_PATTERN.sub('', first).strip()


                # 去掉尾部标点（冒号等）


                _stripped_clean = _stripped.rstrip('：:')


                # 精确匹配：去掉序号和尾部标点后，必须等于某个标记词


                if any(_stripped_clean == kw for kw in matched_markers):


                    is_section_header = True


                    in_target = any(skw in first for skw in section_keywords)


                    if in_target:


                        target_data_rows = []  # 重置，开始新段落


                        target_section_header_row = row  # 保存标题行





            if is_section_header:


                continue





            if not in_target:


                continue





            # 在目标段落内找"小计"行


            if first in ("小计", "合计"):


                found_subtotal = True


                if hdr_closing_idx > 0 and hdr_closing_idx < len(row):


                    v = _safe_float(row[hdr_closing_idx])


                    if v is not None:


                        closing_val = v


                if hdr_opening_idx > 0 and hdr_opening_idx < len(row):


                    v = _safe_float(row[hdr_opening_idx])


                    if v is not None:


                        opening_val = v





                # 如果表头列索引没找到，尝试从小计行中取最后几个数值列


                if closing_val is None and opening_val is None:


                    numeric_indices = []


                    for ci in range(1, len(row)):


                        v = _safe_float(row[ci])


                        if v is not None:


                            numeric_indices.append(ci)


                    if len(numeric_indices) >= 2:


                        closing_val = _safe_float(row[numeric_indices[-2]])


                        opening_val = _safe_float(row[numeric_indices[-1]])


                    elif len(numeric_indices) == 1:


                        closing_val = _safe_float(row[numeric_indices[0]])





                break  # 找到小计行就停止


            else:


                # 收集数据行（用于兜底）


                target_data_rows.append(row)





        # 兜底：段落内没有"小计"/"合计"行时的回退策略


        if not found_subtotal:


            # 优先：段落标题行本身带有数值（如"一、递延所得税资产 | xxx | 7000"）


            # 这种情况下标题行就是小计行


            fallback_row = None


            if target_section_header_row is not None:


                has_num = any(_safe_float(c) is not None for c in target_section_header_row[1:])


                if has_num:


                    fallback_row = target_section_header_row


            # 其次：段落内只有一行数据 → 直接取该行的值


            if fallback_row is None and len(target_data_rows) == 1:


                fallback_row = target_data_rows[0]





            if fallback_row is not None:


                if hdr_closing_idx > 0 and hdr_closing_idx < len(fallback_row):


                    v = _safe_float(fallback_row[hdr_closing_idx])


                    if v is not None:


                        closing_val = v


                if hdr_opening_idx > 0 and hdr_opening_idx < len(fallback_row):


                    v = _safe_float(fallback_row[hdr_opening_idx])


                    if v is not None:


                        opening_val = v





        return (closing_val, opening_val)








    @staticmethod


    def _get_component_section_type(item_name: str) -> Optional[str]:


        """判断报表科目名是否为资产子行项目，返回对应的段落类型。





        例如："固定资产原价" → "cost"，"累计折旧" → "amort"


        返回 None 表示不是子行项目（是净值/账面价值行或主科目行）。


        """


        for kw, section in ReconciliationEngine._COMPONENT_ITEM_TO_SECTION.items():


            if kw in item_name:


                return section


        return None





    @staticmethod


    def _extract_component_section_totals(


        note: NoteTable,


        section_type: str,


    ) -> Tuple[Optional[float], Optional[float]]:


        """从合并附注表格中提取指定段落（cost/amort/impair）的期末/期初值。





        国企版固定资产等科目的附注表格包含多个段落（原值、累计折旧、减值准备、账面价值），


        每个段落有自己的合计行。本方法提取指定段落的合计值。


        """


        section_pattern = _SECTION_PATTERN


        kw_map = {


            "cost": ReconciliationEngine._COST_SECTION_KW,


            "amort": ReconciliationEngine._AMORT_SECTION_KW,


            "impair": ReconciliationEngine._IMPAIR_SECTION_KW,


        }


        target_kw = kw_map.get(section_type)


        if not target_kw:


            return (None, None)





        closing_kw = ReconciliationEngine._CLOSING_COL_KW


        opening_kw = ReconciliationEngine._OPENING_COL_KW


        is_move = ReconciliationEngine._is_movement_col


        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]





        hdr_closing_idx = -1


        hdr_opening_idx = -1


        for ci, h in enumerate(norm_h):


            if is_move(h):


                continue


            has_open = any(kw in h for kw in opening_kw)


            if hdr_closing_idx < 0 and any(kw in h for kw in closing_kw) and not has_open:


                hdr_closing_idx = ci


            if hdr_opening_idx < 0 and has_open:


                hdr_opening_idx = ci





        if hdr_closing_idx <= 0 and hdr_opening_idx <= 0:


            return (None, None)





        total_col = -1


        for ci in range(len(note.headers) - 1, 0, -1):


            h = str(note.headers[ci] or "").replace(" ", "").replace("\u3000", "")


            if h in ("合计", "总计"):


                total_col = ci


                break





        closing_val: Optional[float] = None


        opening_val: Optional[float] = None


        in_target = False





        for row in note.rows:


            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()


            if section_pattern.match(first):


                in_target = any(kw in first for kw in target_kw)


                if in_target:


                    if hdr_closing_idx > 0 and hdr_closing_idx < len(row):


                        v = _safe_float(row[hdr_closing_idx])


                        if v is not None:


                            closing_val = v


                    if hdr_opening_idx > 0 and hdr_opening_idx < len(row):


                        v = _safe_float(row[hdr_opening_idx])


                        if v is not None:


                            opening_val = v


                continue


            if not in_target:


                continue


            if "期末" in first or "年末" in first:


                pick = total_col if total_col > 0 else hdr_closing_idx


                if 0 < pick < len(row):


                    v = _safe_float(row[pick])


                    if v is not None:


                        closing_val = v


            if "期初" in first or "年初" in first:


                pick = total_col if total_col > 0 else hdr_opening_idx


                if 0 < pick < len(row):


                    v = _safe_float(row[pick])


                    if v is not None:


                        opening_val = v





        return (closing_val, opening_val)





    # 明细/分类子表关键词（国企报表中，多个科目的附注包含多张表格：


    # 只有1级汇总表直接与报表余额核对，


    # 其余明细表仅参与 check_cross_table_consistency 的表间核对。）


    # 适用科目：应收票据、应收账款、其他应收款、合同资产、应收款项融资、


    # 长期应收款、预付款项、存货、应付职工薪酬、固定资产等。


    _DETAIL_SUBTABLE_KW = [


        # 应收类：账龄、组合、坏账准备


        "按账龄", "账龄组合", "账龄披露", "账龄列示",


        "组合方法", "组合计提", "按组合",


        "分类披露", "计提方法分类",


        "单项计提", "按单项",


        "坏账准备计提", "坏账准备变动",


        "前五名", "前5名",


        "实际核销", "核销情况",


        "收回或转回", "转回或收回",


        "逾期",


        "款项性质", "按款项性质",


        # 应收票据专用


        "已质押", "已背书", "已贴现",


        "出票人未履约", "转为应收账款",


        "金融资产转移", "终止确认",


        # 预付款项


        "账龄超过",


        # 存货：跌价准备


        "跌价准备", "合同履约成本减值",


        # 存货/无形资产：数据资源子表


        "数据资源",


        # 合同资产


        "减值准备",


        # 应付职工薪酬：明细子表


        "短期薪酬列示", "短期薪酬明细", "设定提存计划列示", "设定提存计划明细",


        "设定受益计划", "辞退福利明细", "一年内到期",


        # 固定资产/在建工程/无形资产：明细子表


        "暂时闲置", "未办妥产权",


        # 在建工程：国企报表明细子表


        "重要在建工程", "本期变动情况", "本期计提",


        # 固定资产清理


        "固定资产清理",


        # 长期股权投资：明细子表


        "长期股权投资明细", "主要财务信息",


        # 受限制的货币资金


        "受限制",


    ]





    # 适用明细子表过滤的科目关键词


    _DETAIL_SUBTABLE_ACCOUNTS = [


        "应收票据", "应收账款", "其他应收款", "合同资产",


        "应收款项融资", "长期应收款",


        "预付款项", "预付账款",


        "存货",


        "应付职工薪酬",


        "固定资产", "在建工程", "无形资产",


        "投资性房地产", "使用权资产",


        "长期股权投资", "货币资金",


        "债权投资", "其他债权投资",


        "其他应付款",


    ]





    def _is_detail_subtable(self, note: NoteTable) -> bool:


        """判断附注表格是否为明细/分类子表（非1级汇总表）。





        国企报表中，多个科目下有多张表格，只有1级汇总表应与报表余额


        直接核对，其余明细表（按账龄披露、按组合计提、坏账准备计提、


        跌价准备变动、短期薪酬列示等）仅参与表间核对。





        科目关键词同时检查 account_name 和 section_title，


        避免 OCR 将标题整体作为 account_name 导致科目关键词匹配失败。


        """


        acct = note.account_name or ""


        title = (note.section_title or "").replace(" ", "").replace("\u3000", "")


        # 科目关键词：account_name 或 section_title 任一包含即可


        if not any(kw in acct or kw in title for kw in self._DETAIL_SUBTABLE_ACCOUNTS):


            return False


        # 明细子表关键词：必须在 section_title 中出现


        return any(kw in title for kw in self._DETAIL_SUBTABLE_KW)





    # 政策/描述性表格的表头特征关键词


    # 这些关键词出现在表头中时，说明该表格是会计政策说明表，不含数值数据


    _POLICY_HEADER_KW = [


        # 坏账准备计提政策表


        "确定组合的依据", "组合名称", "账龄状态",


        # 固定资产/无形资产折旧摊销政策表


        "折旧方法", "摊销方法", "预计使用寿命", "预计净残值率",


        "年折旧率", "年摊销率",


        # 通用政策描述


        "确认标准", "计量方法", "会计政策",


        "减值测试方法", "减值迹象",


    ]





    # 政策/描述性表格的标题特征关键词组


    # 每个元素是一组关键词，标题必须同时包含组内所有关键词才匹配


    # 用于表头为公司名称等无法通过 _POLICY_HEADER_KW 识别的非数据表格


    _POLICY_TITLE_KW_GROUPS: List[List[str]] = [


        # 商誉 — "商誉所在资产组或资产组合的相关信息"


        ["资产组", "相关信息"],


        # 商誉 — 减值测试关键假设/方法描述表


        ["减值测试", "关键假设"],


        # 递延所得税 — "未确认递延所得税资产的可抵扣暂时性差异及可抵扣亏损明细"


        # 未确认部分不等于报表上已确认的递延所得税资产/负债余额


        ["未确认", "递延所得税"],


        # 递延所得税 — "以抵销后净额列示的递延所得税资产或负债"


        # 抵销后净额是展示性表格，不等于报表上的递延所得税资产/负债余额


        ["抵销后", "净额"],


        # 递延所得税 — "可抵扣亏损将于以下年度到期"


        # 亏损到期年度明细表，不含报表余额


        ["可抵扣亏损", "到期"],


        # 应付债券 — "应付债券的增减变动"


        # 增减变动明细表，不是余额汇总表


        ["应付债券", "增减变动"],


    ]





    @staticmethod


    def _is_policy_description_table(note: NoteTable) -> bool:


        """判断附注表格是否为纯政策/描述性表格（不含数值数据列）。





        上市版附注中，应收账款等科目下常有政策说明表格，


        如坏账准备计提政策（"组合名称"、"确定组合的依据"、"账龄状态"等），


        这些表格仅描述会计政策，不应参与金额核对。





        检测策略（正向匹配，两条路径任一命中即跳过）：


        1. 表头中包含政策描述特征关键词 → 政策描述表


        2. 标题同时包含某组关键词 → 非数据描述表（如商誉资产组相关信息表）


        """


        # 路径1：表头关键词匹配


        if note.headers and len(note.headers) >= 2:


            headers_text = " ".join(str(h or "") for h in note.headers[1:])


            if any(kw in headers_text for kw in ReconciliationEngine._POLICY_HEADER_KW):


                return True





        # 路径2：标题关键词组匹配


        title = (note.section_title or "").replace(" ", "").replace("\u3000", "")


        if title:


            for kw_group in ReconciliationEngine._POLICY_TITLE_KW_GROUPS:


                if all(kw in title for kw in kw_group):


                    return True





        return False





    @staticmethod


    def _is_revenue_cost_detail_table(note: NoteTable) -> bool:


        """判断营业收入/营业成本合并表格是否为明细子表（按行业/地区/商品转让时间划分）。





        国企和上市报表中，营业收入、营业成本科目下通常有多张合并表格：


        - 汇总表（主营业务/其他业务/合计）→ 与报表余额直接核对


        - 按行业（或产品类型）划分 → 明细子表，仅参与表间核对


        - 按地区划分 → 明细子表


        - 按商品转让时间划分 → 明细子表





        只有汇总表应与报表余额直接比对。


        """


        title = (note.section_title or "").replace(" ", "").replace("\u3000", "")


        return any(kw in title for kw in ReconciliationEngine._REVENUE_COST_DETAIL_KW)





    # 母公司附注表格识别关键词（section_title 中包含这些关键词时，视为母公司口径）


    PARENT_COMPANY_NOTE_KEYWORDS = [


        "母公司财务报表", "母公司报表", "公司财务报表主要项目",


        "公司报表主要项目", "母公司主要项目",


    ]





    @staticmethod


    def _is_parent_company_note(


        note: NoteTable,


        ancestor_titles: Optional[List[str]] = None,


    ) -> bool:


        """判断附注表格是否属于母公司报表附注（而非合并报表附注）。





        优先检查 NoteSection 层级树中的祖先节点标题（ancestor_titles），


        兜底检查 note.section_title。


        """


        kws = ReconciliationEngine.PARENT_COMPANY_NOTE_KEYWORDS


        # 优先：检查祖先节点标题（从 NoteSection 层级树获取）


        if ancestor_titles:


            for t in ancestor_titles:


                if any(kw in t for kw in kws):


                    return True


        # 兜底：检查 section_title 本身


        title = (note.section_title or "")


        return any(kw in title for kw in kws)





    @staticmethod


    def _build_note_parent_section_map(


        note_sections: List[NoteSection],


    ) -> Dict[str, List[str]]:


        """遍历 NoteSection 层级树，构建 note_table_id → 祖先节点标题列表 的映射。





        返回值示例: {"note-uuid-1": ["五、合并财务报表项目注释", "1、货币资金"]}


        """


        result: Dict[str, List[str]] = {}





        def _walk(nodes: List['NoteSection'], ancestors: List[str]):


            for node in nodes:


                current_ancestors = ancestors + [node.title]


                for nid in node.note_table_ids:


                    result[nid] = current_ancestors


                if node.children:


                    _walk(node.children, current_ancestors)





        _walk(note_sections, [])


        return result





    # 标记"未找到附注合计值"的 finding，用于 report_review_engine 中触发 LLM 重新分析


    NOTE_VALUE_NOT_FOUND_TAG = "[未提取到附注合计值]"





    def check_amount_consistency(


        self,


        matching_map: MatchingMap,


        items: List[StatementItem],


        notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


        note_sections: Optional[List[NoteSection]] = None,


        template_type: Optional[str] = None,


    ) -> List[ReportReviewFinding]:


        """基于 TableStructure 定位附注合计值，与报表余额比对。





        当一个报表科目匹配了多个附注表格时，只要有任一表格的金额与报表一致，


        就视为该科目校验通过（跳过变动表等辅助表格的误报）。





        对于"重要项目"类附注表格（仅披露部分明细），采用宽松比对：


        报表金额 ≥ 附注合计即视为通过。





        当报表科目有余额但所有匹配附注表格均未提取到对应合计值时，


        生成"未找到附注合计值"的警告 finding，提示结构识别可能不完整。





        note_sections: 附注层级结构树，用于判断附注表格所属的母公司/合并口径。


        template_type: 模板类型（'soe'/'listed'），用于限定母公司科目披露范围。


        """


        findings: List[ReportReviewFinding] = []


        item_map = {i.id: i for i in items}


        note_map = {n.id: n for n in notes}





        # 构建 note_table_id → 祖先标题 映射，用于判断母公司/合并口径


        ancestor_map: Dict[str, List[str]] = {}


        if note_sections:


            ancestor_map = self._build_note_parent_section_map(note_sections)





        # 构建预设科目关键词集合，用于限定报表vs附注一致性核对范围。


        # 只有在预设模板中列出的科目才参与一致性核对：


        # - 合并口径：使用 _CONSOLIDATED_ACCOUNTS_SOE/LISTED


        # - 母公司口径：使用 _PARENT_ACCOUNTS_SOE/LISTED


        # 不在预设范围内的科目跳过一致性核对（但仍参与变动异常等其他检查）。


        _parent_account_keywords: List[List[str]] = []


        _consolidated_account_keywords: List[List[str]] = []


        if template_type:


            from .account_mapping_template import account_mapping_template


            parent_accounts = account_mapping_template.get_parent_company_accounts(template_type)


            _parent_account_keywords = [acct['keywords'] for acct in parent_accounts]


            consolidated_accounts = account_mapping_template.get_consolidated_accounts(template_type)


            _consolidated_account_keywords = [acct['keywords'] for acct in consolidated_accounts]





        def _item_in_consolidated_scope(account_name: str) -> bool:


            """判断报表科目是否在合并附注预设范围内。"""


            if not _consolidated_account_keywords:


                return True  # 无模板时不限制


            return any(


                any(kw in account_name for kw in kw_list)


                for kw_list in _consolidated_account_keywords


            )





        for entry in matching_map.entries:


            item = item_map.get(entry.statement_item_id)


            if not item:


                continue





            # 跳过不需要金额核对的科目（汇总行、无附注披露的现金流量表科目等）


            if self._should_skip_amount_check(item):


                continue





            # 跳过不在预设模板范围内的科目：


            # 只有预设模板中列出的科目才参与报表vs附注一致性核对。


            # 合并报表时，科目需在合并预设或母公司预设中至少出现一个；


            # 非合并报表时，科目需在合并预设中。


            if _consolidated_account_keywords:


                _in_cons = _item_in_consolidated_scope(item.account_name)


                _in_parent = any(


                    any(kw in item.account_name for kw in kw_list)


                    for kw_list in _parent_account_keywords


                ) if _parent_account_keywords else False


                if not _in_cons and not _in_parent:


                    continue





            # ── 按口径分别追踪校验状态 ──


            # 合并报表（is_consolidated=True）时，合并附注和母公司附注各自独立校验；


            # 非合并报表时，所有附注统一校验（scope_key="default"）。


            # scope_key: "consolidated" | "parent" | "default"


            scope_matched_closing: Dict[str, bool] = {}


            scope_matched_opening: Dict[str, bool] = {}


            scope_findings_closing: Dict[str, List[ReportReviewFinding]] = {}


            scope_findings_opening: Dict[str, List[ReportReviewFinding]] = {}


            scope_any_closing_found: Dict[str, bool] = {}


            scope_any_opening_found: Dict[str, bool] = {}


            # 收集所有有效匹配的附注表格 ID（用于"未找到值"时的 finding）


            valid_note_ids: List[str] = []





            # ── 位置限制：每个科目下，只有第 1 个通过过滤的表格


            # 参与报表-附注余额核对，后续表格仅参与表间核对。


            # 按口径（合并/母公司）分别计数。


            # 依据：国企/上市报表附注中，科目标题下的第一个表格是汇总表


            # （含期末/期初余额），后续表格均为明细/变动/政策描述表，


            # 不应与报表余额直接比对。


            MAX_VERIFY_TABLES = 1


            scope_verify_count: Dict[str, int] = {}  # scope_key → 已参与核对的表格数





            for note_id in entry.note_table_ids:


                note = note_map.get(note_id)


                ts = table_structures.get(note_id)


                if not note or not ts:


                    continue





                valid_note_ids.append(note_id)


                is_partial = self._is_partial_disclosure(note)





                # 跳过资产组成部分子表（原价/累计折旧/减值准备），


                # 它们的合计值不代表报表余额（账面价值）


                if self._is_component_subtable(note):


                    valid_note_ids.pop()


                    continue





                # 跳过应收类科目的明细/分类子表（按账龄、按组合、坏账准备计提等），


                # 这些表仅参与表间核对，不与报表余额直接比对


                if self._is_detail_subtable(note):


                    valid_note_ids.pop()


                    continue





                # 跳过纯政策/描述性表格（如坏账准备计提政策说明表），


                # 这些表格仅描述会计政策，不含数值数据


                if self._is_policy_description_table(note):


                    valid_note_ids.pop()


                    continue





                # 跳过营业收入/营业成本的明细子表（按行业、按地区、按商品转让时间划分），


                # 仅汇总表（主营业务/其他业务/合计）与报表余额直接比对


                if (self._is_revenue_cost_combined_table(note)


                        and self._is_revenue_cost_detail_table(note)):


                    valid_note_ids.pop()


                    continue





                ancestors = ancestor_map.get(note_id)


                is_parent_note = self._is_parent_company_note(note, ancestors)





                # 母公司科目范围限定：如果该报表科目不在母公司预设披露范围内，


                # 则不允许将任何附注表格识别为母公司口径（无论是层级树还是启发式）。


                # 上市版/国企版附注中，母公司报表项目注释仅披露少数科目，


                # 其他科目即使附注金额恰好接近公司数，也不应按母公司口径核对。


                _item_in_parent_scope = True


                if _parent_account_keywords and item.is_consolidated:


                    _item_in_parent_scope = any(


                        any(kw in item.account_name for kw in kw_list)


                        for kw_list in _parent_account_keywords


                    )


                    if not _item_in_parent_scope:


                        is_parent_note = False  # 强制视为合并口径





                # ── 启发式补救：当 ancestor_map 未能识别母公司附注时，


                # 通过金额接近度推断口径。如果附注合计值与公司余额更接近


                # 而非合并余额，则视为母公司口径。


                # 仅对母公司预设披露范围内的科目启用此推断。


                if (not is_parent_note


                        and _item_in_parent_scope


                        and item.is_consolidated


                        and item.company_closing_balance is not None):


                    _note_val = self._get_cell_value(note, ts.closing_balance_cell)


                    if _note_val is None:


                        _rule_c, _rule_o = self._extract_note_totals_by_rules(note)


                        _note_val = _rule_c


                    if _note_val is not None:


                        _diff_cons = abs(_note_val - (item.closing_balance or 0))


                        _diff_comp = abs(_note_val - (item.company_closing_balance or 0))


                        # 附注值与公司余额一致或明显更接近 → 推断为母公司附注


                        if (_amounts_equal(_note_val, item.company_closing_balance)


                                or (_diff_comp < _diff_cons * 0.5


                                    and not _amounts_equal(_note_val, item.closing_balance))):


                            # 当期末值同时匹配合并和母公司时（两者相等），


                            # 进一步用期初值区分：如果期初值更接近母公司期初 → 母公司


                            if (_amounts_equal(_note_val, item.closing_balance)


                                    and item.company_opening_balance is not None):


                                _note_opening_val = self._get_cell_value(note, ts.opening_balance_cell)


                                if _note_opening_val is None:


                                    _r_c, _r_o = self._extract_note_totals_by_rules(note)


                                    _note_opening_val = _r_o


                                if _note_opening_val is not None:


                                    # 期初值与合并期初一致 → 这是合并附注，不是母公司


                                    if (_amounts_equal(_note_opening_val, item.opening_balance)


                                            and not _amounts_equal(_note_opening_val, item.company_opening_balance)):


                                        is_parent_note = False


                                    else:


                                        is_parent_note = True


                                else:


                                    is_parent_note = True


                            else:


                                is_parent_note = True





                # 根据附注口径选择对应的报表余额：


                # 母公司附注 → 用公司数；合并附注 → 用合并数


                if is_parent_note and item.is_consolidated:


                    stmt_closing = item.company_closing_balance


                    stmt_opening = item.company_opening_balance


                    scope_label = "母公司"


                    scope_key = "parent"


                elif item.is_consolidated:


                    stmt_closing = item.closing_balance


                    stmt_opening = item.opening_balance


                    scope_label = "合并"


                    scope_key = "consolidated"


                else:


                    stmt_closing = item.closing_balance


                    stmt_opening = item.opening_balance


                    scope_label = ""


                    scope_key = "default"





                # 初始化该口径的追踪状态


                scope_matched_closing.setdefault(scope_key, False)


                scope_matched_opening.setdefault(scope_key, False)


                scope_findings_closing.setdefault(scope_key, [])


                scope_findings_opening.setdefault(scope_key, [])


                scope_any_closing_found.setdefault(scope_key, False)


                scope_any_opening_found.setdefault(scope_key, False)





                # ── 位置限制：每个口径下，只有前 MAX_VERIFY_TABLES 个通过过滤的表格


                # 参与报表-附注余额核对。科目标题下的第一个（最多前两个）表格


                # 涉及报表和附注余额验证，后续表格仅参与表间核对。


                _cur_count = scope_verify_count.get(scope_key, 0)


                if _cur_count >= MAX_VERIFY_TABLES:


                    valid_note_ids.pop()  # 不参与余额核对


                    continue


                scope_verify_count[scope_key] = _cur_count + 1





                # ── 提取附注合计值：规则引擎优先，LLM 兜底 ──


                # 规则引擎通过表头语义确定性地定位期初/期末列，比 LLM 的 cell 引用更可靠。


                # LLM 仅在规则引擎无法提取时作为兜底。





                # 规则引擎提取


                rule_closing, rule_opening = self._extract_note_totals_by_rules(note)





                # 特殊处理：营业收入/营业成本合并表格


                # 这类表格一张表包含收入和成本两组列，需按科目名称定位正确的列


                if self._is_revenue_cost_combined_table(note):


                    rc_closing, rc_opening = self._extract_revenue_cost_from_combined_table(


                        note, item.account_name,


                    )


                    if rc_closing is not None:


                        rule_closing = rc_closing


                    if rc_opening is not None:


                        rule_opening = rc_opening





                # 国企版资产子行项目（如"固定资产原价"、"累计折旧"）：


                # 从合并附注表格的对应段落提取值，而非使用账面价值合计


                comp_section = self._get_component_section_type(item.account_name)


                if comp_section and any(kw in (note.account_name or "") for kw in self._SECTION_EXTRACT_ACCOUNTS):


                    sec_closing, sec_opening = self._extract_component_section_totals(note, comp_section)


                    if sec_closing is not None or sec_opening is not None:


                        rule_closing = sec_closing


                        rule_opening = sec_opening





                # 合并小计表格（如"递延所得税资产和递延所得税负债"、"其他综合收益"）：


                # 从合并表中提取对应段落的"小计"行值


                combined_match = self._find_combined_config(note, item.account_name)


                if combined_match is not None:


                    cfg, sec_kws = combined_match


                    sub_closing, sub_opening = self._extract_combined_subtotal(


                        note, sec_kws, section_markers=cfg["section_markers"],


                    )


                    if sub_closing is not None or sub_opening is not None:


                        rule_closing = sub_closing


                        rule_opening = sub_opening





                # 以规则引擎为主值


                note_closing = rule_closing


                note_opening = rule_opening





                # 兜底：规则引擎未提取到时，用 LLM 识别的 cell


                if note_closing is None:


                    note_closing = self._get_cell_value(note, ts.closing_balance_cell)


                if note_opening is None:


                    note_opening = self._get_cell_value(note, ts.opening_balance_cell)





                if note_closing is not None:


                    scope_any_closing_found[scope_key] = True


                if note_opening is not None:


                    scope_any_opening_found[scope_key] = True





                # 期末余额比对


                if stmt_closing is not None and note_closing is not None:


                    if _amounts_equal(stmt_closing, note_closing):


                        scope_matched_closing[scope_key] = True


                    elif is_partial and stmt_closing >= note_closing - TOLERANCE:


                        scope_matched_closing[scope_key] = True


                    else:


                        diff = round(stmt_closing - note_closing, 2)


                        scope_desc = f"（{scope_label}）" if scope_label else ""


                        scope_findings_closing[scope_key].append(self._make_finding(


                            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,


                            account_name=item.account_name,


                            statement_amount=stmt_closing,


                            note_amount=note_closing,


                            difference=diff,


                            location=f"附注-{item.account_name}-{note.section_title}-期末余额",


                            description=f"报表期末余额{scope_desc}{stmt_closing}与附注合计{note_closing}不一致，差异{diff}",


                            risk_level=self._assess_risk(abs(diff), stmt_closing),


                            reasoning=f"校验公式: 报表期末余额{scope_desc}({stmt_closing}) - 附注合计({note_closing}) = {diff}",


                            note_table_ids=[note_id],


                        ))





                # 期初余额比对


                if stmt_opening is not None and note_opening is not None:


                    if _amounts_equal(stmt_opening, note_opening):


                        scope_matched_opening[scope_key] = True


                    elif is_partial and stmt_opening >= note_opening - TOLERANCE:


                        scope_matched_opening[scope_key] = True


                    else:


                        diff = round(stmt_opening - note_opening, 2)


                        scope_desc = f"（{scope_label}）" if scope_label else ""


                        scope_findings_opening[scope_key].append(self._make_finding(


                            category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,


                            account_name=item.account_name,


                            statement_amount=stmt_opening,


                            note_amount=note_opening,


                            difference=diff,


                            location=f"附注-{item.account_name}-{note.section_title}-期初余额",


                            description=f"报表期初余额{scope_desc}{stmt_opening}与附注合计{note_opening}不一致，差异{diff}",


                            risk_level=self._assess_risk(abs(diff), stmt_opening),


                            reasoning=f"校验公式: 报表期初余额{scope_desc}({stmt_opening}) - 附注合计({note_opening}) = {diff}",


                            note_table_ids=[note_id],


                        ))





            # ── 母公司口径补充校验 ──


            # 当 is_consolidated=True 且报表有公司余额，但没有任何附注被识别为母公司口径时，


            # ancestor_map 和启发式都未能识别母公司附注。


            # 此时遍历所有有效附注表格，用公司余额逐个比对，确保母公司口径不被遗漏。


            # 注意：仅对母公司预设披露范围内的科目执行此补充校验，


            # 范围外的科目（如存货、在建工程等）不应进行母公司口径核对。


            _fallback_in_parent_scope = True


            if _parent_account_keywords and item.is_consolidated:


                _fallback_in_parent_scope = any(


                    any(kw in item.account_name for kw in kw_list)


                    for kw_list in _parent_account_keywords


                )


            if (item.is_consolidated


                    and _fallback_in_parent_scope


                    and "parent" not in scope_matched_closing


                    and "parent" not in scope_matched_opening


                    and (item.company_closing_balance is not None


                         or item.company_opening_balance is not None)


                    and valid_note_ids):


                _p_matched_c = False


                _p_matched_o = False


                _p_findings_c: List[ReportReviewFinding] = []


                _p_findings_o: List[ReportReviewFinding] = []


                _p_any_c = False


                _p_any_o = False





                for note_id in valid_note_ids:


                    note = note_map.get(note_id)


                    ts = table_structures.get(note_id)


                    if not note or not ts:


                        continue


                    n_c = self._get_cell_value(note, ts.closing_balance_cell)


                    n_o = self._get_cell_value(note, ts.opening_balance_cell)


                    if self._is_revenue_cost_combined_table(note):


                        rc_c, rc_o = self._extract_revenue_cost_from_combined_table(note, item.account_name)


                        if rc_c is not None:


                            n_c = rc_c


                        if rc_o is not None:


                            n_o = rc_o


                    r_c, r_o = self._extract_note_totals_by_rules(note)


                    if n_c is None and r_c is not None:


                        n_c = r_c


                    if n_o is None and r_o is not None:


                        n_o = r_o





                    # 跳过与合并余额一致的附注（合并口径）


                    if (_amounts_equal(n_c, item.closing_balance)


                            and _amounts_equal(n_o, item.opening_balance)):


                        continue





                    if n_c is not None:


                        _p_any_c = True


                        if item.company_closing_balance is not None:


                            if _amounts_equal(item.company_closing_balance, n_c):


                                _p_matched_c = True


                            else:


                                diff = round(item.company_closing_balance - n_c, 2)


                                _p_findings_c.append(self._make_finding(


                                    category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,


                                    account_name=item.account_name,


                                    statement_amount=item.company_closing_balance,


                                    note_amount=n_c,


                                    difference=diff,


                                    location=f"附注-{item.account_name}-{note.section_title}-期末余额",


                                    description=f"报表期末余额（母公司）{item.company_closing_balance}与附注合计{n_c}不一致，差异{diff}",


                                    risk_level=self._assess_risk(abs(diff), item.company_closing_balance),


                                    reasoning=f"校验公式: 报表期末余额（母公司）({item.company_closing_balance}) - 附注合计({n_c}) = {diff}",


                                    note_table_ids=[note_id],


                                ))


                    if n_o is not None:


                        _p_any_o = True


                        if item.company_opening_balance is not None:


                            if _amounts_equal(item.company_opening_balance, n_o):


                                _p_matched_o = True


                            else:


                                diff = round(item.company_opening_balance - n_o, 2)


                                _p_findings_o.append(self._make_finding(


                                    category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,


                                    account_name=item.account_name,


                                    statement_amount=item.company_opening_balance,


                                    note_amount=n_o,


                                    difference=diff,


                                    location=f"附注-{item.account_name}-{note.section_title}-期初余额",


                                    description=f"报表期初余额（母公司）{item.company_opening_balance}与附注合计{n_o}不一致，差异{diff}",


                                    risk_level=self._assess_risk(abs(diff), item.company_opening_balance),


                                    reasoning=f"校验公式: 报表期初余额（母公司）({item.company_opening_balance}) - 附注合计({n_o}) = {diff}",


                                    note_table_ids=[note_id],


                                ))





                if not _p_matched_c and _p_findings_c:


                    best = min(_p_findings_c, key=lambda f: abs(f.difference or 0))


                    findings.append(best)


                if not _p_matched_o and _p_findings_o:


                    best = min(_p_findings_o, key=lambda f: abs(f.difference or 0))


                    findings.append(best)


                # 合并到 scope 字典供后续"未找到值"警告使用


                scope_matched_closing["parent"] = _p_matched_c


                scope_matched_opening["parent"] = _p_matched_o


                scope_any_closing_found["parent"] = _p_any_c


                scope_any_opening_found["parent"] = _p_any_o





            # 只有当所有匹配表格都不一致时，才报告差异最小的那个 finding


            # 按口径分别聚合：每个 scope 独立判断是否通过


            for sk in set(list(scope_matched_closing.keys()) + list(scope_matched_opening.keys())):


                if not scope_matched_closing.get(sk, False) and scope_findings_closing.get(sk):


                    best = min(scope_findings_closing[sk], key=lambda f: abs(f.difference or 0))


                    findings.append(best)


                if not scope_matched_opening.get(sk, False) and scope_findings_opening.get(sk):


                    best = min(scope_findings_opening[sk], key=lambda f: abs(f.difference or 0))


                    findings.append(best)





            # 报表科目有余额但所有附注表格都没提取到对应值 → 生成警告


            # 但如果所有匹配表格的表头中都没有对应的期初/期末列，说明该表格本身


            # 就不披露该期间数据（如国企版"会计利润与所得税费用调整过程"只有本期数），


            # 此时不应报警告。


            if valid_note_ids:


                has_closing = item.closing_balance is not None and item.closing_balance != 0


                has_opening = item.opening_balance is not None and item.opening_balance != 0





                # 检查匹配表格的表头中是否存在期末/期初列


                # 仅当表头中能识别出至少一种期间列时，才根据缺失情况抑制警告；


                # 如果表头完全无法识别（如"数据A"），仍然保留警告。


                any_table_has_closing_col = False


                any_table_has_opening_col = False


                any_table_has_period_col = False  # 是否有任何可识别的期间列


                for nid in valid_note_ids:


                    n = note_map.get(nid)


                    if not n:


                        continue


                    hdrs = " ".join(str(h or "") for h in (n.headers or []))


                    if any(kw in hdrs for kw in self._CLOSING_COL_KW):


                        any_table_has_closing_col = True


                        any_table_has_period_col = True


                    if any(kw in hdrs for kw in self._OPENING_COL_KW):


                        any_table_has_opening_col = True


                        any_table_has_period_col = True





                # 抑制条件：表头能识别出期间列，但明确缺少对应的期末/期初列


                suppress_closing_warn = any_table_has_period_col and not any_table_has_closing_col


                suppress_opening_warn = any_table_has_period_col and not any_table_has_opening_col





                # 聚合所有口径的追踪状态


                any_closing_value_found = any(scope_any_closing_found.values()) if scope_any_closing_found else False


                any_opening_value_found = any(scope_any_opening_found.values()) if scope_any_opening_found else False


                any_closing_matched = any(scope_matched_closing.values()) if scope_matched_closing else False


                any_opening_matched = any(scope_matched_opening.values()) if scope_matched_opening else False





                if has_closing and not any_closing_value_found and not any_closing_matched and not suppress_closing_warn:


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,


                        account_name=item.account_name,


                        statement_amount=item.closing_balance,


                        note_amount=None,


                        difference=None,


                        location=f"附注-{item.account_name}-期末余额",


                        description=f"{self.NOTE_VALUE_NOT_FOUND_TAG} 报表期末余额{item.closing_balance}，但匹配的{len(valid_note_ids)}个附注表格均未识别出期末合计值，可能是表格结构识别不完整",


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=f"报表期末余额={item.closing_balance}，匹配附注表格{len(valid_note_ids)}个，均未提取到closing_balance_cell",


                        note_table_ids=valid_note_ids,


                    ))





                if has_opening and not any_opening_value_found and not any_opening_matched and not suppress_opening_warn:


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,


                        account_name=item.account_name,


                        statement_amount=item.opening_balance,


                        note_amount=None,


                        difference=None,


                        location=f"附注-{item.account_name}-期初余额",


                        description=f"{self.NOTE_VALUE_NOT_FOUND_TAG} 报表期初余额{item.opening_balance}，但匹配的{len(valid_note_ids)}个附注表格均未识别出期初合计值，可能是表格结构识别不完整",


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=f"报表期初余额={item.opening_balance}，匹配附注表格{len(valid_note_ids)}个，均未提取到opening_balance_cell",


                        note_table_ids=valid_note_ids,


                    ))





        return findings





    # ─── 附注表格内部勾稽 ───





    # 这些表格是汇总性质的财务信息摘要，行之间相互独立，不适用纵向加总/其中项/余额变动校验


    SKIP_INTEGRITY_KEYWORDS = [


        "主要财务信息",


        "重要合营企业",


        "重要联营企业",


        "重要合资企业",


        "不重要的合营企业",


        "不重要的联营企业",


    ]





    def _should_skip_integrity(self, note_table: NoteTable) -> bool:


        """判断表格是否应跳过完整性校验（汇总性质的财务信息表格）。"""


        combined = (note_table.section_title or "") + (note_table.account_name or "")


        if any(kw in combined for kw in self.SKIP_INTEGRITY_KEYWORDS):


            return True


        # "续："独立表格：解析时丢失了原表标题的续表，


        # 通常是重要联营/合营企业财务信息的跨页续表，行间无加总关系


        title_clean = (note_table.section_title or "").replace(" ", "").replace("\u3000", "").strip()


        title_clean = title_clean.rstrip("：:（()）")


        if title_clean == "续":


            return True


        # 未分配利润表有专用校验，跳过通用纵向加总


        if self._is_undistributed_profit_table(note_table):


            return True


        return False





    # ─── 未分配利润专用校验 ───





    UNDISTRIBUTED_PROFIT_KEYWORDS = ["未分配利润"]





    @staticmethod


    def _is_undistributed_profit_table(note_table: NoteTable) -> bool:


        """判断是否为未分配利润表格。"""


        combined = (note_table.section_title or "") + (note_table.account_name or "")


        return "未分配利润" in combined





    def check_undistributed_profit(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> List[ReportReviewFinding]:


        """未分配利润表专用校验。





        表格结构（典型）：


            行标签                          本期数/期末数    上期数/期初数


            调整后 期初未分配利润             A1              B1


            加：本期归属于母公司净利润        A2              B2


                其他（可能多行）              ...             ...


            减：提取法定盈余公积              A3              B3


                其他（可能多行）              ...             ...


            期末未分配利润                    A4              B4





        校验规则：


        1. 纵向公式：A1 + sum(加项) - sum(减项) = A4（每列独立校验）


        2. 跨期衔接：本期列的"调整后期初未分配利润" = 上期列的"期末未分配利润"


        """


        findings: List[ReportReviewFinding] = []


        if not note_table.rows:


            return findings





        rows = note_table.rows


        headers = note_table.headers or []





        # ── 定位关键行 ──


        opening_row_idx = None   # "调整后 期初未分配利润" 行 / 国企"本期期初余额"行


        closing_row_idx = None   # "期末未分配利润" 行 / 国企"本期期末余额"行


        add_start = None         # "加：" 区域起始行 / 国企"本期增加额"行


        sub_start = None         # "减：" 区域起始行 / 国企"本期减少额"行





        for ri, row in enumerate(rows):


            label = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()


            # 上市格式


            if ("期初未分配利润" in label or "期初未分配" in label) and opening_row_idx is None:


                opening_row_idx = ri


            if ("期末未分配利润" in label or "期末未分配" in label) and closing_row_idx is None:


                closing_row_idx = ri


            # 国企格式


            if "本期期初余额" in label and opening_row_idx is None:


                opening_row_idx = ri


            if "本期期末余额" in label and closing_row_idx is None:


                closing_row_idx = ri


            # 上市格式：加/减


            if label.startswith("加") or label.startswith("加：") or label.startswith("加:"):


                if add_start is None:


                    add_start = ri


            if label.startswith("减") or label.startswith("减：") or label.startswith("减:"):


                if sub_start is None:


                    sub_start = ri


            # 国企格式：本期增加额/本期减少额


            if "本期增加额" in label and add_start is None:


                add_start = ri


            if "本期减少额" in label and sub_start is None:


                sub_start = ri





        if opening_row_idx is None or closing_row_idx is None:


            return findings





        # 检测是否为国企格式（"本期增加额"/"本期减少额"行本身包含合计值）


        is_soe_format = False


        for ri in (add_start, sub_start):


            if ri is not None:


                lbl = str(rows[ri][0] if rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()


                if "本期增加额" in lbl or "本期减少额" in lbl:


                    is_soe_format = True


                    break





        # 如果没有明确的"加："/"减："标记，尝试推断：


        # 期初行之后到"减"之前为加项，"减"之后到期末行之前为减项


        if add_start is None:


            add_start = opening_row_idx + 1


        if sub_start is None:


            # 没有减项区域，所有中间行都是加项


            sub_start = closing_row_idx





        # ── 识别数值列（跳过第一列标签列）──


        num_cols = []


        for ci in range(1, len(headers)):


            num_cols.append(ci)


        if not num_cols:


            return findings





        # ── 逐列校验纵向公式 ──


        for ci in num_cols:


            opening_val = self._get_row_col_value(note_table, opening_row_idx, ci)


            closing_val = self._get_row_col_value(note_table, closing_row_idx, ci)


            if opening_val is None or closing_val is None:


                continue





            if is_soe_format:


                # 国企格式：直接取"本期增加额"和"本期减少额"行的值


                add_sum = self._get_row_col_value(note_table, add_start, ci) or 0.0


                sub_sum = self._get_row_col_value(note_table, sub_start, ci) or 0.0


            else:


                # 上市格式：汇总加项（add_start 到 sub_start 之间，排除小计行和空行）


                add_sum = 0.0


                for ri in range(add_start, sub_start):


                    if ri == opening_row_idx:


                        continue


                    label = str(rows[ri][0] if rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()


                    # 跳过"小计"行和纯标记行（如"加："本身）


                    if "小计" in label or label in ("加：", "加:", "加", "减：", "减:", "减"):


                        continue


                    v = self._get_row_col_value(note_table, ri, ci)


                    if v is not None:


                        add_sum += v





                # 汇总减项（sub_start 到 closing_row_idx 之间）


                sub_sum = 0.0


                for ri in range(sub_start, closing_row_idx):


                    label = str(rows[ri][0] if rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()


                    if "小计" in label or label in ("加：", "加:", "加", "减：", "减:", "减"):


                        continue


                    v = self._get_row_col_value(note_table, ri, ci)


                    if v is not None:


                        sub_sum += v





            expected = opening_val + add_sum - sub_sum


            if not _amounts_equal(expected, closing_val):


                diff = round(expected - closing_val, 2)


                col_label = headers[ci] if ci < len(headers) else f"列{ci + 1}"


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=note_table.account_name,


                    location=f"附注-{note_table.account_name}-{note_table.section_title}-{col_label}",


                    description=(


                        f"未分配利润纵向公式不平：期初({opening_val})"


                        f"+加项({add_sum})-减项({sub_sum})={expected}，"


                        f"期末({closing_val})，差异{diff}"


                    ),


                    difference=diff,


                    statement_amount=expected,


                    note_amount=closing_val,


                    risk_level=RiskLevel.MEDIUM,


                    reasoning=(


                        f"公式: {opening_val}+{add_sum}-{sub_sum}={expected}, "


                        f"实际期末={closing_val}"


                    ),


                    note_table_ids=[note_table.id],


                    highlight_cells=[{"row": opening_row_idx, "col": ci}, {"row": closing_row_idx, "col": ci}],


                ))





        # ── 跨期衔接校验 ──


        # 本期列的"调整后期初未分配利润" 应等于 上期列的"期末未分配利润"


        # 表头通常为 [项目, 本期数/期末数, 上期数/期初数]


        if len(num_cols) >= 2:


            closing_col = None  # 本期/期末列


            opening_col = None  # 上期/期初列


            closing_kw = self._CLOSING_COL_KW


            opening_kw = self._OPENING_COL_KW


            for ci in num_cols:


                h = str(headers[ci] if ci < len(headers) else "").replace(" ", "").replace("\u3000", "")


                if opening_col is None and any(kw in h for kw in opening_kw):


                    opening_col = ci


                elif closing_col is None and any(kw in h for kw in closing_kw):


                    closing_col = ci


            # fallback：第一个数值列=本期，第二个=上期


            if closing_col is None and opening_col is None and len(num_cols) >= 2:


                closing_col = num_cols[0]


                opening_col = num_cols[1]





            if closing_col is not None and opening_col is not None:


                # 本期列的期初值


                current_opening = self._get_row_col_value(


                    note_table, opening_row_idx, closing_col


                )


                # 上期列的期末值


                prior_closing = self._get_row_col_value(


                    note_table, closing_row_idx, opening_col


                )


                if (current_opening is not None and prior_closing is not None


                        and not _amounts_equal(current_opening, prior_closing)):


                    diff = round(current_opening - prior_closing, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=note_table.account_name,


                        location=f"附注-{note_table.account_name}-{note_table.section_title}-跨期衔接",


                        description=(


                            f"跨期衔接不平：本期列的调整后期初未分配利润({current_opening})"


                            f"≠上期列的期末未分配利润({prior_closing})，差异{diff}"


                        ),


                        difference=diff,


                        statement_amount=current_opening,


                        note_amount=prior_closing,


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=(


                            f"跨期衔接: 本期期初={current_opening}, "


                            f"上期期末={prior_closing}"


                        ),


                        note_table_ids=[note_table.id],


                        highlight_cells=[{"row": opening_row_idx, "col": closing_col}, {"row": closing_row_idx, "col": opening_col}],


                    ))





        return findings





    def check_note_table_integrity(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> List[ReportReviewFinding]:


        """基于 LLM 识别的合计行/列结构校验横纵加总。"""


        findings: List[ReportReviewFinding] = []





        # 跳过汇总性质的财务信息表格（如"重要合营企业的主要财务信息"及其续表）


        if self._should_skip_integrity(note_table):


            return findings





        # 纵向加总校验：数据行之和 == 合计行


        for total_idx in table_structure.total_row_indices:


            data_indices = self._get_data_rows_for_total(table_structure, total_idx)


            if not data_indices:


                continue





            for col in table_structure.columns:


                if col.semantic in ("label", "other"):


                    continue





                total_val = self._get_row_col_value(note_table, total_idx, col.col_index)


                if total_val is None:


                    continue





                data_sum = 0.0


                has_data = False


                # 构建行索引→sign映射，用于纵向加总时区分加减行


                row_sign_map: Dict[int, int] = {


                    r.row_index: r.sign for r in table_structure.rows


                }


                for di in data_indices:


                    v = self._get_row_col_value(note_table, di, col.col_index)


                    if v is not None:


                        sign = row_sign_map.get(di, 1)


                        data_sum += sign * v


                        has_data = True





                if has_data and not _amounts_equal(data_sum, total_val):


                    diff = round(data_sum - total_val, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=note_table.account_name,


                        statement_amount=total_val,


                        note_amount=data_sum,


                        difference=diff,


                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{total_idx + 1}行合计-列{col.col_index + 1}",


                        description=f"纵向加总不平：数据行合计{data_sum}，合计行{total_val}，差异{diff}",


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=f"校验: sum(数据行)={data_sum}, 合计行={total_val}, 差异={diff}",


                        note_table_ids=[note_table.id],


                        highlight_cells=[{"row": total_idx, "col": col.col_index}],


                    ))





        return findings





    # ─── 余额变动公式校验 ───





    # 长期资产多段表格中，"账面净值"和"账面价值"段的行不适用横向余额变动公式


    # （这些段只有期初和期末，本期增加/减少为空，是由原值-折旧/摊销计算得出的）


    _BOOK_VALUE_SECTION_KW = ["账面净值", "账面价值"]





    def check_balance_formula(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> List[ReportReviewFinding]:


        """校验 期初+增加-减少=期末 余额变动公式。"""


        findings: List[ReportReviewFinding] = []


        if self._should_skip_integrity(note_table):


            return findings


        if not table_structure.has_balance_formula:


            return findings





        # 收集各语义列（可能有多个增加/减少列）


        opening_cols = [c.col_index for c in table_structure.columns if c.semantic == "opening_balance"]


        closing_cols = [c.col_index for c in table_structure.columns if c.semantic == "closing_balance"]


        increase_cols = [c.col_index for c in table_structure.columns if c.semantic == "current_increase"]


        decrease_cols = [c.col_index for c in table_structure.columns if c.semantic == "current_decrease"]





        if not opening_cols or not closing_cols:


            return findings


        # 如果没有增减列，无法校验公式


        if not increase_cols and not decrease_cols:


            return findings





        opening_col = opening_cols[0]


        closing_col = closing_cols[0]





        # 预计算多段表格中"账面净值/账面价值"段的行索引集合


        # 这些段的横向公式不适用（本期增减为空，值由纵向计算得出）


        book_value_rows: set = set()


        if any(kw in (note_table.account_name or '') for kw in self._SECTION_EXTRACT_ACCOUNTS):


            _in_bv_section = False


            for ri, row in enumerate(note_table.rows):


                first = str(row[0] if row else '').replace(' ', '').replace('\u3000', '').strip()


                if _SECTION_PATTERN.match(first):


                    _in_bv_section = any(kw in first for kw in self._BOOK_VALUE_SECTION_KW)


                if _in_bv_section:


                    book_value_rows.add(ri)





        for row_struct in table_structure.rows:


            # 跳过表头行和其中项行（其中项是父项的部分拆分，不一定满足余额变动公式）


            if row_struct.role in ("header", "sub_item"):


                continue


            # 跳过"账面净值/账面价值"段的行（横向公式不适用）


            if row_struct.row_index in book_value_rows:


                continue





            opening = self._get_row_col_value(note_table, row_struct.row_index, opening_col)


            closing = self._get_row_col_value(note_table, row_struct.row_index, closing_col)





            if opening is None or closing is None:


                continue





            # 汇总所有增加列


            total_increase = 0.0


            for ic in increase_cols:


                v = self._get_row_col_value(note_table, row_struct.row_index, ic)


                if v is not None:


                    total_increase += v





            # 汇总所有减少列


            total_decrease = 0.0


            for dc in decrease_cols:


                v = self._get_row_col_value(note_table, row_struct.row_index, dc)


                if v is not None:


                    total_decrease += v





            expected = opening + total_increase - total_decrease


            if not _amounts_equal(expected, closing):


                diff = round(expected - closing, 2)


                _hl = [{"row": row_struct.row_index, "col": opening_col},


                       {"row": row_struct.row_index, "col": closing_col}]


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=note_table.account_name,


                    location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_struct.row_index + 1}行'{row_struct.label}'",


                    description=f"余额变动公式不平：期初{opening}+增加{total_increase}-减少{total_decrease}={expected}，期末{closing}，差异{diff}",


                    difference=diff,


                    statement_amount=expected,


                    note_amount=closing,


                    risk_level=RiskLevel.MEDIUM,


                    reasoning=f"公式: {opening}+{total_increase}-{total_decrease}={expected}, 实际期末={closing}",


                    note_table_ids=[note_table.id],


                    highlight_cells=_hl,


                ))





        return findings





    # ─── 宽表横向公式校验（LLM 辅助识别列语义，本地数值验证）───





    def check_wide_table_formula(


        self,


        note_table: NoteTable,


        wide_table_formula: dict,


    ) -> List[ReportReviewFinding]:


        """根据 LLM 识别的宽表公式结构，逐行验证横向公式。





        支持两种格式：


        - movement（变动公式型/国企版）：期初 + 变动列 = 期末


        - category_sum（分类合计型/上市版）：各分类数据列之和 = 合计列





        wide_table_formula 格式由 TableStructureAnalyzer.analyze_wide_table_formula 返回。


        所有数值计算在本地完成，LLM 只提供列语义和符号。


        """


        findings: List[ReportReviewFinding] = []


        if not wide_table_formula or "columns" not in wide_table_formula:


            return findings





        columns = wide_table_formula["columns"]





        # 判断公式类型：优先使用 LLM 返回的 formula_type，否则根据列角色自动推断


        formula_type = wide_table_formula.get("formula_type", "")


        if not formula_type:


            has_total = any(c.get("role") == "total" for c in columns)


            has_data = any(c.get("role") == "data" for c in columns)


            has_opening = any(c.get("role") == "opening" for c in columns)


            if has_total and has_data:


                formula_type = "category_sum"


            elif has_opening:


                formula_type = "movement"


            else:


                formula_type = "movement"





        if formula_type == "category_sum":


            return self._check_wide_table_category_sum(note_table, wide_table_formula)


        else:


            return self._check_wide_table_movement(note_table, wide_table_formula)





    def _check_wide_table_movement(


        self,


        note_table: NoteTable,


        wide_table_formula: dict,


    ) -> List[ReportReviewFinding]:


        """变动公式型（国企版）：期初 + Σ变动 = 期末"""


        findings: List[ReportReviewFinding] = []


        columns = wide_table_formula["columns"]


        data_row_start = wide_table_formula.get("data_row_start", 0)


        is_multi_section = wide_table_formula.get("multi_section", False)





        opening_cols = [c for c in columns if c.get("role") == "opening"]


        closing_cols = [c for c in columns if c.get("role") == "closing"]


        movement_cols = [c for c in columns if c.get("role") == "movement"]





        if not opening_cols or not closing_cols:


            return findings





        opening_col_idx = opening_cols[0]["col_index"]


        closing_col_idx = closing_cols[0]["col_index"]





        # 构建公式描述


        formula_parts = [opening_cols[0].get("name", "期初")]


        for mc in movement_cols:


            sign = mc.get("sign", "+")


            name = mc.get("name", f"列{mc['col_index']}")


            formula_parts.append(f"{sign} {name}")


        formula_parts.append(f"= {closing_cols[0].get('name', '期末')}")


        formula_desc = " ".join(formula_parts)





        total_keywords = ["合计", "总计", "小计", "合 计", "合\u3000计"]





        # 预计算"账面净值/账面价值"段的行索引集合（长期资产多段表格）


        book_value_rows: set = set()


        section_header_rows: set = set()  # 段标题行（如"一、账面原值"）


        acct_name = note_table.account_name or ''


        if is_multi_section or any(kw in acct_name for kw in self._SECTION_EXTRACT_ACCOUNTS):


            _in_bv = False


            for ri, row in enumerate(note_table.rows):


                first = str(row[0] if row else '').replace(' ', '').replace('\u3000', '').strip()


                if _SECTION_PATTERN.match(first):


                    section_header_rows.add(ri)


                    _in_bv = any(kw in first for kw in self._BOOK_VALUE_SECTION_KW)


                if _in_bv:


                    book_value_rows.add(ri)





        for row_idx in range(data_row_start, len(note_table.rows)):


            row = note_table.rows[row_idx]


            if not row:


                continue





            label = self._get_wide_table_row_label(row, columns)


            if not label:


                continue





            if label.startswith("其中") or label.startswith("其中：") or label.startswith("其中:"):


                continue





            # 跳过段标题行（如"一、账面原值"、"二、累计折旧"）


            if row_idx in section_header_rows:


                continue





            # 跳过"账面净值/账面价值"段的行（横向公式不适用）


            if row_idx in book_value_rows:


                continue





            opening = self._get_row_col_value(note_table, row_idx, opening_col_idx)


            closing = self._get_row_col_value(note_table, row_idx, closing_col_idx)





            if opening is None and closing is None:


                continue


            opening = opening or 0.0


            closing = closing or 0.0





            all_zero = abs(opening) < 0.01 and abs(closing) < 0.01


            if all_zero:


                has_movement = False


                for mc in movement_cols:


                    v = self._get_row_col_value(note_table, row_idx, mc["col_index"])


                    if v is not None and abs(v) >= 0.01:


                        has_movement = True


                        break


                if not has_movement:


                    continue





            expected = opening


            movement_details = []


            for mc in movement_cols:


                v = self._get_row_col_value(note_table, row_idx, mc["col_index"])


                if v is None:


                    v = 0.0


                sign = mc.get("sign", "+")


                name = mc.get("name", f"列{mc['col_index']}")


                if sign == "-":


                    expected -= v


                    movement_details.append(f"-{name}({v})")


                else:


                    expected += v


                    movement_details.append(f"+{name}({v})")





            if not _amounts_equal(expected, closing):


                diff = round(expected - closing, 2)


                is_total = any(kw in label for kw in total_keywords)


                risk = RiskLevel.HIGH if is_total else RiskLevel.MEDIUM





                detail_str = f"期初({opening})" + "".join(movement_details) + f"={expected}"


                _hl = [{"row": row_idx, "col": opening_col_idx}, {"row": row_idx, "col": closing_col_idx}]


                for mc in movement_cols:


                    _hl.append({"row": row_idx, "col": mc["col_index"]})


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=note_table.account_name,


                    location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_idx + 1}行'{label}'",


                    description=f"宽表横向公式不平：{detail_str}，期末{closing}，差异{diff}",


                    difference=diff,


                    statement_amount=expected,


                    note_amount=closing,


                    risk_level=risk,


                    reasoning=f"公式: {formula_desc}",


                    note_table_ids=[note_table.id],


                    highlight_cells=_hl,


                ))





        return findings





    def _check_wide_table_category_sum(


        self,


        note_table: NoteTable,


        wide_table_formula: dict,


    ) -> List[ReportReviewFinding]:


        """分类合计型（上市版）：各分类数据列之和 = 合计列"""


        findings: List[ReportReviewFinding] = []


        columns = wide_table_formula["columns"]


        data_row_start = wide_table_formula.get("data_row_start", 0)





        data_cols = [c for c in columns if c.get("role") == "data"]


        total_cols = [c for c in columns if c.get("role") == "total"]





        if not data_cols or not total_cols:


            return findings





        total_col_idx = total_cols[0]["col_index"]





        # 构建公式描述


        data_names = [c.get("name", f"列{c['col_index']}") for c in data_cols]


        total_name = total_cols[0].get("name", "合计")


        formula_desc = " + ".join(data_names) + f" = {total_name}"





        # 合计行 / 小计行关键词


        total_row_keywords = ["合计", "总计", "小计", "合 计", "合\u3000计"]





        for row_idx in range(data_row_start, len(note_table.rows)):


            row = note_table.rows[row_idx]


            if not row:


                continue





            label = self._get_wide_table_row_label(row, columns)


            if not label:


                continue





            # 跳过"其中"行


            if label.startswith("其中") or label.startswith("其中：") or label.startswith("其中:"):


                continue





            # 获取合计列值


            total_val = self._get_row_col_value(note_table, row_idx, total_col_idx)


            if total_val is None:


                continue





            # 计算各分类列之和


            computed_sum = 0.0


            all_none = True


            detail_parts = []


            for dc in data_cols:


                col_name = dc.get("name", f"列{dc['col_index']}")


                v = self._get_row_col_value(note_table, row_idx, dc["col_index"])


                if v is not None:


                    all_none = False


                    computed_sum += v


                    detail_parts.append(f"{col_name}({v})")


                else:


                    detail_parts.append(f"{col_name}(0)")





            # 如果所有分类列都是 None 且合计也是 0，跳过空行


            if all_none and abs(total_val) < 0.01:


                continue





            computed_sum = round(computed_sum, 2)





            if not _amounts_equal(computed_sum, total_val):


                diff = round(computed_sum - total_val, 2)


                is_total_row = any(kw in label for kw in total_row_keywords)


                risk = RiskLevel.HIGH if is_total_row else RiskLevel.MEDIUM





                detail_str = " + ".join(detail_parts) + f" = {computed_sum}"


                _hl = [{"row": row_idx, "col": total_col_idx}]


                for dc in data_cols:


                    _hl.append({"row": row_idx, "col": dc["col_index"]})


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=note_table.account_name,


                    location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_idx + 1}行'{label}'",


                    description=f"宽表横向合计不平：{detail_str}，合计列{total_val}，差异{diff}",


                    difference=diff,


                    statement_amount=computed_sum,


                    note_amount=total_val,


                    risk_level=risk,


                    reasoning=f"公式: {formula_desc}",


                    note_table_ids=[note_table.id],


                    highlight_cells=_hl,


                ))





        return findings





    @staticmethod


    def _get_wide_table_row_label(row: list, columns: list) -> str:


        """从宽表行中提取行标签。"""


        label_cols = [c for c in columns if c.get("role") == "label"]


        if label_cols:


            label_col_idx = label_cols[0]["col_index"]


            if label_col_idx < len(row):


                return str(row[label_col_idx] or "").strip()


        if len(row) > 0:


            return str(row[0] or "").strip()


        return ""





    # ─── 其中项校验 ───





    def check_sub_items(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> List[ReportReviewFinding]:


        """验证各 sub_item 之和 ≤ 父项金额。"""


        findings: List[ReportReviewFinding] = []


        if self._should_skip_integrity(note_table):


            return findings





        # 按 parent 分组


        parent_children: Dict[int, List[int]] = {}


        for row in table_structure.rows:


            if row.role == "sub_item" and row.parent_row_index is not None:


                # 跳过纯"其中："标记行（只有"其中"关键词，没有实际明细名称）


                stripped = row.label.strip()


                is_bare_header = stripped in ("其中：", "其中:", "其中")


                if is_bare_header:


                    continue


                # 跳过被 LLM 错误标记为 sub_item 的合计/小计行


                norm_label = stripped.replace(" ", "").replace("\u3000", "")


                if any(kw == norm_label or norm_label.endswith(kw)


                       for kw in ("合计", "小计", "总计", "总额")):


                    continue


                parent_children.setdefault(row.parent_row_index, []).append(row.row_index)





        for parent_idx, child_indices in parent_children.items():


            for col in table_structure.columns:


                if col.semantic in ("label", "other"):


                    continue





                parent_val = self._get_row_col_value(note_table, parent_idx, col.col_index)


                if parent_val is None:


                    continue





                child_sum = 0.0


                has_child = False


                for ci in child_indices:


                    v = self._get_row_col_value(note_table, ci, col.col_index)


                    if v is not None:


                        child_sum += v


                        has_child = True





                if has_child and child_sum > parent_val + TOLERANCE:


                    diff = round(child_sum - parent_val, 2)


                    parent_label = ""


                    for r in table_structure.rows:


                        if r.row_index == parent_idx:


                            parent_label = r.label


                            break


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=note_table.account_name,


                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{parent_idx + 1}行'{parent_label}'",


                        description=f"其中项之和{child_sum}超过父项{parent_val}，差异{diff}",


                        difference=diff,


                        statement_amount=parent_val,


                        note_amount=child_sum,


                        risk_level=RiskLevel.LOW,


                        reasoning=f"其中项校验: sum(子项)={child_sum} > 父项={parent_val}",


                        note_table_ids=[note_table.id],


                        highlight_cells=[{"row": parent_idx, "col": col.col_index}] + [{"row": ci, "col": col.col_index} for ci in child_indices],


                    ))





        return findings





    def check_ratio_columns(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> List[ReportReviewFinding]:


        """校验比例列，自动区分两种比例类型：





        1. 纵向占比：比例(%) = 本行金额 / 合计行金额 × 100（如分类占比）


        2. 横向计提率：比例(%) = 紧邻左侧金额 / 同行某金额 × 100（如坏账计提比例）





        判断依据：合计行的比例值 ≈ 100 → 纵向占比；否则 → 横向计提率。


        横向计提率的分母通过合计行数据自动探测。


        """


        findings: List[ReportReviewFinding] = []


        if self._should_skip_integrity(note_table):


            return findings





        RATIO_KEYWORDS = ["比例", "%", "占比", "百分比", "预期信用损失率", "计提比例"]





        # ── 检测比例列：按表头关键词识别，不依赖 LLM 的 semantic 标注 ──


        ratio_cols: List[int] = []


        for ci, header in enumerate(note_table.headers):


            header_str = str(header).strip() if header else ""


            if any(kw in header_str for kw in RATIO_KEYWORDS):


                ratio_cols.append(ci)





        if not ratio_cols:


            return findings





        # ── 收集所有非比例、非标签的金额列索引（按表头判断）──


        amount_col_indices: List[int] = []


        for ci, header in enumerate(note_table.headers):


            if ci in ratio_cols:


                continue


            header_str = str(header).strip() if header else ""


            # 第一列通常是标签列


            if ci == 0:


                continue


            # 跳过明显的非金额列


            if any(kw in header_str for kw in RATIO_KEYWORDS):


                continue


            amount_col_indices.append(ci)





        for ratio_col_idx in ratio_cols:


            # 找比例列左侧最近的金额列作为分子候选


            numerator_col = None


            for ci in reversed(amount_col_indices):


                if ci < ratio_col_idx:


                    numerator_col = ci


                    break


            if numerator_col is None:


                continue





            # ── 判断比例类型：检查合计行的比例值 ──


            total_ratio_val = None


            for ti in table_structure.total_row_indices:


                v = self._get_row_col_value(note_table, ti, ratio_col_idx)


                if v is not None:


                    total_ratio_val = v


                    break





            is_vertical = (total_ratio_val is not None and abs(total_ratio_val - 100.0) < 1.0)





            if is_vertical:


                # ── 纵向占比：比例 = 本行金额 / 合计行金额 × 100 ──


                total_amount = None


                for ti in table_structure.total_row_indices:


                    v = self._get_row_col_value(note_table, ti, numerator_col)


                    if v is not None and abs(v) > 0.01:


                        total_amount = v


                        break


                if total_amount is None:


                    continue





                for row_s in table_structure.rows:


                    if row_s.role not in ("data", "sub_item"):


                        continue


                    amount_val = self._get_row_col_value(note_table, row_s.row_index, numerator_col)


                    ratio_val = self._get_row_col_value(note_table, row_s.row_index, ratio_col_idx)


                    if amount_val is None or ratio_val is None:


                        continue


                    if abs(total_amount) < 0.01:


                        continue


                    expected_ratio = amount_val / total_amount * 100


                    diff = abs(ratio_val - expected_ratio)


                    if diff > RATIO_TOLERANCE:


                        findings.append(self._make_finding(


                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                            account_name=note_table.account_name,


                            location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_s.row_index + 1}行'{row_s.label}'-列{ratio_col_idx + 1}",


                            description=f"比例列数值{ratio_val:.2f}%与计算值{expected_ratio:.2f}%不符，差异{diff:.2f}个百分点",


                            difference=round(diff, 2),


                            statement_amount=expected_ratio,


                            note_amount=ratio_val,


                            risk_level=RiskLevel.LOW,


                            reasoning=f"纵向占比校验: {amount_val}/{total_amount}*100={expected_ratio:.2f}%, 实际={ratio_val:.2f}%",


                            note_table_ids=[note_table.id],


                            highlight_cells=[{"row": row_s.row_index, "col": ratio_col_idx}, {"row": row_s.row_index, "col": numerator_col}],


                        ))


            else:


                # ── 横向计提率：比例 = 分子列 / 分母列 × 100 ──


                # 分子 = 紧邻左侧金额列（numerator_col）


                # 分母 = 通过合计行数据自动探测：遍历所有更左侧的金额列，


                #        找到使 numerator_total / denominator_candidate * 100 ≈ total_ratio_val 的列


                denominator_col = None





                if total_ratio_val is not None and abs(total_ratio_val) > 0.001:


                    # 获取合计行分子值


                    numerator_total = None


                    for ti in table_structure.total_row_indices:


                        v = self._get_row_col_value(note_table, ti, numerator_col)


                        if v is not None:


                            numerator_total = v


                            break





                    if numerator_total is not None:


                        best_diff = 999.0


                        for ci in amount_col_indices:


                            if ci >= numerator_col:


                                continue  # 分母必须在分子左侧


                            for ti in table_structure.total_row_indices:


                                denom_val = self._get_row_col_value(note_table, ti, ci)


                                if denom_val is not None and abs(denom_val) > 0.01:


                                    candidate_ratio = numerator_total / denom_val * 100


                                    d = abs(candidate_ratio - total_ratio_val)


                                    if d < best_diff:


                                        best_diff = d


                                        denominator_col = ci


                                    break  # 只用第一个合计行





                        # 如果最佳匹配差异太大，放弃


                        if best_diff > 1.0:


                            denominator_col = None





                if denominator_col is None:


                    continue





                for row_s in table_structure.rows:


                    if row_s.role not in ("data", "sub_item", "total"):


                        continue


                    numerator_val = self._get_row_col_value(note_table, row_s.row_index, numerator_col)


                    denominator_val = self._get_row_col_value(note_table, row_s.row_index, denominator_col)


                    ratio_val = self._get_row_col_value(note_table, row_s.row_index, ratio_col_idx)


                    if numerator_val is None or denominator_val is None or ratio_val is None:


                        continue


                    if abs(denominator_val) < 0.01:


                        continue


                    expected_ratio = numerator_val / denominator_val * 100


                    diff = abs(ratio_val - expected_ratio)


                    if diff > RATIO_TOLERANCE:


                        findings.append(self._make_finding(


                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                            account_name=note_table.account_name,


                            location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_s.row_index + 1}行'{row_s.label}'-列{ratio_col_idx + 1}",


                            description=f"比例列数值{ratio_val:.2f}%与计算值{expected_ratio:.2f}%不符，差异{diff:.2f}个百分点",


                            difference=round(diff, 2),


                            statement_amount=expected_ratio,


                            note_amount=ratio_val,


                            risk_level=RiskLevel.LOW,


                            reasoning=f"横向计提率校验: {numerator_val}/{denominator_val}*100={expected_ratio:.2f}%, 实际={ratio_val:.2f}%",


                            note_table_ids=[note_table.id],


                            highlight_cells=[{"row": row_s.row_index, "col": ratio_col_idx}, {"row": row_s.row_index, "col": numerator_col}, {"row": row_s.row_index, "col": denominator_col}],


                        ))





        return findings





    # ─── 同科目跨表交叉核对 ───





    # 坏账准备类科目关键词（这些科目通常有 总表 + 分类表 + 坏账变动表 的多表结构）


    BAD_DEBT_ACCOUNT_KEYWORDS = [


        "应收票据", "应收账款", "其他应收款", "合同资产",


        "应收款项融资", "长期应收款",


    ]





    # 坏账准备变动表标题关键词


    BAD_DEBT_MOVEMENT_KEYWORDS = ["坏账准备", "减值准备"]


    BAD_DEBT_MOVEMENT_TITLE_KEYWORDS = ["计提", "收回", "转回", "核销", "变动"]





    # 按坏账计提方法分类表标题关键词


    BAD_DEBT_CLASSIFY_KEYWORDS = ["坏账计提方法", "计提方法分类", "按单项", "按组合"]





    # 应付职工薪酬子表关键词


    PAYROLL_SUB_KEYWORDS = {


        "短期薪酬": ["短期薪酬"],


        "设定提存计划": ["设定提存", "离职后福利"],


    }





    # 固定资产/在建工程/无形资产 汇总表 vs 明细表


    # 国企报表中，投资性房地产（成本模式）、使用权资产、油气资产、生产性生物资产


    # 也采用相同的多段式表格结构（原价/累计折旧/净值/减值准备/账面价值）


    ASSET_SUMMARY_ACCOUNTS = [


        "固定资产", "在建工程", "无形资产",


        "投资性房地产", "使用权资产", "油气资产", "生产性生物资产",


    ]





    # 存货：分类表 vs 跌价准备变动表


    INVENTORY_KEYWORDS = ["存货"]





    # 商誉：原值表 vs 减值准备表


    GOODWILL_KEYWORDS = ["商誉"]





    # 债权投资类科目：总表 vs 减值准备变动表


    DEBT_INVESTMENT_KEYWORDS = ["债权投资", "其他债权投资"]





    # 合同资产：总表 vs 减值准备变动表


    CONTRACT_ASSET_KEYWORDS = ["合同资产"]





    # 营业收入/营业成本：汇总表 vs 按行业/地区/商品转让时间划分的明细表


    REVENUE_COST_KEYWORDS = ["营业收入", "营业成本"]





    # 营业收入/营业成本明细子表标题关键词


    # 国企模板：按行业（或产品类型）划分、按地区划分、按商品转让时间划分


    # 上市模板：按行业（或产品类型）划分、按地区划分、按商品转让时间划分


    _REVENUE_COST_DETAIL_KW = [


        "按行业", "按产品", "按地区", "按商品转让时间",


        "前五名", "前5名",


    ]





    def check_cross_table_consistency(


        self,


        notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """同科目下多个表格之间的交叉核对。





        校验规则：


        1. 坏账准备类科目：总表坏账准备 vs 坏账准备变动表期末余额；


           总表金额 vs 分类表(单项+组合)合计


        2. 应付职工薪酬：汇总表"短期薪酬"行 vs 短期薪酬明细表合计行


        3. 固定资产/在建工程/无形资产/投资性房地产/使用权资产/油气资产/生产性生物资产：


           汇总表 vs 明细表账面价值/净值合计


        4. 在建工程：明细表减值准备合计 vs 减值准备变动表期末余额


        5. 存货：分类表跌价准备 vs 跌价准备变动表期末余额


        6. 商誉：原值表期末 - 减值准备表期末 = 账面价值


        7. 债权投资/其他债权投资：总表减值准备 vs 减值准备变动表期末余额


        8. 合同资产：总表减值准备 vs 减值准备变动表期末余额


        9. 营业收入/营业成本：汇总表合计 vs 按行业/地区/商品转让时间划分明细表合计


        """


        findings: List[ReportReviewFinding] = []





        # 按 account_name 分组


        account_notes: Dict[str, List[NoteTable]] = {}


        for n in notes:


            account_notes.setdefault(n.account_name, []).append(n)





        for acct_name, acct_notes in account_notes.items():


            # ── 1. 坏账准备类科目跨表核对 ──


            if any(kw in acct_name for kw in self.BAD_DEBT_ACCOUNT_KEYWORDS):


                findings.extend(self._check_bad_debt_cross(


                    acct_name, acct_notes, table_structures,


                ))





            # ── 2. 应付职工薪酬跨表核对 ──


            if "应付职工薪酬" in acct_name:


                findings.extend(self._check_payroll_cross(


                    acct_name, acct_notes, table_structures,


                ))





            # ── 3. 固定资产/在建工程/无形资产 汇总表 vs 明细表 ──


            if any(kw == acct_name or acct_name.startswith(kw) for kw in self.ASSET_SUMMARY_ACCOUNTS):


                findings.extend(self._check_asset_summary_cross(


                    acct_name, acct_notes, table_structures,


                ))





            # ── 4. 存货：分类表跌价准备 vs 跌价准备变动表 ──


            if any(kw in acct_name for kw in self.INVENTORY_KEYWORDS):


                findings.extend(self._check_inventory_cross(


                    acct_name, acct_notes, table_structures,


                ))





            # ── 5. 商誉：原值表 vs 减值准备表 ──


            if any(kw in acct_name for kw in self.GOODWILL_KEYWORDS):


                findings.extend(self._check_goodwill_cross(


                    acct_name, acct_notes, table_structures,


                ))





            # ── 6. 债权投资/其他债权投资：总表减值准备 vs 减值准备变动表 ──


            if any(kw == acct_name for kw in self.DEBT_INVESTMENT_KEYWORDS):


                findings.extend(self._check_debt_investment_cross(


                    acct_name, acct_notes, table_structures,


                ))





            # ── 7. 合同资产：总表减值准备 vs 减值准备变动表 ──


            if any(kw in acct_name for kw in self.CONTRACT_ASSET_KEYWORDS):


                findings.extend(self._check_contract_asset_cross(


                    acct_name, acct_notes, table_structures,


                ))





            # ── 8. 营业收入/营业成本：汇总表 vs 明细表 ──


            if any(kw in acct_name for kw in self.REVENUE_COST_KEYWORDS):


                findings.extend(self._check_revenue_cost_cross(


                    acct_name, acct_notes, table_structures,


                ))





        return findings





    def _check_bad_debt_cross(


        self,


        acct_name: str,


        acct_notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """坏账准备类科目：总表 vs 坏账准备变动表 vs 分类表。"""


        findings: List[ReportReviewFinding] = []





        # 识别各类表格


        summary_table = None       # 总表（账面余额 | 坏账准备 | 账面价值）


        movement_table = None      # 坏账准备变动表（期初/计提/转回/核销/期末）


        classify_table = None      # 按坏账计提方法分类表





        for note in acct_notes:


            title = note.section_title or ""


            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""





            # 按坏账计提方法分类表：标题含"坏账计提方法"或"按单项"等（优先匹配，避免被变动表误吞）


            if any(kw in title for kw in self.BAD_DEBT_CLASSIFY_KEYWORDS):


                classify_table = note


                continue





            # 坏账准备变动表：标题含"坏账准备"且含"计提/收回/转回/核销/变动"


            if (any(kw in title for kw in self.BAD_DEBT_MOVEMENT_KEYWORDS)


                    and any(kw in title for kw in self.BAD_DEBT_MOVEMENT_TITLE_KEYWORDS)):


                movement_table = note


                continue





            # 总表：表头含"账面余额"和"坏账准备"（或"减值准备"）和"账面价值"


            if ("账面余额" in headers_str


                    and ("坏账准备" in headers_str or "减值准备" in headers_str)


                    and "账面价值" in headers_str):


                # 优先选第一个匹配的作为总表（通常是科目下的第一个表）


                if summary_table is None:


                    summary_table = note


                    continue





        if not summary_table:


            return findings





        ts_summary = table_structures.get(summary_table.id)


        if not ts_summary:


            return findings





        # 从总表合计行提取坏账准备金额


        summary_bad_debt = self._extract_bad_debt_from_summary(


            summary_table, ts_summary, "期末",


        )


        summary_bad_debt_opening = self._extract_bad_debt_from_summary(


            summary_table, ts_summary, "期初",


        )


        summary_balance = self._extract_balance_from_summary(


            summary_table, ts_summary, "期末",


        )





        # ── 规则 1：总表坏账准备 vs 坏账准备变动表期末余额 ──


        if movement_table and summary_bad_debt is not None:


            movement_end = self._extract_movement_end_balance(movement_table, table_structures)


            if movement_end is not None and not _amounts_equal(summary_bad_debt, movement_end):


                diff = round(summary_bad_debt - movement_end, 2)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=acct_name,


                    location=f"附注-{acct_name}-跨表核对-总表vs坏账变动表",


                    description=(


                        f"总表坏账准备期末{summary_bad_debt}与坏账准备变动表期末余额"


                        f"{movement_end}不一致，差异{diff}"


                    ),


                    difference=diff,


                    statement_amount=summary_bad_debt,


                    note_amount=movement_end,


                    risk_level=RiskLevel.MEDIUM,


                    reasoning=(


                        f"跨表核对: 总表坏账准备({summary_bad_debt}) vs "


                        f"坏账变动表期末({movement_end}), 差异={diff}"


                    ),


                    note_table_ids=[summary_table.id, movement_table.id],


                ))





        # ── 规则 2：总表账面余额/坏账准备 vs 分类表合计 ──


        if classify_table and summary_bad_debt is not None:


            ts_classify = table_structures.get(classify_table.id)


            if ts_classify:


                classify_bad_debt = self._extract_bad_debt_from_summary(


                    classify_table, ts_classify, "期末",


                )


                if (classify_bad_debt is not None


                        and not _amounts_equal(summary_bad_debt, classify_bad_debt)):


                    diff = round(summary_bad_debt - classify_bad_debt, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=acct_name,


                        location=f"附注-{acct_name}-跨表核对-总表vs分类表",


                        description=(


                            f"总表坏账准备{summary_bad_debt}与分类表坏账准备合计"


                            f"{classify_bad_debt}不一致，差异{diff}"


                        ),


                        difference=diff,


                        statement_amount=summary_bad_debt,


                        note_amount=classify_bad_debt,


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=(


                            f"跨表核对: 总表坏账准备({summary_bad_debt}) vs "


                            f"分类表合计({classify_bad_debt}), 差异={diff}"


                        ),


                        note_table_ids=[summary_table.id, classify_table.id],


                    ))





                # 账面余额也核对


                classify_balance = self._extract_balance_from_summary(


                    classify_table, ts_classify, "期末",


                )


                if (summary_balance is not None and classify_balance is not None


                        and not _amounts_equal(summary_balance, classify_balance)):


                    diff = round(summary_balance - classify_balance, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=acct_name,


                        location=f"附注-{acct_name}-跨表核对-总表vs分类表-账面余额",


                        description=(


                            f"总表账面余额{summary_balance}与分类表账面余额合计"


                            f"{classify_balance}不一致，差异{diff}"


                        ),


                        difference=diff,


                        statement_amount=summary_balance,


                        note_amount=classify_balance,


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=(


                            f"跨表核对: 总表账面余额({summary_balance}) vs "


                            f"分类表合计({classify_balance}), 差异={diff}"


                        ),


                        note_table_ids=[summary_table.id, classify_table.id],


                    ))





        return findings





    def _check_payroll_cross(


        self,


        acct_name: str,


        acct_notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """应付职工薪酬：汇总表 vs 短期薪酬/设定提存计划明细表。"""


        findings: List[ReportReviewFinding] = []





        # 识别汇总表和子表


        summary_table = None


        sub_tables: Dict[str, NoteTable] = {}  # "短期薪酬" → NoteTable





        for note in acct_notes:


            title = note.section_title or ""


            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""





            # 汇总表：表头含"期初余额"和"本期增加"和"本期减少"和"期末余额"，


            # 且行中含"短期薪酬"


            has_movement_headers = (


                "期初" in headers_str and "期末" in headers_str


                and ("增加" in headers_str or "减少" in headers_str)


            )


            if not has_movement_headers:


                continue





            # 检查行内容判断是汇总表还是子表


            row_labels = [str(r[0]).strip() for r in note.rows if r and r[0]]


            has_short_term = any("短期薪酬" in lbl for lbl in row_labels)


            has_salary_detail = any(


                kw in lbl for lbl in row_labels


                for kw in ["工资", "奖金", "福利费", "社会保险", "住房公积金"]


            )


            has_pension_detail = any(


                kw in lbl for lbl in row_labels


                for kw in ["基本养老", "失业保险", "企业年金"]


            )





            if has_short_term and not has_salary_detail:


                summary_table = note


            elif has_salary_detail:


                sub_tables["短期薪酬"] = note


            elif has_pension_detail:


                sub_tables["设定提存计划"] = note





        if not summary_table or not sub_tables:


            return findings





        ts_summary = table_structures.get(summary_table.id)


        if not ts_summary:


            return findings





        # 从汇总表中找到"短期薪酬"行


        for sub_name, sub_note in sub_tables.items():


            ts_sub = table_structures.get(sub_note.id)


            if not ts_sub:


                continue





            # 在汇总表中找到对应行


            target_row_idx = None


            for row_s in ts_summary.rows:


                if any(kw in row_s.label for kws in self.PAYROLL_SUB_KEYWORDS.get(sub_name, []) for kw in [kws]):


                    target_row_idx = row_s.row_index


                    break





            if target_row_idx is None:


                continue





            # 子表的合计行


            sub_total_idx = None


            for ti in ts_sub.total_row_indices:


                sub_total_idx = ti


                break


            if sub_total_idx is None:


                continue





            # 逐列比对（期初/本期增加/本期减少/期末 — 跳过标签列）


            for col_s in ts_summary.columns:


                if col_s.semantic in ("label", "other"):


                    continue





                summary_val = self._get_row_col_value(


                    summary_table, target_row_idx, col_s.col_index,


                )


                if summary_val is None:


                    continue





                # 在子表中找同语义列


                sub_col_idx = None


                for col_sub in ts_sub.columns:


                    if col_sub.semantic == col_s.semantic:


                        sub_col_idx = col_sub.col_index


                        break


                if sub_col_idx is None:


                    continue





                sub_val = self._get_row_col_value(sub_note, sub_total_idx, sub_col_idx)


                if sub_val is None:


                    continue





                if not _amounts_equal(summary_val, sub_val):


                    diff = round(summary_val - sub_val, 2)


                    col_label = str(summary_table.headers[col_s.col_index]) if col_s.col_index < len(summary_table.headers) else f"列{col_s.col_index + 1}"


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=acct_name,


                        location=f"附注-{acct_name}-跨表核对-汇总表'{sub_name}'vs{sub_name}明细表-{col_label}",


                        description=(


                            f"汇总表'{sub_name}'行{col_label}={summary_val}，"


                            f"{sub_name}明细表合计行={sub_val}，差异{diff}"


                        ),


                        difference=diff,


                        statement_amount=summary_val,


                        note_amount=sub_val,


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=(


                            f"跨表核对: 汇总表'{sub_name}'({summary_val}) vs "


                            f"明细表合计({sub_val}), 差异={diff}"


                        ),


                        note_table_ids=[summary_table.id, sub_note.id],


                    ))





        return findings





    def _check_asset_summary_cross(


        self,


        acct_name: str,


        acct_notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """固定资产/在建工程/无形资产：汇总表 vs 明细变动表。"""


        findings: List[ReportReviewFinding] = []





        summary_table = None


        detail_table = None


        impairment_movement_table = None  # 减值准备变动表（在建工程用）





        for note in acct_notes:


            title = note.section_title or ""


            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""





            # 减值准备变动表：标题含"减值准备"


            # 期初/期末可能在表头或行标签中，_extract_movement_end_balance 都能处理


            if "减值准备" in title:


                impairment_movement_table = note


                continue





            # 汇总表：行数少（通常 2-5 行），表头含"期末余额"和"上年年末余额"


            # 且行中含子项名称（如"固定资产"+"固定资产清理"，或"在建工程"+"工程物资"）


            row_count = len(note.rows)


            if (row_count <= 6


                    and ("期末" in headers_str or "上年" in headers_str)


                    and "账面原值" not in headers_str


                    and "累计折旧" not in headers_str


                    and "本期增加" not in headers_str):


                if summary_table is None:


                    summary_table = note


                continue





            # 明细变动表：表头含"账面原值"或"累计折旧"或"账面余额"+"减值准备"+"账面净值"


            if ("账面原值" in headers_str or "累计折旧" in headers_str):


                detail_table = note


                continue


            if ("账面余额" in headers_str and "减值准备" in headers_str


                    and ("账面净值" in headers_str or "账面价值" in headers_str)):


                if detail_table is None:


                    detail_table = note


                continue





        # ── 汇总表 vs 明细表 ──


        if summary_table and detail_table:


            ts_summary = table_structures.get(summary_table.id)


            ts_detail = table_structures.get(detail_table.id)


            if ts_summary and ts_detail:


                # 从明细表取期末账面价值/净值合计


                detail_closing = self._get_cell_value(detail_table, ts_detail.closing_balance_cell)


                detail_opening = self._get_cell_value(detail_table, ts_detail.opening_balance_cell)





                # 从汇总表找到对应行（第一个非合计数据行，通常就是科目本身）


                summary_closing = self._get_cell_value(summary_table, ts_summary.closing_balance_cell)


                summary_opening = self._get_cell_value(summary_table, ts_summary.opening_balance_cell)





                # 但汇总表的合计行包含了"固定资产清理"等，我们需要找到科目本身的行


                # 尝试在汇总表中找到与 acct_name 匹配的行


                target_row = None


                for row_s in ts_summary.rows:


                    if row_s.role == "data" and acct_name in row_s.label:


                        target_row = row_s.row_index


                        break





                if target_row is not None:


                    # 从汇总表的科目行取值


                    for col_s in ts_summary.columns:


                        if col_s.semantic == "closing_balance":


                            v = self._get_row_col_value(summary_table, target_row, col_s.col_index)


                            if v is not None:


                                summary_closing = v


                            break


                    for col_s in ts_summary.columns:


                        if col_s.semantic == "opening_balance":


                            v = self._get_row_col_value(summary_table, target_row, col_s.col_index)


                            if v is not None:


                                summary_opening = v


                            break





                if (summary_closing is not None and detail_closing is not None


                        and not _amounts_equal(summary_closing, detail_closing)):


                    diff = round(summary_closing - detail_closing, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=acct_name,


                        location=f"附注-{acct_name}-跨表核对-汇总表vs明细表-期末",


                        description=(


                            f"汇总表'{acct_name}'期末{summary_closing}与"


                            f"明细表期末账面价值合计{detail_closing}不一致，差异{diff}"


                        ),


                        difference=diff,


                        statement_amount=summary_closing,


                        note_amount=detail_closing,


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=(


                            f"跨表核对: 汇总表({summary_closing}) vs "


                            f"明细表({detail_closing}), 差异={diff}"


                        ),


                        note_table_ids=[summary_table.id, detail_table.id],


                    ))





                if (summary_opening is not None and detail_opening is not None


                        and not _amounts_equal(summary_opening, detail_opening)):


                    diff = round(summary_opening - detail_opening, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=acct_name,


                        location=f"附注-{acct_name}-跨表核对-汇总表vs明细表-期初",


                        description=(


                            f"汇总表'{acct_name}'期初{summary_opening}与"


                            f"明细表期初账面价值合计{detail_opening}不一致，差异{diff}"


                        ),


                        difference=diff,


                        statement_amount=summary_opening,


                        note_amount=detail_opening,


                        risk_level=RiskLevel.MEDIUM,


                        reasoning=(


                            f"跨表核对: 汇总表({summary_opening}) vs "


                            f"明细表({detail_opening}), 差异={diff}"


                        ),


                        note_table_ids=[summary_table.id, detail_table.id],


                    ))





        # ── 在建工程：明细表减值准备 vs 减值准备变动表 ──


        if detail_table and impairment_movement_table and "在建工程" in acct_name:


            ts_detail = table_structures.get(detail_table.id)


            if ts_detail:


                # 从明细表合计行找"减值准备"列


                impairment_col = None


                for col in ts_detail.columns:


                    header_str = str(detail_table.headers[col.col_index]).strip() if col.col_index < len(detail_table.headers) else ""


                    if "减值准备" in header_str:


                        impairment_col = col.col_index


                        break





                if impairment_col is not None and ts_detail.total_row_indices:


                    detail_impairment = self._get_row_col_value(


                        detail_table, ts_detail.total_row_indices[-1], impairment_col,


                    )


                    movement_end = self._extract_movement_end_balance(


                        impairment_movement_table, table_structures,


                    )


                    if (detail_impairment is not None and movement_end is not None


                            and not _amounts_equal(detail_impairment, movement_end)):


                        diff = round(detail_impairment - movement_end, 2)


                        findings.append(self._make_finding(


                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                            account_name=acct_name,


                            location=f"附注-{acct_name}-跨表核对-明细表减值准备vs减值变动表",


                            description=(


                                f"明细表减值准备合计{detail_impairment}与"


                                f"减值准备变动表期末余额{movement_end}不一致，差异{diff}"


                            ),


                            difference=diff,


                            statement_amount=detail_impairment,


                            note_amount=movement_end,


                            risk_level=RiskLevel.MEDIUM,


                            reasoning=(


                                f"跨表核对: 明细表减值准备({detail_impairment}) vs "


                                f"变动表期末({movement_end}), 差异={diff}"


                            ),


                            note_table_ids=[detail_table.id, impairment_movement_table.id],


                        ))





        return findings





    def _check_inventory_cross(


        self,


        acct_name: str,


        acct_notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """存货：分类表跌价准备 vs 跌价准备变动表期末余额。"""


        findings: List[ReportReviewFinding] = []





        classification_table = None  # 分类表（账面余额 | 跌价准备 | 账面价值）


        provision_movement_table = None  # 跌价准备变动表





        for note in acct_notes:


            title = note.section_title or ""


            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""





            # 分类表优先判断（特征更具体）：表头含"账面余额"和"跌价准备"（或"减值准备"）和"账面价值"


            if ("账面余额" in headers_str


                    and ("跌价准备" in headers_str or "减值准备" in headers_str)


                    and "账面价值" in headers_str):


                if classification_table is None:


                    classification_table = note


                continue





            # 跌价准备变动表：标题含"跌价准备"或"减值准备"


            # 期初/期末可能在表头或行标签中，_extract_movement_end_balance 都能处理


            if ("跌价准备" in title or "减值准备" in title):


                if provision_movement_table is None:


                    provision_movement_table = note


                continue





        if not classification_table or not provision_movement_table:


            return findings





        ts_class = table_structures.get(classification_table.id)


        if not ts_class or not ts_class.total_row_indices:


            return findings





        # 从分类表合计行提取跌价准备金额


        total_row = ts_class.total_row_indices[-1]


        class_provision = None


        for ci, header in enumerate(classification_table.headers):


            header_str = str(header).strip() if header else ""


            if "跌价准备" in header_str or "减值准备" in header_str:


                val = self._get_row_col_value(classification_table, total_row, ci)


                if val is not None:


                    class_provision = val


                    break





        # 从变动表提取期末余额


        movement_end = self._extract_movement_end_balance(


            provision_movement_table, table_structures,


        )





        if (class_provision is not None and movement_end is not None


                and not _amounts_equal(class_provision, movement_end)):


            diff = round(class_provision - movement_end, 2)


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name=acct_name,


                location=f"附注-{acct_name}-跨表核对-分类表vs跌价准备变动表",


                description=(


                    f"分类表跌价准备合计{class_provision}与"


                    f"跌价准备变动表期末余额{movement_end}不一致，差异{diff}"


                ),


                difference=diff,


                statement_amount=class_provision,


                note_amount=movement_end,


                risk_level=RiskLevel.MEDIUM,


                reasoning=(


                    f"跨表核对: 分类表跌价准备({class_provision}) vs "


                    f"变动表期末({movement_end}), 差异={diff}"


                ),


                note_table_ids=[classification_table.id, provision_movement_table.id],


            ))





        return findings





    def _check_goodwill_cross(


        self,


        acct_name: str,


        acct_notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """商誉：原值表期末 - 减值准备表期末 = 账面价值。"""


        findings: List[ReportReviewFinding] = []





        cost_table = None       # 商誉账面原值表


        impairment_table = None  # 商誉减值准备表





        for note in acct_notes:


            title = note.section_title or ""


            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""





            # 减值准备表：标题含"减值准备"


            if "减值准备" in title:


                if "期初" in headers_str or "本期" in headers_str or "期末" in headers_str:


                    impairment_table = note


                    continue





            # 原值表：标题含"账面原值"或"商誉"（非减值准备），表头含"期初"/"期末"


            if "减值" not in title:


                if "期初" in headers_str or "本期" in headers_str or "期末" in headers_str:


                    if cost_table is None:


                        cost_table = note


                    continue





        if not cost_table or not impairment_table:


            return findings





        # 从原值表提取期末余额


        cost_end = self._extract_movement_end_balance(cost_table, table_structures)


        # 从减值准备表提取期末余额


        impairment_end = self._extract_movement_end_balance(impairment_table, table_structures)





        # 核对：减值准备 ≤ 原值（两表各自的内部一致性已由 check_note_table_integrity 覆盖）
        # 更实用的核对：两表的被投资单位名称应一致


        # 提取两表合计行的期末余额，确保减值准备 ≤ 原值


        if cost_end is not None and impairment_end is not None:


            if impairment_end > cost_end + TOLERANCE:


                diff = round(impairment_end - cost_end, 2)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=acct_name,


                    location=f"附注-{acct_name}-跨表核对-原值表vs减值准备表",


                    description=(


                        f"商誉减值准备期末{impairment_end}超过"


                        f"商誉原值期末{cost_end}，差异{diff}"


                    ),


                    difference=diff,


                    statement_amount=cost_end,


                    note_amount=impairment_end,


                    risk_level=RiskLevel.HIGH,


                    reasoning=(


                        f"跨表核对: 减值准备({impairment_end}) > "


                        f"原值({cost_end}), 差异={diff}"


                    ),


                    note_table_ids=[cost_table.id, impairment_table.id],


                ))





        # 核对两表的逐行被投资单位是否金额匹配


        # 原值表每个被投资单位的期末余额 >= 减值准备表对应单位的期末余额


        ts_cost = table_structures.get(cost_table.id)


        ts_impairment = table_structures.get(impairment_table.id)


        if ts_cost and ts_impairment:


            # 找到两表中期末余额列


            cost_end_col = None


            for col in ts_cost.columns:


                if col.semantic == "closing_balance":


                    cost_end_col = col.col_index


                    break


            # 回退：取最后一列


            if cost_end_col is None and cost_table.headers:


                for ci in range(len(cost_table.headers) - 1, 0, -1):


                    h = str(cost_table.headers[ci]).strip()


                    if "期末" in h:


                        cost_end_col = ci


                        break





            impairment_end_col = None


            for col in ts_impairment.columns:


                if col.semantic == "closing_balance":


                    impairment_end_col = col.col_index


                    break


            if impairment_end_col is None and impairment_table.headers:


                for ci in range(len(impairment_table.headers) - 1, 0, -1):


                    h = str(impairment_table.headers[ci]).strip()


                    if "期末" in h:


                        impairment_end_col = ci


                        break





            if cost_end_col is not None and impairment_end_col is not None:


                # 构建减值准备表的 label → 期末值 映射


                impairment_map: Dict[str, float] = {}


                for row_s in ts_impairment.rows:


                    if row_s.role in ("data",):


                        val = self._get_row_col_value(


                            impairment_table, row_s.row_index, impairment_end_col,


                        )


                        if val is not None:


                            impairment_map[row_s.label.strip()] = val





                # 逐行核对原值表


                for row_s in ts_cost.rows:


                    if row_s.role not in ("data",):


                        continue


                    label = row_s.label.strip()


                    cost_val = self._get_row_col_value(


                        cost_table, row_s.row_index, cost_end_col,


                    )


                    if cost_val is None:


                        continue


                    imp_val = impairment_map.get(label)


                    if imp_val is not None and imp_val > cost_val + TOLERANCE:


                        diff = round(imp_val - cost_val, 2)


                        findings.append(self._make_finding(


                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                            account_name=acct_name,


                            location=f"附注-{acct_name}-跨表核对-'{label}'-减值超原值",


                            description=(


                                f"'{label}'减值准备{imp_val}超过原值{cost_val}，差异{diff}"


                            ),


                            difference=diff,


                            statement_amount=cost_val,


                            note_amount=imp_val,


                            risk_level=RiskLevel.HIGH,


                            reasoning=(


                                f"跨表核对: '{label}'减值({imp_val}) > "


                                f"原值({cost_val}), 差异={diff}"


                            ),


                            note_table_ids=[cost_table.id, impairment_table.id],


                        ))





        return findings





    def _check_debt_investment_cross(


        self,


        acct_name: str,


        acct_notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """债权投资/其他债权投资：总表减值准备 vs 减值准备变动表期末余额。"""


        findings: List[ReportReviewFinding] = []





        summary_table = None       # 总表（账面余额 | 减值准备 | 账面价值）


        movement_table = None      # 减值准备变动表





        for note in acct_notes:


            title = note.section_title or ""


            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""





            # 总表优先判断（特征更具体）：表头含"账面余额"和"减值准备"和"账面价值"


            if ("账面余额" in headers_str


                    and "减值准备" in headers_str


                    and "账面价值" in headers_str):


                if summary_table is None:


                    summary_table = note


                continue





            # 减值准备变动表：标题含"减值准备"


            # 期初/期末可能在表头或行标签中，_extract_movement_end_balance 都能处理


            if "减值准备" in title:


                if movement_table is None:


                    movement_table = note


                continue





        if not summary_table or not movement_table:


            return findings





        ts_summary = table_structures.get(summary_table.id)


        if not ts_summary or not ts_summary.total_row_indices:


            return findings





        # 从总表合计行提取减值准备金额


        total_row = ts_summary.total_row_indices[-1]


        summary_provision = None


        for ci, header in enumerate(summary_table.headers):


            header_str = str(header).strip() if header else ""


            if "减值准备" in header_str:


                val = self._get_row_col_value(summary_table, total_row, ci)


                if val is not None:


                    summary_provision = val


                    break





        # 从变动表提取期末余额


        movement_end = self._extract_movement_end_balance(


            movement_table, table_structures,


        )





        if (summary_provision is not None and movement_end is not None


                and not _amounts_equal(summary_provision, movement_end)):


            diff = round(summary_provision - movement_end, 2)


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name=acct_name,


                location=f"附注-{acct_name}-跨表核对-总表vs减值准备变动表",


                description=(


                    f"总表减值准备合计{summary_provision}与"


                    f"减值准备变动表期末余额{movement_end}不一致，差异{diff}"


                ),


                difference=diff,


                statement_amount=summary_provision,


                note_amount=movement_end,


                risk_level=RiskLevel.MEDIUM,


                reasoning=(


                    f"跨表核对: 总表减值准备({summary_provision}) vs "


                    f"变动表期末({movement_end}), 差异={diff}"


                ),


                note_table_ids=[summary_table.id, movement_table.id],


            ))





        return findings





    def _check_contract_asset_cross(


        self,


        acct_name: str,


        acct_notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """合同资产：总表减值准备 vs 减值准备变动表期末余额。"""


        findings: List[ReportReviewFinding] = []





        summary_table = None       # 总表（账面余额 | 减值准备 | 账面价值）


        movement_table = None      # 减值准备变动表





        for note in acct_notes:


            title = note.section_title or ""


            headers_str = " ".join(str(h) for h in note.headers) if note.headers else ""





            # 总表优先判断：表头含"账面余额"和"减值准备"和"账面价值"


            if ("账面余额" in headers_str


                    and "减值准备" in headers_str


                    and "账面价值" in headers_str):


                if summary_table is None:


                    summary_table = note


                continue





            # 减值准备变动表：标题含"减值准备"


            if "减值准备" in title:


                if movement_table is None:


                    movement_table = note


                continue





        if not summary_table or not movement_table:


            return findings





        ts_summary = table_structures.get(summary_table.id)


        if not ts_summary or not ts_summary.total_row_indices:


            return findings





        # 从总表合计行提取减值准备金额


        total_row = ts_summary.total_row_indices[-1]


        summary_provision = None


        for ci, header in enumerate(summary_table.headers):


            header_str = str(header).strip() if header else ""


            if "减值准备" in header_str:


                val = self._get_row_col_value(summary_table, total_row, ci)


                if val is not None:


                    summary_provision = val


                    break





        # 从变动表提取期末余额


        movement_end = self._extract_movement_end_balance(


            movement_table, table_structures,


        )





        if (summary_provision is not None and movement_end is not None


                and not _amounts_equal(summary_provision, movement_end)):


            diff = round(summary_provision - movement_end, 2)


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name=acct_name,


                location=f"附注-{acct_name}-跨表核对-总表vs减值准备变动表",


                description=(


                    f"总表减值准备合计{summary_provision}与"


                    f"减值准备变动表期末余额{movement_end}不一致，差异{diff}"


                ),


                difference=diff,


                statement_amount=summary_provision,


                note_amount=movement_end,


                risk_level=RiskLevel.MEDIUM,


                reasoning=(


                    f"跨表核对: 总表减值准备({summary_provision}) vs "


                    f"变动表期末({movement_end}), 差异={diff}"


                ),


                note_table_ids=[summary_table.id, movement_table.id],


            ))





        return findings





    def _check_revenue_cost_cross(


        self,


        acct_name: str,


        acct_notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """营业收入/营业成本：汇总表合计 vs 按行业/地区/商品转让时间划分明细表合计。





        国企和上市报表中，营业收入、营业成本科目下通常有多张合并表格：


        - 汇总表（主营业务/其他业务/合计）


        - 按行业（或产品类型）划分


        - 按地区划分


        - 按商品转让时间划分





        核对：汇总表的收入/成本合计 应等于 各明细表的收入/成本合计。


        """


        findings: List[ReportReviewFinding] = []





        # 分离汇总表和明细表


        summary_tables: List[NoteTable] = []


        detail_tables: List[NoteTable] = []





        for note in acct_notes:


            if not self._is_revenue_cost_combined_table(note):


                continue


            if self._is_revenue_cost_detail_table(note):


                detail_tables.append(note)


            else:


                summary_tables.append(note)





        if not summary_tables or not detail_tables:


            return findings





        summary = summary_tables[0]





        # 从汇总表提取收入和成本的本期合计


        summary_rev_closing, _ = self._extract_revenue_cost_from_combined_table(


            summary, "营业收入",


        )


        summary_cost_closing, _ = self._extract_revenue_cost_from_combined_table(


            summary, "营业成本",


        )





        # 逐个明细表核对


        for detail in detail_tables:


            detail_title = detail.section_title or detail.account_name or ""





            detail_rev_closing, _ = self._extract_revenue_cost_from_combined_table(


                detail, "营业收入",


            )


            detail_cost_closing, _ = self._extract_revenue_cost_from_combined_table(


                detail, "营业成本",


            )





            # 核对收入


            if (summary_rev_closing is not None and detail_rev_closing is not None


                    and not _amounts_equal(summary_rev_closing, detail_rev_closing)):


                diff = round(summary_rev_closing - detail_rev_closing, 2)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=acct_name,


                    location=f"附注-{acct_name}-跨表核对-汇总表vs{detail_title}-收入",


                    description=(


                        f"汇总表营业收入合计{summary_rev_closing}与"


                        f"'{detail_title}'收入合计{detail_rev_closing}不一致，差异{diff}"


                    ),


                    difference=diff,


                    statement_amount=summary_rev_closing,


                    note_amount=detail_rev_closing,


                    risk_level=RiskLevel.MEDIUM,


                    reasoning=(


                        f"跨表核对: 汇总表收入({summary_rev_closing}) vs "


                        f"明细表收入({detail_rev_closing}), 差异={diff}"


                    ),


                    note_table_ids=[summary.id, detail.id],


                ))





            # 核对成本


            if (summary_cost_closing is not None and detail_cost_closing is not None


                    and not _amounts_equal(summary_cost_closing, detail_cost_closing)):


                diff = round(summary_cost_closing - detail_cost_closing, 2)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=acct_name,


                    location=f"附注-{acct_name}-跨表核对-汇总表vs{detail_title}-成本",


                    description=(


                        f"汇总表营业成本合计{summary_cost_closing}与"


                        f"'{detail_title}'成本合计{detail_cost_closing}不一致，差异{diff}"


                    ),


                    difference=diff,


                    statement_amount=summary_cost_closing,


                    note_amount=detail_cost_closing,


                    risk_level=RiskLevel.MEDIUM,


                    reasoning=(


                        f"跨表核对: 汇总表成本({summary_cost_closing}) vs "


                        f"明细表成本({detail_cost_closing}), 差异={diff}"


                    ),


                    note_table_ids=[summary.id, detail.id],


                ))





        return findings





    # ─── 权益法投资损益跨科目交叉核对 ───





    # 长期股权投资明细表中"权益法下确认的投资损益"列的关键词


    EQUITY_METHOD_INCOME_COL_KEYWORDS = [


        "权益法下确认的投资损益", "权益法下确认的投资收益",


        "权益法确认的投资损益", "投资损益",


    ]





    # 投资收益附注表中"权益法核算的长期股权投资收益"行的关键词


    EQUITY_METHOD_INCOME_ROW_KEYWORDS = [


        "权益法核算的长期股权投资收益",


        "权益法核算的长期股权投资",


    ]





    # 利润表中"对联营企业和合营企业的投资收益"行的关键词


    INCOME_STMT_EQUITY_KEYWORDS = [


        "对联营企业和合营企业的投资收益",


        "联营企业和合营企业的投资收益",


        "对联营、合营企业的投资收益",


    ]





    def check_equity_method_income_consistency(


        self,


        items: List[StatementItem],


        notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """权益法投资损益跨科目交叉核对。





        校验三方一致：


        A. 长期股权投资明细表 → "权益法下确认的投资损益"列的合计行


        B. 投资收益附注表 → "权益法核算的长期股权投资收益"行的本期发生额


        C. 利润表 → "其中：对联营企业和合营企业的投资收益"行的本期金额





        A = B = C


        """


        findings: List[ReportReviewFinding] = []





        # ── 1. 从长期股权投资明细表提取"权益法下确认的投资损益"合计 ──


        equity_detail_amount: Optional[float] = None


        equity_detail_note: Optional[NoteTable] = None





        # 期初/期末余额列排除关键词：含这些词的列是余额列，不是当期变动列


        _balance_col_exclude = ["期初", "期末", "年初", "年末", "余额", "投资成本"]





        for note in notes:


            if "长期股权投资" not in (note.account_name or ""):


                continue


            # 跳过母公司附注表格（母公司口径的投资损益不应与合并利润表比对）


            if self._is_parent_company_note(note):


                continue


            # 宽表：列数 ≥ 8 且含"投资损益"列


            if not note.headers or len(note.headers) < 8:


                continue


            headers_text = [str(h) for h in note.headers]


            income_col_idx = None


            for ci, h in enumerate(headers_text):


                # 跳过期初/期末余额列，避免误匹配


                if any(bk in h for bk in _balance_col_exclude):


                    continue


                for kw in self.EQUITY_METHOD_INCOME_COL_KEYWORDS:


                    if kw in h:


                        income_col_idx = ci


                        break


                if income_col_idx is not None:


                    break





            if income_col_idx is None:


                continue





            # 找合计行


            for ri, row in enumerate(note.rows):


                if not row:


                    continue


                label = str(row[0] or "").strip()


                if any(kw in label for kw in ["合计", "合 计", "合\u3000计", "总计"]):


                    val = self._get_row_col_value(note, ri, income_col_idx)


                    if val is not None:


                        equity_detail_amount = val


                        equity_detail_note = note


                        break


            if equity_detail_amount is not None:


                break





        # ── 2. 从投资收益附注表提取"权益法核算的长期股权投资收益" ──


        invest_income_amount: Optional[float] = None


        invest_income_note: Optional[NoteTable] = None





        for note in notes:


            combined = (note.account_name or "") + (note.section_title or "")


            if "投资收益" not in combined:


                continue


            # 动态定位"本期"列（通常是"本期发生额"/"本期金额"/"本年金额"等）


            current_col_idx = 1  # 默认第2列


            if note.headers:


                for ci, h in enumerate(note.headers):


                    h_str = str(h or "")


                    if any(kw in h_str for kw in ["本期", "本年"]) and "上期" not in h_str and "上年" not in h_str:


                        current_col_idx = ci


                        break


            for ri, row in enumerate(note.rows):


                if not row:


                    continue


                label = str(row[0] or "").strip()


                for kw in self.EQUITY_METHOD_INCOME_ROW_KEYWORDS:


                    if kw in label:


                        val = self._get_row_col_value(note, ri, current_col_idx)


                        if val is not None:


                            invest_income_amount = val


                            invest_income_note = note


                        break


                if invest_income_amount is not None:


                    break


            if invest_income_amount is not None:


                break





        # ── 3. 从利润表提取"对联营企业和合营企业的投资收益" ──


        stmt_equity_income: Optional[float] = None


        stmt_equity_item: Optional[StatementItem] = None





        for item in items:


            if item.statement_type != StatementType.INCOME_STATEMENT:


                continue


            for kw in self.INCOME_STMT_EQUITY_KEYWORDS:


                if kw in item.account_name:


                    stmt_equity_income = item.closing_balance


                    stmt_equity_item = item


                    break


            if stmt_equity_income is not None:


                break





        # ── 4. 交叉核对 ──


        # 收集所有可用的值


        values = {}


        note_ids = []


        if equity_detail_amount is not None:


            values["长期股权投资明细表-权益法投资损益合计"] = equity_detail_amount


            if equity_detail_note:


                note_ids.append(equity_detail_note.id)


        if invest_income_amount is not None:


            values["投资收益附注-权益法核算的长期股权投资收益"] = invest_income_amount


            if invest_income_note:


                note_ids.append(invest_income_note.id)


        if stmt_equity_income is not None:


            values["利润表-对联营企业和合营企业的投资收益"] = stmt_equity_income





        # 至少需要两个值才能比对


        if len(values) < 2:


            return findings





        # 两两比对


        keys = list(values.keys())


        for i in range(len(keys)):


            for j in range(i + 1, len(keys)):


                a_name, a_val = keys[i], values[keys[i]]


                b_name, b_val = keys[j], values[keys[j]]


                if not _amounts_equal(a_val, b_val):


                    diff = round(a_val - b_val, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name="长期股权投资/投资收益",


                        location=f"跨科目核对-权益法投资损益",


                        description=(


                            f"权益法投资损益跨科目不一致：{a_name}={a_val:,.2f}，"


                            f"{b_name}={b_val:,.2f}，差异{diff:,.2f}"


                        ),


                        difference=diff,


                        statement_amount=a_val,


                        note_amount=b_val,


                        risk_level=self._assess_risk(abs(diff), max(abs(a_val), abs(b_val)) if max(abs(a_val), abs(b_val)) > 0 else None),


                        reasoning=(


                            f"三方核对: {' / '.join(f'{k}={v:,.2f}' for k, v in values.items())}"


                        ),


                        note_table_ids=note_ids,


                    ))





        return findings





    # ─── 跨表核对辅助方法 ───





    def _extract_bad_debt_from_summary(


        self, note: NoteTable, ts: TableStructure, period: str,


    ) -> Optional[float]:


        """从总表/分类表的合计行提取坏账准备金额。





        period: "期末" 或 "期初"


        """


        if not ts.total_row_indices:


            return None





        total_row = ts.total_row_indices[-1]





        # 找"坏账准备"或"减值准备"列


        for ci, header in enumerate(note.headers):


            header_str = str(header).strip() if header else ""


            if "坏账准备" in header_str or "减值准备" in header_str:


                # 区分期末/期初：如果表格有"期末余额"和"上年年末余额"两组列，


                # 坏账准备列可能出现两次。简单策略：期末取第一个，期初取第二个


                if period == "期末":


                    val = self._get_row_col_value(note, total_row, ci)


                    if val is not None:


                        return val


                # 期初暂不处理（续表结构复杂，后续可扩展）





        return None





    def _extract_balance_from_summary(


        self, note: NoteTable, ts: TableStructure, period: str,


    ) -> Optional[float]:


        """从总表/分类表的合计行提取账面余额。"""


        if not ts.total_row_indices:


            return None





        total_row = ts.total_row_indices[-1]





        for ci, header in enumerate(note.headers):


            header_str = str(header).strip() if header else ""


            if "账面余额" in header_str and "坏账" not in header_str:


                if period == "期末":


                    val = self._get_row_col_value(note, total_row, ci)


                    if val is not None:


                        return val





        return None





    def _extract_movement_end_balance(


        self, note: NoteTable, table_structures: Dict[str, TableStructure],


    ) -> Optional[float]:


        """从坏账准备/减值准备变动表中提取期末余额。





        变动表结构：期初余额 / 本期计提 / 本期收回或转回 / 本期核销 / 期末余额


        期末余额通常在最后一个数据行。


        """


        # 尝试通过行标签找"期末余额"行


        for ri, row in enumerate(note.rows):


            label = str(row[0]).strip() if row and row[0] else ""


            if "期末" in label and "余额" in label:


                # 取第二列（金额列）


                for ci in range(1, len(row)):


                    val = _safe_float(row[ci])


                    if val is not None:


                        return val





        # 回退：取最后一行的金额


        if note.rows:


            last_row = note.rows[-1]


            for ci in range(1, len(last_row)):


                val = _safe_float(last_row[ci])


                if val is not None:


                    return val





        return None





    # ─── 现金流量表补充资料 vs 利润表/现金流量表 跨报表校验 ───





    # 补充资料行标签 → (对应报表科目名称, 符号关系)


    # sign=1 表示同号（补充资料值 == 报表值），sign=-1 表示反号（补充资料值 == -报表值）


    CASHFLOW_SUPPLEMENT_MAPPINGS = [


        {"label_keywords": ["净利润"], "statement_name": "净利润",


         "statement_type": StatementType.INCOME_STATEMENT, "sign": 1,


         "exclude_keywords": ["调节"]},


        {"label_keywords": ["资产减值损失"], "statement_name": "资产减值损失",


         "statement_type": StatementType.INCOME_STATEMENT, "sign": -1,


         "exclude_keywords": []},


        {"label_keywords": ["信用减值损失"], "statement_name": "信用减值损失",


         "statement_type": StatementType.INCOME_STATEMENT, "sign": -1,


         "exclude_keywords": []},


        {"label_keywords": ["公允价值变动损失", "公允价值变动"],


         "statement_name": "公允价值变动收益",


         "statement_type": StatementType.INCOME_STATEMENT, "sign": -1,


         "exclude_keywords": []},


        {"label_keywords": ["投资损失"], "statement_name": "投资收益",


         "statement_type": StatementType.INCOME_STATEMENT, "sign": -1,


         "exclude_keywords": []},


        {"label_keywords": ["财务费用"], "statement_name": "财务费用",


         "statement_type": StatementType.INCOME_STATEMENT, "sign": 1,


         "exclude_keywords": [],


         "sub_item": "利息支出"},


    ]





    # 补充资料中"经营活动产生的现金流量净额" vs 现金流量表主表


    CASHFLOW_SUPPLEMENT_TOTAL_KEYWORDS = ["经营活动产生的现金流量净额"]





    # 识别现金流量表补充资料的附注表格


    CASHFLOW_SUPPLEMENT_NOTE_KEYWORDS = [


        "现金流量表补充资料",


        "将净利润调节为经营活动现金流量",


        "补充资料",


    ]





    def check_cashflow_supplement_consistency(


        self,


        items: List[StatementItem],


        notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """现金流量表补充资料中的利润表/现金流量表数值交叉核对。





        校验规则：


        1. 净利润 == 利润表.净利润


        2. 资产减值损失 == 利润表.资产减值损失


        3. 信用减值损失 == 利润表.信用减值损失


        4. 公允价值变动损失 == -利润表.公允价值变动收益


        5. 投资损失 == -利润表.投资收益


        6. 财务费用 == 利润表.财务费用（仅利息支出部分，需从附注明细取值）


        7. 经营活动产生的现金流量净额 == 现金流量表主表.经营活动产生的现金流量净额


        """


        findings: List[ReportReviewFinding] = []





        # 1. 找到补充资料附注表格


        supplement_notes: List[NoteTable] = []


        for n in notes:


            combined = (n.section_title or "") + (n.account_name or "")


            if any(kw in combined for kw in self.CASHFLOW_SUPPLEMENT_NOTE_KEYWORDS):


                supplement_notes.append(n)





        if not supplement_notes:


            return findings





        # 2. 构建报表科目索引（按 statement_type + account_name）


        income_items: Dict[str, StatementItem] = {}


        cashflow_items: Dict[str, StatementItem] = {}


        for item in items:


            if item.statement_type == StatementType.INCOME_STATEMENT:


                income_items[item.account_name] = item


            elif item.statement_type == StatementType.CASH_FLOW:


                cashflow_items[item.account_name] = item





        # 3. 构建财务费用明细索引（从附注中查找财务费用的利息支出子项）


        interest_expense: Optional[float] = None


        for n in notes:


            if "财务费用" in (n.account_name or "") or "财务费用" in (n.section_title or ""):


                # 在补充资料表格本身之外的财务费用明细表中查找利息支出


                if n in supplement_notes:


                    continue


                for row in n.rows:


                    if not row:


                        continue


                    label = str(row[0]).strip() if row else ""


                    if "利息支出" in label:


                        # 取本期发生额（通常第2列）


                        for ci in range(1, len(row)):


                            val = _safe_float(row[ci])


                            if val is not None:


                                interest_expense = val


                                break


                        break





        # 4. 遍历补充资料表格，逐行匹配校验
        # 预检测：通过表头关键词定位"本期金额"列，避免盲取第一个数值列
        _current_period_kw = ["本期", "本年", "当期"]
        _prior_period_kw = ["上期", "上年", "去年"]

        def _detect_current_period_col(note_headers):
            if not note_headers:
                return None
            for ci, h in enumerate(note_headers):
                if ci == 0:
                    continue
                hs = str(h or "").replace(" ", "").replace("\u3000", "")
                if any(kw in hs for kw in _current_period_kw):
                    if not any(kw in hs for kw in _prior_period_kw):
                        return ci
            return None

        for supp_note in supplement_notes:


            ts = table_structures.get(supp_note.id)





            for row_idx, row in enumerate(supp_note.rows):


                if not row:


                    continue


                row_label = str(row[0]).strip() if row else ""


                if not row_label:


                    continue





                # 取本期发生额：优先通过表头定位本期列
                _period_col = _detect_current_period_col(supp_note.headers)
                supp_value: Optional[float] = None
                if _period_col is not None and _period_col < len(row):
                    supp_value = _safe_float(row[_period_col])
                if supp_value is None:
                    # 回退：取第一个非空数值列
                    for ci in range(1, len(row)):
                        val = _safe_float(row[ci])
                        if val is not None:
                            supp_value = val
                            break
                if supp_value is None:


                    continue





                # ── 4a. 利润表项目校验 ──


                for mapping in self.CASHFLOW_SUPPLEMENT_MAPPINGS:


                    # 检查行标签是否匹配


                    label_match = any(kw in row_label for kw in mapping["label_keywords"])


                    if not label_match:


                        continue


                    # 排除关键词（如"将净利润调节为..."不是"净利润"行）


                    if mapping.get("exclude_keywords"):


                        if any(ekw in row_label for ekw in mapping["exclude_keywords"]):


                            continue





                    # 特殊处理：财务费用仅比对利息支出


                    if mapping.get("sub_item") == "利息支出":


                        if interest_expense is not None:


                            expected = interest_expense * mapping["sign"]


                            if not _amounts_equal(supp_value, expected):


                                diff = round(supp_value - expected, 2)


                                findings.append(self._make_finding(


                                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                                    account_name="现金流量表补充资料",


                                    location=f"附注-现金流量表补充资料-第{row_idx + 1}行'{row_label}'",


                                    description=(


                                        f"补充资料'{row_label}'金额 {supp_value:,.2f} "


                                        f"与附注财务费用明细中利息支出 {interest_expense:,.2f} 不一致，"


                                        f"差异 {diff:,.2f}"


                                    ),


                                    statement_amount=interest_expense,


                                    note_amount=supp_value,


                                    difference=diff,


                                    risk_level=self._assess_risk(abs(diff), interest_expense),


                                    reasoning=(


                                        f"校验公式: 补充资料.财务费用({supp_value:,.2f}) "


                                        f"应等于 附注.财务费用.利息支出({interest_expense:,.2f})"


                                    ),


                                    note_table_ids=[supp_note.id],


                                ))


                        # 财务费用已处理，跳过后续通用逻辑


                        break





                    # 通用逻辑：从利润表找对应科目


                    stmt_item = income_items.get(mapping["statement_name"])


                    if not stmt_item:


                        # 尝试模糊匹配


                        for name, item in income_items.items():


                            if mapping["statement_name"] in name or name in mapping["statement_name"]:


                                stmt_item = item


                                break





                    if stmt_item and stmt_item.closing_balance is not None:


                        expected = stmt_item.closing_balance * mapping["sign"]


                        if not _amounts_equal(supp_value, expected):


                            diff = round(supp_value - expected, 2)


                            stmt_display = f"{mapping['statement_name']}({stmt_item.closing_balance:,.2f})"


                            sign_desc = "" if mapping["sign"] == 1 else "（取反）"


                            findings.append(self._make_finding(


                                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                                account_name="现金流量表补充资料",


                                location=f"附注-现金流量表补充资料-第{row_idx + 1}行'{row_label}'",


                                description=(


                                    f"补充资料'{row_label}'金额 {supp_value:,.2f} "


                                    f"与利润表{stmt_display}{sign_desc}不一致，"


                                    f"差异 {diff:,.2f}"


                                ),


                                statement_amount=stmt_item.closing_balance,


                                note_amount=supp_value,


                                difference=diff,


                                risk_level=self._assess_risk(abs(diff), abs(stmt_item.closing_balance)),


                                reasoning=(


                                    f"校验公式: 补充资料.{row_label}({supp_value:,.2f}) "


                                    f"应等于 {'- ' if mapping['sign'] == -1 else ''}"


                                    f"利润表.{mapping['statement_name']}({stmt_item.closing_balance:,.2f})"


                                ),


                                note_table_ids=[supp_note.id],


                            ))


                    break  # 一行只匹配一个 mapping





                # ── 4b. 经营活动现金流量净额 vs 现金流量表主表 ──


                if any(kw in row_label for kw in self.CASHFLOW_SUPPLEMENT_TOTAL_KEYWORDS):


                    cf_item = cashflow_items.get("经营活动产生的现金流量净额")


                    if not cf_item:


                        for name, item in cashflow_items.items():


                            if "经营活动" in name and "净额" in name:


                                cf_item = item


                                break





                    if cf_item and cf_item.closing_balance is not None:


                        if not _amounts_equal(supp_value, cf_item.closing_balance):


                            diff = round(supp_value - cf_item.closing_balance, 2)


                            findings.append(self._make_finding(


                                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                                account_name="现金流量表补充资料",


                                location=f"附注-现金流量表补充资料-第{row_idx + 1}行'{row_label}'",


                                description=(


                                    f"补充资料'{row_label}'金额 {supp_value:,.2f} "


                                    f"与现金流量表主表({cf_item.closing_balance:,.2f})不一致，"


                                    f"差异 {diff:,.2f}"


                                ),


                                statement_amount=cf_item.closing_balance,


                                note_amount=supp_value,


                                difference=diff,


                                risk_level=self._assess_risk(abs(diff), abs(cf_item.closing_balance)),


                                reasoning=(


                                    f"校验公式: 补充资料.经营活动现金流量净额({supp_value:,.2f}) "


                                    f"应等于 现金流量表.经营活动产生的现金流量净额({cf_item.closing_balance:,.2f})"


                                ),


                                note_table_ids=[supp_note.id],


                            ))





        return findings





    # ─── 应交所得税本期增加 vs 当期所得税费用 ───





    # 应交税费表中识别"企业所得税"/"应交所得税"行的关键词


    TAX_PAYABLE_NOTE_KEYWORDS = ["应交税费"]


    INCOME_TAX_ROW_KEYWORDS = ["企业所得税", "应交所得税"]


    # 本期增加列的表头关键词


    CURRENT_INCREASE_HEADER_KEYWORDS = ["本期增加", "本期计提", "本年增加", "本年计提"]





    # 所得税费用表中识别"当期所得税费用"行的关键词


    INCOME_TAX_EXPENSE_NOTE_KEYWORDS = ["所得税费用"]


    CURRENT_TAX_EXPENSE_ROW_KEYWORDS = [


        "当期所得税费用",


        "当期所得税",


        "按税法及相关规定计算的当期所得税",


    ]





    def check_income_tax_consistency(


        self,


        notes: List[NoteTable],


    ) -> List[ReportReviewFinding]:


        """应交税费中应交所得税的本期增加额 vs 所得税费用中的当期所得税费用。





        校验规则：


        应交税费表.企业所得税.本期增加 == 所得税费用表.当期所得税费用.本期发生额


        """


        findings: List[ReportReviewFinding] = []





        # 1. 找到应交税费附注表格，提取企业所得税的本期增加额


        tax_payable_increase: Optional[float] = None


        tax_payable_note_id: Optional[str] = None





        for n in notes:


            combined = (n.account_name or "") + (n.section_title or "")


            if not any(kw in combined for kw in self.TAX_PAYABLE_NOTE_KEYWORDS):


                continue





            # 找"本期增加"列索引


            increase_col: Optional[int] = None


            for ci, h in enumerate(n.headers):


                if any(kw in h for kw in self.CURRENT_INCREASE_HEADER_KEYWORDS):


                    increase_col = ci


                    break





            if increase_col is None:


                continue





            # 找"企业所得税"行


            for row in n.rows:


                if not row:


                    continue


                label = str(row[0]).strip() if row else ""


                if any(kw in label for kw in self.INCOME_TAX_ROW_KEYWORDS):


                    if increase_col < len(row):


                        val = _safe_float(row[increase_col])


                        if val is not None:


                            tax_payable_increase = val


                            tax_payable_note_id = n.id


                    break





        if tax_payable_increase is None:


            return findings





        # 2. 找到所得税费用附注表格，提取当期所得税费用


        current_tax_expense: Optional[float] = None


        tax_expense_note_id: Optional[str] = None





        for n in notes:


            combined = (n.account_name or "") + (n.section_title or "")


            if not any(kw in combined for kw in self.INCOME_TAX_EXPENSE_NOTE_KEYWORDS):


                continue





            for row in n.rows:


                if not row:


                    continue


                label = str(row[0]).strip() if row else ""


                if any(kw in label for kw in self.CURRENT_TAX_EXPENSE_ROW_KEYWORDS):


                    # 取第一个数值列（通常是本期发生额）


                    for ci in range(1, len(row)):


                        val = _safe_float(row[ci])


                        if val is not None:


                            current_tax_expense = val


                            tax_expense_note_id = n.id


                            break


                    break





        if current_tax_expense is None:


            return findings





        # 3. 比对


        if not _amounts_equal(tax_payable_increase, current_tax_expense):


            diff = round(tax_payable_increase - current_tax_expense, 2)


            note_ids = [nid for nid in [tax_payable_note_id, tax_expense_note_id] if nid]


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name="应交税费/所得税费用",


                location="附注-应交税费(企业所得税本期增加) vs 所得税费用(当期所得税费用)",


                description=(


                    f"应交税费中企业所得税本期增加额 {tax_payable_increase:,.2f} "


                    f"与所得税费用中当期所得税费用 {current_tax_expense:,.2f} 不一致，"


                    f"差异 {diff:,.2f}"


                ),


                statement_amount=current_tax_expense,


                note_amount=tax_payable_increase,


                difference=diff,


                risk_level=self._assess_risk(abs(diff), abs(current_tax_expense)),


                reasoning=(


                    f"校验公式: 应交税费.企业所得税.本期增加({tax_payable_increase:,.2f}) "


                    f"应等于 所得税费用.当期所得税费用({current_tax_expense:,.2f})"


                ),


                note_table_ids=note_ids,


            ))





        return findings





    # ─── 跨科目交叉校验：信用减值损失 / 资产减值损失 vs 各科目计提合计 (X-2, X-3) ───





    # 信用减值损失对应的坏账准备科目


    CREDIT_IMPAIRMENT_ACCOUNTS = [


        "应收票据", "应收账款", "其他应收款", "应收款项融资",


        "长期应收款", "债权投资", "其他债权投资", "合同资产",


    ]


    # 资产减值损失对应的减值准备科目


    ASSET_IMPAIRMENT_ACCOUNTS = [


        "存货", "固定资产", "在建工程", "无形资产", "商誉",


        "合同资产", "生产性生物资产", "使用权资产", "长期股权投资",


        "投资性房地产", "油气资产",


    ]


    # 变动表中"本期计提"行关键词


    PROVISION_INCREASE_ROW_KW = ["计提", "本期增加", "本期计提"]


    # 变动表标题关键词


    PROVISION_MOVEMENT_TITLE_KW = [


        "坏账准备", "减值准备", "跌价准备",


        "变动", "计提", "转回",


    ]





    def _extract_provision_increase(
        self, note: "NoteTable",
    ) -> Optional[float]:
        """从坏账/减值准备变动表中提取'本期计提'金额。

        变动表结构: 期初余额 / 本期计提 / 收回或转回 / 核销 / 期末余额

        优先通过表头关键词定位"合计"列取值，回退取最后一个数值列。
        """
        if not note.rows:
            return None

        # 优先通过表头定位合计列
        total_col_idx = None
        if note.headers:
            for ci in range(len(note.headers) - 1, 0, -1):
                h = str(note.headers[ci] or "").replace(" ", "").replace("\u3000", "")
                if h in ("合计", "总计"):
                    total_col_idx = ci
                    break

        for ri, row in enumerate(note.rows):
            if not row:
                continue
            label = str(row[0] or "").strip()
            if not any(kw in label for kw in self.PROVISION_INCREASE_ROW_KW):
                continue

            # 优先从合计列取值
            if total_col_idx is not None and total_col_idx < len(row):
                val = _safe_float(row[total_col_idx])
                if val is not None:
                    return val

            # 回退：取最后一个非空数值列
            last_val = None
            for ci in range(1, len(row)):
                val = _safe_float(row[ci])
                if val is not None:
                    last_val = val
            if last_val is not None:
                return last_val

        return None





    def check_impairment_loss_consistency(


        self,


        items: List[StatementItem],


        notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """信用减值损失/资产减值损失 vs 各科目坏账/减值准备变动表本期计提合计。





        X-2: 信用减值损失 = sum(各应收类科目坏账准备变动表.本期计提)


        X-3: 资产减值损失 = sum(各资产类科目减值准备变动表.本期计提)


        """


        findings: List[ReportReviewFinding] = []





        # 从利润表提取信用减值损失和资产减值损失


        credit_impairment: Optional[float] = None


        asset_impairment: Optional[float] = None


        for item in items:


            if item.statement_type != StatementType.INCOME_STATEMENT:


                continue


            name = item.account_name


            if "信用减值损失" in name and credit_impairment is None:


                credit_impairment = item.closing_balance


            elif "资产减值损失" in name and asset_impairment is None:


                asset_impairment = item.closing_balance





        # 按科目分组附注表格


        account_notes: Dict[str, List["NoteTable"]] = {}


        for n in notes:


            account_notes.setdefault(n.account_name or "", []).append(n)





        def _sum_provision_increase(target_accounts, title_keywords):


            """从目标科目的变动表中汇总本期计提金额。"""


            total = 0.0


            count = 0


            note_ids = []


            for acct, acct_notes_list in account_notes.items():


                if not any(kw in acct for kw in target_accounts):


                    continue


                for n in acct_notes_list:


                    title = n.section_title or ""


                    if not any(kw in title for kw in title_keywords):


                        continue


                    val = self._extract_provision_increase(n)


                    if val is not None:


                        total += val


                        count += 1


                        note_ids.append(n.id)


                        break  # 每个科目只取第一个变动表


            return total, count, note_ids





        # X-2: 信用减值损失 vs 各科目坏账准备计提合计


        if credit_impairment is not None and abs(credit_impairment) > 0.01:


            provision_total, prov_count, prov_nids = _sum_provision_increase(


                self.CREDIT_IMPAIRMENT_ACCOUNTS,


                ["坏账准备", "减值准备", "变动", "计提"],


            )


            if prov_count > 0:


                # 信用减值损失在利润表中通常为负数（损失），计提金额为正数


                # 比较时取绝对值


                stmt_abs = abs(credit_impairment)


                if not _amounts_equal(stmt_abs, provision_total):


                    diff = round(stmt_abs - provision_total, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name="信用减值损失",


                        location="跨科目核对-信用减值损失 vs 各科目坏账准备计提合计",


                        description=(


                            f"利润表信用减值损失 {credit_impairment:,.2f}"


                            f"（绝对值 {stmt_abs:,.2f}）与各科目坏账准备变动表"


                            f"本期计提合计 {provision_total:,.2f} 不一致"


                            f"（来自 {prov_count} 个科目），差异 {diff:,.2f}"


                        ),


                        difference=diff,


                        statement_amount=credit_impairment,


                        note_amount=provision_total,


                        risk_level=self._assess_risk(abs(diff), stmt_abs),


                        reasoning=(


                            f"X-2: |信用减值损失|({stmt_abs:,.2f}) vs "


                            f"sum(坏账准备.本期计提)({provision_total:,.2f})"


                        ),


                        note_table_ids=prov_nids,


                    ))





        # X-3: 资产减值损失 vs 各科目减值准备计提合计


        if asset_impairment is not None and abs(asset_impairment) > 0.01:


            provision_total, prov_count, prov_nids = _sum_provision_increase(


                self.ASSET_IMPAIRMENT_ACCOUNTS,


                ["减值准备", "跌价准备", "变动", "计提"],


            )


            if prov_count > 0:


                stmt_abs = abs(asset_impairment)


                if not _amounts_equal(stmt_abs, provision_total):


                    diff = round(stmt_abs - provision_total, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name="资产减值损失",


                        location="跨科目核对-资产减值损失 vs 各科目减值准备计提合计",


                        description=(


                            f"利润表资产减值损失 {asset_impairment:,.2f}"


                            f"（绝对值 {stmt_abs:,.2f}）与各科目减值准备变动表"


                            f"本期计提合计 {provision_total:,.2f} 不一致"


                            f"（来自 {prov_count} 个科目），差异 {diff:,.2f}"


                        ),


                        difference=diff,


                        statement_amount=asset_impairment,


                        note_amount=provision_total,


                        risk_level=self._assess_risk(abs(diff), stmt_abs),


                        reasoning=(


                            f"X-3: |资产减值损失|({stmt_abs:,.2f}) vs "


                            f"sum(减值准备.本期计提)({provision_total:,.2f})"


                        ),


                        note_table_ids=prov_nids,


                    ))





        return findings





    # ─── 跨科目交叉校验：在建工程转固 / 开发支出转无形 (X-4, X-5) ───





    # 在建工程变动表中"转入固定资产"行关键词


    CIP_TO_FA_ROW_KW = ["转入固定资产", "转入固定", "转固"]


    # 固定资产变动表中"在建工程转入"行关键词


    FA_FROM_CIP_ROW_KW = ["在建工程转入", "在建工程", "转入"]


    # 开发支出变动表中"确认为无形资产"行关键词


    DEV_TO_IA_ROW_KW = ["确认为无形资产", "转入无形资产", "转无形"]


    # 无形资产变动表中"开发支出转入"/"内部开发"行关键词


    IA_FROM_DEV_ROW_KW = ["开发支出转入", "内部开发", "开发支出"]





    def _extract_movement_row_amount(


        self,


        note: "NoteTable",


        row_keywords: List[str],


        prefer_last_col: bool = False,


    ) -> Optional[float]:


        """从变动表中提取指定行的金额。





        row_keywords: 行标签匹配关键词


        prefer_last_col: True时取最后一个数值列（合计列），False时取第一个


        """


        if not note.rows:


            return None


        for ri, row in enumerate(note.rows):


            if not row:


                continue


            label = str(row[0] or "").strip()


            if not any(kw in label for kw in row_keywords):


                continue


            vals = []


            for ci in range(1, len(row)):


                val = _safe_float(row[ci])


                if val is not None:


                    vals.append(val)


            if vals:


                return vals[-1] if prefer_last_col else vals[0]


        return None





    def check_transfer_consistency(


        self,


        notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """在建工程转固 / 开发支出转无形资产 跨科目交叉校验。





        X-4: 在建工程变动表."转入固定资产" = 固定资产变动表."在建工程转入"


        X-5: 开发支出变动表."确认为无形资产" = 无形资产变动表."开发支出转入"


        """


        findings: List[ReportReviewFinding] = []





        # 按科目分组


        account_notes: Dict[str, List["NoteTable"]] = {}


        for n in notes:


            account_notes.setdefault(n.account_name or "", []).append(n)





        def _find_movement_table(acct_keyword: str) -> Optional["NoteTable"]:


            """找到指定科目的变动表。


            支持两种格式：


            1. 宽表：列含期初/期末（如 项目|期初|增加|减少|期末）


            2. 转置表：行含期初/期末（如 期初余额|本期增加|转入固定资产|期末余额）


            """


            for acct, ns in account_notes.items():


                if acct_keyword not in acct:


                    continue


                for n in ns:


                    title = n.section_title or ""


                    # 排除减值准备表（非在建工程科目）


                    if "减值" in title and acct_keyword not in ["在建工程"]:


                        continue


                    hdrs = " ".join(str(h or "") for h in (n.headers or []))


                    # 格式1：列含期初/期末，且列数>=4


                    if (("期初" in hdrs or "年初" in hdrs)


                            and ("期末" in hdrs or "年末" in hdrs)


                            and len(n.headers or []) >= 4):


                        return n


                    # 格式2：行标签含期初/期末（变动表转置格式）


                    if n.rows and len(n.rows) >= 3:


                        row_labels = [str(r[0] or "").strip() for r in n.rows if r]


                        labels_text = " ".join(row_labels)


                        has_opening = any(k in labels_text for k in ["期初", "年初"])


                        has_closing = any(k in labels_text for k in ["期末", "年末"])


                        if has_opening and has_closing:


                            return n


            return None





        # X-4: 在建工程转固


        cip_table = _find_movement_table("在建工程")


        fa_table = _find_movement_table("固定资产")





        if cip_table and fa_table:


            cip_transfer = self._extract_movement_row_amount(


                cip_table, self.CIP_TO_FA_ROW_KW, prefer_last_col=True,


            )


            fa_from_cip = self._extract_movement_row_amount(


                fa_table, self.FA_FROM_CIP_ROW_KW, prefer_last_col=True,


            )


            if (cip_transfer is not None and fa_from_cip is not None


                    and not _amounts_equal(abs(cip_transfer), abs(fa_from_cip))):


                diff = round(abs(cip_transfer) - abs(fa_from_cip), 2)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name="在建工程/固定资产",


                    location="跨科目核对-在建工程转固",


                    description=(


                        f"在建工程变动表'转入固定资产' {cip_transfer:,.2f} 与"


                        f"固定资产变动表'在建工程转入' {fa_from_cip:,.2f} "


                        f"不一致，差异 {diff:,.2f}"


                    ),


                    difference=diff,


                    statement_amount=cip_transfer,


                    note_amount=fa_from_cip,


                    risk_level=self._assess_risk(


                        abs(diff), max(abs(cip_transfer), abs(fa_from_cip))),


                    reasoning=(


                        f"X-4: 在建工程.转入固定资产({cip_transfer:,.2f}) vs "


                        f"固定资产.在建工程转入({fa_from_cip:,.2f})"


                    ),


                    note_table_ids=[cip_table.id, fa_table.id],


                ))





        # X-5: 开发支出转无形资产


        dev_table = _find_movement_table("开发支出")


        ia_table = _find_movement_table("无形资产")





        if dev_table and ia_table:


            dev_transfer = self._extract_movement_row_amount(


                dev_table, self.DEV_TO_IA_ROW_KW, prefer_last_col=True,


            )


            ia_from_dev = self._extract_movement_row_amount(


                ia_table, self.IA_FROM_DEV_ROW_KW, prefer_last_col=True,


            )


            if (dev_transfer is not None and ia_from_dev is not None


                    and not _amounts_equal(abs(dev_transfer), abs(ia_from_dev))):


                diff = round(abs(dev_transfer) - abs(ia_from_dev), 2)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name="开发支出/无形资产",


                    location="跨科目核对-开发支出转无形资产",


                    description=(


                        f"开发支出变动表'确认为无形资产' {dev_transfer:,.2f} 与"


                        f"无形资产变动表'开发支出转入' {ia_from_dev:,.2f} "


                        f"不一致，差异 {diff:,.2f}"


                    ),


                    difference=diff,


                    statement_amount=dev_transfer,


                    note_amount=ia_from_dev,


                    risk_level=self._assess_risk(


                        abs(diff), max(abs(dev_transfer), abs(ia_from_dev))),


                    reasoning=(


                        f"X-5: 开发支出.确认为无形资产({dev_transfer:,.2f}) vs "


                        f"无形资产.开发支出转入({ia_from_dev:,.2f})"


                    ),


                    note_table_ids=[dev_table.id, ia_table.id],


                ))





        return findings





    # ─── 二级明细校验 (D-series) ───





    # 二级明细匹配规则：报表子行名 → 附注行名的同义词映射


    SUB_ITEM_SYNONYMS = {


        "应付工资": ["工资", "奖金", "津贴和补贴", "工资、奖金、津贴和补贴"],


        "应付福利费": ["职工福利费", "职工福利"],


        "原材料": ["原材料"],


        "库存商品": ["库存商品", "产成品", "库存商品（产成品）"],


        "应收利息": ["应收利息"],


        "应收股利": ["应收股利"],


        "应付利息": ["应付利息"],


        "应付股利": ["应付股利"],


        "法定公积金": ["法定盈余公积金", "法定盈余公积"],


        "任意公积金": ["任意盈余公积金", "任意盈余公积"],


        "储备基金": ["储备基金"],


        "企业发展基金": ["企业发展基金"],


        "利润归还投资": ["利润归还投资"],


        "固定资产原价": ["账面原值合计", "一、账面原值合计"],


        "累计折旧": ["累计折旧合计", "二、累计折旧合计"],


        "固定资产减值准备": ["减值准备合计", "四、减值准备合计"],


    }





    def check_sub_item_detail(


        self,


        matching_map: "MatchingMap",


        items: List[StatementItem],


        notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """报表二级子明细行 vs 附注明细表对应行的金额校验。





        D-series: 报表中 is_sub_item=True 的行（如"其中：原材料"）


        与附注表格中对应行名的金额进行比对。


        """


        findings: List[ReportReviewFinding] = []


        item_map = {i.id: i for i in items}


        note_map = {n.id: n for n in notes}





        # 找到所有二级子行


        sub_items = [i for i in items if i.is_sub_item or i.parent_id]


        if not sub_items:


            return findings





        # 构建 parent_id -> note_table_ids 映射


        parent_note_map: Dict[str, List[str]] = {}


        for entry in matching_map.entries:


            if entry.note_table_ids:


                parent_note_map[entry.statement_item_id] = entry.note_table_ids





        for sub in sub_items:


            # 清洗子行名称：去除"其中："、"减："等前缀


            raw_name = sub.account_name


            clean_name = raw_name


            for prefix in ["其中：", "其中:", "减：", "减:", "加：", "加:"]:


                if clean_name.startswith(prefix):


                    clean_name = clean_name[len(prefix):]


                    break


            clean_name = clean_name.strip()


            if not clean_name:


                continue





            # 找到父科目的附注表格


            parent_id = sub.parent_id


            if not parent_id:


                continue


            note_ids = parent_note_map.get(parent_id, [])


            if not note_ids:


                continue





            # 构建匹配关键词列表


            match_keywords = [clean_name]


            for syn_key, syn_vals in self.SUB_ITEM_SYNONYMS.items():


                if syn_key in clean_name or clean_name in syn_key:


                    match_keywords.extend(syn_vals)


                    break





            # 在附注表格中查找匹配行


            matched = False


            for nid in note_ids:


                note = note_map.get(nid)


                ts = table_structures.get(nid)


                if not note or not ts or not note.rows:


                    continue





                # 找期末/期初列


                closing_col = None


                opening_col = None


                for col in ts.columns:


                    if col.semantic == "closing_balance" and closing_col is None:


                        closing_col = col.col_index


                    elif col.semantic == "opening_balance" and opening_col is None:


                        opening_col = col.col_index





                if closing_col is None and opening_col is None:


                    continue





                # 遍历附注表格行，查找匹配的行名


                for ri, row in enumerate(note.rows):


                    if not row:


                        continue


                    row_label = str(row[0] or "").strip()


                    # 去除行名前缀


                    for pfx in ["其中：", "其中:", "减：", "减:", "一、", "二、",


                                "三、", "四、", "五、"]:


                        if row_label.startswith(pfx):


                            row_label_clean = row_label[len(pfx):].strip()


                            break


                    else:


                        row_label_clean = row_label





                    # 匹配


                    hit = False


                    for kw in match_keywords:


                        if kw in row_label_clean or row_label_clean in kw:


                            hit = True


                            break


                    if not hit:


                        continue





                    # 比对期末


                    if closing_col is not None and sub.closing_balance is not None:


                        note_val = self._get_row_col_value(note, ri, closing_col)


                        if note_val is not None:


                            if _amounts_equal(sub.closing_balance, note_val):


                                matched = True


                            else:


                                diff = round(sub.closing_balance - note_val, 2)


                                findings.append(self._make_finding(


                                    category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,


                                    account_name=raw_name,


                                    location=f"附注-{note.account_name}-{note.section_title}-二级明细-期末",


                                    description=(


                                        f"报表二级明细'{raw_name}'期末 {sub.closing_balance:,.2f}"


                                        f" 与附注'{row_label}'行期末 {note_val:,.2f}"


                                        f" 不一致，差异 {diff:,.2f}"


                                    ),


                                    difference=diff,


                                    statement_amount=sub.closing_balance,


                                    note_amount=note_val,


                                    risk_level=self._assess_risk(abs(diff), abs(sub.closing_balance) if sub.closing_balance else None),


                                    reasoning=f"二级明细: 报表({sub.closing_balance:,.2f}) vs 附注({note_val:,.2f})",


                                    note_table_ids=[nid],


                                ))


                                matched = True





                    # 比对期初


                    if opening_col is not None and sub.opening_balance is not None:


                        note_val = self._get_row_col_value(note, ri, opening_col)


                        if note_val is not None:


                            if not _amounts_equal(sub.opening_balance, note_val):


                                diff = round(sub.opening_balance - note_val, 2)


                                findings.append(self._make_finding(


                                    category=ReportReviewFindingCategory.AMOUNT_INCONSISTENCY,


                                    account_name=raw_name,


                                    location=f"附注-{note.account_name}-{note.section_title}-二级明细-期初",


                                    description=(


                                        f"报表二级明细'{raw_name}'期初 {sub.opening_balance:,.2f}"


                                        f" 与附注'{row_label}'行期初 {note_val:,.2f}"


                                        f" 不一致，差异 {diff:,.2f}"


                                    ),


                                    difference=diff,


                                    statement_amount=sub.opening_balance,


                                    note_amount=note_val,


                                    risk_level=self._assess_risk(abs(diff), abs(sub.opening_balance) if sub.opening_balance else None),


                                    reasoning=f"二级明细: 报表({sub.opening_balance:,.2f}) vs 附注({note_val:,.2f})",


                                    note_table_ids=[nid],


                                ))


                                matched = True





                    if matched:


                        break


                if matched:


                    break





        return findings








    # ─── 跨科目交叉校验：盈余公积提取 vs 未分配利润 (X-7) ───





    def check_surplus_reserve_consistency(


        self,


        notes: List[NoteTable],


    ) -> List[ReportReviewFinding]:


        """盈余公积明细表'本期增加-提取'合计 vs 未分配利润明细表'提取盈余公积'行。





        X-7 / F57-4 / F58-4


        """


        findings: List[ReportReviewFinding] = []





        # 1. 从盈余公积明细表提取"本期增加"列的合计行金额


        surplus_increase: Optional[float] = None


        surplus_note_id: Optional[str] = None





        for n in notes:


            acct = n.account_name or ""


            if "盈余公积" not in acct:


                continue


            if not n.headers or not n.rows:


                continue


            # 找"本期增加"或"提取"列


            increase_col = None


            for ci, h in enumerate(n.headers):


                h_str = str(h or "")


                if any(kw in h_str for kw in ["本期增加", "提取"]):


                    if "减少" not in h_str:


                        increase_col = ci


                        break


            if increase_col is None:


                continue


            # 找合计行


            for ri, row in enumerate(n.rows):


                if not row:


                    continue


                label = str(row[0] or "").strip()


                if any(kw in label for kw in ["合计", "合 计", "总计"]):


                    val = _safe_float(row[increase_col]) if increase_col < len(row) else None


                    if val is not None:


                        surplus_increase = val


                        surplus_note_id = n.id


                    break


            if surplus_increase is not None:


                break





        if surplus_increase is None:


            return findings





        # 2. 从未分配利润明细表提取"提取盈余公积"行金额


        undist_extract: Optional[float] = None


        undist_note_id: Optional[str] = None





        for n in notes:


            acct = n.account_name or ""


            title = n.section_title or ""


            if "未分配利润" not in acct and "未分配利润" not in title:


                continue


            if not n.rows:


                continue


            for ri, row in enumerate(n.rows):


                if not row:


                    continue


                label = str(row[0] or "").strip()


                if "提取盈余公积" in label or "盈余公积" in label:


                    # 取第一个数值列


                    for ci in range(1, len(row)):


                        val = _safe_float(row[ci])


                        if val is not None:


                            undist_extract = abs(val)  # 可能为负数（减少项）


                            undist_note_id = n.id


                            break


                    break


            if undist_extract is not None:


                break





        if undist_extract is None:


            return findings





        # 3. 比对


        if not _amounts_equal(surplus_increase, undist_extract):


            diff = round(surplus_increase - undist_extract, 2)


            note_ids = [nid for nid in [surplus_note_id, undist_note_id] if nid]


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name="盈余公积/未分配利润",


                location="跨科目核对-盈余公积提取 vs 未分配利润",


                description=(


                    f"盈余公积明细表本期增加(提取)合计 {surplus_increase:,.2f} 与"


                    f"未分配利润明细表'提取盈余公积' {undist_extract:,.2f} "


                    f"不一致，差异 {diff:,.2f}"


                ),


                difference=diff,


                statement_amount=surplus_increase,


                note_amount=undist_extract,


                risk_level=self._assess_risk(abs(diff), surplus_increase),


                reasoning=(


                    f"X-7: 盈余公积.本期增加({surplus_increase:,.2f}) vs "


                    f"未分配利润.提取盈余公积({undist_extract:,.2f})"


                ),


                note_table_ids=note_ids,


            ))





        return findings





    # ─── X-10: 货币资金 vs 现金等价物 ───


    # ─── X-11: 一年内到期的非流动资产 vs 各长期资产科目 ───


    # ─── X-12: 一年内到期的非流动负债 vs 各长期负债科目 ───





    _MATURITY_ASSET_MAPPINGS = [


        # (汇总表行名关键词, 对应科目名关键词, 对应科目附注中减项行关键词)


        (["长期应收款"], "长期应收款", ["1年内到期", "一年内到期"]),


        (["债权投资"], "债权投资", ["1年内到期", "一年内到期"]),


        (["其他债权投资"], "其他债权投资", ["1年内到期", "一年内到期"]),


    ]





    _MATURITY_LIABILITY_MAPPINGS = [


        (["长期借款"], "长期借款", ["1年内到期", "一年内到期"]),


        (["应付债券"], "应付债券", ["1年内到期", "一年内到期"]),


        (["长期应付款"], "长期应付款", ["1年内到期", "一年内到期"]),


        (["租赁负债"], "租赁负债", ["1年内到期", "一年内到期", "重分类至一年内"]),


    ]





    def check_maturity_reclassification(


        self,


        items: List["StatementItem"],


        notes: List["NoteTable"],


        table_structures: Dict[str, "TableStructure"],


    ) -> List[ReportReviewFinding]:


        """一年内到期的非流动资产/负债 vs 各长期科目附注中的减项行。





        X-10: 货币资金 vs 现金等价物（受限货币资金 = 货币资金 - 现金等价物）


        X-11: 一年内到期的非流动资产汇总表各行 vs 长期应收款/债权投资/其他债权投资


        X-12: 一年内到期的非流动负债汇总表各行 vs 长期借款/应付债券/长期应付款/租赁负债


        """


        findings: List[ReportReviewFinding] = []





        account_notes: Dict[str, List["NoteTable"]] = {}


        for n in notes:


            account_notes.setdefault(n.account_name or "", []).append(n)





        # X-10


        findings.extend(self._check_cash_equivalents(items, notes))


        # X-11


        findings.extend(self._check_maturity_cross(


            account_notes, "一年内到期的非流动资产", self._MATURITY_ASSET_MAPPINGS,


            "X-11", table_structures,


        ))


        # X-12


        findings.extend(self._check_maturity_cross(


            account_notes, "一年内到期的非流动负债", self._MATURITY_LIABILITY_MAPPINGS,


            "X-12", table_structures,


        ))





        return findings





    def _check_cash_equivalents(


        self,


        items: List["StatementItem"],


        notes: List["NoteTable"],


    ) -> List[ReportReviewFinding]:


        """X-10: 货币资金受限制表合计 = 货币资金 - 现金及现金等价物余额。"""


        findings: List[ReportReviewFinding] = []





        cash_balance: Optional[float] = None


        for item in items:


            if item.account_name and "货币资金" in item.account_name:


                if item.closing_balance is not None:


                    cash_balance = item.closing_balance


                    break


        if cash_balance is None:


            return findings





        # 从补充资料表取"期末现金及现金等价物余额"


        cash_equiv: Optional[float] = None


        cash_equiv_note_id: Optional[str] = None


        _supp_kw = ["现金和现金等价物", "现金及现金等价物", "补充资料"]


        _row_kw = ["期末现金及现金等价物余额", "三、期末现金及现金等价物"]





        for n in notes:


            combined = (n.section_title or "") + (n.account_name or "")


            if not any(kw in combined for kw in _supp_kw):


                continue


            for row in (n.rows or []):


                if not row:


                    continue


                label = str(row[0] or "").strip()


                if any(kw in label for kw in _row_kw):


                    for ci in range(1, len(row)):


                        val = _safe_float(row[ci])


                        if val is not None:


                            cash_equiv = val


                            cash_equiv_note_id = n.id


                            break


                    break


            if cash_equiv is not None:


                break





        if cash_equiv is None:


            return findings





        # 从货币资金受限制表取合计行


        restricted_total: Optional[float] = None


        restricted_note_id: Optional[str] = None


        for n in notes:


            acct = n.account_name or ""


            title = n.section_title or ""


            if "货币资金" not in acct:


                continue


            if not any(kw in title for kw in ["受限", "限制", "冻结"]):


                continue


            for row in (n.rows or []):


                if not row:


                    continue


                label = str(row[0] or "").strip()


                if any(kw in label for kw in ["合计", "合 计", "总计"]):


                    for ci in range(1, len(row)):


                        val = _safe_float(row[ci])


                        if val is not None:


                            restricted_total = val


                            restricted_note_id = n.id


                            break


                    break


            if restricted_total is not None:


                break





        if restricted_total is None:


            return findings





        expected_restricted = round(cash_balance - cash_equiv, 2)


        if not _amounts_equal(restricted_total, expected_restricted):


            diff = round(restricted_total - expected_restricted, 2)


            note_ids = [nid for nid in [restricted_note_id, cash_equiv_note_id] if nid]


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name="货币资金",


                location="跨科目核对-货币资金 vs 现金等价物",


                description=(


                    f"货币资金受限制表合计 {restricted_total:,.2f} 与"


                    f"(货币资金{cash_balance:,.2f} - 现金等价物{cash_equiv:,.2f} "


                    f"= {expected_restricted:,.2f}) 不一致，差异 {diff:,.2f}"


                ),


                difference=diff,


                statement_amount=expected_restricted,


                note_amount=restricted_total,


                risk_level=self._assess_risk(abs(diff), cash_balance),


                reasoning=(


                    f"X-10: 受限货币资金({restricted_total:,.2f}) vs "


                    f"货币资金({cash_balance:,.2f}) - 现金等价物({cash_equiv:,.2f})"


                ),


                note_table_ids=note_ids,


            ))





        return findings





    def _check_maturity_cross(


        self,


        account_notes: Dict[str, List["NoteTable"]],


        summary_acct_keyword: str,


        mappings: list,


        rule_id: str,


        table_structures: Dict[str, "TableStructure"],


    ) -> List[ReportReviewFinding]:


        """通用：一年内到期汇总表各行 vs 对应长期科目附注中的减项行。"""


        findings: List[ReportReviewFinding] = []





        # 找到一年内到期汇总表


        summary_note: Optional["NoteTable"] = None


        for acct, ns in account_notes.items():


            if summary_acct_keyword not in acct:


                continue


            for n in ns:


                if n.rows and len(n.headers or []) <= 5:


                    summary_note = n


                    break


            if summary_note:


                break





        if not summary_note or not summary_note.rows:


            return findings





        for row in summary_note.rows:


            if not row:


                continue


            label = str(row[0] or "").strip()


            if any(kw in label for kw in ["合计", "合 计", "总计", "小计"]):


                continue





            summary_val: Optional[float] = None


            for ci in range(1, len(row)):


                val = _safe_float(row[ci])


                if val is not None:


                    summary_val = val


                    break





            if summary_val is None or abs(summary_val) < 0.005:


                continue





            for row_kws, target_acct, deduct_kws in mappings:


                if not any(kw in label for kw in row_kws):


                    continue





                target_val: Optional[float] = None


                target_note_id: Optional[str] = None





                for acct, ns in account_notes.items():


                    if target_acct not in acct:


                        continue


                    if target_acct == "债权投资" and "其他债权投资" in acct:


                        continue


                    for n in ns:


                        for r in (n.rows or []):


                            if not r:


                                continue


                            r_label = str(r[0] or "").strip()


                            if not any(dk in r_label for dk in deduct_kws):


                                continue


                            for ci2 in range(1, len(r)):


                                v = _safe_float(r[ci2])


                                if v is not None:


                                    target_val = abs(v)


                                    target_note_id = n.id


                                    break


                            if target_val is not None:


                                break


                        if target_val is not None:


                            break


                    if target_val is not None:


                        break





                if target_val is None:


                    continue





                if not _amounts_equal(abs(summary_val), target_val):


                    diff = round(abs(summary_val) - target_val, 2)


                    note_ids = [nid for nid in [summary_note.id, target_note_id] if nid]


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=f"{summary_acct_keyword}/{target_acct}",


                        location=f"跨科目核对-{summary_acct_keyword}'{label}'",


                        description=(


                            f"{summary_acct_keyword}汇总表'{label}' {abs(summary_val):,.2f} 与"


                            f"{target_acct}附注中减项行 {target_val:,.2f} "


                            f"不一致，差异 {abs(diff):,.2f}"


                        ),


                        difference=diff,


                        statement_amount=target_val,


                        note_amount=abs(summary_val),


                        risk_level=self._assess_risk(


                            abs(diff), max(abs(summary_val), target_val)),


                        reasoning=(


                            f"{rule_id}: {summary_acct_keyword}.{label}"


                            f"({abs(summary_val):,.2f}) vs "


                            f"{target_acct}.减项行({target_val:,.2f})"


                        ),


                        note_table_ids=note_ids,


                    ))


                break





        return findings














    # ─── X-14: 其他综合收益 vs 利润表（上市版特有）───





    def check_oci_vs_income_statement(


        self,


        items: list,


        notes: list,


    ) -> list:


        """X-14: 其他综合收益附注表合计 vs 利润表'其他综合收益'行。





        上市版特有：其他综合收益在资产负债表中单独列示，附注中有


        '利润表中归属于母公司的其他综合收益'表，其合计行应等于


        利润表中'其他综合收益'行的本期金额。


        """


        findings = []





        # 1. 从利润表中找"其他综合收益"行


        oci_statement_val = None


        for item in items:


            if not item.account_name:


                continue


            if item.statement_type and item.statement_type.value == "income_statement":


                name = item.account_name.strip()


                if "其他综合收益" in name and "税后" not in name:


                    # 取本期金额（closing_balance 在利润表中对应本期发生额）


                    if item.closing_balance is not None:


                        oci_statement_val = item.closing_balance


                        break





        if oci_statement_val is None:


            return findings





        # 2. 从附注中找其他综合收益相关表格


        oci_note_val = None


        oci_note_id = None


        for n in notes:


            acct = n.account_name or ""


            title = n.section_title or ""


            combined = acct + title


            if "其他综合收益" not in combined:


                continue


            # 优先找"利润表中"或"税后净额"相关的表


            is_income_oci = any(kw in combined for kw in [


                "利润表中", "税后", "归属于母公司",


            ])


            if not is_income_oci and oci_note_val is not None:


                continue  # 已找到更精确的表，跳过





            # 在合计行中查找值


            for row in (n.rows or []):


                if not row:


                    continue


                label = str(row[0] or "").strip()


                if any(kw in label for kw in ["合计", "合 计", "总计"]):


                    # 取第一个数值列（本期金额）


                    for ci in range(1, len(row)):


                        v = _safe_float(row[ci])


                        if v is not None:


                            oci_note_val = v


                            oci_note_id = n.id


                            break


                    break


            if oci_note_val is not None and is_income_oci:


                break  # 找到精确匹配的表，停止搜索





        if oci_note_val is None:


            return findings





        # 3. 比对


        if not _amounts_equal(oci_statement_val, oci_note_val):


            diff = round(oci_statement_val - oci_note_val, 2)


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name="其他综合收益",


                location="跨科目核对-其他综合收益 vs 利润表",


                description=(


                    f"其他综合收益附注表合计 {oci_note_val:,.2f} 与"


                    f"利润表'其他综合收益' {oci_statement_val:,.2f} "


                    f"不一致，差异 {diff:,.2f}"


                ),


                difference=diff,


                statement_amount=oci_statement_val,


                note_amount=oci_note_val,


                risk_level=self._assess_risk(abs(diff), abs(oci_statement_val)),


                reasoning=(


                    f"X-14: 其他综合收益附注合计({oci_note_val:,.2f}) vs "


                    f"利润表.其他综合收益({oci_statement_val:,.2f})"


                ),


                note_table_ids=[oci_note_id] if oci_note_id else [],


            ))





        return findings








    # ─── E-series: 所有者权益变动表 vs 附注 ───





    # 权益变动表列名 → 附注科目名 映射（国企版/上市版通用）


    _EQUITY_COL_ACCOUNT_MAP = [


        # (列名关键词列表, 附注科目名关键词列表)


        (["实收资本", "股本"], ["实收资本", "股本"]),


        (["资本公积"], ["资本公积"]),


        (["专项储备"], ["专项储备"]),


        (["盈余公积"], ["盈余公积"]),


        (["未分配利润"], ["未分配利润"]),


        (["其他权益工具"], ["其他权益工具"]),


        (["其他综合收益"], ["其他综合收益"]),


        (["库存股"], ["库存股"]),


    ]





    # 权益变动表中"期初余额"行的关键词


    _EQUITY_OPENING_ROW_KW = [


        "期初余额", "上年年末余额", "年初余额",


        "一、上年年末余额", "一、期初余额",


        "上年末余额",


    ]





    # 权益变动表中"期末余额"行的关键词


    _EQUITY_CLOSING_ROW_KW = [


        "期末余额", "本年年末余额", "年末余额",


        "四、期末余额", "四、本期期末余额",


        "三、期末余额", "三、本期期末余额",


    ]





    def check_equity_change_vs_notes(


        self,


        sheet_data_map: dict,


        notes: list,


        table_structures: dict,


    ) -> list:


        """E-series: 所有者权益变动表各列期初/期末 vs 对应附注科目期初/期末合计。





        权益变动表是转置结构：列=权益科目（实收资本/资本公积/盈余公积/未分配利润等），


        行=变动事项（期初余额/本期增减/期末余额等）。


        本方法解析列头识别科目，提取期初/期末行的值，与附注表格的合计行比对。





        Args:


            sheet_data_map: session.sheet_data, Dict[str, List[ReportSheetData]]


            notes: session.note_tables


            table_structures: table_structures dict





        Returns:


            List[ReportReviewFinding]


        """


        findings = []





        # 1. 找到权益变动表的 ReportSheetData


        equity_sheets = []


        for file_id, sheets in sheet_data_map.items():


            for sd in sheets:


                if sd.statement_type and sd.statement_type.value == "equity_change":


                    equity_sheets.append(sd)





        if not equity_sheets:


            return findings





        # 2. 构建附注科目 → NoteTable 索引


        account_notes = {}


        for n in notes:


            account_notes.setdefault(n.account_name or "", []).append(n)





        # 3. 对每个权益变动表 sheet 进行校验


        for sd in equity_sheets:


            findings.extend(self._check_single_equity_sheet(sd, account_notes, table_structures))





        return findings





    def _check_single_equity_sheet(self, sd, account_notes, table_structures):


        """校验单个权益变动表 sheet 的各列 vs 附注。"""


        findings = []


        headers = sd.headers or []


        raw_data = sd.raw_data or []





        if not headers or not raw_data:


            return findings





        # 识别各列对应的权益科目


        col_account_map = {}  # col_index -> (col_header, note_account_keywords)


        for ci, hdr in enumerate(headers):


            if ci == 0:


                continue  # 第一列是行标签


            hdr_clean = str(hdr or "").strip()


            if not hdr_clean:


                continue


            for col_kws, note_kws in self._EQUITY_COL_ACCOUNT_MAP:


                if any(kw in hdr_clean for kw in col_kws):


                    col_account_map[ci] = (hdr_clean, note_kws)


                    break





        if not col_account_map:


            return findings





        # 识别期初/期末行


        opening_row_idx = None


        closing_row_idx = None


        for ri, row in enumerate(raw_data):


            if not row:


                continue


            label = str(row[0] or "").strip()


            if not label:


                continue


            # 期初


            if opening_row_idx is None:


                if any(kw in label for kw in self._EQUITY_OPENING_ROW_KW):


                    opening_row_idx = ri


            # 期末（取最后一个匹配的行，因为可能有"调整后期初"等中间行）


            if any(kw in label for kw in self._EQUITY_CLOSING_ROW_KW):


                closing_row_idx = ri





        if opening_row_idx is None and closing_row_idx is None:


            return findings





        # 对每个识别到的列/科目进行校验


        for ci, (col_header, note_kws) in col_account_map.items():


            # 提取权益变动表中该列的期初/期末值


            eq_opening = None


            eq_closing = None


            if opening_row_idx is not None and opening_row_idx < len(raw_data):


                row = raw_data[opening_row_idx]


                if ci < len(row):


                    eq_opening = _safe_float(row[ci])


            if closing_row_idx is not None and closing_row_idx < len(raw_data):


                row = raw_data[closing_row_idx]


                if ci < len(row):


                    eq_closing = _safe_float(row[ci])





            if eq_opening is None and eq_closing is None:


                continue





            # 在附注中查找对应科目的表格


            note_opening, note_closing, note_id = self._find_note_opening_closing(


                note_kws, account_notes, table_structures,


            )





            # 比对期初


            if eq_opening is not None and note_opening is not None:


                if not _amounts_equal(eq_opening, note_opening):


                    diff = round(eq_opening - note_opening, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=col_header,


                        location=f"权益变动表 vs 附注-{col_header}期初",


                        description=(


                            f"权益变动表\"{col_header}\"列期初 {eq_opening:,.2f} 与"


                            f"附注{col_header}期初合计 {note_opening:,.2f} "


                            f"不一致，差异 {diff:,.2f}"


                        ),


                        difference=diff,


                        statement_amount=eq_opening,


                        note_amount=note_opening,


                        risk_level=self._assess_risk(abs(diff), abs(eq_opening) if eq_opening else 0),


                        reasoning=(


                            f"E-series: 权益变动表.{col_header}.期初({eq_opening:,.2f}) vs "


                            f"附注.{col_header}.期初合计({note_opening:,.2f})"


                        ),


                        note_table_ids=[note_id] if note_id else [],


                    ))





            # 比对期末


            if eq_closing is not None and note_closing is not None:


                if not _amounts_equal(eq_closing, note_closing):


                    diff = round(eq_closing - note_closing, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=col_header,


                        location=f"权益变动表 vs 附注-{col_header}期末",


                        description=(


                            f"权益变动表\"{col_header}\"列期末 {eq_closing:,.2f} 与"


                            f"附注{col_header}期末合计 {note_closing:,.2f} "


                            f"不一致，差异 {diff:,.2f}"


                        ),


                        difference=diff,


                        statement_amount=eq_closing,


                        note_amount=note_closing,


                        risk_level=self._assess_risk(abs(diff), abs(eq_closing) if eq_closing else 0),


                        reasoning=(


                            f"E-series: 权益变动表.{col_header}.期末({eq_closing:,.2f}) vs "


                            f"附注.{col_header}.期末合计({note_closing:,.2f})"


                        ),


                        note_table_ids=[note_id] if note_id else [],


                    ))





        return findings





    def _find_note_opening_closing(self, note_kws, account_notes, table_structures):


        """从附注表格中查找指定科目的期初/期末合计值。





        优先使用 TableStructure 中标注的 opening/closing_balance_cell，


        回退到在合计行中按列语义查找。





        Returns:


            (opening, closing, note_id)


        """


        # 查找匹配的附注表格


        matched_notes = []


        for acct, ns in account_notes.items():


            if any(kw in acct for kw in note_kws):


                matched_notes.extend(ns)





        if not matched_notes:


            return None, None, None





        # 优先找"明细表"或"①"标记的主表


        primary_note = None


        for n in matched_notes:


            title = (n.section_title or "")


            if "明细" in title or "\u2460" in title or "①" in title:


                primary_note = n


                break


        if not primary_note:


            primary_note = matched_notes[0]





        note_id = primary_note.id


        ts = table_structures.get(note_id)





        opening = None


        closing = None





        # 方法1: 使用 TableStructure 的 opening/closing_balance_cell


        if ts:


            if ts.opening_balance_cell:


                opening = self._extract_cell_value(primary_note, ts.opening_balance_cell)


            if ts.closing_balance_cell:


                closing = self._extract_cell_value(primary_note, ts.closing_balance_cell)





        # 方法2: 在合计行中按列语义查找


        if (opening is None or closing is None) and ts and ts.total_row_indices:


            col_semantics = {}


            for col in (ts.columns or []):


                col_semantics[col.col_index] = col.semantic





            for tri in ts.total_row_indices:


                if tri >= len(primary_note.rows or []):


                    continue


                row = primary_note.rows[tri]


                for ci, val in enumerate(row):


                    sem = col_semantics.get(ci, "")


                    v = _safe_float(val)


                    if v is None:


                        continue


                    if opening is None and "opening" in sem:


                        opening = v


                    if closing is None and "closing" in sem:


                        closing = v





        # 方法3: 回退 - 在合计行中先按表头关键词定位，再按位置猜测
        if (opening is None or closing is None) and primary_note.rows:
            total_kws = ["合计", "合 计", "总计", "期末", "期末合计"]
            # 先通过表头关键词确定期末/期初列
            _fb_headers = [str(h or "").replace(" ", "").replace("\u3000", "")
                           for h in (primary_note.headers or [])]
            _fb_closing_col = -1
            _fb_opening_col = -1
            _close_kw = ["期末", "年末", "本期"]
            _open_kw = ["期初", "年初", "上期", "上年"]
            _move_kw = ["增加", "减少", "变动", "转入", "转出", "计提", "处置"]
            for ci, h in enumerate(_fb_headers):
                if ci == 0:
                    continue
                if any(kw in h for kw in _move_kw):
                    continue
                has_open = any(kw in h for kw in _open_kw)
                has_close = any(kw in h for kw in _close_kw) and not has_open
                if has_close and _fb_closing_col < 0:
                    _fb_closing_col = ci
                if has_open and _fb_opening_col < 0:
                    _fb_opening_col = ci

            for row in primary_note.rows:
                if not row:
                    continue
                label = str(row[0] or "").strip()
                if not any(kw in label for kw in total_kws):
                    continue
                # 优先按表头关键词取值
                if closing is None and _fb_closing_col > 0 and _fb_closing_col < len(row):
                    closing = _safe_float(row[_fb_closing_col])
                if opening is None and _fb_opening_col > 0 and _fb_opening_col < len(row):
                    opening = _safe_float(row[_fb_opening_col])
                # 回退：按位置猜测
                if closing is None or opening is None:
                    vals = []
                    for ci in range(1, len(row)):
                        v = _safe_float(row[ci])
                        if v is not None:
                            vals.append((ci, v))
                    if len(vals) >= 2:
                        if closing is None:
                            closing = vals[0][1]
                        if opening is None:
                            opening = vals[1][1]
                    elif len(vals) == 1:
                        if closing is None:
                            closing = vals[0][1]
                break
        # 未分配利润特殊处理：期初取"调整后"行


        if any("未分配利润" in kw for kw in note_kws):


            adj_opening = self._find_undist_adjusted_opening(primary_note)


            if adj_opening is not None:


                opening = adj_opening





        return opening, closing, note_id





    def _find_undist_adjusted_opening(self, note):


        """未分配利润明细表：查找'调整后'期初值。"""


        if not note or not note.rows:


            return None


        adj_kws = ["调整后", "调整后的期初"]


        for row in note.rows:


            if not row:


                continue


            label = str(row[0] or "").strip()


            if any(kw in label for kw in adj_kws):


                for ci in range(1, len(row)):


                    v = _safe_float(row[ci])


                    if v is not None:


                        return v


        return None





    def _extract_cell_value(self, note, cell_ref):


        """从 NoteTable 中按单元格引用提取值。cell_ref 格式如 'R5C2' 或 '(5,2)'。"""


        if not note or not note.rows or not cell_ref:


            return None


        try:


            # 尝试解析 R{row}C{col} 格式


            m = re.match(r'R(\d+)C(\d+)', str(cell_ref), re.IGNORECASE)


            if m:


                ri, ci = int(m.group(1)), int(m.group(2))


                if ri < len(note.rows) and ci < len(note.rows[ri]):


                    return _safe_float(note.rows[ri][ci])


            # 尝试解析 (row, col) 格式


            m2 = re.match(r'\((\d+)\s*,\s*(\d+)\)', str(cell_ref))


            if m2:


                ri, ci = int(m2.group(1)), int(m2.group(2))


                if ri < len(note.rows) and ci < len(note.rows[ri]):


                    return _safe_float(note.rows[ri][ci])


        except (ValueError, IndexError):


            pass


        return None








    # ─── 受限资产交叉披露验证（LLM 辅助）───





    RESTRICTED_ASSET_NOTE_KEYWORDS = [


        "所有权或使用权受到限制",


        "所有权和使用权受到限制",


        "受限资产",


    ]





    async def check_restricted_asset_disclosure(


        self,


        notes: List[NoteTable],


        note_sections: list,


        openai_service,


    ) -> List[ReportReviewFinding]:


        """受限资产表中的每个资产明细，验证对应科目附注中是否有受限相关披露。





        对于受限资产表中有金额的每个资产项目（如"货币资金"、"固定资产"等），


        收集该科目在附注中的所有文字内容，调用 LLM 判断是否有受限/抵押/质押等披露。


        """


        findings: List[ReportReviewFinding] = []





        if not openai_service:


            return findings





        # 1. 找到受限资产附注表格


        restricted_note: Optional[NoteTable] = None


        for n in notes:


            combined = (n.section_title or "") + (n.account_name or "")


            if any(kw in combined for kw in self.RESTRICTED_ASSET_NOTE_KEYWORDS):


                restricted_note = n


                break





        if not restricted_note:


            return findings





        # 2. 提取有金额的受限资产明细行


        restricted_items: List[dict] = []


        skip_labels = {"合计", "小计", "总计", "项目", "项  目", ""}


        for row in restricted_note.rows:


            if not row:


                continue


            label = str(row[0]).strip() if row else ""


            # 跳过合计行、表头行


            if label in skip_labels or "合" in label and "计" in label:


                continue


            # 检查是否有数值


            has_amount = False


            amount_val = None


            for ci in range(1, len(row)):


                val = _safe_float(row[ci])


                if val is not None and abs(val) > 0.01:


                    has_amount = True


                    amount_val = val


                    break


            if has_amount:


                restricted_items.append({


                    "asset_name": label,


                    "amount": amount_val,


                })





        if not restricted_items:


            return findings





        # 3. 为每个受限资产项目收集对应科目的附注文字内容


        # 构建 account_name → 附注文字内容 映射


        def _collect_section_text(nodes: list, target_name: str) -> str:


            """递归搜索 note_sections 树，收集与目标科目相关的文字内容。"""


            texts = []


            for node in nodes:


                title = node.title if hasattr(node, 'title') else ""


                # 科目名称出现在标题中


                if target_name in title:


                    for p in (node.content_paragraphs if hasattr(node, 'content_paragraphs') else []):


                        if p.strip():


                            texts.append(p.strip())


                if hasattr(node, 'children') and node.children:


                    texts.append(_collect_section_text(node.children, target_name))


            return "\n".join(t for t in texts if t)





        # 同时从 note_tables 中收集相关表格的标题信息


        note_account_map: Dict[str, List[str]] = {}


        for n in notes:


            if n == restricted_note:


                continue


            note_account_map.setdefault(n.account_name, []).append(n.section_title or "")





        # 4. 对每个受限资产项目调用 LLM 判断


        import asyncio





        async def _check_one_asset(item: dict) -> Optional[ReportReviewFinding]:


            asset_name = item["asset_name"]


            amount = item["amount"]





            # 收集该科目的附注文字


            section_text = ""


            if note_sections:


                section_text = _collect_section_text(note_sections, asset_name)





            # 收集该科目的附注表格标题


            related_titles = note_account_map.get(asset_name, [])


            # 也尝试模糊匹配


            for acct, titles in note_account_map.items():


                if asset_name in acct or acct in asset_name:


                    related_titles.extend(titles)





            context_parts = []


            if section_text:


                # 截断避免过长


                context_parts.append(f"【{asset_name}附注文字内容】\n{section_text[:3000]}")


            if related_titles:


                context_parts.append(f"【{asset_name}附注表格标题】\n" + "\n".join(set(related_titles)))





            if not context_parts:


                # 没有找到该科目的附注内容，直接报告


                return self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=f"受限资产/{asset_name}",


                    location=f"附注-受限资产-{asset_name}",


                    description=(


                        f"受限资产表中'{asset_name}'有受限金额 {amount:,.2f}，"


                        f"但未找到'{asset_name}'科目的附注内容，无法验证是否有受限披露"


                    ),


                    risk_level=RiskLevel.MEDIUM,


                    reasoning=f"受限资产表列示'{asset_name}'受限金额 {amount:,.2f}，需在对应科目附注中披露",


                    note_table_ids=[restricted_note.id],


                )





            context = "\n\n".join(context_parts)





            prompt = (


                f"受限资产表中列示了'{asset_name}'有受限金额 {amount:,.2f}。\n"


                f"请判断以下'{asset_name}'科目的附注内容中，是否有关于资产受限、抵押、质押、"


                f"冻结、查封、担保等相关的说明或披露。\n\n"


                f"{context}\n\n"


                "请以JSON格式返回判断结果：\n"


                '{"has_disclosure": true/false, "evidence": "找到的相关披露内容摘要（如有）", '


                '"reason": "判断理由"}\n'


                "如果附注中有任何关于该资产受限、抵押、质押、冻结、查封、担保的说明，"


                "has_disclosure 为 true；否则为 false。"


            )





            try:


                messages = [


                    {"role": "system", "content": "你是审计报告附注复核专家，负责验证受限资产的交叉披露完整性。"},


                    {"role": "user", "content": prompt},


                ]


                response = ""


                async for chunk in openai_service.stream_chat_completion(messages, temperature=0.2):


                    if isinstance(chunk, str):


                        response += chunk





                match = re.search(r'\{[\s\S]*\}', response)


                if match:


                    result = json.loads(match.group())


                    if not result.get("has_disclosure", True):


                        reason = result.get("reason", "")


                        return self._make_finding(


                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                            account_name=f"受限资产/{asset_name}",


                            location=f"附注-受限资产-{asset_name} vs 附注-{asset_name}",


                            description=(


                                f"受限资产表中'{asset_name}'有受限金额 {amount:,.2f}，"


                                f"但'{asset_name}'科目附注中未发现受限相关披露。{reason}"


                            ),


                            risk_level=RiskLevel.MEDIUM,


                            reasoning=(


                                f"受限资产表列示'{asset_name}'受限金额 {amount:,.2f}，"


                                f"对应科目附注应有受限/抵押/质押等说明"


                            ),


                            note_table_ids=[restricted_note.id],


                        )


            except Exception as e:


                logger.warning("受限资产交叉披露验证失败 %s: %s", asset_name, e)





            return None





        semaphore = asyncio.Semaphore(3)





        async def _check_with_limit(item: dict):


            async with semaphore:


                return await _check_one_asset(item)





        results = await asyncio.gather(


            *[_check_with_limit(item) for item in restricted_items],


            return_exceptions=True,


        )





        for r in results:


            if isinstance(r, ReportReviewFinding):


                findings.append(r)


            elif isinstance(r, Exception):


                logger.warning("受限资产交叉披露验证异常: %s", r)





        return findings





    # ─── 统计汇总 ───





    def get_reconciliation_summary(


        self, findings: List[ReportReviewFinding]


    ) -> Dict[str, int]:


        """生成匹配/不匹配/未检查统计。"""


        matched = sum(1 for f in findings if f.difference is not None and abs(f.difference) < TOLERANCE)


        not_found = sum(1 for f in findings if self.NOTE_VALUE_NOT_FOUND_TAG in (f.description or ""))


        mismatched = sum(1 for f in findings if f.difference is not None and abs(f.difference) >= TOLERANCE)


        return {


            "matched": matched,


            "mismatched": mismatched,


            "unchecked": not_found,


        }





    # ─── 规则引擎：从附注表格中提取期末/期初合计值（LLM 识别的兜底） ───





    # 变动列关键词（排除这些列，它们不是余额列）


    _MOVEMENT_COL_KW = [


        "增加", "减少", "增减", "转入", "转出", "摊销", "折旧",


        "计提", "处置", "变动", "核销", "转回",


    ]


    # 期末列关键词


    _CLOSING_COL_KW = ["期末", "年末", "本期", "本年"]


    # 期初列关键词


    _OPENING_COL_KW = ["期初", "年初", "上期", "上年"]


    # 账面价值关键词


    _BOOK_VALUE_KW = ["账面价值", "账面净值", "净值"]


    # 原值/成本段关键词


    _COST_SECTION_KW = ["原价", "原值", "账面原值"]


    # 累计摊销/折旧段关键词


    _AMORT_SECTION_KW = ["累计摊销", "累计折旧"]


    # 减值准备段关键词


    _IMPAIR_SECTION_KW = ["减值准备"]





    @staticmethod


    def _is_movement_col(header: str) -> bool:


        """判断表头是否为变动列（本期增加/减少等）。"""


        return any(kw in header for kw in ReconciliationEngine._MOVEMENT_COL_KW)





    @staticmethod


    def _extract_note_totals_by_rules(


        note: NoteTable,


    ) -> Tuple[Optional[float], Optional[float]]:


        """规则引擎：从附注表格中提取期末/期初合计值。





        当 LLM 的 TableStructure 未识别出 closing_balance_cell / opening_balance_cell 时，


        用本方法作为兜底。返回 (closing, opening)。





        策略优先级：


        1. 找"合计"/"总计"行 → 通过表头语义分配期末/期初


        2. 找"期末账面价值"/"期初账面价值"行


        3. 多段表格（原价-累计摊销-减值准备）→ 计算账面价值


        4. 单行表格回退


        """


        if not note.rows:


            return (None, None)





        headers = note.headers or []


        header_rows = getattr(note, "header_rows", None) or []


        # 标准化表头（去空格）


        norm_headers = [str(h or "").replace(" ", "").replace("\u3000", "") for h in headers]





        # ── 策略 1：找"合计"/"总计"行 ──


        # 对于多段变动表（包含原价/累计折旧等段落），表格中有多个"合计"行，


        # 每个段落各有一个。简单取最后一个"合计"行可能取到错误段落的值


        # （如累计折旧合计而非账面价值合计）。此时应跳过策略1，


        # 让策略2（账面价值行）或策略3（段落计算）来处理。


        _has_multi_section = False


        _total_count = 0


        for _row in note.rows:


            _first = str(_row[0] if _row else "").replace(" ", "").replace("\u3000", "").strip()


            if _first in ("合计", "总计"):


                _total_count += 1


            if _SECTION_PATTERN.match(_first) and any(


                kw in _first for kw in (


                    ReconciliationEngine._COST_SECTION_KW


                    + ReconciliationEngine._AMORT_SECTION_KW


                )


            ):


                _has_multi_section = True





        total_row = None


        if not (_has_multi_section and _total_count > 1):


            # 非多段变动表，或只有一个合计行 → 正常取最后一个合计/总计行


            # 当有多个"合计"行时，优先选"总计"行（"总计"通常是全表汇总，


            # "合计"可能是段落小计）


            _last_heji_ri = -1  # 最后一个"合计"行


            _last_zongji_ri = -1  # 最后一个"总计"行


            for ri in range(len(note.rows) - 1, -1, -1):


                first = str(note.rows[ri][0] if note.rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()


                if first == "总计" and _last_zongji_ri < 0:


                    _last_zongji_ri = ri


                if first == "合计" and _last_heji_ri < 0:


                    _last_heji_ri = ri


                if _last_heji_ri >= 0 and _last_zongji_ri >= 0:


                    break


            # 优先"总计"，其次最后一个"合计"


            pick_ri = _last_zongji_ri if _last_zongji_ri >= 0 else _last_heji_ri


            if pick_ri >= 0:


                total_row = note.rows[pick_ri]





        if total_row is not None:


            return ReconciliationEngine._extract_from_total_row(


                total_row, norm_headers, header_rows,


            )





        # ── 策略 2：找"账面价值"行（固定资产/投资性房地产等） ──


        book_result = ReconciliationEngine._extract_book_value_rows(note)


        if book_result != (None, None):


            return book_result





        # ── 策略 3：多段表格（原价-累计摊销-减值准备）→ 计算账面价值 ──


        calc_result = ReconciliationEngine._extract_by_section_calculation(note)


        if calc_result != (None, None):


            return calc_result





        # ── 策略 4：变动表中找"期末余额"/"期末未分配利润"行 ──


        # 未分配利润等科目的附注表格是变动表（期初+增减=期末），


        # 没有"合计"行，但有"期末余额"/"期末未分配利润"行直接包含期末值。


        balance_row_result = ReconciliationEngine._extract_from_balance_label_rows(


            note, norm_headers, header_rows,


        )


        if balance_row_result != (None, None):


            return balance_row_result





        # ── 策略 5：单数据行回退 ──


        # 当表格只有一行含有效数值的数据行时，该行即为合计行


        data_rows = [r for r in note.rows if any(_safe_float(c) is not None for c in r[1:])]


        if len(data_rows) == 1:


            return ReconciliationEngine._extract_from_total_row(


                data_rows[0], norm_headers, header_rows,


            )





        return (None, None)





    @staticmethod


    @staticmethod
    def _extract_from_balance_label_rows(
        note: NoteTable,
        norm_headers: List[str],
        header_rows: List[List[str]],
    ) -> Tuple[Optional[float], Optional[float]]:
        """从变动表中找"期末余额"/"期末未分配利润"/"期初余额"行提取值。

        未分配利润等科目的附注表格是变动表（期初+增减变动=期末），
        没有"合计"行，但有标签行直接包含期末/期初值。

        取值策略：行标签已标明期间（"期末余额"/"期初余额"），
        因此取该行的"合计"列或第一个非空数值即可。
        不应按表头期间关键词选列（"本年金额"列中的"期初余额"行
        才是正确的本年期初值）。
        """
        closing_label_kw = ["期末余额", "期末未分配", "本期期末余额", "年末余额", "期末数", "期末金额", "期末合计"]
        opening_label_kw = ["期初余额", "期初未分配", "本期期初余额", "年初余额", "期初数", "期初金额", "期初合计"]

        # 找"合计"/"总计"列索引（优先取该列的值）
        total_col = -1
        for ci in range(len(norm_headers) - 1, 0, -1):
            h = norm_headers[ci]
            if h in ("合计", "总计"):
                total_col = ci
                break

        closing_val: Optional[float] = None
        opening_val: Optional[float] = None

        for row in note.rows:
            if not row:
                continue
            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()

            is_closing_row = any(kw in first for kw in closing_label_kw)
            is_opening_row = any(kw in first for kw in opening_label_kw)

            if not is_closing_row and not is_opening_row:
                continue

            # 取值：优先合计列，回退第一个非空数值
            val = None
            if total_col > 0 and total_col < len(row):
                val = _safe_float(row[total_col])
            if val is None:
                # 回退：取第一个非空数值（跳过标签列）
                for ci in range(1, len(row)):
                    v = _safe_float(row[ci])
                    if v is not None:
                        val = v
                        break

            if val is not None:
                if is_closing_row and closing_val is None:
                    closing_val = val
                elif is_opening_row and opening_val is None:
                    opening_val = val

        return (closing_val, opening_val)
    @staticmethod


    def _extract_from_total_row(


        total_row: list,


        norm_headers: List[str],


        header_rows: List[List[str]],


    ) -> Tuple[Optional[float], Optional[float]]:


        """从合计行中根据表头语义提取期末/期初值。"""


        # 收集所有数值列


        nums: List[Tuple[int, float]] = []


        for ci in range(1, len(total_row)):


            v = _safe_float(total_row[ci])


            if v is not None:


                nums.append((ci, v))


        if not nums:


            return (None, None)





        is_move = ReconciliationEngine._is_movement_col


        closing_kw = ReconciliationEngine._CLOSING_COL_KW


        opening_kw = ReconciliationEngine._OPENING_COL_KW





        # ── 多行表头：先尝试最后一行表头中的"账面价值"列 ──


        if header_rows and len(header_rows) >= 2:


            last_row_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in header_rows[-1]]


            first_row_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in header_rows[0]]





            def _parent_group_of(col_idx: int) -> str:


                """回溯第一行表头，找到 col_idx 所属的父列标签。





                多行表头中，第一行通常是"期末数 | | | 期初数 | | |"这样的合并单元格，


                空列继承左边最近的非空列标签。


                """


                for ci in range(col_idx, -1, -1):


                    h = first_row_h[ci] if ci < len(first_row_h) else ""


                    if h:


                        return h


                return ""





            def _is_closing_group(col_idx: int) -> bool:


                """判断 col_idx 是否属于"期末"组。"""


                parent = _parent_group_of(col_idx)


                has_close = any(kw in parent for kw in closing_kw)


                has_open = any(kw in parent for kw in opening_kw)


                return has_close and not has_open





            def _is_opening_group(col_idx: int) -> bool:


                """判断 col_idx 是否属于"期初"组。"""


                parent = _parent_group_of(col_idx)


                return any(kw in parent for kw in opening_kw)





            # 在最后一行找"账面价值"列


            bv_cols = [ci for ci, h in enumerate(last_row_h)


                       if any(kw in h for kw in ReconciliationEngine._BOOK_VALUE_KW)]


            if len(bv_cols) >= 2:


                # 根据第一行表头判断哪个是期末、哪个是期初


                closing_bv = None


                opening_bv = None


                for ci in bv_cols:


                    if closing_bv is None and _is_closing_group(ci):


                        closing_bv = ci


                    elif opening_bv is None and _is_opening_group(ci):


                        opening_bv = ci


                # 如果无法通过父列判断，回退到位置顺序（期末在前）


                if closing_bv is None and opening_bv is None:


                    closing_bv, opening_bv = bv_cols[0], bv_cols[1]


                elif closing_bv is None:


                    closing_bv = [ci for ci in bv_cols if ci != opening_bv][0] if len(bv_cols) > 1 else None


                elif opening_bv is None:


                    opening_bv = [ci for ci in bv_cols if ci != closing_bv][0] if len(bv_cols) > 1 else None


                return (_safe_float(total_row[closing_bv]) if closing_bv is not None and closing_bv < len(total_row) else None,


                        _safe_float(total_row[opening_bv]) if opening_bv is not None and opening_bv < len(total_row) else None)


            if len(bv_cols) == 1:


                vci = bv_cols[0]


                parent_label = _parent_group_of(vci)


                val = _safe_float(total_row[vci]) if vci < len(total_row) else None


                if any(kw in parent_label for kw in opening_kw):


                    return (None, val)


                return (val, None)





            # 在最后一行找"账面余额/原值"和"减值准备"列 → 计算


            bal_cols = [ci for ci, h in enumerate(last_row_h)


                        if "账面余额" in h or "原值" in h]


            prov_cols = [ci for ci, h in enumerate(last_row_h)


                         if "减值准备" in h or "坏账准备" in h]


            if len(bal_cols) >= 2 and len(prov_cols) >= 2:


                # 根据第一行表头判断哪组是期末、哪组是期初


                closing_bal_idx = None


                opening_bal_idx = None


                for ci in bal_cols:


                    if closing_bal_idx is None and _is_closing_group(ci):


                        closing_bal_idx = ci


                    elif opening_bal_idx is None and _is_opening_group(ci):


                        opening_bal_idx = ci


                closing_prov_idx = None


                opening_prov_idx = None


                for ci in prov_cols:


                    if closing_prov_idx is None and _is_closing_group(ci):


                        closing_prov_idx = ci


                    elif opening_prov_idx is None and _is_opening_group(ci):


                        opening_prov_idx = ci


                # 回退到位置顺序


                if closing_bal_idx is None and opening_bal_idx is None:


                    closing_bal_idx, opening_bal_idx = bal_cols[0], bal_cols[1]


                elif closing_bal_idx is None:


                    closing_bal_idx = [ci for ci in bal_cols if ci != opening_bal_idx][0] if len(bal_cols) > 1 else None


                elif opening_bal_idx is None:


                    opening_bal_idx = [ci for ci in bal_cols if ci != closing_bal_idx][0] if len(bal_cols) > 1 else None


                if closing_prov_idx is None and opening_prov_idx is None:


                    closing_prov_idx, opening_prov_idx = prov_cols[0], prov_cols[1]


                elif closing_prov_idx is None:


                    closing_prov_idx = [ci for ci in prov_cols if ci != opening_prov_idx][0] if len(prov_cols) > 1 else None


                elif opening_prov_idx is None:


                    opening_prov_idx = [ci for ci in prov_cols if ci != closing_prov_idx][0] if len(prov_cols) > 1 else None





                cb = _safe_float(total_row[closing_bal_idx]) if closing_bal_idx is not None and closing_bal_idx < len(total_row) else None


                cp = _safe_float(total_row[closing_prov_idx]) if closing_prov_idx is not None and closing_prov_idx < len(total_row) else 0


                ob = _safe_float(total_row[opening_bal_idx]) if opening_bal_idx is not None and opening_bal_idx < len(total_row) else None


                op = _safe_float(total_row[opening_prov_idx]) if opening_prov_idx is not None and opening_prov_idx < len(total_row) else 0


                closing = (cb - (cp or 0)) if cb is not None else None


                opening = (ob - (op or 0)) if ob is not None else None


                return (closing, opening)





            # 在最后一行找期末/期初列（排除变动列）


            closing_cols = [ci for ci, h in enumerate(last_row_h)


                            if any(kw in h for kw in closing_kw) and not is_move(h)


                            and not any(kw in h for kw in opening_kw)]


            opening_cols = [ci for ci, h in enumerate(last_row_h)


                            if any(kw in h for kw in opening_kw) and not is_move(h)]


            if closing_cols or opening_cols:


                c_val = _safe_float(total_row[closing_cols[0]]) if closing_cols and closing_cols[0] < len(total_row) else None


                o_val = _safe_float(total_row[opening_cols[0]]) if opening_cols and opening_cols[0] < len(total_row) else None


                return (c_val, o_val)





            # 在第一行找期末/期初父列，取子列范围内第一个非变动数值


            closing_parent = -1


            opening_parent = -1


            for ci, h in enumerate(first_row_h):


                if not h or is_move(h):


                    continue


                has_open = any(kw in h for kw in opening_kw)


                if closing_parent < 0 and any(kw in h for kw in closing_kw) and not has_open:


                    closing_parent = ci


                if opening_parent < 0 and has_open:


                    opening_parent = ci





            def _pick_from_range(start: int, end: int) -> Optional[float]:


                """在列范围内找第一个非变动列的数值。


                优先选择含"账面价值"的列（应收类科目的表头中，


                同一期间组下有"账面余额"、"坏账准备"、"账面价值"三列，


                应取"账面价值"列的值）。


                """


                bv_kw_local = ReconciliationEngine._BOOK_VALUE_KW


                # 先找含"账面价值"的列


                for ci, v in nums:


                    if start <= ci < end:


                        h = last_row_h[ci] if ci < len(last_row_h) else ""


                        if not is_move(h) and any(kw in h for kw in bv_kw_local):


                            return v


                # 回退：取第一个非变动列


                for ci, v in nums:


                    if start <= ci < end:


                        h = last_row_h[ci] if ci < len(last_row_h) else ""


                        if not is_move(h):


                            return v


                return None





            if closing_parent >= 0 or opening_parent >= 0:


                c_val = None


                o_val = None


                if closing_parent >= 0:


                    parent_val = first_row_h[closing_parent]


                    end = len(total_row)


                    for ci in range(closing_parent + 1, len(first_row_h)):


                        h = first_row_h[ci]


                        if h and h != parent_val:


                            end = ci


                            break


                    c_val = _pick_from_range(closing_parent, end)


                if opening_parent >= 0:


                    parent_val = first_row_h[opening_parent]


                    end = len(total_row)


                    for ci in range(opening_parent + 1, len(first_row_h)):


                        h = first_row_h[ci]


                        if h and h != parent_val:


                            end = ci


                            break


                    o_val = _pick_from_range(opening_parent, end)


                if c_val is not None or o_val is not None:


                    return (c_val, o_val)





        # ── 单行表头或多行表头策略都未命中 → 用 norm_headers ──


        # 优先选择含"账面价值"的期末/期初列（应收类科目的合并表头如


        # "期末余额-账面余额"、"期末余额-坏账准备"、"期末余额-账面价值"，


        # 应取"账面价值"列而非"账面余额"列）


        bv_kw = ReconciliationEngine._BOOK_VALUE_KW


        closing_idx = -1


        opening_idx = -1


        closing_bv_idx = -1  # 含"账面价值"的期末列


        opening_bv_idx = -1  # 含"账面价值"的期初列


        for ci, h in enumerate(norm_headers):


            if is_move(h):


                continue


            has_open = any(kw in h for kw in opening_kw)


            has_close = any(kw in h for kw in closing_kw) and not has_open


            has_bv = any(kw in h for kw in bv_kw)


            if has_close:


                if closing_idx < 0:


                    closing_idx = ci


                if has_bv and closing_bv_idx < 0:


                    closing_bv_idx = ci


            if has_open:


                if opening_idx < 0:


                    opening_idx = ci


                if has_bv and opening_bv_idx < 0:


                    opening_bv_idx = ci


        # 优先使用含"账面价值"的列


        if closing_bv_idx >= 0:


            closing_idx = closing_bv_idx


        if opening_bv_idx >= 0:


            opening_idx = opening_bv_idx





        # ── 当表头含"账面余额"+"坏账准备"但无"账面价值"时，计算净值 ──


        # 应收类科目的合并表头可能是 ["项目", "期末余额-账面余额", "期末余额-坏账准备",


        # "期初余额-账面余额", "期初余额-坏账准备"]，没有"账面价值"列。


        # 此时需要计算 账面价值 = 账面余额 - 坏账准备。


        provision_kw = ["坏账准备", "减值准备", "跌价准备"]


        balance_kw_net = ["账面余额", "原值"]


        c_bal_idx, c_prov_idx, o_bal_idx, o_prov_idx = -1, -1, -1, -1


        for ci, h in enumerate(norm_headers):


            has_open = any(kw in h for kw in opening_kw)


            has_close_h = any(kw in h for kw in closing_kw) and not has_open


            has_bal = any(kw in h for kw in balance_kw_net)


            has_prov = any(kw in h for kw in provision_kw)


            if has_close_h and has_bal and c_bal_idx < 0:


                c_bal_idx = ci


            if has_close_h and has_prov and c_prov_idx < 0:


                c_prov_idx = ci


            if has_open and has_bal and o_bal_idx < 0:


                o_bal_idx = ci


            if has_open and has_prov and o_prov_idx < 0:


                o_prov_idx = ci


        # 如果有"账面余额"和"坏账准备"列但没有"账面价值"列，计算净值


        if c_bal_idx >= 0 and c_prov_idx >= 0 and closing_bv_idx < 0:


            cb = _safe_float(total_row[c_bal_idx]) if c_bal_idx < len(total_row) else None


            cp = _safe_float(total_row[c_prov_idx]) if c_prov_idx < len(total_row) else None


            ob = _safe_float(total_row[o_bal_idx]) if o_bal_idx >= 0 and o_bal_idx < len(total_row) else None


            op = _safe_float(total_row[o_prov_idx]) if o_prov_idx >= 0 and o_prov_idx < len(total_row) else None


            c_net = (cb - (cp or 0)) if cb is not None else None


            o_net = (ob - (op or 0)) if ob is not None else None


            if c_net is not None or o_net is not None:


                return (c_net, o_net)


        if closing_idx < 0:


            for ci, h in enumerate(norm_headers):


                if ("本期" in h or "本年" in h) and not is_move(h) and not any(kw in h for kw in opening_kw):


                    closing_idx = ci


                    break


        if opening_idx < 0:


            for ci, h in enumerate(norm_headers):


                if ("上期" in h or "上年" in h) and not is_move(h):


                    opening_idx = ci


                    break





        if closing_idx >= 0 or opening_idx >= 0:


            c_val = _safe_float(total_row[closing_idx]) if closing_idx >= 0 and closing_idx < len(total_row) else None


            o_val = _safe_float(total_row[opening_idx]) if opening_idx >= 0 and opening_idx < len(total_row) else None


            return (c_val, o_val)





        # 最终 fallback：≤2 个数值列时按位置分配


        if len(nums) <= 2:


            return (nums[0][1] if nums else None, nums[1][1] if len(nums) > 1 else None)





        return (None, None)





    @staticmethod


    def _extract_book_value_rows(


        note: NoteTable,


    ) -> Tuple[Optional[float], Optional[float]]:


        """从"期末账面价值"/"期初账面价值"行中提取值。"""


        bv_kw = ReconciliationEngine._BOOK_VALUE_KW


        closing_val = None


        opening_val = None





        # 找"合计"列索引


        total_col = -1


        for ci in range(len(note.headers) - 1, 0, -1):


            h = str(note.headers[ci] or "").replace(" ", "").replace("\u3000", "")


            if h in ("合计", "总计"):


                total_col = ci


                break





        def _pick_row_val(row: list) -> Optional[float]:


            if total_col > 0 and total_col < len(row):


                v = _safe_float(row[total_col])


                if v is not None:


                    return v


            for ci in range(len(row) - 1, 0, -1):


                v = _safe_float(row[ci])


                if v is not None:


                    return v


            return None





        # 策略 A：分别找"期末账面价值"和"期初账面价值"行


        for row in note.rows:


            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()


            if ("期末" in first or "年末" in first) and any(kw in first for kw in bv_kw):


                closing_val = _pick_row_val(row)


            if ("期初" in first or "年初" in first) and any(kw in first for kw in bv_kw):


                opening_val = _pick_row_val(row)





        if closing_val is not None or opening_val is not None:


            return (closing_val, opening_val)





        # 策略 B：在"账面价值"标题行之后找"期末"/"期初"子行


        in_bv_section = False


        for row in note.rows:


            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()


            if any(kw in first for kw in bv_kw) and "期末" not in first and "期初" not in first and "年末" not in first and "年初" not in first:


                in_bv_section = True


                continue


            if in_bv_section:


                if "期末" in first or "年末" in first:


                    closing_val = _pick_row_val(row)


                if "期初" in first or "年初" in first:


                    opening_val = _pick_row_val(row)


                if _SECTION_PATTERN.match(first) and not any(kw in first for kw in bv_kw):


                    break





        if closing_val is not None or opening_val is not None:


            return (closing_val, opening_val)





        # 策略 C（国企报表）：找"X、…账面价值…合计"行，按表头语义提取期末/期初


        # 国企报表中固定资产/无形资产等科目的附注表格，账面价值行的标签形如


        # "五、固定资产账面价值合计"，值在"期初余额"和"期末余额"列中。


        # 优先匹配"账面价值"，其次"账面净值"/"净值"。


        section_pattern = _SECTION_PATTERN


        closing_kw = ReconciliationEngine._CLOSING_COL_KW


        opening_kw = ReconciliationEngine._OPENING_COL_KW


        is_move = ReconciliationEngine._is_movement_col


        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]





        # 预计算表头中的期末/期初列索引


        c_idx = -1


        o_idx = -1


        for ci, h in enumerate(norm_h):


            if is_move(h):


                continue


            has_open = any(kw in h for kw in opening_kw)


            if c_idx < 0 and any(kw in h for kw in closing_kw) and not has_open:


                c_idx = ci


            if o_idx < 0 and has_open:


                o_idx = ci





        if c_idx > 0 or o_idx > 0:


            best_cv, best_ov = None, None


            best_priority = 0  # 1=净值, 2=账面价值


            for row in note.rows:


                first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()


                if not (section_pattern.match(first) and any(kw in first for kw in bv_kw)):


                    continue


                # 判断优先级："账面价值" > "账面净值"/"净值"


                priority = 2 if "账面价值" in first else 1


                if priority <= best_priority:


                    continue


                cv = _safe_float(row[c_idx]) if 0 < c_idx < len(row) else None


                ov = _safe_float(row[o_idx]) if 0 < o_idx < len(row) else None


                if cv is not None or ov is not None:


                    best_cv, best_ov, best_priority = cv, ov, priority


            if best_cv is not None or best_ov is not None:


                return (best_cv, best_ov)





        return (None, None)





    @staticmethod


    def _extract_by_section_calculation(


        note: NoteTable,


    ) -> Tuple[Optional[float], Optional[float]]:


        """多段表格（原价-累计摊销-减值准备）→ 计算账面价值。"""


        section_pattern = _SECTION_PATTERN


        cost_kw = ReconciliationEngine._COST_SECTION_KW


        amort_kw = ReconciliationEngine._AMORT_SECTION_KW


        impair_kw = ReconciliationEngine._IMPAIR_SECTION_KW





        has_cost = False


        has_amort = False


        for row in note.rows:


            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()


            if section_pattern.match(first):


                if any(kw in first for kw in cost_kw):


                    has_cost = True


                if any(kw in first for kw in amort_kw):


                    has_amort = True





        if not (has_cost and has_amort):


            return (None, None)





        # 找"合计"列索引


        total_col = -1


        for ci in range(len(note.headers) - 1, 0, -1):


            h = str(note.headers[ci] or "").replace(" ", "").replace("\u3000", "")


            if h in ("合计", "总计"):


                total_col = ci


                break


        if total_col < 0 and len(note.headers) > 1:


            total_col = len(note.headers) - 1





        if total_col <= 0:


            return (None, None)





        current_section = ""


        section_vals: Dict[str, Dict[str, Optional[float]]] = {}





        # 国企报表：段标题行本身包含数值（如"一、账面原值合计 | XX | XX | XX | XX"），


        # 需要按表头语义（期初余额/期末余额）从段标题行直接提取。


        closing_kw = ReconciliationEngine._CLOSING_COL_KW


        opening_kw = ReconciliationEngine._OPENING_COL_KW


        is_move = ReconciliationEngine._is_movement_col


        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]


        # 预计算表头中的期末/期初列索引（排除变动列）


        hdr_closing_idx = -1


        hdr_opening_idx = -1


        for ci, h in enumerate(norm_h):


            if is_move(h):


                continue


            has_open = any(kw in h for kw in opening_kw)


            if hdr_closing_idx < 0 and any(kw in h for kw in closing_kw) and not has_open:


                hdr_closing_idx = ci


            if hdr_opening_idx < 0 and has_open:


                hdr_opening_idx = ci





        for row in note.rows:


            first = str(row[0] if row else "").replace(" ", "").replace("\u3000", "").strip()


            if section_pattern.match(first):


                if any(kw in first for kw in cost_kw):


                    current_section = "cost"


                elif any(kw in first for kw in amort_kw):


                    current_section = "amort"


                elif any(kw in first for kw in impair_kw):


                    current_section = "impair"


                else:


                    current_section = ""


                # 国企报表：段标题行本身可能包含数值，按表头语义提取


                if current_section and (hdr_closing_idx > 0 or hdr_opening_idx > 0):


                    if hdr_closing_idx > 0 and hdr_closing_idx < len(row):


                        v = _safe_float(row[hdr_closing_idx])


                        if v is not None:


                            section_vals.setdefault(current_section, {})["closing"] = v


                    if hdr_opening_idx > 0 and hdr_opening_idx < len(row):


                        v = _safe_float(row[hdr_opening_idx])


                        if v is not None:


                            section_vals.setdefault(current_section, {})["opening"] = v


                continue


            if not current_section:


                continue


            if "期末" in first or "年末" in first:


                v = _safe_float(row[total_col]) if total_col < len(row) else None


                if v is not None:


                    section_vals.setdefault(current_section, {})["closing"] = v


            if "期初" in first or "年初" in first:


                v = _safe_float(row[total_col]) if total_col < len(row) else None


                if v is not None:


                    section_vals.setdefault(current_section, {})["opening"] = v





        cost_v = section_vals.get("cost", {})


        amort_v = section_vals.get("amort", {})


        impair_v = section_vals.get("impair", {})





        closing_bv = None


        opening_bv = None


        if cost_v.get("closing") is not None:


            closing_bv = cost_v["closing"] - (amort_v.get("closing") or 0) - (impair_v.get("closing") or 0)


        if cost_v.get("opening") is not None:


            opening_bv = cost_v["opening"] - (amort_v.get("opening") or 0) - (impair_v.get("opening") or 0)





        if closing_bv is not None or opening_bv is not None:


            return (closing_bv, opening_bv)





        return (None, None)





    # ─── 营业收入/营业成本合并表格专用提取 ───





    # 识别"营业收入、营业成本"合并表格的关键词


    _REVENUE_COST_TABLE_KW = ["营业收入", "营业成本"]


    _REVENUE_ACCOUNT_KW = ["营业收入", "收入"]


    _COST_ACCOUNT_KW_INCOME = ["营业成本", "成本"]





    @staticmethod


    def _is_revenue_cost_combined_table(note: NoteTable) -> bool:


        """判断附注表格是否为"营业收入、营业成本"合并表格。





        这类表格的特征：section_title 或 account_name 同时包含"营业收入"和"营业成本"，


        且表头中有"收入"和"成本"子列。


        """


        combined = (note.section_title or "") + (note.account_name or "")


        has_revenue = "营业收入" in combined


        has_cost = "营业成本" in combined


        if not (has_revenue and has_cost):


            return False


        # 检查表头中是否有"收入"和"成本"子列


        all_headers = []


        for h in (note.headers or []):


            all_headers.append(str(h or "").replace(" ", "").replace("\u3000", ""))


        for row in (getattr(note, "header_rows", None) or []):


            for h in row:


                all_headers.append(str(h or "").replace(" ", "").replace("\u3000", ""))


        header_text = " ".join(all_headers)


        return "收入" in header_text and "成本" in header_text





    @staticmethod


    def _extract_revenue_cost_from_combined_table(


        note: NoteTable,


        account_name: str,


    ) -> Tuple[Optional[float], Optional[float]]:


        """从"营业收入、营业成本按行业划分"合并表格中，按科目名称提取对应列的合计值。





        表格结构（多行表头）：


        Row0: [项目, 本期发生额, (merged), 上期发生额, (merged)]


        Row1: [项目, 收入, 成本, 收入, 成本]


        ...


        合计: [合计, 本期收入合计, 本期成本合计, 上期收入合计, 上期成本合计]





        对于"营业收入"：closing = 本期收入列, opening = 上期收入列


        对于"营业成本"：closing = 本期成本列, opening = 上期成本列





        返回 (closing, opening)。


        """


        if not note.rows:


            return (None, None)





        # 判断要提取的是"收入"还是"成本"


        clean_name = ReconciliationEngine._strip_parenthetical(account_name)


        want_cost = "成本" in clean_name





        # 找合计行


        total_row = None


        for ri in range(len(note.rows) - 1, -1, -1):


            first = str(note.rows[ri][0] if note.rows[ri] else "").replace(" ", "").replace("\u3000", "").strip()


            if first in ("合计", "总计"):


                total_row = note.rows[ri]


                break


        if total_row is None:


            return (None, None)





        # 从多行表头或合并表头中定位"收入"和"成本"列


        header_rows = getattr(note, "header_rows", None) or []


        norm_headers = [str(h or "").replace(" ", "").replace("\u3000", "") for h in (note.headers or [])]





        # 策略：在最后一行表头中找"收入"和"成本"列


        last_row_h = norm_headers


        if header_rows and len(header_rows) >= 2:


            last_row_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in header_rows[-1]]





        revenue_cols: List[int] = []


        cost_cols: List[int] = []


        for ci, h in enumerate(last_row_h):


            if ci == 0:


                continue  # 跳过标签列


            if "成本" in h:


                cost_cols.append(ci)


            elif "收入" in h:


                revenue_cols.append(ci)





        if not revenue_cols and not cost_cols:


            return (None, None)





        target_cols = cost_cols if want_cost else revenue_cols


        if not target_cols:


            return (None, None)





        # 多行表头时，通过父列（第一行）区分"本期"和"上期"


        first_row_h = []


        if header_rows and len(header_rows) >= 2:


            first_row_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in header_rows[0]]





        closing_col = None


        opening_col = None





        closing_kw = ReconciliationEngine._CLOSING_COL_KW


        opening_kw = ReconciliationEngine._OPENING_COL_KW





        if first_row_h:


            # 为每个目标列找其父列标签


            for ci in target_cols:


                parent = ""


                for pi in range(ci, -1, -1):


                    if pi < len(first_row_h) and first_row_h[pi]:


                        parent = first_row_h[pi]


                        break


                is_opening = any(kw in parent for kw in opening_kw)


                is_closing = any(kw in parent for kw in closing_kw)


                if is_opening and opening_col is None:


                    opening_col = ci


                elif is_closing and closing_col is None:


                    closing_col = ci


                elif closing_col is None:


                    closing_col = ci  # 默认第一个为本期


                elif opening_col is None:


                    opening_col = ci  # 第二个为上期


        else:


            # 单行表头：按位置分配（第一个=本期，第二个=上期）


            if len(target_cols) >= 2:


                closing_col = target_cols[0]


                opening_col = target_cols[1]


            elif len(target_cols) == 1:


                closing_col = target_cols[0]





        closing_val = None


        opening_val = None


        if closing_col is not None and closing_col < len(total_row):


            closing_val = _safe_float(total_row[closing_col])


        if opening_col is not None and opening_col < len(total_row):


            opening_val = _safe_float(total_row[opening_col])





        return (closing_val, opening_val)





    # ─── 内部工具 ───





    @staticmethod


    def _strip_parenthetical(name: str) -> str:


        """去掉科目名称中的括号说明文字，如 '资产处置收益(损失以"-"号填列）' → '资产处置收益'。"""


        return _PARENTHETICAL_PATTERN.sub('', name).strip()





    @staticmethod


    def _match_score(name1: str, name2: str) -> float:


        """科目名称匹配评分（精确优先）。"""


        if not name1 or not name2:


            return 0.0


        # 先去掉括号说明文字，避免共同的括号内容（如"损失以号填列"）抬高分数


        name1 = ReconciliationEngine._strip_parenthetical(name1)


        name2 = ReconciliationEngine._strip_parenthetical(name2)


        if not name1 or not name2:


            return 0.0


        if name1 == name2:


            return 1.0


        # 包含匹配：较短名称被较长名称完全包含


        if name1 in name2 or name2 in name1:


            shorter, longer = (name1, name2) if len(name1) <= len(name2) else (name2, name1)


            ratio = len(shorter) / len(longer)


            # shorter 不是 longer 的前缀 → longer 有额外前缀，通常是不同科目


            # 如"营业收入" in "营业外收入"，shorter 不是前缀 → 不同科目


            if not longer.startswith(shorter):


                return ratio * 0.5


            # 前缀包含：shorter 是 longer 的前缀（如"应收账款" → "应收账款——账龄"）


            # 短名称（≤2字）区分度低（如"其他" in "其他收益"），要求 ratio ≥ 0.8


            # 较长名称（>2字）前缀包含是强信号，保证 ≥ 0.5


            if len(shorter) <= 2:


                if ratio < 0.8:


                    return ratio * 0.8


            return max(0.5, ratio)


        # Jaccard — 仅作为兜底参考，上限 0.49 确保不会单独触发匹配


        # （只有精确匹配和前缀包含匹配才能达到 0.5 阈值）


        s1, s2 = set(name1), set(name2)


        inter = s1 & s2


        union = s1 | s2


        jaccard = len(inter) / len(union) if union else 0.0


        return min(jaccard, 0.49)





    @staticmethod


    def _get_cell_value(note: NoteTable, cell_ref: Optional[str]) -> Optional[float]:


        """从 RxCy 格式引用获取单元格值。"""


        if not cell_ref:


            return None


        try:


            parts = cell_ref.upper().replace("R", "").split("C")


            row_idx = int(parts[0])


            col_idx = int(parts[1])


            if row_idx < len(note.rows) and col_idx < len(note.rows[row_idx]):


                return _safe_float(note.rows[row_idx][col_idx])


        except (ValueError, IndexError):


            pass


        return None





    @staticmethod


    def _get_row_col_value(note: NoteTable, row_idx: int, col_idx: int) -> Optional[float]:


        """获取指定行列的浮点值。"""


        try:


            if row_idx < len(note.rows) and col_idx < len(note.rows[row_idx]):


                return _safe_float(note.rows[row_idx][col_idx])


        except (IndexError, TypeError):


            pass


        return None





    def _get_data_rows_for_total(


        self, ts: TableStructure, total_idx: int


    ) -> List[int]:


        """获取某合计行对应的数据行索引。





        策略：


        - 如果 total 行与前一个 total/subtotal 之间存在 subtotal 行，


          说明该 total 是对 subtotal 行的汇总，此时只收集 subtotal 行。


        - 否则只收集 data 行（排除 sub_item，避免重复计算）。


        """


        # 找到当前 total 行之前最近的 total 行索引作为起始边界


        prev_boundary = -1


        for r in ts.rows:


            if r.row_index >= total_idx:


                break


            if r.role == "total":


                prev_boundary = r.row_index





        # 检查区间内是否有 subtotal 行


        subtotal_rows = []


        data_rows = []


        for r in ts.rows:


            if r.row_index >= total_idx:


                break


            if r.row_index <= prev_boundary:


                continue


            if r.role == "subtotal":


                subtotal_rows.append(r.row_index)


            elif r.role == "data":


                data_rows.append(r.row_index)





        # 如果有 subtotal 行，total 应该是对 subtotal 的汇总


        if subtotal_rows:


            return subtotal_rows


        return data_rows











    # ─── 三阶段ECL表校验（F8-8/8a, F14-4/4a, F15-7/7a）───





    # ECL表列头关键词


    _ECL_STAGE_COL_KW = {


        "stage1": ["第一阶段", "阶段一", "12个月", "未来12个月"],


        "stage2": ["第二阶段", "阶段二", "整个存续期.*未发生", "整个存续期（未"],


        "stage3": ["第三阶段", "阶段三", "整个存续期.*已发生", "整个存续期（已", "已发生信用减值"],


        "total": ["合计", "合 计", "总计"],


    }





    # ECL表行标签关键词（用于识别期初/期末行）


    _ECL_OPENING_ROW_KW = ["期初余额", "年初余额", "期初"]


    _ECL_CLOSING_ROW_KW = ["期末余额", "年末余额", "期末"]





    # ECL表科目关键词（用于识别是否为ECL表）


    _ECL_TABLE_ACCOUNT_KW = [


        "坏账准备", "减值准备", "跌价准备",


    ]


    _ECL_TABLE_TITLE_KW = [


        "三阶段", "ECL", "预期信用损失",


        "计提情况", "变动情况",


    ]





    def check_ecl_three_stage_table(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> list:


        """三阶段ECL表校验：转置结构（行=变动项目，列=阶段）。





        校验内容：


        1. 横向：每行的第一阶段 + 第二阶段 + 第三阶段 = 合计列


        2. 纵向：每列的期初 + 变动项 = 期末





        适用于：应收账款/其他应收款/应收利息/债权投资/其他债权投资等科目的


        坏账准备/减值准备变动表（三阶段ECL模型）。


        """


        findings = []





        if not note_table or not note_table.rows or not note_table.headers:


            return findings





        # 1. 判断是否为三阶段ECL表


        if not self._is_ecl_three_stage_table(note_table):


            return findings





        headers = note_table.headers


        rows = note_table.rows





        # 2. 识别列映射：stage1, stage2, stage3, total


        col_map = self._identify_ecl_columns(headers)


        if not col_map.get("total"):


            return findings  # 至少需要合计列





        stage_cols = []


        for key in ["stage1", "stage2", "stage3"]:


            if key in col_map:


                stage_cols.append(col_map[key])





        if len(stage_cols) < 2:


            return findings  # 至少需要2个阶段列才有意义





        total_col = col_map["total"]





        # 3. 横向校验：每行的各阶段之和 = 合计列


        for ri, row in enumerate(rows):


            if not row:


                continue


            label = str(row[0] or "").strip()


            if not label:


                continue


            # 跳过表头行和空行


            if any(kw in label for kw in ["项目", "项 目", "项　目"]):


                continue





            total_val = _safe_float(row[total_col]) if total_col < len(row) else None


            if total_val is None:


                continue





            stage_sum = 0.0


            all_none = True


            for sc in stage_cols:


                if sc < len(row):


                    v = _safe_float(row[sc])


                    if v is not None:


                        stage_sum += v


                        all_none = False





            if all_none:


                continue





            if not _amounts_equal(stage_sum, total_val):


                diff = round(stage_sum - total_val, 2)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name=note_table.account_name or "",


                    location=f"三阶段ECL表横向校验-'{label}'行",


                    description=(


                        f"三阶段ECL表'{label}'行：各阶段之和 {stage_sum:,.2f} "


                        f"≠ 合计列 {total_val:,.2f}，差异 {diff:,.2f}"


                    ),


                    difference=diff,


                    statement_amount=stage_sum,


                    note_amount=total_val,


                    risk_level=self._assess_risk(abs(diff), abs(total_val)),


                    reasoning=(


                        f"ECL横向: {label}: 阶段和({stage_sum:,.2f}) vs "


                        f"合计({total_val:,.2f})"


                    ),


                    note_table_ids=[note_table.id],


                ))





        # 4. 纵向校验：每列的期初 + 变动项 = 期末


        all_stage_and_total = stage_cols + [total_col]


        for col_idx in all_stage_and_total:


            col_name = headers[col_idx] if col_idx < len(headers) else f"列{col_idx}"


            findings.extend(


                self._check_ecl_column_movement(note_table, rows, col_idx, col_name)


            )





        return findings





    def _is_ecl_three_stage_table(self, note):


        """判断是否为三阶段ECL表。"""


        headers = note.headers or []


        acct = note.account_name or ""


        title = note.section_title or ""


        combined = acct + title





        # 条件1：科目或标题含ECL相关关键词


        has_ecl_context = any(kw in combined for kw in self._ECL_TABLE_ACCOUNT_KW)


        has_ecl_title = any(kw in combined for kw in self._ECL_TABLE_TITLE_KW)





        if not has_ecl_context and not has_ecl_title:


            return False





        # 条件2：列头中至少有2个阶段关键词


        header_text = " ".join(str(h or "") for h in headers)


        stage_count = 0


        for key in ["stage1", "stage2", "stage3"]:


            for kw in self._ECL_STAGE_COL_KW[key]:


                if kw in header_text:


                    stage_count += 1


                    break


        return stage_count >= 2





    def _identify_ecl_columns(self, headers):


        """识别ECL表的阶段列和合计列。"""


        col_map = {}


        for ci, hdr in enumerate(headers):


            if ci == 0:


                continue


            hdr_str = str(hdr or "").strip()


            if not hdr_str:


                continue


            for key, kws in self._ECL_STAGE_COL_KW.items():


                if key in col_map:


                    continue


                for kw in kws:


                    if kw in hdr_str:


                        col_map[key] = ci


                        break


        return col_map





    def _check_ecl_column_movement(self, note, rows, col_idx, col_name):


        """纵向校验单列：期初 + 变动项 = 期末。"""


        findings = []





        opening_val = None


        closing_val = None


        movement_sum = 0.0


        has_movement = False





        for ri, row in enumerate(rows):


            if not row or col_idx >= len(row):


                continue


            label = str(row[0] or "").strip()


            if not label:


                continue


            val = _safe_float(row[col_idx])





            # 识别期初行


            if any(kw in label for kw in self._ECL_OPENING_ROW_KW):


                if val is not None:


                    opening_val = val


                continue





            # 识别期末行


            if any(kw in label for kw in self._ECL_CLOSING_ROW_KW):


                if val is not None:


                    closing_val = val


                continue





            # 跳过表头/标题行


            if any(kw in label for kw in ["项目", "项 目", "项　目"]):


                continue





            # 其余行视为变动项


            if val is not None:


                movement_sum += val


                has_movement = True





        if opening_val is None or closing_val is None:


            return findings





        if not has_movement and abs(opening_val - closing_val) < TOLERANCE:


            return findings  # 无变动且期初=期末，跳过





        expected_closing = round(opening_val + movement_sum, 2)


        if not _amounts_equal(expected_closing, closing_val):


            diff = round(expected_closing - closing_val, 2)


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name=note.account_name or "",


                location=f"三阶段ECL表纵向校验-'{col_name}'列",


                description=(


                    f"三阶段ECL表'{col_name}'列：期初 {opening_val:,.2f} + "


                    f"变动合计 {movement_sum:,.2f} = {expected_closing:,.2f} "


                    f"≠ 期末 {closing_val:,.2f}，差异 {diff:,.2f}"


                ),


                difference=diff,


                statement_amount=expected_closing,


                note_amount=closing_val,


                risk_level=self._assess_risk(abs(diff), abs(closing_val)),


                reasoning=(


                    f"ECL纵向: {col_name}: 期初({opening_val:,.2f}) + "


                    f"变动({movement_sum:,.2f}) = {expected_closing:,.2f} vs "


                    f"期末({closing_val:,.2f})"


                ),


                note_table_ids=[note.id],


            ))





        return findings











    # ─── Step 2: 纵向勾稽（账面余额 - 坏账/减值准备 = 账面价值） ───





    _GROSS_COL_KW = ["账面余额", "原值", "原价"]


    _PROVISION_COL_KW = ["坏账准备", "减值准备", "跌价准备", "累计摊销", "累计折旧"]


    _NET_COL_KW = ["账面价值", "账面净值", "净值", "净额"]


    _BV_PERIOD_CLOSE = ["期末", "年末"]


    _BV_PERIOD_OPEN = ["期初", "年初", "上年"]





    def check_book_value_formula(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> List[ReportReviewFinding]:


        """纵向勾稽：账面余额 - 扣减项(累计折旧/摊销 + 减值准备等) = 账面价值。





        自动识别表头中的列组（毛额、一个或多个扣减列、净额），按期末/期初分别校验。


        支持多扣减列场景：如固定资产表头同时有"累计折旧"和"减值准备"两列时，


        公式为 原值 - 累计折旧 - 减值准备 = 账面价值。


        """


        findings: List[ReportReviewFinding] = []


        if self._should_skip_integrity(note_table):


            return findings


        headers = note_table.headers or []


        if len(headers) < 3:


            return findings


        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in headers]





        # 按期间分组查找列：(gross_col, [prov_cols], net_col)


        col_groups = []  # [(gross, [prov_col1, ...], net, period_label)]





        def _find_col(keywords, period_kw=None, exclude_indices=None):


            for ci, h in enumerate(norm_h):


                if exclude_indices and ci in exclude_indices:


                    continue


                if any(kw in h for kw in keywords):


                    if period_kw is None or any(pk in h for pk in period_kw):


                        return ci


            return None





        def _find_all_cols(keywords, period_kw=None, exclude_indices=None):


            """查找所有匹配的列索引（支持多扣减列）。"""


            result = []


            for ci, h in enumerate(norm_h):


                if exclude_indices and ci in exclude_indices:


                    continue


                if any(kw in h for kw in keywords):


                    if period_kw is None or any(pk in h for pk in period_kw):


                        result.append(ci)


            return result





        # 尝试按期末/期初分组


        for period_kw, period_label in [(self._BV_PERIOD_CLOSE, "期末"), (self._BV_PERIOD_OPEN, "期初")]:


            g = _find_col(self._GROSS_COL_KW, period_kw)


            prov_cols = _find_all_cols(self._PROVISION_COL_KW, period_kw)


            n = _find_col(self._NET_COL_KW, period_kw)


            if g is not None and prov_cols and n is not None:


                col_groups.append((g, prov_cols, n, period_label))





        # 如果按期间没找到，尝试不区分期间（表格只有一组列）


        if not col_groups:


            g = _find_col(self._GROSS_COL_KW)


            prov_cols = _find_all_cols(self._PROVISION_COL_KW)


            n = _find_col(self._NET_COL_KW)


            if g is not None and prov_cols and n is not None:


                col_groups.append((g, prov_cols, n, ""))





        if not col_groups:


            return findings





        for gross_col, prov_cols, net_col, period_label in col_groups:


            for row_s in table_structure.rows:


                if row_s.role == "header":


                    continue


                gross_v = self._get_row_col_value(note_table, row_s.row_index, gross_col)


                net_v = self._get_row_col_value(note_table, row_s.row_index, net_col)


                if gross_v is None or net_v is None:


                    continue





                # 累加所有扣减列


                total_prov = 0.0


                all_prov_none = True


                prov_details = []


                for pc in prov_cols:


                    pv = self._get_row_col_value(note_table, row_s.row_index, pc)


                    if pv is not None:


                        total_prov += pv


                        all_prov_none = False


                        prov_details.append(f"{pv:,.2f}")


                    else:


                        prov_details.append("N/A")





                if all_prov_none:


                    continue





                expected = gross_v - total_prov


                if not _amounts_equal(expected, net_v):


                    diff = round(net_v - expected, 2)


                    label = (row_s.label or "").strip()


                    p_str = f"（{period_label}）" if period_label else ""


                    # 构建扣减描述


                    if len(prov_cols) == 1:


                        prov_desc = f"准备{total_prov:,.2f}"


                        reasoning_calc = f"{gross_v} - {total_prov} = {expected}"


                    else:


                        prov_parts = " - ".join(prov_details)


                        prov_desc = f"扣减项合计{total_prov:,.2f}（{prov_parts}）"


                        reasoning_calc = f"{gross_v} - ({' + '.join(prov_details)}) = {expected}"


                    hl_cells = [


                        {"row": row_s.row_index, "col": gross_col},


                    ] + [


                        {"row": row_s.row_index, "col": pc} for pc in prov_cols


                    ] + [


                        {"row": row_s.row_index, "col": net_col},


                    ]


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=note_table.account_name,


                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{row_s.row_index+1}行'{label}'{p_str}",


                        description=f"纵向勾稽不平{p_str}：账面余额{gross_v:,.2f} - {prov_desc} = {expected:,.2f}，但账面价值为{net_v:,.2f}，差异{diff:,.2f}",


                        risk_level=RiskLevel.MEDIUM,


                        statement_amount=expected, note_amount=net_v, difference=diff,


                        reasoning=f"纵向: {reasoning_calc}, 实际 {net_v}",


                        note_table_ids=[note_table.id],


                        highlight_cells=hl_cells,


                    ))


        return findings





    # ─── Step 3: 完整性校验 ───





    # 完整性校验模式：(标题关键词, 金额列关键词, 必填文本列关键词列表)


    # 匹配规则：标题包含任一标题关键词 → 找金额列 → 金额非零时检查文本列是否为空


    _COMPLETENESS_PATTERNS = [


        # ── 坏账/减值相关 ──


        # 单项计提表（应收票据F4-14、应收账款F5-14、其他应收款F8-13、合同资产F10-9a、债权投资F14-10a等）


        (["单项计提", "按单项"], ["账面余额", "余额"],


         ["名称", "债务人", "承兑人", "坏账准备", "计提理由", "预期信用损失率", "计提依据"]),


        # 核销表（应收票据F4-29、应收账款F5-33、其他应收款F8-30）


        (["实际核销", "本期核销"], ["核销金额", "核销"],


         ["名称", "单位", "性质", "核销原因", "核销程序", "关联交易"]),


        # 收回或转回坏账准备（应收票据F4-27、应收账款F5-31、其他应收款F8-28）


        (["收回或转回", "转回的坏账"], ["转回金额", "收回金额", "转回或收回", "金额"],


         ["名称", "债务人", "承兑人", "原因", "方式"]),


        # 在建工程减值准备计提（国企版F22-5a）


        (["减值准备计提", "本期计提减值"], ["计提金额", "本期计提"],


         ["计提原因"]),





        # ── 逾期/账龄相关 ──


        # 逾期利息表（F8-39）


        (["逾期利息", "重要逾期"], ["期末余额", "余额"],


         ["借款单位", "逾期时间", "逾期原因", "是否发生减值"]),


        # 账龄超过1年的大额预付/应付/合同负债（F7-9、F36-3a、F37-3a、F38-5a、F41-8a）


        (["账龄超过1年", "账龄超过一年"], ["期末余额", "余额", "账面余额"],


         ["单位", "债务人", "账龄", "原因", "未结算", "未偿还", "未结转"]),





        # ── 固定资产/在建工程相关 ──


        # 固定资产清理（F21-7b）


        (["固定资产清理"], ["账面价值", "期末"],


         ["原因", "转入清理"]),


        # 未办妥产权证书（固定资产F21-10a、投资性房地产F20-7a）


        (["未办妥产权证书"], ["账面价值"],


         ["原因"]),


        # 在建工程项目变动（F22-10a）


        (["重要在建工程", "在建工程项目变动", "在建工程项目本期变动"], ["期末余额", "期末"],


         ["预算", "工程进度", "资金来源"]),





        # ── 债券/借款相关 ──


        # 应付债券增减变动（F46-5a）


        (["应付债券增减", "应付债券变动", "一年内到期的应付债券"], ["期末余额", "期末"],


         ["面值", "发行日期", "债券期限", "发行金额"]),


        # 重要的债权投资（F14-7a）


        (["重要的债权投资", "期末重要的债权"], ["面值"],


         ["债权项目", "票面利率", "实际利率", "到期日"]),


        # 长期借款利率区间（F45-3，上市版特有：期末/期初各有利率列）


        (["长期借款"], ["期末余额", "余额"],


         ["利率"]),





        # ── 上市版特有：形成原因列 ──


        # 专项应付款形成原因（上市版F48-7a）


        (["专项应付款"], ["期末余额", "期末"],


         ["形成原因"]),


        # 预计负债形成原因（上市版F50-3a）


        (["预计负债"], ["期末余额", "期末"],


         ["形成原因"]),


        # 递延收益形成原因（上市版F51-4a）


        (["递延收益"], ["期末余额", "期末"],


         ["形成原因"]),





        # ── 其他 ──


        # 应收股利（F8-45）


        (["应收股利"], ["期末余额", "余额"],


         ["未收回的原因", "是否发生减值"]),


        # 政府补助（F51-7a）


        (["政府补助"], ["期末余额", "期初余额", "余额"],


         ["与资产相关", "与收益相关"]),


    ]





    def check_data_completeness(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> List[ReportReviewFinding]:


        """完整性校验：当金额列 != 0 时，关键文本列不应为空。"""


        findings: List[ReportReviewFinding] = []


        if self._should_skip_integrity(note_table):


            return findings


        headers = note_table.headers or []


        if len(headers) < 3:


            return findings





        title = (note_table.section_title or "") + (note_table.account_name or "")


        norm_h = [str(h or "").replace(" ", "").replace("\u3000", "") for h in headers]





        matched_pattern = None


        for title_kws, amt_kws, text_kws in self._COMPLETENESS_PATTERNS:


            if any(kw in title for kw in title_kws):


                matched_pattern = (amt_kws, text_kws)


                break


        if matched_pattern is None:


            return findings





        amt_kws, text_kws = matched_pattern





        # 找金额列


        amt_col = None


        for ci, h in enumerate(norm_h):


            if any(kw in h for kw in amt_kws):


                amt_col = ci


                break


        if amt_col is None:


            return findings





        # 找必填文本列


        text_cols = []  # [(col_index, header_name)]


        for ci, h in enumerate(norm_h):


            if ci == amt_col:


                continue


            if any(kw in h for kw in text_kws):


                text_cols.append((ci, headers[ci]))


        if not text_cols:


            return findings





        # 逐行检查


        empty_cells = []  # [(row_index, label, col_index, col_name)]


        for row_s in table_structure.rows:


            if row_s.role in ("total", "subtotal", "header"):


                continue


            amt_v = self._get_row_col_value(note_table, row_s.row_index, amt_col)


            if amt_v is None or abs(amt_v) < 0.01:


                continue


            label = (row_s.label or "").strip()


            for tc_idx, tc_name in text_cols:


                if row_s.row_index < len(note_table.rows):


                    row_data = note_table.rows[row_s.row_index]


                    if tc_idx < len(row_data):


                        cell_val = row_data[tc_idx]


                        if cell_val is None or str(cell_val).strip() in ("", "—", "-", "－"):


                            empty_cells.append((row_s.row_index, label, tc_idx, str(tc_name)))





        if not empty_cells:


            return findings





        # 合并同行的空列，生成一条 finding


        from collections import defaultdict


        row_empties = defaultdict(list)


        for ri, label, ci, cname in empty_cells:


            row_empties[(ri, label)].append((ci, cname))





        for (ri, label), cols in row_empties.items():


            col_names = "、".join(c[1] for c in cols)


            findings.append(self._make_finding(


                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                account_name=note_table.account_name,


                location=f"附注-{note_table.account_name}-{note_table.section_title}-第{ri+1}行'{label}'",


                description=f"完整性校验：该行金额非零但以下列为空：{col_names}",


                risk_level=RiskLevel.LOW,


                reasoning=f"金额列有值但文本列为空: {col_names}",


                note_table_ids=[note_table.id],


                highlight_cells=[{"row": ri, "col": c[0]} for c in cols],


            ))





        return findings





    # 风险评估阈值（可按审计场景调整）
    RISK_RATIO_HIGH = 0.05      # 差异占比 > 5% → HIGH
    RISK_RATIO_MEDIUM = 0.01    # 差异占比 > 1% → MEDIUM
    RISK_ABS_HIGH = 10000       # 绝对差异 > 10000 → HIGH
    RISK_ABS_MEDIUM = 100       # 绝对差异 > 100 → MEDIUM

    @staticmethod
    def _assess_risk(abs_diff: float, base_amount: Optional[float]) -> RiskLevel:
        """基于差异金额评估风险等级。"""
        if base_amount and abs(base_amount) > 0:
            ratio = abs_diff / abs(base_amount)
            if ratio > ReconciliationEngine.RISK_RATIO_HIGH:
                return RiskLevel.HIGH
            elif ratio > ReconciliationEngine.RISK_RATIO_MEDIUM:
                return RiskLevel.MEDIUM
        if abs_diff > ReconciliationEngine.RISK_ABS_HIGH:
            return RiskLevel.HIGH
        elif abs_diff > ReconciliationEngine.RISK_ABS_MEDIUM:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
    # ─── 账龄衔接校验 ───





    # 账龄段关键词（按从短到长排序），用于识别账龄行并确定顺序


    _AGING_BRACKET_PATTERNS = [


        # (正则, 排序权重) — 权重越小越靠前


        (re.compile(r'1年以内|1\s*年以内|一年以内'), 1),


        (re.compile(r'1[至到\-—~～]2年|1\s*-\s*2\s*年|一至二年'), 2),


        (re.compile(r'2[至到\-—~～]3年|2\s*-\s*3\s*年|二至三年'), 3),


        (re.compile(r'3[至到\-—~～]4年|3\s*-\s*4\s*年|三至四年'), 4),


        (re.compile(r'4[至到\-—~～]5年|4\s*-\s*5\s*年|四至五年'), 5),


        (re.compile(r'5年以上|5\s*年以上|五年以上'), 6),


        (re.compile(r'3年以上|3\s*年以上|三年以上'), 6),  # 3年段的兜底段


    ]





    # 账龄表标题关键词


    _AGING_TABLE_KEYWORDS = ["账龄", "按账龄"]





    @classmethod


    def _parse_aging_bracket(cls, label: str) -> Optional[int]:


        """解析行标签中的账龄段，返回排序权重。None 表示非账龄行。"""


        clean = label.replace(" ", "").replace("\u3000", "")


        # 跳过"其中"子项和合计行


        if clean.startswith("其中") or clean in ("合计", "总计", "小计"):


            return None


        for pattern, weight in cls._AGING_BRACKET_PATTERNS:


            if pattern.search(clean):


                return weight


        return None





    def check_aging_transition(


        self,


        note_table: NoteTable,


        table_structure: TableStructure,


    ) -> List[ReportReviewFinding]:


        """账龄衔接校验：期末某账龄段金额 ≤ 期初前一账龄段金额。





        适用于按账龄披露的表格（应收账款、预付款项、组合计提按账龄子表等）。


        这是合理性校验（≤），不是精确等式；不满足时标记为异常提示。





        使用"账面余额"列（而非坏账准备或账面价值列）进行衔接比较。


        """


        findings: List[ReportReviewFinding] = []





        if not self._is_aging_table(note_table):


            return findings


        if self._should_skip_integrity(note_table):


            return findings





        headers = note_table.headers or []


        norm_headers = [str(h or "").replace(" ", "").replace("\u3000", "") for h in headers]





        # ── 识别期末/期初的"账面余额"列 ──


        # 优先选"账面余额"列，其次选"金额"/"余额"列，排除"坏账准备"/"减值准备"/"账面价值"列


        _exclude_kw = ["坏账", "减值", "账面价值", "比例", "%", "占比"]


        _balance_kw = ["账面余额", "金额", "余额"]


        _closing_kw = ["期末", "年末", "本期"]


        _opening_kw = ["期初", "年初", "上期", "上年"]





        closing_col = None


        opening_col = None





        for ci, h in enumerate(norm_headers):


            if any(ek in h for ek in _exclude_kw):


                continue


            is_balance = any(bk in h for bk in _balance_kw)


            if not is_balance:


                continue


            if any(ck in h for ck in _closing_kw):


                if closing_col is None:


                    closing_col = ci


            elif any(ok in h for ok in _opening_kw):


                if opening_col is None:


                    opening_col = ci





        # 如果没有明确的期末/期初标记，尝试用 TableStructure 的列语义


        if closing_col is None or opening_col is None:


            for col in table_structure.columns:


                if col.semantic == "closing_balance" and closing_col is None:


                    # 确认不是排除列


                    h = norm_headers[col.col_index] if col.col_index < len(norm_headers) else ""


                    if not any(ek in h for ek in _exclude_kw):


                        closing_col = col.col_index


                elif col.semantic == "opening_balance" and opening_col is None:


                    h = norm_headers[col.col_index] if col.col_index < len(norm_headers) else ""


                    if not any(ek in h for ek in _exclude_kw):


                        opening_col = col.col_index





        if closing_col is None or opening_col is None:


            return findings





        # ── 收集账龄行数据 ──


        # (排序权重, 行索引, 行标签, 期末值, 期初值)


        aging_rows: List[tuple] = []


        for row_s in table_structure.rows:


            if row_s.role in ("total", "subtotal", "header"):


                continue


            # 跳过 sub_item（"其中"子项不参与衔接校验）


            if row_s.role == "sub_item":


                continue


            label = row_s.label.strip() if row_s.label else ""


            weight = self._parse_aging_bracket(label)


            if weight is None:


                continue


            closing_val = self._get_row_col_value(note_table, row_s.row_index, closing_col)


            opening_val = self._get_row_col_value(note_table, row_s.row_index, opening_col)


            aging_rows.append((weight, row_s.row_index, label, closing_val, opening_val))





        if len(aging_rows) < 2:


            return findings





        # 按权重排序


        aging_rows.sort(key=lambda x: x[0])





        # ── 逐段衔接比较 ──


        # 规则：期末第 N 段 ≤ 期初第 N-1 段


        # 最后兜底段：期末最后段 ≤ 期初同段 + 期初前一段


        for i in range(1, len(aging_rows)):


            curr_weight, curr_ri, curr_label, curr_closing, _ = aging_rows[i]


            prev_weight, prev_ri, prev_label, _, prev_opening = aging_rows[i - 1]





            if curr_closing is None or prev_opening is None:


                continue


            if curr_closing < 0 or prev_opening < 0:


                continue  # 负数不适用衔接校验





            is_last = (i == len(aging_rows) - 1)





            if is_last:


                # 兜底段：期末最后段 ≤ 期初同段 + 期初前一段


                _, _, _, _, same_opening = aging_rows[i]


                upper_bound = prev_opening + (same_opening or 0)


                if curr_closing > upper_bound + TOLERANCE:


                    diff = round(curr_closing - upper_bound, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=note_table.account_name,


                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{curr_ri + 1}行'{curr_label}'",


                        description=(


                            f"账龄衔接异常（兜底段）：期末'{curr_label}'{curr_closing:,.2f} "


                            f"> 期初'{prev_label}'{prev_opening:,.2f} + 期初'{curr_label}'{same_opening or 0:,.2f} "


                            f"= {upper_bound:,.2f}，超出{diff:,.2f}"


                        ),


                        risk_level=RiskLevel.LOW,


                        statement_amount=upper_bound,


                        note_amount=curr_closing,


                        difference=diff,


                        reasoning=f"账龄衔接: 期末{curr_label}({curr_closing}) > 期初{prev_label}({prev_opening}) + 期初{curr_label}({same_opening or 0})",


                        note_table_ids=[note_table.id],


                        highlight_cells=[


                            {"row": curr_ri, "col": closing_col},


                            {"row": prev_ri, "col": opening_col},


                        ],


                    ))


            else:


                # 中间段：期末第 N 段 ≤ 期初第 N-1 段


                if curr_closing > prev_opening + TOLERANCE:


                    diff = round(curr_closing - prev_opening, 2)


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name=note_table.account_name,


                        location=f"附注-{note_table.account_name}-{note_table.section_title}-第{curr_ri + 1}行'{curr_label}'",


                        description=(


                            f"账龄衔接异常：期末'{curr_label}'{curr_closing:,.2f} "


                            f"> 期初'{prev_label}'{prev_opening:,.2f}，超出{diff:,.2f}"


                        ),


                        risk_level=RiskLevel.LOW,


                        statement_amount=prev_opening,


                        note_amount=curr_closing,


                        difference=diff,


                        reasoning=f"账龄衔接: 期末{curr_label}({curr_closing}) > 期初{prev_label}({prev_opening})",


                        note_table_ids=[note_table.id],


                        highlight_cells=[


                            {"row": curr_ri, "col": closing_col},


                            {"row": prev_ri, "col": opening_col},


                        ],


                    ))





        return findings














    # ─── 所得税费用调整过程表校验 (F74-4 ~ F74-6) ───





    INCOME_TAX_ADJUSTMENT_NOTE_KEYWORDS = [


        "会计利润与所得税费用调整",


        "利润总额与所得税费用调整",


        "所得税费用调整过程",


    ]


    INCOME_TAX_DETAIL_NOTE_KEYWORDS = ["所得税费用"]





    def check_income_tax_adjustment_process(


        self,


        items: List[StatementItem],


        notes: List[NoteTable],


    ) -> List[ReportReviewFinding]:


        """所得税费用调整过程表校验 (F74-4 ~ F74-6)。





        F74-4: "按适用税率计算的所得税费用" ≈ "利润总额" × 适用税率(默认25%)


        F74-5: 调整过程表合计 = 所得税费用明细表合计


        F74-6: 按适用税率计算 + 各调整项 = 合计


        """


        findings: List[ReportReviewFinding] = []





        # 1. 找到调整过程表


        adj_note: Optional[NoteTable] = None


        for n in notes:


            combined = (n.section_title or "") + (n.account_name or "")


            if any(kw in combined for kw in self.INCOME_TAX_ADJUSTMENT_NOTE_KEYWORDS):


                adj_note = n


                break





        if not adj_note or not adj_note.rows:


            return findings





        # 2. 解析调整过程表行


        profit_total: Optional[float] = None


        tax_by_rate: Optional[float] = None


        tax_total: Optional[float] = None


        adjustment_items: List[Tuple[str, float]] = []


        tax_rate: Optional[float] = None





        skip_labels = {"合计", "小计", "总计", "项目", "项  目", ""}





        for ri, row in enumerate(adj_note.rows):


            if not row:


                continue


            label = str(row[0]).strip() if row else ""


            if not label:


                continue





            # 取第一个数值列


            val: Optional[float] = None


            for ci in range(1, len(row)):


                v = _safe_float(row[ci])


                if v is not None:


                    val = v


                    break





            if val is None:


                continue





            # 识别利润总额行


            if "利润总额" in label and "税率" not in label:


                profit_total = val


                continue





            # 识别"按适用/适定税率计算的所得税费用"行


            if ("按" in label or "适用" in label or "适定" in label) and "税率" in label and "所得税" in label:


                tax_by_rate = val


                # 尝试从行名提取税率，如 "按25%的税率计算"


                rate_match = re.search(r'(\d+(?:\.\d+)?)\s*%', label)


                if rate_match:


                    tax_rate = float(rate_match.group(1)) / 100


                continue





            # 识别合计行


            clean_label = label.replace(" ", "").replace("\u3000", "")


            if clean_label in {"合计", "所得税费用", "所得税费用合计"}:


                tax_total = val


                continue





            # 其余为调整项


            if clean_label not in skip_labels:


                adjustment_items.append((label, val))





        # 默认税率25%


        if tax_rate is None:


            tax_rate = 0.25





        # F74-4: 利润总额 × 税率 ≈ 按适用税率计算的所得税费用


        if profit_total is not None and tax_by_rate is not None:


            expected = round(profit_total * tax_rate, 2)


            if not _amounts_equal(tax_by_rate, expected):


                diff = round(tax_by_rate - expected, 2)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name="所得税费用/调整过程",


                    location=f"附注-所得税费用调整过程表-按适用税率计算行",


                    description=(


                        f"按适用税率({tax_rate*100:.0f}%)计算的所得税费用 {tax_by_rate:,.2f} "


                        f"≠ 利润总额 {profit_total:,.2f} × {tax_rate*100:.0f}% = {expected:,.2f}，"


                        f"差异 {diff:,.2f}"


                    ),


                    risk_level=RiskLevel.MEDIUM,


                    statement_amount=expected,


                    note_amount=tax_by_rate,


                    difference=diff,


                    reasoning=(


                        f"F74-4: 利润总额({profit_total:,.2f}) × 税率({tax_rate*100:.0f}%) "


                        f"= {expected:,.2f}，实际 {tax_by_rate:,.2f}"


                    ),


                    note_table_ids=[adj_note.id],


                ))





        # F74-5: 调整过程表合计 = 所得税费用明细表合计


        if tax_total is not None:


            # 找所得税费用明细表的合计


            detail_total: Optional[float] = None


            detail_note_id: Optional[str] = None


            for n in notes:


                if n == adj_note:


                    continue


                combined = (n.account_name or "") + (n.section_title or "")


                if not any(kw in combined for kw in self.INCOME_TAX_DETAIL_NOTE_KEYWORDS):


                    continue


                # 已经是调整过程表则跳过


                if any(kw in combined for kw in self.INCOME_TAX_ADJUSTMENT_NOTE_KEYWORDS):


                    continue


                # 找合计行


                for row in n.rows:


                    if not row:


                        continue


                    lbl = str(row[0]).strip().replace(" ", "").replace("\u3000", "")


                    if lbl in {"合计", "所得税费用合计"}:


                        for ci in range(1, len(row)):


                            v = _safe_float(row[ci])


                            if v is not None:


                                detail_total = v


                                detail_note_id = n.id


                                break


                        break


                if detail_total is not None:


                    break





            if detail_total is not None and not _amounts_equal(tax_total, detail_total):


                diff = round(tax_total - detail_total, 2)


                note_ids = [adj_note.id]


                if detail_note_id:


                    note_ids.append(detail_note_id)


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name="所得税费用/调整过程",


                    location="附注-所得税费用调整过程表合计 vs 所得税费用明细表合计",


                    description=(


                        f"调整过程表合计 {tax_total:,.2f} "


                        f"与所得税费用明细表合计 {detail_total:,.2f} 不一致，"


                        f"差异 {diff:,.2f}"


                    ),


                    risk_level=RiskLevel.MEDIUM,


                    statement_amount=detail_total,


                    note_amount=tax_total,


                    difference=diff,


                    reasoning=(


                        f"F74-5: 调整过程表合计({tax_total:,.2f}) "


                        f"应等于 所得税费用明细表合计({detail_total:,.2f})"


                    ),


                    note_table_ids=note_ids,


                ))





        # F74-6: 按适用税率计算 + 各调整项 = 合计


        if tax_by_rate is not None and tax_total is not None and adjustment_items:


            adj_sum = sum(v for _, v in adjustment_items)


            expected_total = round(tax_by_rate + adj_sum, 2)


            if not _amounts_equal(expected_total, tax_total):


                diff = round(tax_total - expected_total, 2)


                adj_desc = " + ".join(f"{name}({val:,.2f})" for name, val in adjustment_items[:5])


                if len(adjustment_items) > 5:


                    adj_desc += f" + ...共{len(adjustment_items)}项"


                findings.append(self._make_finding(


                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                    account_name="所得税费用/调整过程",


                    location="附注-所得税费用调整过程表-纵向加总",


                    description=(


                        f"按适用税率计算 {tax_by_rate:,.2f} + 各调整项合计 {adj_sum:,.2f} "


                        f"= {expected_total:,.2f}，与合计行 {tax_total:,.2f} 不一致，"


                        f"差异 {diff:,.2f}"


                    ),


                    risk_level=RiskLevel.MEDIUM,


                    statement_amount=tax_total,


                    note_amount=expected_total,


                    difference=diff,


                    reasoning=(


                        f"F74-6: 按税率计算({tax_by_rate:,.2f}) + 调整项({adj_desc}) "


                        f"= {expected_total:,.2f}，合计行 {tax_total:,.2f}"


                    ),


                    note_table_ids=[adj_note.id],


                ))





        return findings








    # ─── 其他综合收益明细表结构校验 (F75-3 ~ F75-7) ───





    OCI_DETAIL_NOTE_KEYWORDS = [


        "其他综合收益",


    ]


    # 一类标识


    OCI_CAT1_KEYWORDS = ["以后不能重分类", "不能重分类"]


    # 二类标识


    OCI_CAT2_KEYWORDS = ["将重分类", "以后将重分类"]


    # 合计标识


    OCI_TOTAL_KEYWORDS = ["三、", "其他综合收益合计"]


    # 前期转入损益标识


    OCI_RECLASSIFY_KEYWORDS = ["前期计入", "前期转入", "转入损益", "转入当期"]


    # 小计标识


    OCI_SUBTOTAL_KEYWORDS = ["小计"]





    def check_oci_detail_structure(


        self,


        notes: List[NoteTable],


    ) -> List[ReportReviewFinding]:


        """其他综合收益明细表复杂结构校验 (F75-3 ~ F75-7)。





        F75-3: 三 = 一 + 二 (各数值列)


        F75-4: 每行 税后净额 = 税前金额 - 所得税 (本期/上期)


        F75-5: 一类子项之和 = 一类合计


        F75-6: 二类中每个子项 - 前期转入 = 小计


        F75-7: 二类各小计之和 = 二类合计


        """


        findings: List[ReportReviewFinding] = []





        # 找到其他综合收益明细表


        oci_note: Optional[NoteTable] = None


        for n in notes:


            combined = (n.section_title or "") + (n.account_name or "")


            if any(kw in combined for kw in self.OCI_DETAIL_NOTE_KEYWORDS):


                # 排除仅含"其他综合收益"但实际是利润表行的表格


                if "利润" in combined and "明细" not in combined:


                    continue


                # 需要有多列（税前/所得税/税后结构）


                if len(n.headers) >= 4:


                    oci_note = n


                    break





        if not oci_note or len(oci_note.rows) < 3:


            return findings





        headers = oci_note.headers


        num_cols = len(headers)





        # 识别列结构：找税前/所得税/税后列组


        # 典型结构: [项目, 本期税前, 本期所得税, 本期税后, 上期税前, 上期所得税, 上期税后]


        col_groups: List[Tuple[int, int, int]] = []  # (税前col, 所得税col, 税后col)


        i = 1


        while i < num_cols - 2:


            h1 = str(headers[i]) if i < len(headers) else ""


            h2 = str(headers[i+1]) if i+1 < len(headers) else ""


            h3 = str(headers[i+2]) if i+2 < len(headers) else ""


            if ("税前" in h1 or "金额" in h1) and "所得税" in h2 and ("税后" in h3 or "净额" in h3):


                col_groups.append((i, i+1, i+2))


                i += 3


            else:


                i += 1





        # 如果没有识别到列组，尝试简单的3列模式


        if not col_groups and num_cols >= 4:


            # 可能只有本期3列


            col_groups.append((1, 2, 3))





        # 解析行结构


        cat1_total_ri: Optional[int] = None  # 一类合计行


        cat2_total_ri: Optional[int] = None  # 二类合计行


        grand_total_ri: Optional[int] = None  # 三、合计行


        cat1_item_ris: List[int] = []  # 一类子项行


        cat2_sub_groups: List[dict] = []  # 二类子项组 [{item_ri, reclassify_ri, subtotal_ri}]


        cat2_subtotal_ris: List[int] = []  # 二类各小计行





        in_cat1 = False


        in_cat2 = False


        current_cat2_group: Optional[dict] = None





        for ri, row in enumerate(oci_note.rows):


            if not row:


                continue


            label = str(row[0]).strip() if row else ""


            if not label:


                continue


            clean = label.replace(" ", "").replace("\u3000", "")





            # 识别一类标题


            if any(kw in label for kw in self.OCI_CAT1_KEYWORDS):


                in_cat1 = True


                in_cat2 = False


                # 如果这行本身有数值，它可能是一类合计行


                has_val = any(_safe_float(row[ci]) is not None for ci in range(1, len(row)))


                if has_val:


                    cat1_total_ri = ri


                continue





            # 识别二类标题


            if any(kw in label for kw in self.OCI_CAT2_KEYWORDS):


                in_cat1 = False


                in_cat2 = True


                has_val = any(_safe_float(row[ci]) is not None for ci in range(1, len(row)))


                if has_val:


                    cat2_total_ri = ri


                continue





            # 识别三、合计行


            if any(kw in clean for kw in self.OCI_TOTAL_KEYWORDS) or clean.startswith("三"):


                has_val = any(_safe_float(row[ci]) is not None for ci in range(1, len(row)))


                if has_val:


                    grand_total_ri = ri


                in_cat1 = False


                in_cat2 = False


                continue





            # 在一类区域内


            if in_cat1:


                has_val = any(_safe_float(row[ci]) is not None for ci in range(1, len(row)))


                if has_val:


                    # 检查是否是一类合计行（如"一、以后不能重分类...合计"）


                    if "合计" in clean or "小计" in clean:


                        cat1_total_ri = ri


                    else:


                        cat1_item_ris.append(ri)





            # 在二类区域内


            if in_cat2:


                has_val = any(_safe_float(row[ci]) is not None for ci in range(1, len(row)))


                if not has_val:


                    continue





                if any(kw in label for kw in self.OCI_RECLASSIFY_KEYWORDS):


                    # 前期转入损益行


                    if current_cat2_group:


                        current_cat2_group["reclassify_ri"] = ri


                elif any(kw in clean for kw in self.OCI_SUBTOTAL_KEYWORDS):


                    # 小计行


                    if current_cat2_group:


                        current_cat2_group["subtotal_ri"] = ri


                        cat2_sub_groups.append(current_cat2_group)


                        cat2_subtotal_ris.append(ri)


                        current_cat2_group = None


                elif "合计" in clean:


                    cat2_total_ri = ri


                else:


                    # 新的二类子项


                    if current_cat2_group and "subtotal_ri" not in current_cat2_group:


                        # 上一个子项没有小计行，直接作为简单子项


                        cat2_sub_groups.append(current_cat2_group)


                        cat2_subtotal_ris.append(current_cat2_group["item_ri"])


                    current_cat2_group = {"item_ri": ri}





        # 处理最后一个未关闭的二类子项组


        if current_cat2_group:


            if "subtotal_ri" not in current_cat2_group:


                cat2_subtotal_ris.append(current_cat2_group["item_ri"])


            cat2_sub_groups.append(current_cat2_group)





        def _get_val(ri: int, ci: int) -> Optional[float]:


            if ri < len(oci_note.rows) and ci < len(oci_note.rows[ri]):


                return _safe_float(oci_note.rows[ri][ci])


            return None





        # F75-4: 每行 税后 = 税前 - 所得税


        if col_groups:


            for ri, row in enumerate(oci_note.rows):


                if not row:


                    continue


                label = str(row[0]).strip() if row else ""


                if not label:


                    continue


                for pre_ci, tax_ci, post_ci in col_groups:


                    pre_val = _get_val(ri, pre_ci)


                    tax_val = _get_val(ri, tax_ci)


                    post_val = _get_val(ri, post_ci)


                    if pre_val is not None and tax_val is not None and post_val is not None:


                        expected = round(pre_val - tax_val, 2)


                        if not _amounts_equal(post_val, expected):


                            diff = round(post_val - expected, 2)


                            findings.append(self._make_finding(


                                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                                account_name="其他综合收益",


                                location=f"附注-其他综合收益明细表-第{ri+1}行'{label}'-税后净额",


                                description=(


                                    f"税后净额 {post_val:,.2f} ≠ 税前 {pre_val:,.2f} - 所得税 {tax_val:,.2f} "


                                    f"= {expected:,.2f}，差异 {diff:,.2f}"


                                ),


                                risk_level=RiskLevel.LOW,


                                statement_amount=expected,


                                note_amount=post_val,


                                difference=diff,


                                reasoning=f"F75-4: 第{ri+1}行 税后({post_val}) ≠ 税前({pre_val}) - 所得税({tax_val})",


                                note_table_ids=[oci_note.id],


                            ))





        # F75-3: 三 = 一 + 二


        if grand_total_ri is not None and cat1_total_ri is not None and cat2_total_ri is not None:


            for ci in range(1, num_cols):


                gt = _get_val(grand_total_ri, ci)


                c1 = _get_val(cat1_total_ri, ci)


                c2 = _get_val(cat2_total_ri, ci)


                if gt is not None and c1 is not None and c2 is not None:


                    expected = round(c1 + c2, 2)


                    if not _amounts_equal(gt, expected):


                        diff = round(gt - expected, 2)


                        col_name = str(headers[ci]) if ci < len(headers) else f"第{ci+1}列"


                        findings.append(self._make_finding(


                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                            account_name="其他综合收益",


                            location=f"附注-其他综合收益明细表-合计行-{col_name}",


                            description=(


                                f"三、合计 {gt:,.2f} ≠ 一类合计 {c1:,.2f} + 二类合计 {c2:,.2f} "


                                f"= {expected:,.2f}，差异 {diff:,.2f}"


                            ),


                            risk_level=RiskLevel.MEDIUM,


                            statement_amount=expected,


                            note_amount=gt,


                            difference=diff,


                            reasoning=f"F75-3: 三({gt}) ≠ 一({c1}) + 二({c2})",


                            note_table_ids=[oci_note.id],


                        ))





        # F75-5: 一类子项之和 = 一类合计


        if cat1_total_ri is not None and cat1_item_ris:


            for ci in range(1, num_cols):


                total_val = _get_val(cat1_total_ri, ci)


                if total_val is None:


                    continue


                item_sum = 0.0


                all_none = True


                for item_ri in cat1_item_ris:


                    v = _get_val(item_ri, ci)


                    if v is not None:


                        item_sum += v


                        all_none = False


                if all_none:


                    continue


                item_sum = round(item_sum, 2)


                if not _amounts_equal(item_sum, total_val):


                    diff = round(total_val - item_sum, 2)


                    col_name = str(headers[ci]) if ci < len(headers) else f"第{ci+1}列"


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name="其他综合收益",


                        location=f"附注-其他综合收益明细表-一类合计-{col_name}",


                        description=(


                            f"一类各子项之和 {item_sum:,.2f} ≠ 一类合计 {total_val:,.2f}，"


                            f"差异 {diff:,.2f}"


                        ),


                        risk_level=RiskLevel.LOW,


                        statement_amount=total_val,


                        note_amount=item_sum,


                        difference=diff,


                        reasoning=f"F75-5: 一类子项和({item_sum}) ≠ 一类合计({total_val})",


                        note_table_ids=[oci_note.id],


                    ))





        # F75-7: 二类各小计之和 = 二类合计


        if cat2_total_ri is not None and cat2_subtotal_ris:


            for ci in range(1, num_cols):


                total_val = _get_val(cat2_total_ri, ci)


                if total_val is None:


                    continue


                sub_sum = 0.0


                all_none = True


                for sub_ri in cat2_subtotal_ris:


                    v = _get_val(sub_ri, ci)


                    if v is not None:


                        sub_sum += v


                        all_none = False


                if all_none:


                    continue


                sub_sum = round(sub_sum, 2)


                if not _amounts_equal(sub_sum, total_val):


                    diff = round(total_val - sub_sum, 2)


                    col_name = str(headers[ci]) if ci < len(headers) else f"第{ci+1}列"


                    findings.append(self._make_finding(


                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                        account_name="其他综合收益",


                        location=f"附注-其他综合收益明细表-二类合计-{col_name}",


                        description=(


                            f"二类各小计之和 {sub_sum:,.2f} ≠ 二类合计 {total_val:,.2f}，"


                            f"差异 {diff:,.2f}"


                        ),


                        risk_level=RiskLevel.LOW,


                        statement_amount=total_val,


                        note_amount=sub_sum,


                        difference=diff,


                        reasoning=f"F75-7: 二类小计和({sub_sum}) ≠ 二类合计({total_val})",


                        note_table_ids=[oci_note.id],


                    ))





        # F75-6: 二类中每个子项 - 前期转入 = 小计


        for grp in cat2_sub_groups:


            item_ri = grp.get("item_ri")


            reclassify_ri = grp.get("reclassify_ri")


            subtotal_ri = grp.get("subtotal_ri")


            if item_ri is None or reclassify_ri is None or subtotal_ri is None:


                continue


            item_label = str(oci_note.rows[item_ri][0]).strip() if item_ri < len(oci_note.rows) else ""


            for ci in range(1, num_cols):


                item_val = _get_val(item_ri, ci)


                recl_val = _get_val(reclassify_ri, ci)


                sub_val = _get_val(subtotal_ri, ci)


                if item_val is not None and recl_val is not None and sub_val is not None:


                    expected = round(item_val - recl_val, 2)


                    if not _amounts_equal(sub_val, expected):


                        diff = round(sub_val - expected, 2)


                        col_name = str(headers[ci]) if ci < len(headers) else f"第{ci+1}列"


                        findings.append(self._make_finding(


                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                            account_name="其他综合收益",


                            location=f"附注-其他综合收益明细表-'{item_label}'-小计-{col_name}",


                            description=(


                                f"'{item_label}'小计 {sub_val:,.2f} ≠ "


                                f"子项 {item_val:,.2f} - 前期转入 {recl_val:,.2f} "


                                f"= {expected:,.2f}，差异 {diff:,.2f}"


                            ),


                            risk_level=RiskLevel.LOW,


                            statement_amount=expected,


                            note_amount=sub_val,


                            difference=diff,


                            reasoning=f"F75-6: {item_label} 小计({sub_val}) ≠ 子项({item_val}) - 转入({recl_val})",


                            note_table_ids=[oci_note.id],


                        ))





        return findings








    # ─── 补充资料折旧/摊销精确交叉校验 (F83-3 ~ F83-5a) ───





    # 固定资产累计折旧段关键词


    _DEPR_SECTION_KW = ["累计折旧"]


    # 无形资产累计摊销段关键词


    _AMORT_IA_SECTION_KW = ["累计摊销"]


    # 长期待摊费用本期摊销关键词


    _LT_PREPAID_AMORT_KW = ["本期摊销", "摊销"]


    # 使用权资产累计折旧段关键词


    _ROU_DEPR_SECTION_KW = ["累计折旧"]


    # 本期增加/计提列关键词


    _IMPAIRMENT_INCREASE_COL_KW = ["本期增加", "本期计提", "本年增加", "本年计提", "购置或计提"]





    # 补充资料行匹配


    _SUPP_DEPR_MAPPINGS = [


        {


            "label_keywords": ["固定资产折旧", "油气资产折耗", "生产性生物资产折旧"],


            "source_accounts": ["固定资产"],


            "source_section_kw": ["累计折旧"],


            "formula_id": "F83-3",


        },


        {


            "label_keywords": ["无形资产摊销"],


            "exclude_keywords": ["长期待摊"],


            "source_accounts": ["无形资产"],


            "source_section_kw": ["累计摊销"],


            "formula_id": "F83-4",


        },


        {


            "label_keywords": ["长期待摊费用摊销"],


            "source_accounts": ["长期待摊费用"],


            "source_section_kw": [],  # 直接从明细表取"本期摊销"行


            "use_amort_row": True,


            "formula_id": "F83-5",


        },


        {


            "label_keywords": ["使用权资产折旧", "使用权资产摊销"],


            "source_accounts": ["使用权资产"],


            "source_section_kw": ["累计折旧"],


            "formula_id": "F83-5a",


        },


    ]





    def _extract_provision_from_movement_section(


        self,


        notes: List[NoteTable],


        account_name: str,


        section_keywords: List[str],


    ) -> Optional[Tuple[float, str]]:


        """从资产变动表的指定段（如累计折旧段）提取本期计提合计。





        返回 (金额, note_id) 或 None。


        """


        for n in notes:


            if account_name not in (n.account_name or ""):


                continue


            title = (n.section_title or "")


            # 检查是否是目标段


            if section_keywords and not any(kw in title for kw in section_keywords):


                continue





            # 找"本期增加/计提"列


            provision_col: Optional[int] = None


            for ci, h in enumerate(n.headers):


                if any(kw in h for kw in self._IMPAIRMENT_INCREASE_COL_KW):


                    provision_col = ci


                    break





            if provision_col is None:


                continue





            # 找合计行


            for row in reversed(n.rows):


                if not row:


                    continue


                label = str(row[0]).strip().replace(" ", "").replace("\u3000", "")


                if label in {"合计", "小计", "总计"} or "合计" in label:


                    if provision_col < len(row):


                        val = _safe_float(row[provision_col])


                        if val is not None:


                            return (val, n.id)


            # 如果没有合计行但只有一行数据，取该行


            data_rows = [r for r in n.rows if r and str(r[0]).strip() not in {"", "项目", "项  目"}]


            if len(data_rows) == 1 and provision_col < len(data_rows[0]):


                val = _safe_float(data_rows[0][provision_col])


                if val is not None:


                    return (val, n.id)





        return None





    def _extract_lt_prepaid_amortization(


        self,


        notes: List[NoteTable],


    ) -> Optional[Tuple[float, str]]:


        """从长期待摊费用明细表提取本期摊销合计。"""


        for n in notes:


            if "长期待摊费用" not in (n.account_name or ""):


                continue





            # 找"本期摊销"列或行


            # 方式1: 列模式（宽表）


            amort_col: Optional[int] = None


            for ci, h in enumerate(n.headers):


                if any(kw in h for kw in self._LT_PREPAID_AMORT_KW):


                    amort_col = ci


                    break





            if amort_col is not None:


                # 找合计行


                for row in reversed(n.rows):


                    if not row:


                        continue


                    label = str(row[0]).strip().replace(" ", "").replace("\u3000", "")


                    if "合计" in label:


                        if amort_col < len(row):


                            val = _safe_float(row[amort_col])


                            if val is not None:


                                return (val, n.id)





            # 方式2: 行模式（简单明细表）


            for row in n.rows:


                if not row:


                    continue


                label = str(row[0]).strip()


                if any(kw in label for kw in self._LT_PREPAID_AMORT_KW):


                    for ci in range(1, len(row)):


                        val = _safe_float(row[ci])


                        if val is not None:


                            return (val, n.id)





        return None





    def check_supplement_depreciation_cross(


        self,


        items: List[StatementItem],


        notes: List[NoteTable],


        table_structures: Dict[str, TableStructure],


    ) -> List[ReportReviewFinding]:


        """补充资料折旧/摊销行 vs 各科目附注本期计提精确交叉校验 (F83-3~F83-5a)。





        F83-3: 补充资料."固定资产折旧..." ≈ 固定资产①累计折旧段.本期计提合计


        F83-4: 补充资料."无形资产摊销" ≈ 无形资产①累计摊销段.本期计提合计


        F83-5: 补充资料."长期待摊费用摊销" ≈ 长期待摊费用①.本期摊销合计


        F83-5a: 补充资料."使用权资产折旧" ≈ 使用权资产①累计折旧段.本期计提合计


        """


        findings: List[ReportReviewFinding] = []





        # 找到补充资料表格


        supplement_notes: List[NoteTable] = []


        for n in notes:


            combined = (n.section_title or "") + (n.account_name or "")


            if any(kw in combined for kw in self.CASHFLOW_SUPPLEMENT_NOTE_KEYWORDS):


                supplement_notes.append(n)





        if not supplement_notes:


            return findings





        for supp_note in supplement_notes:


            for ri, row in enumerate(supp_note.rows):


                if not row:


                    continue


                label = str(row[0]).strip() if row else ""


                if not label:


                    continue





                # 取本期发生额：优先通过表头定位本期列
                supp_value: Optional[float] = None
                _s_period_col = None
                if supp_note.headers:
                    for _sci, _sh in enumerate(supp_note.headers):
                        if _sci == 0:
                            continue
                        _shs = str(_sh or "").replace(" ", "").replace("\u3000", "")
                        if any(kw in _shs for kw in ["本期", "本年", "当期"]):
                            if not any(kw in _shs for kw in ["上期", "上年"]):
                                _s_period_col = _sci
                                break
                if _s_period_col is not None and _s_period_col < len(row):
                    supp_value = _safe_float(row[_s_period_col])
                if supp_value is None:
                    for ci in range(1, len(row)):
                        val = _safe_float(row[ci])
                        if val is not None:
                            supp_value = val
                            break
                if supp_value is None:


                    continue





                for mapping in self._SUPP_DEPR_MAPPINGS:


                    if not any(kw in label for kw in mapping["label_keywords"]):


                        continue


                    if mapping.get("exclude_keywords"):


                        if any(ekw in label for ekw in mapping["exclude_keywords"]):


                            continue





                    # 提取对应科目的本期计提金额


                    source_val: Optional[float] = None


                    source_note_id: Optional[str] = None





                    if mapping.get("use_amort_row"):


                        result = self._extract_lt_prepaid_amortization(notes)


                        if result:


                            source_val, source_note_id = result


                    else:


                        for acct in mapping["source_accounts"]:


                            result = self._extract_provision_from_movement_section(


                                notes, acct, mapping["source_section_kw"],


                            )


                            if result:


                                source_val, source_note_id = result


                                break





                    if source_val is None:


                        continue





                    if not _amounts_equal(supp_value, source_val):


                        diff = round(supp_value - source_val, 2)


                        note_ids = [supp_note.id]


                        if source_note_id:


                            note_ids.append(source_note_id)


                        acct_desc = "/".join(mapping["source_accounts"])


                        findings.append(self._make_finding(


                            category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                            account_name=f"补充资料/{acct_desc}",


                            location=f"附注-补充资料-第{ri+1}行'{label}' vs {acct_desc}附注",


                            description=(


                                f"补充资料'{label}' {supp_value:,.2f} "


                                f"与{acct_desc}附注本期计提 {source_val:,.2f} 不一致，"


                                f"差异 {diff:,.2f}"


                            ),


                            risk_level=self._assess_risk(abs(diff), abs(source_val)),


                            statement_amount=source_val,


                            note_amount=supp_value,


                            difference=diff,


                            reasoning=(


                                f"{mapping['formula_id']}: 补充资料.{label}({supp_value:,.2f}) "


                                f"应等于 {acct_desc}.本期计提({source_val:,.2f})"


                            ),


                            note_table_ids=note_ids,


                        ))


                    break  # 一行只匹配一个 mapping





        return findings








    # ─── LLM 文本合理性审核框架 (40+ formulas) ───





    # 文本列检查类型


    _TEXT_CHECK_TYPES = {


        "company_name": "判断是否为规范的公司全称（非简称、非个人名称）",


        "reason": "判断表述是否合理、具体（非空泛、非模板化）",


        "date": "判断是否为合理的日期格式",


        "aging": "判断账龄表达是否规范一致",


    }





    # 表格模式定义：table_keywords 用于匹配表格标题/科目名


    # amount_keywords 用于识别金额列，text_checks 定义需要检查的文本列


    LLM_TEXT_CHECK_PATTERNS: List[dict] = [


        # 单项计提表 (F4-15/F5-15/F8-14)


        {


            "table_keywords": ["单项计提"],


            "amount_keywords": ["账面余额", "账面金额"],


            "text_checks": [


                (["承兑人名称", "债务人名称", "款项性质", "单位名称"], "company_name"),


                (["计提理由", "计提原因"], "reason"),


            ],


        },


        # 收回或转回表 (F4-28/F5-32/F8-29)


        {


            "table_keywords": ["收回或转回", "转回或收回"],


            "amount_keywords": ["转回", "收回", "金额"],


            "text_checks": [


                (["承兑人名称", "债务人名称", "单位名称"], "company_name"),


                (["原因", "方式"], "reason"),


            ],


        },


        # 核销表 (F4-30/F5-34/F8-31)


        {


            "table_keywords": ["核销"],


            "amount_keywords": ["核销金额", "核销"],


            "text_checks": [


                (["单位名称", "债务人名称"], "company_name"),


                (["核销原因", "原因"], "reason"),


            ],


        },


        # 应收款项融资未结算 (F7-10)


        {


            "table_keywords": ["未结算"],


            "amount_keywords": ["期末余额", "余额"],


            "text_checks": [


                (["债权单位", "债务单位"], "company_name"),


                (["未结算的原因", "原因"], "reason"),


                (["账龄"], "aging"),


            ],


        },


        # 逾期利息 (F8-40)


        {


            "table_keywords": ["逾期利息", "重要逾期"],


            "amount_keywords": ["期末余额", "余额"],


            "text_checks": [


                (["借款单位"], "company_name"),


                (["逾期原因", "原因"], "reason"),


                (["减值", "判断依据"], "reason"),


            ],


        },


        # 应收股利 (F8-46)


        {


            "table_keywords": ["应收股利"],


            "amount_keywords": ["期末余额", "期初余额", "余额"],


            "text_checks": [


                (["未收回的原因", "原因"], "reason"),


                (["减值", "判断依据"], "reason"),


            ],


        },


        # 债权投资明细 (F14-7b)


        {


            "table_keywords": ["债权投资"],


            "amount_keywords": ["面值", "账面余额"],


            "text_checks": [


                (["到期日", "到期"], "date"),


            ],


        },


        # 减值准备计提理由 (F14-10b/F15-7f)


        {


            "table_keywords": ["减值准备计提", "各阶段减值"],


            "amount_keywords": ["账面余额", "余额"],


            "text_checks": [


                (["理由", "原因"], "reason"),


            ],


        },


        # 未办妥产权证书 (F20-7b/F21-10b)


        {


            "table_keywords": ["产权证书", "未办妥"],


            "amount_keywords": ["账面价值", "余额"],


            "text_checks": [


                (["原因"], "reason"),


            ],


        },


        # 固定资产清理 (F21-7c)


        {


            "table_keywords": ["固定资产清理"],


            "amount_keywords": ["账面价值", "期末", "余额"],


            "text_checks": [


                (["转入清理的原因", "原因"], "reason"),


            ],


        },


        # 在建工程减值 (F22-5b)


        {


            "table_keywords": ["在建工程", "减值准备计提"],


            "amount_keywords": ["计提金额", "计提"],


            "text_checks": [


                (["计提原因", "原因"], "reason"),


            ],


        },


        # 应付账款超1年 (F36-3b)


        {


            "table_keywords": ["应付账款", "账龄超过"],


            "amount_keywords": ["期末余额", "余额"],


            "text_checks": [


                (["未偿还原因", "原因"], "reason"),


            ],


        },


        # 预收款项超1年 (F37-3b)


        {


            "table_keywords": ["预收款项", "预收账款", "账龄超过"],


            "amount_keywords": ["期末余额", "余额"],


            "text_checks": [


                (["未结转原因", "原因"], "reason"),


            ],


        },


        # 合同负债变动 (F38-4b)


        {


            "table_keywords": ["合同负债", "重大变动"],


            "amount_keywords": ["变动金额", "金额"],


            "text_checks": [


                (["变动原因", "原因"], "reason"),


            ],


        },


        # 其他应付款超1年 (F41-5c)


        {


            "table_keywords": ["其他应付款", "账龄超过"],


            "amount_keywords": ["期末余额", "余额"],


            "text_checks": [


                (["未偿还原因", "原因"], "reason"),


            ],


        },


        # 无形资产内部研发文字 (F26-7a) - 特殊：文字说明中提取金额


        # 这类需要从附注文字中提取，暂不在通用框架中处理


    ]





    def _match_text_check_pattern(self, note: NoteTable) -> Optional[dict]:


        """匹配附注表格到LLM文本检查模式。"""


        combined = (note.section_title or "") + (note.account_name or "")


        for pattern in self.LLM_TEXT_CHECK_PATTERNS:


            if all(kw in combined for kw in pattern["table_keywords"]):


                return pattern


        return None





    def _find_amount_col(self, headers: List[str], keywords: List[str]) -> Optional[int]:


        """找到金额列索引。"""


        for ci, h in enumerate(headers):


            if any(kw in h for kw in keywords):


                return ci


        # 回退：找第一个看起来像数值列的列（含"额""值""计"等关键词）


        for ci in range(1, len(headers)):


            h = str(headers[ci])


            if any(kw in h for kw in ["余额", "金额", "价值", "面值", "合计", "本期", "期末", "期初"]):


                return ci


        return None





    def _find_text_col(self, headers: List[str], keywords: List[str]) -> Optional[int]:


        """找到文本列索引。"""


        for ci, h in enumerate(headers):


            if any(kw in h for kw in keywords):


                return ci


        return None





    async def check_text_reasonableness(


        self,


        notes: List[NoteTable],


        openai_service,


    ) -> List[ReportReviewFinding]:


        """LLM文本合理性审核框架。





        遍历所有附注表格，匹配到LLM审核模式后，对每个有金额的数据行


        提取文本列内容，批量调用LLM判断文本合理性。


        """


        findings: List[ReportReviewFinding] = []





        if not openai_service:


            return findings





        import asyncio





        # 收集所有需要检查的项目


        check_items: List[dict] = []


        skip_labels = {"合计", "小计", "总计", "项目", "项  目", ""}





        for note in notes:


            pattern = self._match_text_check_pattern(note)


            if not pattern:


                continue





            headers = note.headers


            amount_col = self._find_amount_col(headers, pattern["amount_keywords"])


            if amount_col is None:


                continue





            for ri, row in enumerate(note.rows):


                if not row:


                    continue


                label = str(row[0]).strip() if row else ""


                clean_label = label.replace(" ", "").replace("\u3000", "")


                if clean_label in skip_labels or "合计" in clean_label or "小计" in clean_label:


                    continue





                # 检查金额列是否有值


                amount_val = None


                if amount_col < len(row):


                    amount_val = _safe_float(row[amount_col])


                if amount_val is None or abs(amount_val) < 0.01:


                    continue





                # 收集需要检查的文本列


                for col_keywords, check_type in pattern["text_checks"]:


                    text_col = self._find_text_col(headers, col_keywords)


                    if text_col is None or text_col >= len(row):


                        continue


                    text_val = str(row[text_col]).strip() if row[text_col] else ""


                    if not text_val or text_val in {"-", "—", "/", "无", "N/A"}:


                        continue





                    check_items.append({


                        "note": note,


                        "row_index": ri,


                        "row_label": label,


                        "text_col": text_col,


                        "text_col_name": str(headers[text_col]) if text_col < len(headers) else "",


                        "text_value": text_val,


                        "check_type": check_type,


                        "amount": amount_val,


                    })





        if not check_items:


            return findings





        # 批量处理：按表格分组，每组最多10行，合并为一次LLM调用


        from itertools import groupby





        groups: Dict[str, List[dict]] = {}


        for item in check_items:


            key = f"{item['note'].id}_{item['check_type']}"


            groups.setdefault(key, []).append(item)





        semaphore = asyncio.Semaphore(3)





        async def _check_batch(batch: List[dict]) -> List[ReportReviewFinding]:


            """对一批同类型检查项调用LLM。"""


            batch_findings: List[ReportReviewFinding] = []


            if not batch:


                return batch_findings





            check_type = batch[0]["check_type"]


            type_desc = self._TEXT_CHECK_TYPES.get(check_type, "判断内容是否合理")


            note = batch[0]["note"]


            table_desc = f"{note.account_name}-{note.section_title}"





            # 构建检查列表


            items_desc = []


            for i, item in enumerate(batch[:15]):  # 最多15行


                items_desc.append(


                    f"{i+1}. 第{item['row_index']+1}行 '{item['row_label']}' "


                    f"的'{item['text_col_name']}'列: \"{item['text_value']}\""


                )





            prompt = (


                f"你是审计报告附注复核专家。以下是'{table_desc}'表格中需要审核的文本内容。\n"


                f"审核要求：{type_desc}\n\n"


                + "\n".join(items_desc)


                + "\n\n请逐条判断，以JSON数组格式返回：\n"


                  '[{"index": 1, "ok": true/false, "issue": "问题描述（如有）"}]\n'


                  "如果文本合理，ok为true；如果有问题，ok为false并说明issue。"


            )





            try:


                messages = [


                    {"role": "system", "content": "你是审计报告附注复核专家，负责审核附注表格中文本内容的合理性。"},


                    {"role": "user", "content": prompt},


                ]


                response = ""


                async with semaphore:


                    async for chunk in openai_service.stream_chat_completion(messages, temperature=0.2):


                        if isinstance(chunk, str):


                            response += chunk





                # 解析JSON数组


                match = re.search(r'\[[\s\S]*\]', response)


                if match:


                    results = json.loads(match.group())


                    for r in results:


                        idx = r.get("index", 0) - 1


                        if 0 <= idx < len(batch) and not r.get("ok", True):


                            item = batch[idx]


                            issue = r.get("issue", "文本内容不合理")


                            batch_findings.append(self._make_finding(


                                category=ReportReviewFindingCategory.RECONCILIATION_ERROR,


                                account_name=item["note"].account_name,


                                location=(


                                    f"附注-{item['note'].account_name}-{item['note'].section_title}"


                                    f"-第{item['row_index']+1}行'{item['row_label']}'"


                                    f"-'{item['text_col_name']}'列"


                                ),


                                description=(


                                    f"LLM审核：'{item['text_col_name']}'列内容"


                                    f"\"{item['text_value'][:50]}\"存在问题：{issue}"


                                ),


                                risk_level=RiskLevel.LOW,


                                reasoning=(


                                    f"LLM文本审核({check_type}): {issue}"


                                ),


                                note_table_ids=[item["note"].id],


                            ))


            except Exception as e:


                logger.warning("LLM文本审核失败 %s: %s", table_desc, e)





            return batch_findings





        # 并发执行所有批次


        tasks = []


        for key, group_items in groups.items():


            # 分批，每批最多15行


            for i in range(0, len(group_items), 15):


                tasks.append(_check_batch(group_items[i:i+15]))





        if tasks:


            results = await asyncio.gather(*tasks, return_exceptions=True)


            for r in results:


                if isinstance(r, list):


                    findings.extend(r)


                elif isinstance(r, Exception):


                    logger.warning("LLM文本审核批次异常: %s", r)





        return findings





    @staticmethod


    def _make_finding(


        category: ReportReviewFindingCategory,


        account_name: str,


        location: str,


        description: str,


        risk_level: RiskLevel = RiskLevel.MEDIUM,


        statement_amount: Optional[float] = None,


        note_amount: Optional[float] = None,


        difference: Optional[float] = None,


        reasoning: str = "",


        note_table_ids: Optional[List[str]] = None,


        highlight_cells: Optional[List[Dict[str, int]]] = None,


    ) -> ReportReviewFinding:


        return ReportReviewFinding(


            id=str(uuid.uuid4())[:8],


            category=category,


            risk_level=risk_level,


            account_name=account_name,


            statement_amount=statement_amount,


            note_amount=note_amount,


            difference=difference,


            location=location,


            description=description,


            suggestion="请核实数据并修正",


            analysis_reasoning=reasoning,


            note_table_ids=note_table_ids or [],


            highlight_cells=highlight_cells,


            confirmation_status=FindingConfirmationStatus.PENDING_CONFIRMATION,


            status=FindingStatus.OPEN,


        )












    def check_financial_expense_detail(

        self,

        note_table: NoteTable,

        table_structure: TableStructure,

    ) -> List[ReportReviewFinding]:

        """财务费用纵向: 利息费用总额 - 利息资本化 = 利息费用净额 (F64-3)."""

        findings: List[ReportReviewFinding] = []

        combined = (note_table.account_name or "") + (note_table.section_title or "")

        if "财务费用" not in combined:

            return findings

        rows = note_table.rows

        if not rows:

            return findings

        total_row_idx = None

        capitalized_row_idx = None

        net_row_idx = None

        for ri, row in enumerate(rows):

            if not row:

                continue

            label = str(row[0]).replace(" ", "").replace("\u3000", "").strip()

            if ("利息费用总额" in label or label == "利息费用") and total_row_idx is None:

                if "净额" not in label and "资本化" not in label:

                    total_row_idx = ri

            if "资本化" in label and capitalized_row_idx is None:

                capitalized_row_idx = ri

            if ("利息费用净额" in label or "利息支出净额" in label) and net_row_idx is None:

                net_row_idx = ri

        if total_row_idx is None or net_row_idx is None:

            return findings

        num_cols = len(rows[0]) if rows else 0

        for ci in range(1, num_cols):

            total_val = _safe_float(rows[total_row_idx][ci]) if ci < len(rows[total_row_idx]) else None

            cap_val = _safe_float(rows[capitalized_row_idx][ci]) if capitalized_row_idx is not None and ci < len(rows[capitalized_row_idx]) else None

            net_val = _safe_float(rows[net_row_idx][ci]) if ci < len(rows[net_row_idx]) else None

            if total_val is None or net_val is None:

                continue

            if cap_val is None:

                cap_val = 0.0

            expected = total_val - cap_val

            if not _amounts_equal(net_val, expected):

                diff = round(net_val - expected, 2)

                findings.append(self._make_finding(

                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,

                    account_name=note_table.account_name or "财务费用",

                    location=f"附注-{note_table.account_name}-第{net_row_idx + 1}行-第{ci + 1}列",

                    description=(

                        f"利息费用净额 {net_val:,.2f} 应与计算值 {expected:,.2f} 不一致"

                        f"(利息费用总额{total_val:,.2f} - 利息资本化{cap_val:,.2f})，差异{diff:,.2f}"

                    ),

                    statement_amount=expected,

                    note_amount=net_val,

                    difference=diff,

                    risk_level=self._assess_risk(abs(diff), expected),

                    reasoning=f"F64-3: 利息费用净额({net_val:,.2f}) 应等于 利息费用总额({total_val:,.2f}) - 利息资本化({cap_val:,.2f}) = {expected:,.2f}",

                    note_table_ids=[note_table.id],

                    highlight_cells=[

                        {"row": total_row_idx, "col": ci},

                        {"row": net_row_idx, "col": ci},

                    ] + ([{"row": capitalized_row_idx, "col": ci}] if capitalized_row_idx is not None else []),

                ))

        return findings





    def check_benefit_plan_movement(

        self,

        note_table: NoteTable,

        table_structure: TableStructure,

    ) -> List[ReportReviewFinding]:

        """设定受益计划变动表校验 (F49-5~10a).



        校验规则:

        1. 纵向: 一期初 + 二计入当期损益 + 三计入其他综合收益 + 四其他变动 = 五期末

        2. 其中项: 每个主段(二/三/四)下子项之和 = 该主段金额

        """

        findings: List[ReportReviewFinding] = []

        combined = (note_table.account_name or "") + (note_table.section_title or "")

        if "设定受益" not in combined:

            return findings

        rows = note_table.rows

        if not rows:

            return findings



        # Locate the 5 main section rows (一~五)

        section_indices = {}  # key: section number (1-5), value: row_index

        section_children = {}  # key: section number, value: list of child row indices

        current_section = None

        _section_prefixes = {

            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,

        }



        for ri, row in enumerate(rows):

            if not row:

                continue

            label = str(row[0]).replace(" ", "").replace("\u3000", "").strip()

            if not label:

                continue

            # Check if this is a main section header (starts with 一、/二、etc or 一./二.etc)

            matched_section = None

            for prefix, num in _section_prefixes.items():

                if label.startswith(prefix + "、") or label.startswith(prefix + ".") or label.startswith(prefix + "．") or label.startswith(prefix + "，") or label.startswith(prefix + ","):

                    matched_section = num

                    break

                # Also match "一、期初余额" style

                if label.startswith(prefix) and len(label) > 1 and label[1] in "、.．，,":

                    matched_section = num

                    break

            if matched_section is not None:

                section_indices[matched_section] = ri

                current_section = matched_section

                section_children.setdefault(matched_section, [])

            elif current_section is not None and current_section != 5:

                # This is a child row of the current section

                # Skip empty label rows

                if label and not label.startswith("五") and not label.startswith("四") and not label.startswith("三") and not label.startswith("二"):

                    section_children.setdefault(current_section, []).append(ri)



        # Need at least section 1 (opening) and 5 (closing)

        if 1 not in section_indices or 5 not in section_indices:

            return findings



        # Validate each numeric column

        num_cols = len(rows[0]) if rows else 0

        for ci in range(1, num_cols):

            # ── F49-5/6/7: Vertical formula ──

            opening = self._get_row_col_value(note_table, section_indices[1], ci)

            closing = self._get_row_col_value(note_table, section_indices[5], ci)

            if opening is None or closing is None:

                continue



            section_sums = {}

            for sec_num in [2, 3, 4]:

                if sec_num in section_indices:

                    val = self._get_row_col_value(note_table, section_indices[sec_num], ci)

                    section_sums[sec_num] = val if val is not None else 0.0

                else:

                    section_sums[sec_num] = 0.0



            expected_closing = opening + section_sums[2] + section_sums[3] + section_sums[4]

            if not _amounts_equal(closing, expected_closing):

                diff = round(closing - expected_closing, 2)

                findings.append(self._make_finding(

                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,

                    account_name=note_table.account_name or "设定受益计划",

                    location=f"附注-{note_table.account_name}-第{section_indices[5] + 1}行-第{ci + 1}列",

                    description=(

                        f"期末余额 {closing:,.2f} 应等于 期初{opening:,.2f}"

                        f" + 计入当期损益{section_sums[2]:,.2f}"

                        f" + 计入其他综合收益{section_sums[3]:,.2f}"

                        f" + 其他变动{section_sums[4]:,.2f}"

                        f" = {expected_closing:,.2f}，差异{diff:,.2f}"

                    ),

                    statement_amount=expected_closing,

                    note_amount=closing,

                    difference=diff,

                    risk_level=self._assess_risk(abs(diff), expected_closing),

                    reasoning=(

                        f"F49纵向: 五期末({closing:,.2f}) 应等于"

                        f" 一期初({opening:,.2f}) + 二({section_sums[2]:,.2f})"

                        f" + 三({section_sums[3]:,.2f}) + 四({section_sums[4]:,.2f})"

                        f" = {expected_closing:,.2f}"

                    ),

                    note_table_ids=[note_table.id],

                ))



            # ── F49-9/9a/9b/10/10a: Sub-item check for sections 2, 3, 4 ──

            for sec_num in [2, 3, 4]:

                if sec_num not in section_indices:

                    continue

                children = section_children.get(sec_num, [])

                if not children:

                    continue

                parent_val = self._get_row_col_value(note_table, section_indices[sec_num], ci)

                if parent_val is None:

                    continue

                child_sum = 0.0

                has_child = False

                for child_ri in children:

                    v = self._get_row_col_value(note_table, child_ri, ci)

                    if v is not None:

                        child_sum += v

                        has_child = True

                if has_child and not _amounts_equal(child_sum, parent_val):

                    diff = round(child_sum - parent_val, 2)

                    sec_label = {2: "计入当期损益", 3: "计入其他综合收益", 4: "其他变动"}.get(sec_num, "")

                    findings.append(self._make_finding(

                        category=ReportReviewFindingCategory.RECONCILIATION_ERROR,

                        account_name=note_table.account_name or "设定受益计划",

                        location=f"附注-{note_table.account_name}-第{section_indices[sec_num] + 1}行-第{ci + 1}列",

                        description=(

                            f"'{sec_label}'子项之和 {child_sum:,.2f} 与主段金额 {parent_val:,.2f} 不一致，差异{diff:,.2f}"

                        ),

                        statement_amount=parent_val,

                        note_amount=child_sum,

                        difference=diff,

                        risk_level=RiskLevel.LOW,

                        reasoning=f"F49其中项: {sec_label}子项合计({child_sum:,.2f}) != 主段({parent_val:,.2f})",

                        note_table_ids=[note_table.id],

                    ))



        return findings





    def check_equity_subtotal_detail(

        self,

        note_table: NoteTable,

        table_structure: TableStructure,

    ) -> List[ReportReviewFinding]:

        """股本/实收资本明细表"小计"列校验 (F53-3a).



        校验: 发行新股 + 送股 + 公积金转股 + 其他 = 小计

        即: 期初余额和期末余额之间的所有明细列之和 = 小计列

        """

        findings: List[ReportReviewFinding] = []

        combined = (note_table.account_name or "") + (note_table.section_title or "")

        if not any(kw in combined for kw in ["股本", "实收资本"]):

            return findings

        headers = note_table.headers or []

        if len(headers) < 4:

            return findings

        rows = note_table.rows

        if not rows:

            return findings



        # Locate key columns by header keywords

        opening_col = None

        closing_col = None

        subtotal_col = None



        _opening_kw = ["期初余额", "期初投资", "期初数", "期初"]

        _closing_kw = ["期末余额", "期末投资", "期末数", "期末"]

        _subtotal_kw = ["小计", "本期增减"]



        for ci, h in enumerate(headers):

            hs = str(h or "").replace(" ", "").replace("\u3000", "")

            if opening_col is None and any(kw in hs for kw in _opening_kw):

                opening_col = ci

            if closing_col is None and any(kw in hs for kw in _closing_kw):

                # Must be after opening col

                if opening_col is not None and ci > opening_col:

                    closing_col = ci

            if subtotal_col is None and any(kw in hs for kw in _subtotal_kw):

                subtotal_col = ci



        if opening_col is None or closing_col is None or subtotal_col is None:

            return findings

        # subtotal_col must be between opening and closing

        if not (opening_col < subtotal_col < closing_col):

            # Try: subtotal might be right before closing

            if not (opening_col < subtotal_col <= closing_col):

                return findings



        # Detail columns: between opening and closing, excluding opening/closing/subtotal

        detail_cols = []

        for ci in range(opening_col + 1, closing_col):

            if ci == subtotal_col:

                continue

            # Skip ratio/percentage columns

            hs = str(headers[ci] or "").replace(" ", "").replace("\u3000", "")

            if "比例" in hs or "%" in hs or "％" in hs:

                continue

            detail_cols.append(ci)



        if not detail_cols:

            return findings



        # Validate each data row

        for ri, row in enumerate(rows):

            if not row or ri >= len(rows):

                continue

            label = str(row[0]).replace(" ", "").replace("\u3000", "").strip()

            # Skip header-like or empty rows

            if not label:

                continue



            subtotal_val = _safe_float(row[subtotal_col]) if subtotal_col < len(row) else None

            if subtotal_val is None:

                continue



            detail_sum = 0.0

            has_detail = False

            for dc in detail_cols:

                v = _safe_float(row[dc]) if dc < len(row) else None

                if v is not None:

                    detail_sum += v

                    has_detail = True



            if not has_detail:

                continue



            if not _amounts_equal(detail_sum, subtotal_val):

                diff = round(detail_sum - subtotal_val, 2)

                findings.append(self._make_finding(

                    category=ReportReviewFindingCategory.RECONCILIATION_ERROR,

                    account_name=note_table.account_name or "股本",

                    location=f"附注-{note_table.account_name}-第{ri + 1}行'{label}'",

                    description=(

                        f"明细列之和 {detail_sum:,.2f} 与小计列 {subtotal_val:,.2f} 不一致，差异{diff:,.2f}"

                    ),

                    statement_amount=subtotal_val,

                    note_amount=detail_sum,

                    difference=diff,

                    risk_level=RiskLevel.LOW,

                    reasoning=f"F53-3a: 明细列合计({detail_sum:,.2f}) != 小计({subtotal_val:,.2f})",

                    note_table_ids=[note_table.id],

                ))



        return findings





# 模块级单例


reconciliation_engine = ReconciliationEngine()


