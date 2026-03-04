"""知识库API路由"""
import logging
import os
import tempfile
import aiofiles
from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import List
from ..services.knowledge_service import knowledge_service
from ..services.file_service import FileService

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
        allowed_extensions = ['pdf', 'docx', 'doc', 'txt', 'md', 'markdown']
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
        
        # 添加到知识库（直接使用原始内容）
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


@router.post("/search")
async def search_knowledge(req: SearchRequest):
    """搜索知识库内容"""
    try:
        content = knowledge_service.search_knowledge(req.library_ids, req.query)
        return {"success": True, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preview/{library_id}/{doc_id}")
async def preview_document(library_id: str, doc_id: str, max_chars: int = 5000):
    """预览文档内容"""
    try:
        content = knowledge_service.get_document_content(library_id, doc_id)
        if content is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        # 截断过长内容
        truncated = len(content) > max_chars
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


