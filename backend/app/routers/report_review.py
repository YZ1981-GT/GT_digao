"""审计报告复核路由层。

注册到 /api/report-review/ 前缀。
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote as requests_quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..models.audit_schemas import (
    FindingConfirmationStatus,
    FindingConversation,
    FindingStatus,
    MatchingMap,
    ReportFileType,
    ReportReviewConfig,
    ReportReviewFinding,
    ReportReviewResult,
    ReportReviewSession,
    ReportTemplateType,
    RiskLevel,
    TemplateCategory,
)
from ..services.report_review_engine import report_review_engine
from ..services.report_parser import report_parser
from ..services.report_template_service import report_template_service
from ..services.reconciliation_engine import reconciliation_engine
from ..services.table_structure_analyzer import TableStructureAnalyzer
from ..services.file_service import FileService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/report-review", tags=["report-review"])

# 内存会话存储
_sessions: Dict[str, ReportReviewSession] = {}
_findings: Dict[str, List[ReportReviewFinding]] = {}
_conversations: Dict[str, FindingConversation] = {}


# ─── Request/Response Models ───

class UploadRequest(BaseModel):
    template_type: str = "soe"

class ConfirmMatchingRequest(BaseModel):
    session_id: str
    matching_map: MatchingMap

class StartReviewRequest(BaseModel):
    session_id: str
    template_type: str = "soe"
    prompt_id: Optional[str] = None
    custom_prompt: Optional[str] = None
    change_threshold: float = 0.3

class EditFindingRequest(BaseModel):
    description: Optional[str] = None
    suggestion: Optional[str] = None
    risk_level: Optional[str] = None

class ChatRequest(BaseModel):
    message: str

class TraceRequest(BaseModel):
    trace_type: str  # cross_reference / template_compare / data_drill_down

class BatchRequest(BaseModel):
    finding_ids: List[str]
    action: str  # confirm / dismiss

class StatusUpdateRequest(BaseModel):
    status: str  # open / resolved


# ─── 文件上传与解析 ───

@router.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    template_type: str = Form("soe"),
):
    """上传审计报告文件并解析。"""
    import tempfile
    import aiofiles

    try:
        tt = ReportTemplateType(template_type)
    except ValueError:
        raise HTTPException(400, f"不支持的模板类型: {template_type}")

    session_id = str(uuid.uuid4())[:8]
    session = ReportReviewSession(
        id=session_id,
        template_type=tt,
        created_at=datetime.now().isoformat(),
    )

    # 保存文件到临时目录并解析
    temp_files: List[str] = []
    try:
        for file in files:
            if file.size and file.size > 50 * 1024 * 1024:
                raise HTTPException(413, f"文件 {file.filename} 超过50MB限制")

            filename = file.filename or "unknown"
            ext = os.path.splitext(filename)[1].lower()
            content = await file.read()

            # 保存到临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            temp_files.append(tmp_path)

            file_id = str(uuid.uuid4())[:8]
            session.file_ids.append(file_id)

            # 记录文件名映射
            session.source_file_names[file_id] = filename

            # 生成页面截图（PDF 文件）
            if ext == '.pdf':
                try:
                    page_dir = os.path.join("uploads", "pages", session_id, file_id)
                    page_map = FileService.render_pdf_page_images(tmp_path, page_dir, dpi=150)
                    if page_map:
                        if not session.page_image_dir:
                            session.page_image_dir = os.path.join("uploads", "pages", session_id)
                        logger.info("PDF 页面截图生成: %s, %d 页", filename, len(page_map))
                except Exception as e:
                    logger.warning("页面截图生成失败 %s: %s", filename, e)

            # 分类文件
            try:
                if ext in ('.doc', '.docx', '.xlsx', '.xls', '.pdf'):
                    content_text = ""
                else:
                    try:
                        content_text = content.decode('utf-8')[:2000]
                    except (UnicodeDecodeError, AttributeError):
                        content_text = content.decode('utf-8', errors='ignore')[:2000]
                file_type = report_parser.classify_report_file(filename, content_text)
                session.file_classifications[file_id] = file_type
            except Exception as e:
                raise HTTPException(400, f"文件分类失败: {e}")

            # 实际解析文件内容（根据文件分类决定提取方式）
            try:
                if ext in ('.xlsx', '.xls'):
                    excel_result = await report_parser.parse_excel(tmp_path, ext)
                    sheets = report_parser.extract_sheets(excel_result)
                    session.sheet_data[file_id] = sheets
                    for sheet in sheets:
                        items = report_parser.extract_statement_items(sheet)
                        session.statement_items.extend(items)

                elif ext in ('.docx', '.doc'):
                    word_result = await report_parser.parse_word(tmp_path)
                    # 用解析后的文本重新分类（上面分类时 content_text 为空）
                    word_text = ' '.join(
                        p.get('text', '') for p in word_result.paragraphs[:50]
                    )
                    file_type = report_parser.classify_report_file(filename, word_text)
                    session.file_classifications[file_id] = file_type

                    if file_type == ReportFileType.NOTES_TO_STATEMENTS:
                        # 附注文件：提取表格和层级结构
                        note_tables = report_parser.extract_note_tables(word_result)
                        session.note_tables.extend(note_tables)
                        note_sections = report_parser.extract_note_sections(word_result, note_tables)
                        session.note_sections.extend(note_sections)
                    elif file_type == ReportFileType.AUDIT_REPORT_BODY:
                        # 审计报告正文：提取段落内容
                        for para in word_result.paragraphs:
                            text = para.get('text', '').strip()
                            if not text:
                                # 保留空行用于段落分隔
                                session.audit_report_content.append({
                                    'text': '', 'level': None, 'style': '',
                                })
                                continue
                            session.audit_report_content.append({
                                'text': text,
                                'level': para.get('level'),
                                'style': para.get('style', ''),
                            })
                    else:
                        logger.info(f"Word 文件 {filename} 分类为 {file_type.value}")

                elif ext == '.pdf':
                    pdf_result = await report_parser.parse_pdf(tmp_path)
                    logger.info(f"PDF 文件 {filename} 分类为 {file_type.value}")

            except Exception as e:
                logger.warning(f"文件 {filename} 解析失败: {e}")

        session.status = "parsed"

        # 自动构建科目匹配映射（基于标准模板）
        if session.statement_items and session.note_tables:
            try:
                session.matching_map = reconciliation_engine.build_matching_map(
                    session.statement_items, session.note_tables
                )
                logger.info("自动匹配完成: %d 条映射, %d 未匹配",
                            len(session.matching_map.entries),
                            len(session.matching_map.unmatched_items))
            except Exception as e:
                logger.warning("自动匹配失败: %s", e)

            # 预先用规则识别表格结构（毫秒级），复核阶段直接复用
            try:
                analyzer = TableStructureAnalyzer()
                for note in session.note_tables:
                    ts = analyzer._analyze_with_rules(note)
                    session.table_structures[note.id] = ts
                logger.info("表格结构预识别完成: %d 个表格", len(session.table_structures))
            except Exception as e:
                logger.warning("表格结构预识别失败: %s", e)

        _sessions[session_id] = session
        return {
            "session_id": session_id,
            "file_count": len(files),
            "template_type": template_type,
            "statement_items": len(session.statement_items),
            "note_tables": len(session.note_tables),
            "note_sections": len(session.note_sections),
        }
    finally:
        # 清理临时文件
        for tmp_path in temp_files:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass


@router.post("/parse")
async def parse_session(session_id: str = Form(...)):
    """解析已上传文件。"""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    session.status = "parsed"
    _sessions[session_id] = session
    return {"status": "parsed", "session_id": session_id}


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取会话状态。"""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return session.model_dump()


