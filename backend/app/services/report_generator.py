"""复核报告生成与导出服务。

将 ReviewEngine 的复核结果整合为结构化复核报告，
支持导出为 Word（.docx）和 PDF 格式。
Word 导出排版规范参照审计报告复核导出：
  - 页边距：左3cm、右3.18cm、上3.2cm、下2.54cm
  - 中文字体：仿宋_GB2312，小四号(12pt)；表格内五号(10.5pt)
  - 英文/数字字体：Arial Narrow
  - 段落间距：段前0行、段后0.9行，单倍行距
  - 表格：上下边框1磅，内部0.5磅，左右无，标题行加粗，高风险行标红
  - 页脚页码
PDF 导出使用 weasyprint 将 HTML 渲染为 PDF。
"""
import io
import uuid
import logging
from datetime import datetime
from typing import List, Optional, Dict

import docx
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml

from ..models.audit_schemas import (
    ReviewReport,
    ReviewFinding,
    RiskLevel,
)

logger = logging.getLogger(__name__)

# 风险等级排序权重（高→中→低）
_RISK_SORT_ORDER = {
    RiskLevel.HIGH: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.LOW: 2,
}

# 风险等级中文标签
_RISK_LABELS = {
    RiskLevel.HIGH: "高风险",
    RiskLevel.MEDIUM: "中风险",
    RiskLevel.LOW: "低风险",
}


