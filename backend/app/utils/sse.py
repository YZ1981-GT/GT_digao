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

    注意：不能使用 asyncio.wait_for，因为它在超时时会 cancel 底层协程，
    导致生成器内部的 LLM 流式调用被中断。改用 asyncio.wait + FIRST_COMPLETED
    模式，超时时只发送心跳，不影响正在进行的数据获取。

    用法:
        return sse_response(sse_with_heartbeat(my_generator()))
    """
    gen_iter = generator.__aiter__()
    # 持久化的 __anext__ 任务，超时后不取消，继续等待
    next_task: asyncio.Task | None = None

    try:
        while True:
            if next_task is None:
                next_task = asyncio.ensure_future(gen_iter.__anext__())

            # 等待数据就绪或心跳超时（不取消 next_task）
            done_set, _ = await asyncio.wait(
                {next_task}, timeout=heartbeat_interval
            )

            if done_set:
                # 数据就绪
                task = done_set.pop()
                next_task = None  # 重置，下次循环创建新任务
                try:
                    data = task.result()
                    yield data
                except StopAsyncIteration:
                    return
            else:
                # 超时 → 发送心跳注释，next_task 继续运行
                yield ": heartbeat\n\n"
    finally:
        # 清理：如果还有未完成的任务，取消它
        if next_task is not None and not next_task.done():
            next_task.cancel()
            try:
                await next_task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
