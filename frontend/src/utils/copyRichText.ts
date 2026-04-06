import { markdownToHtml } from './markdownToHtml';

/**
 * 将 Markdown 内容以富文本格式复制到剪贴板。
 * 同时写入 text/html（保留格式）和 text/plain（Markdown 原文）。
 * 如果 Clipboard API 不可用或富文本写入失败，回退到纯文本复制。
 */
export async function copyRichText(markdown: string): Promise<boolean> {
  try {
    const html = markdownToHtml(markdown);
    await navigator.clipboard.write([
      new ClipboardItem({
        'text/html': new Blob([html], { type: 'text/html' }),
        'text/plain': new Blob([markdown], { type: 'text/plain' }),
      }),
    ]);
    return true;
  } catch {
    // 回退：复制纯文本
    try {
      await navigator.clipboard.writeText(markdown);
      return true;
    } catch {
      return false;
    }
  }
}
