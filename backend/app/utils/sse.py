"""SSE (Server-Sent Events) 相关工具"""
import asyncio
from typing import AsyncGenerator, Any, Dict, Optional

from fastapi.responses import StreamingResponse


DEFAULT_SSE_HEADERS: Dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Content-Type": "text/event-stream",
    "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
}


def sse_response(
    generator: AsyncGenerator[str, Any],
    extra_headers: Optional[Dict[str, str]] = None,
) -> StreamingResponse:
    """
    包装 SSE 异步生成器为 StreamingResponse，统一 headers 和 media_type。

    Args:
        generator: 异步生成器，yield 已经带好 "data: ..." 和 "\n\n" 的字符串
        extra_headers: 额外需要添加或覆盖的响应头
    """
    headers = DEFAULT_SSE_HEADERS.copy()
    if extra_headers:
        headers.update(extra_headers)

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers=headers,
    )


async def sse_with_heartbeat(
    generator: AsyncGenerator[str, Any],
    heartbeat_interval: float = 15.0,
) -> AsyncGenerator[str, Any]:
    """
    为 SSE 生成器添加心跳，防止长时间无数据时连接被代理或浏览器断开。

    每隔 heartbeat_interval 秒发送一条 SSE 注释（: heartbeat），
    浏览器 EventSource 会忽略注释行，不影响业务逻辑。

    用法:
        return sse_response(sse_with_heartbeat(my_generator()))
    """
    done = False
    gen_iter = generator.__aiter__()

    while not done:
        try:
            # 使用 asyncio.wait_for 替代 async_timeout，无需额外依赖
            data = await asyncio.wait_for(gen_iter.__anext__(), timeout=heartbeat_interval)
            yield data
        except asyncio.TimeoutError:
            # 超时 → 发送心跳注释
            yield ": heartbeat\n\n"
        except StopAsyncIteration:
            done = True
