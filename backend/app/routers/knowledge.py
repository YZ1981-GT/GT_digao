"""知识库API路由"""
import json
import logging
import os
import tempfile
import aiofiles
from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from typing import List, Optional
from ..services.knowledge_service import knowledge_service
from ..services.file_service import FileService
from ..utils.sse import sse_response, sse_with_heartbeat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["知识库管理"])


@router.get("/libraries")
async def get_libraries():
    """获取所有知识库列表"""
    try:
        data = knowledge_service.get_libraries()
        libs = data['libraries']
        total_cached = data['total_cached']
        max_cache = data['max_cache']
        return {
            "success": True,
            "libraries": libs,
            "cache_info": {
                "total_cached": total_cached,
                "max_cache": max_cache,
                "usage_percent": round(total_cached / max_cache * 100, 1) if max_cache > 0 else 0,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{library_id}")
async def get_documents(library_id: str):
    """获取某个知识库的文档列表"""
    try:
        docs = knowledge_service.get_documents(library_id)
        return {"success": True, "documents": docs}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/{library_id}")
async def upload_document(library_id: str, file: UploadFile = File(...)):
    """上传文档到知识库"""
    try:
        filename = file.filename or "未命名文档"
        ext = filename.lower().split('.')[-1] if '.' in filename else ""
        
        # 文件类型白名单校验
        allowed_extensions = ['pdf', 'docx', 'doc', 'txt', 'md', 'markdown', 'xlsx', 'xls']
        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: .{ext}，支持的格式: {', '.join('.' + e for e in allowed_extensions)}"
            )
        
        # 将文件保存到临时目录
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp_path = tmp.name
        
        async with aiofiles.open(tmp_path, 'wb') as f:
            file_content = await file.read()
            await f.write(file_content)
        
        try:
            # 根据文件类型提取文本
            if ext == 'pdf':
                content = await FileService.extract_text_from_pdf(tmp_path)
            elif ext in ['doc', 'docx']:
                content = await FileService.extract_text_from_docx(tmp_path)
            elif ext in ['xlsx', 'xls']:
                content = await FileService.extract_text_from_excel(tmp_path)
            elif ext in ['txt', 'md', 'markdown']:
                # 支持 .txt 和 .md 格式，尝试多种编码
                try:
                    content = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        content = file_content.decode('gbk')
                    except UnicodeDecodeError:
                        content = file_content.decode('utf-8', errors='ignore')
            else:
                # 其他文本格式也尝试解码
                try:
                    content = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    content = file_content.decode('utf-8', errors='ignore')
        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        
        # 直接保存原始文档内容（不做AI压缩处理，保留全文）
        logger.info(f"[知识库] 文档提取完成: {filename}, 原始内容长度: {len(content)} 字符")
        
        # 上传时自动做本地排版（毫秒级，不影响上传速度）
        try:
            from ..services.analysis_service import AnalysisService
            formatted = AnalysisService._local_format_to_markdown(content)
            if formatted and len(formatted) > len(content) * 0.3:
                logger.info(f"[知识库] 本地排版完成: {filename}, {len(content)} -> {len(formatted)} 字符")
                content = formatted
            else:
                logger.warning(f"[知识库] 本地排版结果异常，使用原始内容: {filename}")
        except Exception as e:
            logger.warning(f"[知识库] 本地排版失败，使用原始内容: {filename}, {e}")
        
        # 添加到知识库
        doc = knowledge_service.add_document(library_id, filename, content)
        return {"success": True, "document": doc, "message": f"文档 {filename} 已添加（{len(content)} 字符）"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.delete("/documents/{library_id}/{doc_id}")
async def delete_document(library_id: str, doc_id: str):
    """删除知识库中的文档"""
    try:
        success = knowledge_service.delete_document(library_id, doc_id)
        if success:
            return {"success": True, "message": "文档已删除"}
        else:
            raise HTTPException(status_code=404, detail="文档不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from pydantic import BaseModel


class SearchRequest(BaseModel):
    library_ids: List[str]
    query: str


class UpdateDocumentRequest(BaseModel):
    content: str


@router.put("/documents/{library_id}/{doc_id}")
async def update_document(library_id: str, doc_id: str, req: UpdateDocumentRequest):
    """更新知识库文档内容"""
    try:
        success = knowledge_service.update_document_content(library_id, doc_id, req.content)
        if success:
            return {"success": True, "message": "文档已更新", "size": len(req.content)}
        else:
            raise HTTPException(status_code=404, detail="文档不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-folder/report_templates")
async def upload_report_template_folder(
    files: List[UploadFile] = File(...),
    folder_name: str = Form(""),
):
    """上传报告模板文件夹。

    通过 folder_name 自动识别模板类型（国企版/上市版）。
    文件夹中的文档按 report_body / notes 分类存入知识库。
    支持 .docx, .doc, .txt, .md, .xlsx, .xls, .pdf 格式。
    """
    from ..services.report_template_service import report_template_service
    from ..models.audit_schemas import ReportTemplateType, TemplateCategory

    # 从 folder_name 识别模板类型
    template_type = None
    folder_lower = folder_name.lower()
    if "国企" in folder_name or "soe" in folder_lower:
        template_type = ReportTemplateType.SOE
    elif "上市" in folder_name or "listed" in folder_lower:
        template_type = ReportTemplateType.LISTED

    if not template_type:
        raise HTTPException(
            400,
            f"无法从文件夹名称 '{folder_name}' 识别模板类型。"
            "文件夹名称需包含 '国企' 或 '上市' 关键字。"
        )

    allowed_extensions = ['pdf', 'docx', 'doc', 'txt', 'md', 'markdown', 'xlsx', 'xls']
    results = []
    processed = 0

    for file in files:
        filename = file.filename or "未命名文档"
        ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ""
        if ext not in allowed_extensions:
            results.append({"name": filename, "success": False, "message": f"不支持的格式: .{ext}"})
            continue

        # 从文件名/路径推断分类（report_body / notes）
        name_lower = filename.lower()
        # 路径中可能包含子文件夹信息（浏览器 webkitRelativePath）
        full_path_lower = (file.filename or "").lower()
        if "附注" in filename or "notes" in name_lower or "附注" in full_path_lower:
            category = TemplateCategory.NOTES
        else:
            category = TemplateCategory.REPORT_BODY

        # 提取文本内容
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp_path = tmp.name
        try:
            file_content = await file.read()
            async with aiofiles.open(tmp_path, 'wb') as f:
                await f.write(file_content)

            if ext == 'pdf':
                content = await FileService.extract_text_from_pdf(tmp_path)
            elif ext in ['doc', 'docx']:
                content = await FileService.extract_text_from_docx(tmp_path)
            elif ext in ['xlsx', 'xls']:
                content = await FileService.extract_text_from_excel(tmp_path)
            elif ext in ['txt', 'md', 'markdown']:
                try:
                    content = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        content = file_content.decode('gbk')
                    except UnicodeDecodeError:
                        content = file_content.decode('utf-8', errors='ignore')
            else:
                content = file_content.decode('utf-8', errors='ignore')

            if not content or not content.strip():
                results.append({"name": filename, "success": False, "message": "文件内容为空"})
                continue

            # 上传时自动做本地排版
            try:
                from ..services.analysis_service import AnalysisService
                formatted = AnalysisService._local_format_to_markdown(content)
                if formatted and len(formatted) > len(content) * 0.3:
                    content = formatted
            except Exception:
                pass  # 排版失败不影响上传

            # 每个原始文件单独存一条到知识库（保留原始文档）
            added_doc = knowledge_service.add_document(
                "report_templates",
                filename,
                content,
            )

            # 同时更新 report_template_service 的结构化合并模板（内存缓存，不再存知识库）
            try:
                existing = report_template_service.get_template(template_type, category)
                if existing and existing.full_content.strip():
                    merged = existing.full_content + f"\n\n# {filename}\n\n{content}"
                else:
                    merged = f"# {filename}\n\n{content}"
                # 直接更新内存缓存，不持久化到知识库（避免重复）
                sections = report_template_service._parse_markdown_sections(merged)
                from datetime import datetime as _dt
                from ..models.audit_schemas import ReportTemplateDocument
                now = _dt.now().isoformat()
                doc = ReportTemplateDocument(
                    template_type=template_type,
                    template_category=category,
                    full_content=merged,
                    sections=sections,
                    version=now,
                    updated_at=now,
                )
                key = (template_type.value, category.value)
                report_template_service._cache[key] = doc
                # 清除该模板的章节缓存
                to_remove = [k for k in report_template_service._section_cache
                             if k[0] == template_type.value and k[1] == category.value]
                for k in to_remove:
                    del report_template_service._section_cache[k]
            except Exception as e:
                logger.warning("更新结构化模板缓存失败: %s", e)

            processed += 1
            results.append({
                "name": filename,
                "success": True,
                "message": f"已导入为 {template_type.value}/{category.value}",
                "doc_id": added_doc.get("id") if isinstance(added_doc, dict) else None,
            })
        except Exception as e:
            results.append({"name": filename, "success": False, "message": str(e)})
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    return {
        "success": processed > 0,
        "template_type": template_type.value,
        "processed": processed,
        "total": len(files),
        "results": results,
        "message": f"已导入 {processed}/{len(files)} 个文件到 {template_type.value} 模板",
    }


class FormatDocumentRequest(BaseModel):
    custom_instruction: Optional[str] = None


@router.post("/local-format/{library_id}/{doc_id}")
async def local_format_document(library_id: str, doc_id: str):
    """使用本地脚本将文档内容整理为 Markdown 格式（同步，不调用 LLM）"""
    try:
        content = knowledge_service.get_document_content(library_id, doc_id)
        if content is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        if not content.strip():
            raise HTTPException(status_code=400, detail="文档内容为空")

        from ..services.analysis_service import AnalysisService
        formatted = AnalysisService._local_format_to_markdown(content)
        return {"success": True, "content": formatted}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("本地排版处理失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"本地排版处理失败: {str(e)}")


@router.post("/ai-format/{library_id}/{doc_id}")
async def ai_format_document(library_id: str, doc_id: str, request: FormatDocumentRequest = None):
    """使用 AI 将文档内容精细化整理为 Markdown 格式（SSE 流式）"""
    content = knowledge_service.get_document_content(library_id, doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not content.strip():
        raise HTTPException(status_code=400, detail="文档内容为空")

    # 获取文档 filename
    docs = knowledge_service.get_documents(library_id)
    filename = "未知文档"
    for doc in docs:
        if doc.get("id") == doc_id:
            filename = doc.get("filename", filename)
            break

    from ..services.analysis_service import analysis_service

    async def stream():
        try:
            async for event in analysis_service.format_document_to_markdown(
                content_text=content,
                filename=filename,
                custom_instruction=request.custom_instruction if request else None,
            ):
                yield event
        except Exception as e:
            logger.error("AI排版处理失败: %s", e, exc_info=True)
            yield f'data: {json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)}\n\n'

    return sse_response(sse_with_heartbeat(stream()))


@router.post("/search")
async def search_knowledge(req: SearchRequest):
    """搜索知识库内容"""
    try:
        content = knowledge_service.search_knowledge(req.library_ids, req.query)
        return {"success": True, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preview/{library_id}/{doc_id}")
async def preview_document(library_id: str, doc_id: str, max_chars: int = 0):
    """预览文档内容"""
    try:
        content = knowledge_service.get_document_content(library_id, doc_id)
        if content is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        # 截断过长内容（max_chars=0 表示不截断）
        truncated = max_chars > 0 and len(content) > max_chars
        preview = content[:max_chars] if truncated else content
        return {
            "success": True,
            "content": preview,
            "total_length": len(content),
            "truncated": truncated
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


