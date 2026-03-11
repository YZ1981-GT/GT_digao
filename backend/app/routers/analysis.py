"""文档分析处理 API 路由

提供文档上传解析、缓存预览编辑、章节框架生成、
逐章节内容生成（SSE）、章节修改（SSE）等端点。
"""
import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ..models.analysis_schemas import (
    AnalysisChapter,
    AnalysisDocumentInfo,
    AnalysisMode,
    AnalysisProject,
    AnalysisUploadResponse,
    ConfirmOutlineRequest,
    FormatDocumentRequest,
    GenerateChapterRequest,
    GenerateOutlineRequest,
    ReviseChapterRequest,
    UpdateDocumentRequest,
    ANALYSIS_MODE_CONFIG,
)
from ..services.analysis_service import analysis_service
from ..services.workpaper_parser import WorkpaperParser
from ..services.ocr_service import ocr_service, OCRService
from ..utils.sse import sse_response, sse_with_heartbeat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# 复用已有的文件解析器
workpaper_parser = WorkpaperParser()

# In-memory stores
_analysis_documents: dict = {}   # doc_id -> AnalysisDocumentInfo
_analysis_projects: dict = {}    # project_id -> AnalysisProject


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """上传文档并解析缓存（含智能 OCR）

    解析策略：
    - 纯文本文件（txt/md）→ 直接读取
    - 图片文件（jpg/png/tiff/bmp）→ OCR 识别
    - PDF → 检测类型：图文层直接读取，扫描版/混合做 OCR
    - Word/Excel → 常规解析 + 嵌入图片 OCR 补充
    """
    try:
        filename = file.filename or "unknown"
        ext = os.path.splitext(filename)[1].lower()

        supported = {
            '.xlsx', '.xls', '.doc', '.docx', '.pdf', '.txt', '.md',
            '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp',
        }
        if ext not in supported:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式: {ext}，支持: {', '.join(sorted(supported))}",
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        # 将原始文件保存到持久化目录，用于源文档预览
        _ANALYSIS_UPLOADS_DIR = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', '..', 'uploads', 'analysis_originals'
        )
        _ANALYSIS_UPLOADS_DIR = os.path.abspath(_ANALYSIS_UPLOADS_DIR)
        os.makedirs(_ANALYSIS_UPLOADS_DIR, exist_ok=True)

        try:
            file_size = os.path.getsize(tmp_path)
            if file_size > 50 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="文件大小超过限制（最大50MB）")

            now_iso = datetime.now(timezone.utc).isoformat()
            doc_id = str(uuid.uuid4())
            ocr_method = ""

            # 将原始文件复制到持久化目录
            persistent_name = f"{doc_id}{ext}"
            persistent_path = os.path.join(_ANALYSIS_UPLOADS_DIR, persistent_name)
            shutil.copy2(tmp_path, persistent_path)
            logger.info("原始文件已保存: %s", persistent_path)

            # ─── 纯文本文件 ───
            if ext in ('.txt', '.md'):
                with open(tmp_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content_text = f.read()
                doc = AnalysisDocumentInfo(
                    id=doc_id, filename=filename, file_format=ext,
                    file_size=file_size, content_text=content_text,
                    parsed_at=now_iso,
                    original_file_path=persistent_path,
                )
                _analysis_documents[doc_id] = doc
                return {"success": True, "message": "文档上传成功", "document": doc.model_dump()}

            # ─── 图片文件 → 纯 OCR ───
            if OCRService.is_image_file(ext):
                content_text, ocr_method = await ocr_service.smart_parse(
                    tmp_path, filename, ext
                )
                doc = AnalysisDocumentInfo(
                    id=doc_id, filename=filename, file_format=ext,
                    file_size=file_size, content_text=content_text,
                    parse_status="success" if content_text else "error",
                    error_message=None if content_text else "OCR 未能识别出文本内容",
                    parsed_at=now_iso,
                    original_file_path=persistent_path,
                )
                _analysis_documents[doc_id] = doc
                msg = f"文档上传成功（OCR: {ocr_method}）" if content_text else "图片上传成功，但 OCR 未识别到文本"
                return {"success": True, "message": msg, "document": doc.model_dump()}

            # ─── PDF / Word / Excel → 常规解析 + OCR 补充 ───
            result = await workpaper_parser.parse_file(tmp_path, filename)
            content_text = result.content_text or ""
            structured_data = result.structured_data

            # ─── PDF 特殊处理：MinerU 文字提取 + 整页 OCR 补充图片内容 ───
            if ext == '.pdf':
                from ..services.ocr_service import HAS_MINERU, HAS_PYMUPDF, HAS_TESSERACT
                has_images = False
                if HAS_PYMUPDF:
                    has_images = await OCRService._pdf_has_images(tmp_path)

                if has_images and HAS_MINERU:
                    # PDF 含图片且 MinerU 可用 → MinerU 全文解析（提取文字层+版面分析）
                    logger.info("[上传] PDF 含嵌入图片，使用 MinerU 全文解析: %s", filename)
                    mineru_text = await ocr_service.ocr_with_mineru(tmp_path)
                    if mineru_text and len(mineru_text.strip()) > 50:
                        content_text = mineru_text
                        ocr_method = "MinerU(全文解析)"
                    else:
                        logger.warning("[上传] MinerU 全文解析失败，保留 pdfplumber 结果: %s", filename)

                    # 不管 MinerU 是否成功，都对含图片的页面做整页渲染 OCR
                    # 这样截图里的文字也能被识别（MinerU 不会 OCR 嵌入图片内容）
                    if HAS_TESSERACT and HAS_PYMUPDF:
                        logger.info("[上传] 对含图片页面做整页渲染 OCR 补充: %s", filename)
                        page_ocr_text = await ocr_service.ocr_pdf_image_pages(
                            tmp_path, lang="chi_sim+eng"
                        )
                        if page_ocr_text and len(page_ocr_text.strip()) > 20:
                            content_text = content_text + "\n\n--- 图片页面 OCR 补充 ---\n" + page_ocr_text
                            ocr_method = (ocr_method or "") + "+整页OCR"

                elif has_images and HAS_TESSERACT and HAS_PYMUPDF:
                    # MinerU 不可用但有图片 → 整页渲染 OCR
                    logger.info("[上传] MinerU 不可用，使用整页渲染 OCR: %s", filename)
                    page_ocr_text = await ocr_service.ocr_pdf_image_pages(
                        tmp_path, lang="chi_sim+eng"
                    )
                    if page_ocr_text:
                        content_text = content_text + "\n\n--- 图片页面 OCR 补充 ---\n" + page_ocr_text
                        ocr_method = "整页OCR"
                else:
                    # 无图片 → 常规 smart_parse
                    ocr_text, ocr_method = await ocr_service.smart_parse(
                        tmp_path, filename, ext, skip_embedded_image_ocr=True,
                    )
                    if ocr_text and ocr_method != "direct_text(无需OCR)":
                        if not content_text.strip() or len(content_text.strip()) < 50:
                            content_text = ocr_text
                        else:
                            content_text = content_text + "\n\n--- OCR 补充内容 ---\n" + ocr_text

            elif ext in ('.docx', '.doc', '.xlsx', '.xls'):
                # Word/Excel 嵌入图片 OCR
                ocr_text, ocr_method = await ocr_service.smart_parse(
                    tmp_path, filename, ext,
                )
                if ocr_text:
                    content_text = content_text + "\n\n--- 嵌入图片 OCR 内容 ---\n" + ocr_text

            doc = AnalysisDocumentInfo(
                id=doc_id, filename=filename, file_format=ext,
                file_size=file_size, content_text=content_text,
                structured_data=structured_data,
                parse_status=result.parse_status,
                error_message=result.error_message,
                parsed_at=now_iso,
                original_file_path=persistent_path,
            )

            _analysis_documents[doc_id] = doc
            msg = "文档上传成功"
            if ocr_method and ocr_method not in ("direct_text(无需OCR)", "no_images", "unsupported"):
                msg += f"（OCR: {ocr_method}）"
            return {"success": True, "message": msg, "document": doc.model_dump()}
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("文档上传失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"文档上传失败: {str(e)}")


@router.get("/document/{doc_id}")
async def get_document(doc_id: str):
    """获取文档缓存内容（预览）"""
    doc = _analysis_documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"success": True, "document": doc.model_dump()}


@router.put("/document/{doc_id}")
async def update_document(doc_id: str, request: UpdateDocumentRequest):
    """用户编辑保存文档缓存内容"""
    doc = _analysis_documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc.content_text = request.content_text
    _analysis_documents[doc_id] = doc
    return {"success": True, "message": "文档内容已更新"}


@router.delete("/document/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档缓存及原始文件"""
    doc = _analysis_documents.get(doc_id)
    if doc and getattr(doc, 'original_file_path', None):
        try:
            if os.path.exists(doc.original_file_path):
                os.remove(doc.original_file_path)
        except Exception:
            pass
    if doc_id in _analysis_documents:
        del _analysis_documents[doc_id]
    return {"success": True, "message": "文档已删除"}


@router.get("/document/{doc_id}/original")
async def get_original_document(doc_id: str):
    """获取原始上传文件（用于源文档预览）"""
    doc = _analysis_documents.get(doc_id)
    if not doc:
        logger.warning("获取原始文件失败: 文档 %s 不存在", doc_id)
        raise HTTPException(status_code=404, detail="文档不存在")

    file_path = getattr(doc, 'original_file_path', None)
    logger.info("获取原始文件: doc_id=%s, file_path=%s", doc_id, file_path)

    if not file_path:
        raise HTTPException(status_code=404, detail="原始文件路径未记录（可能是旧版本上传的文档，请重新上传）")

    if not os.path.exists(file_path):
        logger.warning("原始文件不存在: %s", file_path)
        raise HTTPException(status_code=404, detail=f"原始文件不存在: {file_path}")

    # 根据文件格式设置 Content-Type
    content_type_map = {
        '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.txt': 'text/plain; charset=utf-8',
        '.md': 'text/plain; charset=utf-8',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.tiff': 'image/tiff', '.tif': 'image/tiff',
        '.bmp': 'image/bmp',
        '.webp': 'image/webp',
    }
    media_type = content_type_map.get(doc.file_format, 'application/octet-stream')

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=doc.filename,
    )


@router.get("/document/{doc_id}/pages")
async def get_document_pages(doc_id: str):
    """获取 PDF 文档的页数信息"""
    doc = _analysis_documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    file_path = getattr(doc, 'original_file_path', None)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")

    if doc.file_format != '.pdf':
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    try:
        import fitz
        pdf_doc = fitz.open(file_path)
        page_count = pdf_doc.page_count
        pdf_doc.close()
        return {"success": True, "page_count": page_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取 PDF 页数失败: {str(e)}")


@router.get("/document/{doc_id}/page-image/{page_num}")
async def get_page_image(doc_id: str, page_num: int):
    """将 PDF 指定页渲染为图片返回（用于 PDF 原件预览与文本映射）"""
    doc = _analysis_documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    file_path = getattr(doc, 'original_file_path', None)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")

    if doc.file_format != '.pdf':
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    try:
        import fitz
        pdf_doc = fitz.open(file_path)
        if page_num < 1 or page_num > pdf_doc.page_count:
            pdf_doc.close()
            raise HTTPException(status_code=400, detail=f"页码超出范围 (1-{pdf_doc.page_count})")

        page = pdf_doc[page_num - 1]
        # 渲染为 150 DPI 的图片（平衡清晰度和传输大小）
        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        pix = None
        pdf_doc.close()

        return Response(content=img_data, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"渲染 PDF 页面失败: {str(e)}")


@router.post("/format-document/{doc_id}")
async def format_document(doc_id: str, request: FormatDocumentRequest = None):
    """对文档内容进行智能排版处理，转换为标准 Markdown 格式（SSE 流式）

    利用 LLM 对 OCR 识别后的原始文本进行：
    - 段落识别与分割
    - 标题层级识别（# / ## / ### 等）
    - 表格结构还原
    - 列表项识别
    - 去除 OCR 噪声（乱码、重复行、页眉页脚等）
    - 保留原文内容，不做内容增删
    """
    doc = _analysis_documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    if not doc.content_text or not doc.content_text.strip():
        raise HTTPException(status_code=400, detail="文档内容为空，无法排版")

    from ..services.analysis_service import analysis_service

    async def stream():
        try:
            async for event in analysis_service.format_document_to_markdown(
                content_text=doc.content_text,
                filename=doc.filename,
                custom_instruction=request.custom_instruction if request else None,
            ):
                yield event
        except Exception as e:
            logger.error("文档排版处理失败: %s", e, exc_info=True)
            yield f'data: {json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)}\n\n'

    return sse_response(sse_with_heartbeat(stream()))


@router.post("/create-project")
async def create_project(data: dict):
    """创建分析项目（关联已上传的文档）"""
    doc_ids = data.get("document_ids", [])
    documents = []
    for did in doc_ids:
        doc = _analysis_documents.get(did)
        if doc:
            documents.append(doc)

    if not documents:
        raise HTTPException(status_code=400, detail="请至少上传一个文档")

    project_id = str(uuid.uuid4())
    project = AnalysisProject(
        id=project_id,
        documents=documents,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _analysis_projects[project_id] = project
    return {"success": True, "project_id": project_id}


@router.get("/modes")
async def get_analysis_modes():
    """获取可用的分析模式列表"""
    return {"success": True, "modes": ANALYSIS_MODE_CONFIG}


@router.post("/generate-outline")
async def generate_outline(request: GenerateOutlineRequest):
    """根据文档内容和分析模式，流式生成章节框架（SSE）"""
    project = _analysis_projects.get(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 更新项目配置
    project.mode = request.mode
    project.target_word_count = request.target_word_count
    project.custom_instruction = request.custom_instruction

    async def stream():
        try:
            async for event in analysis_service.generate_outline(
                documents=project.documents,
                mode=request.mode,
                target_word_count=request.target_word_count,
                custom_instruction=request.custom_instruction,
            ):
                yield event
        except Exception as e:
            logger.error("章节框架生成失败: %s", e, exc_info=True)
            yield f'data: {json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)}\n\n'

    return sse_response(sse_with_heartbeat(stream()))


@router.put("/confirm-outline")
async def confirm_outline(request: ConfirmOutlineRequest):
    """用户确认/编辑章节框架"""
    project = _analysis_projects.get(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 将 dict 列表转为 AnalysisChapter 列表
    def parse_chapters(items):
        result = []
        for item in items:
            children = parse_chapters(item.get("children", []) or [])
            ch = AnalysisChapter(
                id=item.get("id", ""),
                title=item.get("title", ""),
                annotation=item.get("annotation", ""),
                target_word_count=item.get("target_word_count", 800),
                children=children if children else None,
            )
            result.append(ch)
        return result

    project.outline = parse_chapters(request.outline)
    return {"success": True, "message": "章节框架已确认"}


@router.post("/generate-chapter")
async def generate_chapter(request: GenerateChapterRequest):
    """流式生成单个章节内容（SSE）"""
    project = _analysis_projects.get(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 查找目标章节
    def find_chapter(chapters, chapter_id):
        for ch in chapters:
            if ch.id == chapter_id:
                return ch
            if ch.children:
                found = find_chapter(ch.children, chapter_id)
                if found:
                    return found
        return None

    chapter = find_chapter(project.outline, request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    async def stream():
        try:
            async for event in analysis_service.generate_chapter_content(
                documents=project.documents,
                chapter=chapter,
                mode=project.mode,
                outline=project.outline,
                custom_instruction=request.custom_instruction,
            ):
                yield event
        except Exception as e:
            logger.error("章节内容生成失败: %s", e, exc_info=True)
            yield f'data: {json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)}\n\n'

    return sse_response(sse_with_heartbeat(stream()))


@router.post("/revise-chapter")
async def revise_chapter(request: ReviseChapterRequest):
    """AI修改章节内容（SSE）"""
    project = _analysis_projects.get(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    async def stream():
        try:
            async for event in analysis_service.revise_chapter_content(
                documents=project.documents,
                current_content=request.current_content,
                user_instruction=request.user_instruction,
                selected_text=request.selected_text,
                messages=request.messages,
            ):
                yield event
        except Exception as e:
            logger.error("章节修改失败: %s", e, exc_info=True)
            yield f'data: {json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)}\n\n'

    return sse_response(sse_with_heartbeat(stream()))


@router.get("/project/{project_id}")
async def get_project(project_id: str):
    """获取分析项目详情"""
    project = _analysis_projects.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"success": True, "project": project.model_dump()}