@router.get("/session/{session_id}/sheets")
async def get_sheets(session_id: str):
    """获取已解析的 Sheet 列表。"""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return {"sheets": session.sheet_data}


@router.get("/session/{session_id}/note-tables")
async def get_note_tables(session_id: str, account_name: Optional[str] = None, note_id: Optional[str] = None, note_ids: Optional[str] = None):
    """获取附注表格数据，可按科目名、表格ID或多个ID筛选。"""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    tables = session.note_tables

    # 优先按 note_ids（逗号分隔）精确查找
    if note_ids:
        id_list = [x.strip() for x in note_ids.split(",") if x.strip()]
        id_set = set(id_list)
        tables = [t for t in tables if t.id in id_set]
    elif note_id:
        tables = [t for t in tables if t.id == note_id]
    elif account_name:
        # 多策略匹配：精确 → 包含 → 模糊
        exact = [t for t in tables if t.account_name == account_name]
        if exact:
            tables = exact
        else:
            contains = [t for t in tables if account_name in t.account_name
                        or t.account_name in account_name
                        or account_name in t.section_title
                        or t.account_name in account_name.replace("按", "").replace("分类披露", "").replace("计提方法", "")]
            tables = contains if contains else []
    return {"note_tables": [t.model_dump() for t in tables]}


