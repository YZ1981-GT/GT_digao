---
inclusion: always
---

# 网页访问规则

当需要搜索或访问网页获取内容时，自动在目标 URL 前加上 `r.jina.ai/` 前缀，以通过 Jina Reader 获取干净的网页文本内容。

例如：
- 原始链接：`https://example.com/article`
- 实际访问：`https://r.jina.ai/https://example.com/article`

如果当前调用的技能（Skill）本身已经使用了 `r.jina.ai/` 前缀，则不重复添加，直接继续执行即可。
