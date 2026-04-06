import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import rehypeStringify from 'rehype-stringify';
import type { Root, Element } from 'hast';
import type { Plugin } from 'unified';

/**
 * 内联样式映射 — 确保粘贴到 Word / 邮件客户端时格式正确。
 * 只对需要的标签注入关键样式，不影响纯文本回退。
 */
const INLINE_STYLES: Record<string, string> = {
  table: 'border-collapse:collapse;width:100%;margin:8px 0;font-size:14px;',
  th: 'border:1px solid #999;padding:6px 10px;text-align:left;background-color:#f0f0f0;font-weight:600;',
  td: 'border:1px solid #ccc;padding:6px 10px;text-align:left;',
  blockquote: 'margin:10px 0;padding:8px 14px;border-left:3px solid #a06dff;background-color:#f9f7fc;color:#666;',
  pre: 'margin:10px 0;padding:12px 14px;background-color:#f8f8f8;border:1px solid #e8e8e8;border-radius:6px;overflow-x:auto;font-family:Consolas,Monaco,monospace;font-size:13px;',
  code: 'font-family:Consolas,Monaco,monospace;font-size:13px;background-color:#f5f5f5;padding:1px 4px;border-radius:3px;',
  h1: 'font-size:18px;font-weight:600;margin:14px 0 6px;',
  h2: 'font-size:16px;font-weight:600;margin:12px 0 6px;',
  h3: 'font-size:15px;font-weight:600;margin:10px 0 4px;',
  hr: 'border:none;border-top:1px solid #ddd;margin:12px 0;',
};

/**
 * rehype 插件：为指定 HTML 标签注入内联 style 属性。
 * 这样剪贴板中的 HTML 不依赖外部 CSS，粘贴到任何富文本环境都能保留格式。
 */
const rehypeInlineStyles: Plugin<[], Root> = () => {
  const visit = (node: Root | Element) => {
    if ('children' in node) {
      for (const child of node.children) {
        if (child.type === 'element') {
          const tag = child.tagName;
          if (INLINE_STYLES[tag]) {
            child.properties = child.properties || {};
            // 追加而非覆盖，保留已有 style
            const existing = (child.properties.style as string) || '';
            child.properties.style = existing ? `${existing};${INLINE_STYLES[tag]}` : INLINE_STYLES[tag];
          }
          // pre > code 不需要 code 的背景色
          if (tag === 'pre') {
            for (const grandchild of child.children) {
              if (grandchild.type === 'element' && grandchild.tagName === 'code') {
                grandchild.properties = grandchild.properties || {};
                grandchild.properties.style = 'font-family:Consolas,Monaco,monospace;font-size:13px;background:none;padding:0;';
              }
            }
          }
          visit(child);
        }
      }
    }
  };
  return (tree: Root) => { visit(tree); };
};

/**
 * 将 Markdown 文本转换为带内联样式的 HTML 字符串。
 * 用于富文本复制（ClipboardItem text/html），确保粘贴到 Word / 邮件客户端时保留格式。
 */
export function markdownToHtml(markdown: string): string {
  const result = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkRehype)
    .use(rehypeInlineStyles)
    .use(rehypeStringify)
    .processSync(markdown);
  return String(result);
}