@router.get("/session/{session_id}/page-image/{file_id}/{page_num}")
async def get_page_image(session_id: str, file_id: str, page_num: int):
    """获取源文档指定页的截图。"""
    from fastapi.responses import FileResponse

    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    img_path = os.path.join("uploads", "pages", session_id, file_id, f"page_{page_num}.jpg")
    if not os.path.isfile(img_path):
        raise HTTPException(404, "页面截图不存在")

    return FileResponse(img_path, media_type="image/jpeg")


@router.get("/session/{session_id}/page-images-info")
async def get_page_images_info(session_id: str):
    """获取会话中所有可用的页面截图信息。"""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    result = {}
    base_dir = os.path.join("uploads", "pages", session_id)
    if os.path.isdir(base_dir):
        for fid in os.listdir(base_dir):
            fid_dir = os.path.join(base_dir, fid)
            if os.path.isdir(fid_dir):
                pages = sorted([
                    int(f.replace("page_", "").replace(".jpg", ""))
                    for f in os.listdir(fid_dir) if f.startswith("page_") and f.endswith(".jpg")
                ])
                result[fid] = {
                    "filename": session.source_file_names.get(fid, fid),
                    "pages": pages,
                }
    return {"page_images": result}


# ─── 匹配与复核 ───

@router.post("/confirm-matching")
async def confirm_matching(req: ConfirmMatchingRequest):
    """用户确认/调整科目匹配映射。"""
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    session.matching_map = req.matching_map
    session.status = "matched"
    return {"status": "matched"}


@router.post("/start")
async def start_review(req: StartReviewRequest):
    """发起复核，SSE 流式返回。"""
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    try:
        tt = ReportTemplateType(req.template_type)
    except ValueError:
        tt = session.template_type

    config = ReportReviewConfig(
        session_id=req.session_id,
        template_type=tt,
        prompt_id=req.prompt_id,
        custom_prompt=req.custom_prompt,
        change_threshold=req.change_threshold,
    )

    async def event_stream():
        async for event in report_review_engine.review_stream(session, config):
            yield f"data: {event}\n\n"
            await asyncio.sleep(0)  # 强制 flush，确保 SSE 事件立即发送到客户端
            # 收集 findings
            try:
                data = json.loads(event)
                if data.get("status") == "completed" and "result" in data:
                    result = data["result"]
                    if "findings" in result:
                        _findings[req.session_id] = [
                            ReportReviewFinding(**f) for f in result["findings"]
                        ]
            except Exception:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─── Finding 交互 ───

@router.get("/findings/{session_id}")
async def get_findings(session_id: str):
    """获取所有 Finding。"""
    findings = _findings.get(session_id, [])
    return {"findings": [f.model_dump() for f in findings]}


@router.get("/finding/{finding_id}")
async def get_finding(finding_id: str):
    """获取单条 Finding 详情。"""
    for session_findings in _findings.values():
        for f in session_findings:
            if f.id == finding_id:
                conv = _conversations.get(finding_id)
                return {
                    "finding": f.model_dump(),
                    "conversation": conv.model_dump() if conv else None,
                }
    raise HTTPException(404, "Finding 不存在")


@router.patch("/finding/{finding_id}/edit")
async def edit_finding(finding_id: str, req: EditFindingRequest):
    """编辑 Finding。"""
    for session_findings in _findings.values():
        for f in session_findings:
            if f.id == finding_id:
                if req.description is not None:
                    f.description = req.description
                if req.suggestion is not None:
                    f.suggestion = req.suggestion
                if req.risk_level is not None:
                    f.risk_level = RiskLevel(req.risk_level)
                return {"status": "updated"}
    raise HTTPException(404, "Finding 不存在")


@router.patch("/finding/{finding_id}/confirm")
async def confirm_finding(finding_id: str):
    """确认 Finding。"""
    for session_findings in _findings.values():
        for f in session_findings:
            if f.id == finding_id:
                f.confirmation_status = FindingConfirmationStatus.CONFIRMED
                return {"status": "confirmed"}
    raise HTTPException(404, "Finding 不存在")


