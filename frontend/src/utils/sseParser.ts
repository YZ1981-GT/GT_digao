/**
 * 健壮的 SSE 流解析器
 * 处理跨 chunk 的 data 行拼接问题
 */
export class SSEParser {
  private buffer = '';

  /**
   * 将新的 chunk 喂入解析器，返回解析出的完整 data 行
   */
  feed(chunk: string): string[] {
    this.buffer += chunk;
    const results: string[] = [];

    // 按换行符分割，但保留最后一个不完整的行在 buffer 中
    const lines = this.buffer.split('\n');
    // 最后一个元素可能是不完整的行
    this.buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('data: ')) {
        results.push(trimmed.slice(6));
      }
    }

    return results;
  }

  /**
   * 刷新缓冲区中剩余的内容
   */
  flush(): string[] {
    const results: string[] = [];
    if (this.buffer.trim().startsWith('data: ')) {
      results.push(this.buffer.trim().slice(6));
    }
    this.buffer = '';
    return results;
  }

  reset(): void {
    this.buffer = '';
  }
}

/**
 * 处理 SSE 流的通用函数
 */
export async function processSSEStream(
  response: Response,
  onData: (data: string) => void,
  onDone?: () => void,
  onError?: (error: Error) => void,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('无法读取响应流');
  }

  const decoder = new TextDecoder();
  const parser = new SSEParser();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const dataLines = parser.feed(chunk);

      for (const data of dataLines) {
        if (data === '[DONE]') {
          onDone?.();
          return;
        }
        onData(data);
      }
    }

    // 处理缓冲区中剩余的数据
    const remaining = parser.flush();
    for (const data of remaining) {
      if (data === '[DONE]') {
        onDone?.();
        return;
      }
      onData(data);
    }

    onDone?.();
  } catch (error) {
    onError?.(error instanceof Error ? error : new Error(String(error)));
  }
}
