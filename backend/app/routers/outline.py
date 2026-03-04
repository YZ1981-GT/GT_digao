"""目录相关API路由"""
import logging
from fastapi import APIRouter, HTTPException
from ..models.schemas import OutlineRequest
from ..services.openai_service import OpenAIService
from ..utils.config_manager import config_manager
from ..utils import prompt_manager
from ..utils.sse import sse_response
import json
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outline", tags=["目录管理"])


@router.post("/generate")
async def generate_outline(request: OutlineRequest):
    """生成文档目录结构（以SSE流式返回）"""
    try:
        # 创建OpenAI服务实例（内部会加载配置）
        openai_service = OpenAIService()

        if not openai_service.api_key:
            raise HTTPException(status_code=400, detail="请先配置OpenAI API密钥")
        
        async def generate():
            try:
                # 从配置读取字数（复用 OpenAIService 已加载的配置管理器）
                config = config_manager.load_config()
                word_count = config.get('word_count', 100000)
                
                # 检查是否有参考目录
                if request.uploaded_expand and request.old_outline:
                    # 有参考目录，使用参考目录生成
                    yield f"data: {json.dumps({'chunk': '', 'progress': '正在分析参考目录...'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.1)
                    
                    system_prompt, user_prompt = prompt_manager.generate_outline_with_old_prompt(
                        request.overview, 
                        request.requirements, 
                        request.old_outline,
                        request.old_document or ""
                    )
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                    
                    # 收集AI返回的内容
                    full_content = ""
                    async for chunk in openai_service.stream_chat_completion(messages, temperature=0.7, response_format={"type": "json_object"}):
                        full_content += chunk
                    
                    logger.debug(f"[参考目录] AI返回内容: {full_content[:200]}...")
                    
                    # 解析并返回结果
                    try:
                        result = json.loads(full_content)
                    except json.JSONDecodeError as e:
                        logger.error(f"[参考目录] JSON解析失败: {str(e)}")
                        raise Exception(f"参考目录解析失败: {str(e)}")
                    
                else:
                    # 没有参考目录，正常生成
                    # 发送进度：开始生成一级目录
                    yield f"data: {json.dumps({'chunk': '', 'progress': '正在生成一级目录...'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.1)
                    
                    # 进度队列：generate_outline_v2 完成每个章节时往里放消息
                    progress_queue: asyncio.Queue = asyncio.Queue()

                    async def on_progress(msg: str):
                        await progress_queue.put(msg)

                    # 后台计算主任务
                    compute_task = asyncio.create_task(openai_service.generate_outline_v2(
                        overview=request.overview,
                        requirements=request.requirements,
                        word_count=word_count,
                        progress_callback=on_progress
                    ))

                    # 在等待计算完成期间，从队列读取真实进度并推送
                    while not compute_task.done():
                        try:
                            msg = await asyncio.wait_for(progress_queue.get(), timeout=2.0)
                            yield f"data: {json.dumps({'chunk': '', 'progress': msg}, ensure_ascii=False)}\n\n"
                        except asyncio.TimeoutError:
                            # 超时没有新进度，发心跳保持连接
                            yield f"data: {json.dumps({'chunk': ''}, ensure_ascii=False)}\n\n"

                    # 计算完成后，把队列里剩余的进度消息都发出去
                    while not progress_queue.empty():
                        msg = await progress_queue.get()
                        yield f"data: {json.dumps({'chunk': '', 'progress': msg}, ensure_ascii=False)}\n\n"

                    # 计算完成
                    result = await compute_task
                
                # 发送进度：开始返回结果
                yield f"data: {json.dumps({'chunk': '', 'progress': '目录生成完成，正在返回结果...'}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.1)

                # 确保为字符串
                if isinstance(result, dict):
                    result_str = json.dumps(result, ensure_ascii=False)
                else:
                    result_str = str(result)

                # 直接发送完整结果，避免人为分片延迟
                yield f"data: {json.dumps({'chunk': result_str}, ensure_ascii=False)}\n\n"
                
                # 发送结束信号
                yield "data: [DONE]\n\n"
            except Exception as e:
                # 捕获后台任务中的异常，通过 SSE 友好返回给前端
                error_message = f"目录生成失败: {str(e)}"
                payload = {
                    "chunk": "",
                    "error": True,
                    "message": error_message,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return sse_response(generate())
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"目录生成失败: {str(e)}")