@router.patch("/finding/{finding_id}/dismiss")
async def dismiss_finding(finding_id: str):
    """忽略 Finding。"""
    for session_findings in _findings.values():
        for f in session_findings:
            if f.id == finding_id:
                f.confirmation_status = FindingConfirmationStatus.DISMISSED
                return {"status": "dismissed"}
    raise HTTPException(404, "Finding 不存在")


@router.patch("/finding/{finding_id}/restore")
async def restore_finding(finding_id: str):
    """恢复已忽略的 Finding。"""
    for session_findings in _findings.values():
        for f in session_findings:
            if f.id == finding_id:
                f.confirmation_status = FindingConfirmationStatus.PENDING_CONFIRMATION
                return {"status": "restored"}
    raise HTTPException(404, "Finding 不存在")


@router.post("/findings/batch")
async def batch_findings(req: BatchRequest):
    """批量确认/忽略。"""
    status_map = {
        "confirm": FindingConfirmationStatus.CONFIRMED,
        "dismiss": FindingConfirmationStatus.DISMISSED,
    }
    new_status = status_map.get(req.action)
    if not new_status:
        raise HTTPException(400, f"不支持的操作: {req.action}")

    updated = 0
    for session_findings in _findings.values():
        for f in session_findings:
            if f.id in req.finding_ids:
                f.confirmation_status = new_status
                updated += 1
    return {"updated": updated}


# ─── Finding 对话与溯源 ───

@router.post("/finding/{finding_id}/chat")
async def chat_finding(finding_id: str, req: ChatRequest):
    """用户追问，SSE 流式返回。"""
    finding = _find_finding(finding_id)
    if not finding:
        raise HTTPException(404, "Finding 不存在")

    conv = _conversations.setdefault(finding_id, FindingConversation(finding_id=finding_id))

    async def event_stream():
        async for event in report_review_engine.chat_about_finding(
            finding, req.message, conv, report_review_engine.openai_service
        ):
            yield f"data: {event}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/finding/{finding_id}/trace")
async def trace_finding(finding_id: str, req: TraceRequest):
    """溯源分析，SSE 流式返回。"""
    finding = _find_finding(finding_id)
    if not finding:
        raise HTTPException(404, "Finding 不存在")

    conv = _conversations.setdefault(finding_id, FindingConversation(finding_id=finding_id))

    async def event_stream():
        async for event in report_review_engine.trace_finding(
            finding, req.trace_type, conv, report_review_engine.openai_service
        ):
            yield f"data: {event}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/finding/{finding_id}/conversation")
async def get_conversation(finding_id: str):
    """获取 Finding 对话历史。"""
    conv = _conversations.get(finding_id)
    if not conv:
        return {"messages": []}
    return conv.model_dump()


# ─── 报告与导出 ───

@router.get("/result/{session_id}")
async def get_result(session_id: str):
    """获取复核结果。如果用户未勾选任何问题，则导出全部问题。"""
    findings = _findings.get(session_id, [])
    confirmed = [f for f in findings if f.confirmation_status == FindingConfirmationStatus.CONFIRMED]
    dismissed = [f for f in findings if f.confirmation_status == FindingConfirmationStatus.DISMISSED]
    pending = [f for f in findings if f.confirmation_status == FindingConfirmationStatus.PENDING_CONFIRMATION]

    # 如果没有任何已确认的问题，则输出所有未忽略的问题（pending + confirmed）
    output = confirmed if confirmed else [f for f in findings if f.confirmation_status != FindingConfirmationStatus.DISMISSED]

    category_summary = {}
    risk_summary = {"high": 0, "medium": 0, "low": 0}
    for f in output:
        cat = f.category.value
        category_summary[cat] = category_summary.get(cat, 0) + 1
        risk_summary[f.risk_level.value] += 1

    # 生成结论
    total = len(output)
    if total == 0:
        conclusion = "本次复核未发现明显问题。"
    else:
        high = sum(1 for f in output if f.risk_level.value == "high")
        medium = sum(1 for f in output if f.risk_level.value == "medium")
        low = sum(1 for f in output if f.risk_level.value == "low")
        parts = [f"本次复核共发现 {total} 个待确认问题"]
        details = []
        if high:
            details.append(f"高风险 {high} 个")
        if medium:
            details.append(f"中风险 {medium} 个")
        if low:
            details.append(f"低风险 {low} 个")
        if details:
            parts.append(f"（{'、'.join(details)}）")
        parts.append("。所有问题需经用户确认后纳入最终报告。")
        conclusion = "".join(parts)

    return {
        "session_id": session_id,
        "findings": [f.model_dump() for f in output],
        "category_summary": category_summary,
        "risk_summary": risk_summary,
        "confirmation_summary": {
            "confirmed": len(confirmed),
            "dismissed": len(dismissed),
            "pending": len(pending),
        },
        "conclusion": conclusion,
        "total_findings": len(findings),
    }