class ReportGenerator:
    """复核报告生成与导出服务。"""

    def __init__(self):
        pass  # No external service dependencies needed for report generation

    # ── 报告生成 ──

    def generate_report(
        self,
        workpaper_ids: List[str],
        dimensions: List[str],
        findings: List[ReviewFinding],
        conclusion: str,
        project_id: Optional[str] = None,
        entity_name: Optional[str] = None,
    ) -> ReviewReport:
        """将复核结果整合为结构化复核报告。

        报告结构：复核概要、问题清单（按风险等级排序）、修改建议、复核结论。
        自动计算风险等级统计汇总。
        """
        # 按风险等级排序：HIGH → MEDIUM → LOW
        sorted_findings = sorted(
            findings,
            key=lambda f: _RISK_SORT_ORDER.get(f.risk_level, 99),
        )

        # 统计各风险等级数量
        summary: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for f in sorted_findings:
            level_key = f.risk_level.value  # "high" / "medium" / "low"
            summary[level_key] = summary.get(level_key, 0) + 1

        return ReviewReport(
            id=str(uuid.uuid4()),
            workpaper_ids=workpaper_ids,
            dimensions=dimensions,
            findings=sorted_findings,
            summary=summary,
            conclusion=conclusion,
            reviewed_at=datetime.now().isoformat(),
            project_id=project_id,
            entity_name=entity_name,
        )

    # ── 排版常量（与审计报告复核导出一致） ──
    CN_FONT = "仿宋_GB2312"
    EN_FONT = "Arial Narrow"
    BODY_SIZE = Pt(12)       # 小四号
    TABLE_SIZE = Pt(10.5)    # 五号
    SMALL_SIZE = Pt(9)       # 小五号

    # ── Word 导出 ──

    def export_to_word(self, report: ReviewReport) -> bytes:
        """导出复核报告为 Word 格式（.docx）。

        排版规范与审计报告复核导出一致：
        - 页边距：左3cm、右3.18cm、上3.2cm、下2.54cm
        - 字体：仿宋_GB2312 + Arial Narrow
        - 表格：上下1磅边框、内部0.5磅、左右无、标题行加粗
        - 高风险行标红
        - 页脚页码
        """
        doc = docx.Document()

        # ── 页面设置 ──
        for section in doc.sections:
            section.left_margin = Cm(3)
            section.right_margin = Cm(3.18)
            section.top_margin = Cm(3.2)
            section.bottom_margin = Cm(2.54)
            section.header_distance = Cm(1.3)
            section.footer_distance = Cm(1.3)

        # ── 默认样式字体 ──
        style = doc.styles["Normal"]
        style.font.name = self.EN_FONT
        style.font.size = self.BODY_SIZE
        style._element.rPr.rFonts.set(qn("w:eastAsia"), self.CN_FONT)

        # ── 标题 ──
        title_para = doc.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._set_para_spacing(title_para, before=1.0, after=0.5)
        title_run = title_para.add_run("审计底稿复核报告")
        self._set_run_font(title_run, size=Pt(18), bold=True)

        # ── 编制单位 ──
        if report.entity_name:
            self._add_body_para(doc, f"编制单位：{report.entity_name}",
                                before=0.3, after=0.3)

        # ── 基本信息 ──
        self._add_body_para(doc, f"复核时间：{report.reviewed_at}", before=0.5, after=0.3)
        self._add_body_para(doc, f"复核维度：{'、'.join(report.dimensions)}", after=0.3)
        self._add_body_para(doc, f"底稿数量：{len(report.workpaper_ids)}", after=0.3)

        # ── 一、风险汇总 ──
        self._add_body_para(doc, "一、风险汇总", bold=True, before=0.5, after=0.5)

        summary_tbl = doc.add_table(rows=2, cols=4)
        summary_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        self._set_table_borders(summary_tbl)

        for ci, hdr_text in enumerate(["风险等级", "高风险", "中风险", "低风险"]):
            self._format_table_cell(summary_tbl.rows[0].cells[ci], hdr_text, bold=True)
        self._set_header_bottom_border(summary_tbl.rows[0])

        self._format_table_cell(summary_tbl.rows[1].cells[0], "数量")
        for j, rk in enumerate(["high", "medium", "low"]):
            self._format_table_cell(summary_tbl.rows[1].cells[j + 1],
                                    str(report.summary.get(rk, 0)))

        # 表格后间距
        self._add_body_para(doc, "", before=0.5, after=0.3)

        # ── 二、问题清单（按风险等级分组） ──
        self._add_body_para(doc, "二、问题清单", bold=True, before=0.5, after=0.5)

        group_idx = 0
        for risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW):
            level_findings = [
                f for f in report.findings if f.risk_level == risk_level
            ]
            if not level_findings:
                continue

            group_idx += 1
            self._add_body_para(
                doc,
                f"（{group_idx}）{_RISK_LABELS[risk_level]}（{len(level_findings)} 项）",
                bold=True, before=0.5, after=0.3,
            )

            # 问题表格：5列（序号、维度、风险、位置、描述/建议）
            tbl = doc.add_table(rows=1, cols=5)
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            self._set_table_borders(tbl)

            col_widths = [Cm(0.8), Cm(2.2), Cm(0.8), Cm(3.0), Cm(8.3)]
            for ci, w in enumerate(col_widths):
                tbl.columns[ci].width = w

            for ci, ht in enumerate(["序号", "维度", "风险", "位置", "描述及建议"]):
                self._format_table_cell(tbl.rows[0].cells[ci], ht, bold=True)
            self._set_header_bottom_border(tbl.rows[0])

            for fi, finding in enumerate(level_findings, 1):
                row = tbl.add_row()

                desc_parts = []
                if finding.description:
                    desc_parts.append(finding.description)
                if finding.reference:
                    desc_parts.append(f"依据：{finding.reference}")
                if finding.suggestion:
                    desc_parts.append(f"建议：{finding.suggestion}")
                desc_text = "\n".join(desc_parts)

                cell_data = [
                    (str(fi), WD_ALIGN_PARAGRAPH.CENTER),
                    (finding.dimension, WD_ALIGN_PARAGRAPH.CENTER),
                    (_RISK_LABELS[finding.risk_level][:1], WD_ALIGN_PARAGRAPH.CENTER),
                    (finding.location or "", WD_ALIGN_PARAGRAPH.LEFT),
                    (desc_text, WD_ALIGN_PARAGRAPH.LEFT),
                ]
                for ci, (text, align) in enumerate(cell_data):
                    self._format_table_cell(row.cells[ci], text, align=align)

                # 高风险行标红
                if finding.risk_level == RiskLevel.HIGH:
                    for ci in range(5):
                        for p in row.cells[ci].paragraphs:
                            for run in p.runs:
                                run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)

            # 表格后空行
            self._add_body_para(doc, "", before=0.5, after=0.3)

        # ── 三、复核结论 ──
        self._add_body_para(doc, "三、复核结论", bold=True, before=0.5, after=0.5)
        if report.conclusion:
            self._add_body_para(doc, report.conclusion)

        # ── 页脚页码 ──
        self._add_page_number_footer(doc)

        # 输出字节
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.read()

    # ── Word 排版工具方法 ──

    def _set_run_font(self, run, size=None, bold=False, color=None):
        """统一设置 run 的中英文字体、字号、加粗、颜色。"""
        if size is None:
            size = self.BODY_SIZE
        run.font.name = self.EN_FONT
        run.font.size = size
        run.bold = bold
        r = run._element
        rpr = r.find(qn("w:rPr"))
        if rpr is None:
            rpr = parse_xml(f'<w:rPr {nsdecls("w")}></w:rPr>')
            r.insert(0, rpr)
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = parse_xml(f'<w:rFonts {nsdecls("w")}/>')
            rpr.insert(0, rfonts)
        rfonts.set(qn("w:eastAsia"), self.CN_FONT)
        rfonts.set(qn("w:ascii"), self.EN_FONT)
        rfonts.set(qn("w:hAnsi"), self.EN_FONT)
        if color:
            run.font.color.rgb = color

    @staticmethod
    def _set_para_spacing(para, before=0, after=0.9, line=1.0):
        """设置段落间距（单位：行）。"""
        fmt = para.paragraph_format
        fmt.space_before = Pt(before * 12)
        fmt.space_after = Pt(after * 12)
        fmt.line_spacing = line

    def _add_body_para(self, doc, text, bold=False,
                       align=WD_ALIGN_PARAGRAPH.LEFT,
                       before=0, after=0.9):
        """添加正文段落，自动应用字体和间距。"""
        p = doc.add_paragraph()
        p.alignment = align
        self._set_para_spacing(p, before=before, after=after)
        run = p.add_run(text)
        self._set_run_font(run, size=self.BODY_SIZE, bold=bold)
        return p

    @staticmethod
    def _set_table_borders(table):
        """设置表格边框：上下1磅，内部0.5磅，左右无。"""
        tbl = table._tbl
        tblPr = tbl.tblPr if tbl.tblPr is not None else parse_xml(
            f'<w:tblPr {nsdecls("w")}></w:tblPr>')
        borders = parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            '  <w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
            '  <w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
            '  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
            '  <w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '  <w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '  <w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '</w:tblBorders>'
        )
        for old in tblPr.findall(qn("w:tblBorders")):
            tblPr.remove(old)
        tblPr.append(borders)

    @staticmethod
    def _set_header_bottom_border(row):
        """给表头行下方设置 0.5 磅边框。"""
        for cell in row.cells:
            tc = cell._tc
            tcPr = tc.tcPr if tc.tcPr is not None else parse_xml(
                f'<w:tcPr {nsdecls("w")}></w:tcPr>')
            borders = parse_xml(
                f'<w:tcBorders {nsdecls("w")}>'
                '  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                '</w:tcBorders>'
            )
            for old in tcPr.findall(qn("w:tcBorders")):
                tcPr.remove(old)
            tcPr.append(borders)
            if tc.tcPr is None:
                tc.append(tcPr)

    def _format_table_cell(self, cell, text, bold=False,
                           align=WD_ALIGN_PARAGRAPH.CENTER):
        """格式化表格单元格：设置文本、字体、对齐、垂直居中。"""
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = align
        self._set_para_spacing(p, before=0, after=0, line=1.0)
        run = p.add_run(text)
        self._set_run_font(run, size=self.TABLE_SIZE, bold=bold)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    @staticmethod
    def _add_page_number_footer(doc):
        """添加页脚页码。"""
        for section in doc.sections:
            footer = section.footer
            footer.is_linked_to_previous = False
            fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
            fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            ReportGenerator._set_para_spacing(fp, before=0, after=0)
            run = fp.add_run()
            fld_begin = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
            run._element.append(fld_begin)
            run2 = fp.add_run()
            instr = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> PAGE </w:instrText>')
            run2._element.append(instr)
            run3 = fp.add_run()
            fld_end = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
            run3._element.append(fld_end)

    # ── PDF 导出 ──

    def export_to_pdf(self, report: ReviewReport) -> bytes:
        """导出复核报告为 PDF 格式。

        使用 weasyprint 将 HTML 渲染为 PDF。
        A4 尺寸（210mm × 297mm），页边距上下 20mm、左右 15mm，黑白配色。
        """
        html_content = self._build_report_html(report)
        from weasyprint import HTML  # lazy import to avoid startup cost

        pdf_bytes = HTML(string=html_content).write_pdf()
        return pdf_bytes

    def _build_report_html(self, report: ReviewReport) -> str:
        """构建复核报告的 HTML 模板（A4 黑白配色）。"""
        # 按风险等级分组构建 findings HTML
        findings_html = ""
        for risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW):
            level_findings = [
                f for f in report.findings if f.risk_level == risk_level
            ]
            if not level_findings:
                continue

            findings_html += f'<h2>{_RISK_LABELS[risk_level]}（{len(level_findings)} 项）</h2>\n'
            findings_html += '<table>\n<thead><tr>'
            findings_html += '<th>序号</th><th>维度</th><th>描述</th><th>位置</th><th>建议</th><th>状态</th>'
            findings_html += '</tr></thead>\n<tbody>\n'

            for idx, finding in enumerate(level_findings, 1):
                findings_html += "<tr>"
                findings_html += f"<td>{idx}</td>"
                findings_html += f"<td>{_escape_html(finding.dimension)}</td>"
                findings_html += f"<td>{_escape_html(finding.description)}</td>"
                findings_html += f"<td>{_escape_html(finding.location)}</td>"
                findings_html += f"<td>{_escape_html(finding.suggestion)}</td>"
                findings_html += f"<td>{_escape_html(finding.status.value)}</td>"
                findings_html += "</tr>\n"

            findings_html += "</tbody>\n</table>\n"

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
@page {{
    size: A4;
    margin: 20mm 15mm;
}}
body {{
    font-family: "SimSun", "宋体", serif;
    font-size: 12pt;
    color: #000;
    line-height: 1.6;
}}
h1 {{
    text-align: center;
    font-size: 18pt;
    margin-bottom: 20px;
}}
h2 {{
    font-size: 14pt;
    border-bottom: 1px solid #000;
    padding-bottom: 4px;
    margin-top: 20px;
}}
h3 {{
    font-size: 12pt;
    margin-top: 16px;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0;
    page-break-inside: auto;
}}
th, td {{
    border: 1px solid #000;
    padding: 6px 8px;
    text-align: left;
    font-size: 10pt;
    word-wrap: break-word;
}}
th {{
    background-color: #eee;
    font-weight: bold;
}}
tr {{
    page-break-inside: avoid;
}}
.summary-table td:first-child {{
    width: 120px;
    font-weight: bold;
}}
.conclusion {{
    margin-top: 20px;
    padding: 10px;
    border: 1px solid #000;
}}
</style>
</head>
<body>
<h1>审计底稿复核报告</h1>

