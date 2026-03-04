"""内容相关API路由"""
import logging
from fastapi import APIRouter, HTTPException
from ..models.schemas import ChapterContentRequest, ChapterRevisionRequest
from ..services.openai_service import OpenAIService
from ..utils.sse import sse_response, sse_with_heartbeat
import json
from pydantic import BaseModel
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/content", tags=["内容管理"])


class PreloadKnowledgeRequest(BaseModel):
    """知识库预加载请求"""
    library_ids: Optional[List[str]] = None
    library_docs: Optional[Dict[str, List[str]]] = None


@router.post("/preload-knowledge")
async def preload_knowledge(request: PreloadKnowledgeRequest):
    """流式预加载知识库内容到内存缓存，实时返回读取进度。"""
    try:
        openai_service = OpenAIService()
        if not openai_service.api_key:
            raise HTTPException(status_code=400, detail="请先配置API密钥")
        
        async def generate():
            try:
                for event in openai_service.preload_knowledge_stream(
                    library_ids=request.library_ids,
                    library_docs=request.library_docs,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        
        return sse_response(generate())
    except Exception as e:
        logger.error(f"知识库预加载失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"知识库预加载失败: {str(e)}")


@router.post("/generate-chapter-stream")
async def generate_chapter_content_stream(request: ChapterContentRequest):
    """流式为单个章节生成内容"""
    try:
        # 创建OpenAI服务实例（内部会加载配置）
        openai_service = OpenAIService()
        
        if not openai_service.api_key:
            raise HTTPException(status_code=400, detail="请先配置OpenAI API密钥")
        
        async def generate():
            try:
                # 发送开始信号
                yield f"data: {json.dumps({'status': 'started', 'message': '开始生成章节内容...'}, ensure_ascii=False)}\n\n"
                
                # 发送知识库读取进度
                yield f"data: {json.dumps({'status': 'loading_knowledge', 'message': '正在读取知识库...'}, ensure_ascii=False)}\n\n"
                
                # 使用章节自身的目标字数，如果没有则使用默认值
                target_words_per_chapter = request.chapter.get('target_word_count', 1500)
                logger.info(f"[内容生成] 章节: {request.chapter.get('title', '未知')} 目标字数: {target_words_per_chapter}")
                
                # 流式生成章节内容
                full_content = ""
                async for chunk in openai_service._generate_chapter_content(
                    chapter=request.chapter,
                    parent_chapters=request.parent_chapters,
                    sibling_chapters=request.sibling_chapters,
                    project_overview=request.project_overview,
                    target_word_count=target_words_per_chapter,
                    library_ids=request.library_ids,
                    library_docs=request.library_docs,
                    web_references=request.web_references
                ):
                    full_content += chunk
                    # 只发送增量 chunk，前端自行拼接，避免 O(n²) 传输
                    yield f"data: {json.dumps({'status': 'streaming', 'content': chunk}, ensure_ascii=False)}\n\n"
                
                # 发送完成信号
                yield f"data: {json.dumps({'status': 'completed', 'content': full_content}, ensure_ascii=False)}\n\n"
                
            except Exception as e:
                # 发送错误信息
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            
            # 发送结束信号
            yield "data: [DONE]\n\n"
        
        return sse_response(sse_with_heartbeat(generate()))
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"章节内容生成失败: {str(e)}")



@router.post("/revise-chapter-stream")
async def revise_chapter_stream(request: ChapterRevisionRequest):
    """流式修改章节内容（支持对话）"""
    try:
        # 创建OpenAI服务实例（内部会加载配置）
        openai_service = OpenAIService()
        
        if not openai_service.api_key:
            raise HTTPException(status_code=400, detail="请先配置OpenAI API密钥")
        
        logger.info(f"[章节修改] 开始修改章节: {request.chapter.get('title', '未知')}")
        logger.debug(f"[章节修改] 用户指令: {request.user_instruction}")
        logger.debug(f"[章节修改] 历史消息数: {len(request.messages)}")
        
        async def generate():
            try:
                # 发送开始信号
                yield f"data: {json.dumps({'status': 'started', 'message': '开始修改章节内容...'}, ensure_ascii=False)}\n\n"
                
                # 流式修改章节内容
                full_content = ""
                async for chunk in openai_service.revise_chapter_content(
                    chapter=request.chapter,
                    current_content=request.current_content,
                    messages=[m.model_dump() for m in request.messages],
                    user_instruction=request.user_instruction,
                    project_overview=request.project_overview,
                    parent_chapters=request.parent_chapters,
                    sibling_chapters=request.sibling_chapters,
                    library_docs=request.library_docs,
                    web_references=request.web_references
                ):
                    full_content += chunk
                    # 只发送增量 chunk，前端自行拼接
                    yield f"data: {json.dumps({'status': 'streaming', 'content': chunk}, ensure_ascii=False)}\n\n"
                
                logger.info(f"[章节修改] 修改完成，内容长度: {len(full_content)}")
                
                # 发送完成信号
                yield f"data: {json.dumps({'status': 'completed', 'content': full_content}, ensure_ascii=False)}\n\n"
                
            except Exception as e:
                logger.error(f"[章节修改] 错误: {str(e)}", exc_info=True)
                # 发送错误信息
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            
            # 发送结束信号
            yield "data: [DONE]\n\n"
        
        return sse_response(sse_with_heartbeat(generate()))
        
    except Exception as e:
        logger.error(f"[章节修改] 路由错误: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"章节内容修改失败: {str(e)}")