class ExportRequest(BaseModel):
    session_id: str
    format: str = "word"


@router.post("/export")
async def export_report(req: ExportRequest):
    """导出复核报告为 Word 文档。"""
    import io
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from fastapi.responses import Response

    try:
        session_id = req.session_id

        findings = _findings.get(session_id, [])
        confirmed = [f for f in findings if f.confirmation_status == FindingConfirmationStatus.CONFIRMED]
        output = confirmed if confirmed else [f for f in findings if f.confirmation_status != FindingConfirmationStatus.DISMISSED]

        doc = Document()

        title = doc.add_heading('审计报告复核结果', level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph(f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}')
        doc.add_paragraph(f'问题总数：{len(output)}')
        doc.add_paragraph('')

        if not output:
            doc.add_paragraph('未发现需要关注的问题。')
        else:
            grouped: Dict[str, list] = {}
            for f in output:
                grouped.setdefault(f.account_name, []).append(f)

            risk_map = {'high': '高', 'medium': '中', 'low': '低'}
            cat_map = {
                'amount_inconsistency': '金额不一致',
                'reconciliation_error': '勾稽错误',
                'change_abnormal': '变动异常',
                'note_missing': '附注缺失',
                'report_body_compliance': '正文规范性',
                'note_content': '附注内容',
                'text_quality': '文本质量',
                'expression_compliance': '表达合规性',
                'missing_disclosure': '披露缺失',
                'other': '其他',
            }

            for account, flist in grouped.items():
                doc.add_heading(f'{account}（{len(flist)}项）', level=2)

                table = doc.add_table(rows=1, cols=6)
                table.style = 'Table Grid'
                hdr = table.rows[0].cells
                for i, text in enumerate(['分类', '风险', '位置', '描述', '建议', '状态']):
                    hdr[i].text = text
                    for p in hdr[i].paragraphs:
                        for run in p.runs:
                            run.bold = True
                            run.font.size = Pt(9)

                for f in flist:
                    row = table.add_row().cells
                    row[0].text = cat_map.get(f.category.value if hasattr(f.category, 'value') else str(f.category), str(f.category))
                    row[1].text = risk_map.get(f.risk_level.value if hasattr(f.risk_level, 'value') else str(f.risk_level), str(f.risk_level))
                    row[2].text = f.location or ''
                    row[3].text = f.description or ''
                    row[4].text = f.suggestion or ''
                    row[5].text = f.status.value if hasattr(f.status, 'value') else str(f.status)
                    for cell in row:
                        for p in cell.paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(9)

                    # 如果有源文档页面截图，插入到表格下方
                    if f.source_page and session_id:
                        session = _sessions.get(session_id)
                        if session and session.page_image_dir:
                            page_img_path = None
                            pages_base = os.path.join("uploads", "pages", session_id)
                            if os.path.isdir(pages_base):
                                for fid_dir in os.listdir(pages_base):
                                    candidate = os.path.join(pages_base, fid_dir, f"page_{f.source_page}.jpg")
                                    if os.path.isfile(candidate):
                                        page_img_path = candidate
                                        break
                            if page_img_path:
                                try:
                                    doc.add_picture(page_img_path, width=Inches(5.5))
                                    last_para = doc.paragraphs[-1]
                                    last_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                    caption = doc.add_paragraph(f'▲ 源文档第{f.source_page}页{" - " + f.source_file if f.source_file else ""}')
                                    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                    for r in caption.runs:
                                        r.font.size = Pt(8)
                                        r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
                                except Exception as img_e:
                                    logger.warning("插入页面截图失败: %s", img_e)

                doc.add_paragraph('')

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        filename = f'audit_review_{datetime.now().strftime("%Y%m%d_%H%M")}.docx'
        display_name = f'审计报告复核结果_{datetime.now().strftime("%Y%m%d_%H%M")}.docx'
        return Response(
            content=buf.getvalue(),
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={
                'Content-Disposition': f"attachment; filename=\"{filename}\"; filename*=UTF-8''{requests_quote(display_name)}",
            },
        )
    except Exception as e:
        logger.exception("导出复核报告失败")
        raise HTTPException(500, f"导出失败: {str(e)}")


@router.patch("/finding/{finding_id}/status")
async def update_finding_status(finding_id: str, req: StatusUpdateRequest):
    """更新已确认问题的处理状态。"""
    finding = _find_finding(finding_id)
    if not finding:
        raise HTTPException(404, "Finding 不存在")
    finding.status = FindingStatus(req.status)
    return {"status": req.status}


# ─── 源文档预览 ───

@router.get("/source-preview/{file_id}")
async def source_preview(file_id: str):
    """获取源文档预览数据。"""
    return {"file_id": file_id, "content_html": "<p>预览功能待实现</p>"}


@router.get("/source-preview/{file_id}/sheet/{sheet_name}")
async def source_preview_sheet(file_id: str, sheet_name: str):
    """获取指定 Sheet 的预览数据。"""
    return {"file_id": file_id, "sheet_name": sheet_name, "content_html": "<p>Sheet预览待实现</p>"}


# ─── 母公司附注预设科目 ───

@router.get("/parent-accounts/{template_type}")
async def get_parent_accounts(template_type: str):
    """获取母公司附注预设科目清单。"""
    from ..services.account_mapping_template import account_mapping_template
    accounts = account_mapping_template.get_parent_company_accounts(template_type)
    if not accounts:
        raise HTTPException(400, f"不支持的模板类型: {template_type}")
    return {"template_type": template_type, "accounts": accounts}


# ─── 模板管理 ───

@router.get("/templates/{template_type}/{template_category}")
async def get_template(template_type: str, template_category: str):
    """获取模板内容。"""
    try:
        tt = ReportTemplateType(template_type)
        tc = TemplateCategory(template_category)
    except ValueError as e:
        raise HTTPException(400, str(e))

    doc = report_template_service.get_template(tt, tc)
    if not doc:
        raise HTTPException(404, "模板未找到")
    return doc.model_dump()


@router.get("/templates/{template_type}/{template_category}/toc")
async def get_template_toc(template_type: str, template_category: str):
    """获取模板目录结构。"""
    try:
        tt = ReportTemplateType(template_type)
        tc = TemplateCategory(template_category)
    except ValueError as e:
        raise HTTPException(400, str(e))

    toc = report_template_service.get_template_toc(tt, tc)
    return {"toc": [e.model_dump() for e in toc]}


@router.get("/templates/{template_type}/{template_category}/section")
async def get_template_section(template_type: str, template_category: str, path: str = ""):
    """按路径获取模板章节内容。"""
    try:
        tt = ReportTemplateType(template_type)
        tc = TemplateCategory(template_category)
    except ValueError as e:
        raise HTTPException(400, str(e))

    content = report_template_service.get_template_section(tt, tc, path)
    if content is None:
        raise HTTPException(404, "章节未找到")
    return {"path": path, "content": content}


class UpdateTemplateRequest(BaseModel):
    content: str


@router.put("/templates/{template_type}/{template_category}")
async def update_template(template_type: str, template_category: str, req: UpdateTemplateRequest):
    """更新模板内容。"""
    try:
        tt = ReportTemplateType(template_type)
        tc = TemplateCategory(template_category)
    except ValueError as e:
        raise HTTPException(400, str(e))

    try:
        doc = report_template_service.update_template(tt, tc, req.content)
        return doc.model_dump()
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/templates/import")
async def import_template(
    file: UploadFile = File(...),
    template_type: str = Form(...),
    template_category: str = Form(...),
):
    """从 Word 导入模板。"""
    try:
        tt = ReportTemplateType(template_type)
        tc = TemplateCategory(template_category)
    except ValueError as e:
        raise HTTPException(400, str(e))

    content = await file.read()
    try:
        doc = report_template_service.import_from_word(content, tt, tc)
        return doc.model_dump()
    except ValueError as e:
        raise HTTPException(422, str(e))


# ─── Helper ───

def _find_finding(finding_id: str) -> Optional[ReportReviewFinding]:
    for session_findings in _findings.values():
        for f in session_findings:
            if f.id == finding_id:
                return f
    return None