{"<p><strong>编制单位：</strong>" + _escape_html(report.entity_name) + "</p>" if report.entity_name else ""}
<h2>一、复核概要</h2>
<table class="summary-table">
<tr><td>复核时间</td><td>{_escape_html(report.reviewed_at)}</td></tr>
<tr><td>复核维度</td><td>{_escape_html("、".join(report.dimensions))}</td></tr>
<tr><td>底稿数量</td><td>{len(report.workpaper_ids)}</td></tr>
<tr><td>风险统计</td><td>高风险 {report.summary.get("high", 0)} 项 / 中风险 {report.summary.get("medium", 0)} 项 / 低风险 {report.summary.get("low", 0)} 项</td></tr>
</table>

<h2>二、问题清单</h2>
{findings_html}

<h2>三、复核结论</h2>
<div class="conclusion">{_escape_html(report.conclusion)}</div>
</body>
</html>"""
        return html

    # ── 序列化 / 反序列化 ──

    def parse_report_to_structured(self, report: ReviewReport) -> dict:
        """将复核报告解析为结构化数据格式（字典）。"""
        return report.model_dump(mode="json")

    def structured_to_report(self, data: dict) -> ReviewReport:
        """从结构化数据重建复核报告对象（往返一致性）。"""
        return ReviewReport.model_validate(data)


def _escape_html(text: str) -> str:
    """简单 HTML 转义。"""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
