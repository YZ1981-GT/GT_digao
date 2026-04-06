"""聊天服务 — 会话管理、RAG 注入、文档处理"""
import re
import logging
from typing import Dict, List, Optional

from .openai_service import estimate_token_count, _get_context_limit
from .knowledge_service import knowledge_service
from ..utils.config_manager import config_manager

logger = logging.getLogger(__name__)


class ChatService:
    """聊天服务 — 会话管理、RAG 注入、文档处理"""

    # 模块功能描述（注入 system prompt，使 LLM 了解可用工具）
    MODULE_DESCRIPTIONS = (
        "# 角色与格式规范\n"
        "\n"
        "你是致同AI审计助手，专为审计专业人士服务。\n"
        "\n"
        "## 【重要】回复格式强制要求\n"
        "\n"
        "你的每一条回复都**必须**严格遵守以下 Markdown 排版规范：\n"
        "\n"
        "- **禁止**输出超过3句话的连续纯文本段落，必须用空行分段\n"
        "- 回复超过2段时，**必须**使用 `##` 或 `###` 标题来划分章节\n"
        "- 列举多个要点时，**必须**使用无序列表（`-`）或有序列表（`1.`）\n"
        "- 关键术语、结论、数字用 `**加粗**` 强调\n"
        "- 引用法规条文时使用 `>` 引用块\n"
        "- 每个段落之间保留一个空行\n"
        "\n"
        "示例格式：\n"
        "```\n"
        "## 概述\n"
        "\n"
        "简要说明...\n"
        "\n"
        "## 具体要点\n"
        "\n"
        "1. **第一点**：说明内容\n"
        "2. **第二点**：说明内容\n"
        "\n"
        "## 建议\n"
        "\n"
        "- 建议一\n"
        "- 建议二\n"
        "```\n"
        "\n"
        "## 可用工作模块\n"
        "\n"
        "- 底稿复核（/复核）：上传审计底稿，多维度智能复核\n"
        "- 文档生成（/生成）：基于模板与知识库生成审计文档\n"
        "- 文档分析（/分析）：上传文档进行总结分析和汇总\n"
        "- 审计报告复核（/报告复核）：校验金额勾稽、正文规范性\n"
        "\n"
        "当用户的问题更适合使用某个模块时，在回答末尾添加 [推荐模块:review/generate/analysis/report_review]。"
    )

    # 笔记保存建议 — 本地规则关键词（不调 LLM，优先用规则检测）
    NOTE_SUGGEST_KEYWORDS = [
        r'第\d+[条号]',              # 法规条文引用
        r'准则第?\d+号',             # 会计/审计准则引用
        r'[\d,]+\.?\d*\s*[万亿元]',  # 金额数值
        r'\|.*\|.*\|',              # 表格数据
        r'```',                      # 代码块
        r'结论[：:]',                # 审计结论
        r'建议[：:]',                # 审计建议
    ]

    def __init__(self):
        pass

    def should_suggest_save_note(self, reply_content: str) -> bool:
        """本地规则检测是否建议保存到笔记（不调 LLM）"""
        return any(re.search(kw, reply_content) for kw in self.NOTE_SUGGEST_KEYWORDS)

    async def build_messages(
        self,
        messages: List[dict],
        knowledge_library_ids: Optional[List[str]] = None,
        document_context: Optional[str] = None,
        image_ocr_context: Optional[str] = None,
    ) -> List[dict]:
        """构建发送给 LLM 的完整 messages 列表

        1. 以 MODULE_DESCRIPTIONS 为基础构建 system prompt
        2. 有 knowledge_library_ids 时调用 knowledge_service.search_knowledge 注入 RAG 内容
        3. 有 document_context / image_ocr_context 时追加到 system prompt
        4. 调用 _truncate_messages 截断以适应上下文窗口
        """
        system_parts = [self.MODULE_DESCRIPTIONS]

        # 知识库 RAG 注入
        if knowledge_library_ids:
            user_query = messages[-1]["content"] if messages else ""
            try:
                kb_content = knowledge_service.search_knowledge(
                    knowledge_library_ids, user_query
                )
                if kb_content:
                    system_parts.append(f"以下是从知识库检索到的参考资料：\n{kb_content}")
            except Exception as e:
                logger.warning("知识库检索失败: %s", e)

        # 文档上下文注入
        if document_context:
            system_parts.append(f"用户上传了文档，内容如下：\n{document_context}")

        # 图片 OCR 上下文注入
        if image_ocr_context:
            system_parts.append(f"用户上传了图片，OCR 识别内容：\n{image_ocr_context}")

        system_message = {"role": "system", "content": "\n\n".join(system_parts)}

        full_messages = [system_message] + messages
        return self._truncate_messages(full_messages)

    def _truncate_messages(self, messages: List[dict]) -> List[dict]:
        """截断较早的消息以适应上下文窗口

        策略：
        1. 从 config_manager 获取当前模型的上下文窗口大小
        2. 预留 30% 给输出（与 knowledge_retriever 一致）
        3. system 消息始终保留
        4. 从最早的 user/assistant 消息开始删除，直到总 token 数在预算内
        5. 至少保留最近 2 轮对话（4 条消息）
        """
        cfg = config_manager.load_config()
        model_name = cfg.get("model_name", "default")
        context_limit = _get_context_limit(model_name)
        max_input_tokens = int(context_limit * 0.7)  # 70% 给输入

        # system 消息始终保留
        system_msg = messages[0] if messages and messages[0]["role"] == "system" else None
        history = messages[1:] if system_msg else messages

        # 计算总 token
        total = estimate_token_count(system_msg["content"]) if system_msg else 0
        for msg in history:
            total += estimate_token_count(msg["content"])

        # 从前往后删除，至少保留最近 2 轮（4 条消息）
        keep_from = 0
        while total > max_input_tokens and keep_from < len(history) - 4:
            total -= estimate_token_count(history[keep_from]["content"])
            keep_from += 1

        result = ([system_msg] if system_msg else []) + history[keep_from:]
        return result


# 全局实例
chat_service = ChatService()
