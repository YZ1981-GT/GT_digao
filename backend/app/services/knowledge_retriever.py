"""知识库分批缓存与检索服务

核心策略：
1. 预加载阶段：完整读取所有知识库文档，按段落切分
2. 分批阶段：按 token 预算将片段分成多个 batch，每个 batch 打上标记存入缓存
3. 建立倒排索引：keyword → batch_id 列表，方便按章节快速定位相关 batch
4. 调用阶段：根据章节标题/描述查索引，直接取出相关 batch 的已格式化文本

缓存结构：
    _batches[batch_id] = {
        'id': 'B001',
        'chunks': [KnowledgeChunk, ...],
        'tokens': 3200,
        'formatted': '已格式化的文本，可直接注入 prompt',
        'tags': {'货币资金', '银行函证', ...},  # 该 batch 的关键词标记
        'lib_names': {'会计准则库', '审计程序库'},  # 来源知识库
        'filenames': {'准则01.pdf', '程序02.docx'},  # 来源文件
    }
"""

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数"""
    if not text:
        return 0
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - chinese
    return int(chinese * 1.5 + other * 0.4)


_STOP_WORDS = frozenset({
    '的', '和', '与', '或', '在', '是', '有', '为', '等', '及', '对', '中',
    '上', '下', '了', '着', '过', '到', '从', '向', '把', '被', '让', '给',
    '用', '以', '按', '将', '能', '可', '要', '会', '应', '请', '不', '也',
    '都', '就', '而', '但', '如', '若', '则', '其', '之', '所', '于', '此',
    '该', '本', '各', '每', '已', '未', '无', '非', '更', '最', '很', '较',
    '进行', '相关', '情况', '内容', '方面', '包括', '以及', '通过', '根据',
    '确保', '是否', '需要', '要求', '以下', '如下', '具体', '主要', '重点',
    # 审计领域高频词（几乎每个 batch 都有，区分度极低）
    '审计', '检查', '测试', '程序', '工作', '报告', '项目', '公司',
    '企业', '单位', '人员', '管理', '执行', '实施', '分析', '评估',
    '记录', '文件', '资料', '信息', '数据', '结果', '问题', '意见',
    '说明', '规定', '标准', '制度', '流程', '方法', '措施', '方案',
})


class KnowledgeChunk:
    """知识库文档片段"""
    __slots__ = ('doc_id', 'lib_id', 'lib_name', 'filename', 'text', 'tokens', 'keywords')

    def __init__(self, doc_id: str, lib_id: str, lib_name: str,
                 filename: str, text: str):
        self.doc_id = doc_id
        self.lib_id = lib_id
        self.lib_name = lib_name
        self.filename = filename
        self.text = text
        self.tokens = _estimate_tokens(text)
        self.keywords = self._extract_keywords(text)

    @staticmethod
    def _extract_keywords(text: str) -> set:
        cn_words = set(re.findall(r'[\u4e00-\u9fff]{2,6}', text))
        en_words = set(w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text))
        cn_words -= _STOP_WORDS
        return cn_words | en_words


class KnowledgeRetriever:
    """知识库分批缓存与检索器

    预加载时就把内容分好批、打好标记、格式化好文本存入缓存。
    调用时按章节关键词查索引，直接取出已格式化的 batch 文本拼接即可。
    """

    MIN_CHUNK_CHARS = 50
    MAX_CHUNK_CHARS = 2000

    def __init__(self):
        # ── 原始片段 ──
        self._chunks: List[KnowledgeChunk] = []

        # ── 分批缓存（核心） ──
        # batch_id -> batch 元数据
        self._batches: Dict[str, Dict[str, Any]] = {}
        # batch 的有序 ID 列表（保持插入顺序）
        self._batch_ids: List[str] = []

        # ── 倒排索引：keyword -> set(batch_id) ──
        self._tag_index: Dict[str, set] = defaultdict(set)

        # ── 元数据 ──
        self._total_docs = 0
        self._total_chars = 0
        self._total_tokens = 0
        self._batch_token_limit = 0  # 每个 batch 的 token 上限
        self._loaded = False
        self._cache_key = ''

        # ── 模型相关元数据（原 _knowledge_cache 的职责） ──
        self._use_retrieval = False   # 是否使用检索模式（大型知识库）
        self._max_kb_tokens = 0       # 每个章节可用的知识库 token 预算
        self._model_name = ''         # 缓存对应的模型名
        self._all_formatted = ''      # 全量注入模式下的预格式化文本

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def use_retrieval(self) -> bool:
        return self._use_retrieval

    @property
    def max_kb_tokens(self) -> int:
        return self._max_kb_tokens

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            'loaded': self._loaded,
            'total_docs': self._total_docs,
            'total_chunks': len(self._chunks),
            'total_chars': self._total_chars,
            'total_tokens': self._total_tokens,
            'total_batches': len(self._batches),
            'batch_token_limit': self._batch_token_limit,
            'use_retrieval': self._use_retrieval,
            'max_kb_tokens': self._max_kb_tokens,
        }

    def clear(self):
        self._chunks.clear()
        self._batches.clear()
        self._batch_ids.clear()
        self._tag_index.clear()
        self._total_docs = 0
        self._total_chars = 0
        self._total_tokens = 0
        self._batch_token_limit = 0
        self._loaded = False
        self._cache_key = ''
        self._use_retrieval = False
        self._max_kb_tokens = 0
        self._model_name = ''
        self._all_formatted = ''
        logger.info("[知识库缓存] 已清除")

    def configure_for_model(self, model_name: str, context_limit: int, output_reserve_ratio: float = 0.3):
        """根据模型上下文配置检索策略（全量注入 vs 智能检索）。

        在 preload 完成后调用，决定后续 get_knowledge_for_chapter 的行为。
        """
        self._model_name = model_name
        max_input_tokens = int(context_limit * (1 - output_reserve_ratio))
        fixed_overhead = 3000  # system prompt + user prompt 固定开销
        self._max_kb_tokens = max(max_input_tokens - fixed_overhead, 2000)

        # 知识库总 token < 每章节预算的 80% → 全量注入；否则智能检索
        self._use_retrieval = self._total_tokens > int(self._max_kb_tokens * 0.8)

        if self._use_retrieval:
            self._all_formatted = ''
            logger.info(
                f"[知识库] 启用智能检索模式（{self._total_tokens} tokens > 预算 {self._max_kb_tokens} 的 80%）"
            )
        else:
            self._all_formatted = self.get_all_formatted()
            logger.info(
                f"[知识库] 使用全量注入模式（{self._total_tokens} tokens <= 预算 80%）"
            )

    def get_knowledge_for_chapter(self, chapter_title: str, chapter_description: str = '') -> str:
        """统一的知识库获取入口：根据当前模式返回全量或检索结果。

        全量注入模式：返回预格式化的完整文本。
        检索模式：根据章节标题和描述检索相关片段。
        """
        if not self._loaded:
            return ''

        if not self._use_retrieval:
            return self._all_formatted

        result = self.get_formatted_for_chapter(
            chapter_title=chapter_title,
            chapter_description=chapter_description,
            max_tokens=self._max_kb_tokens,
        )
        logger.info(f"[知识库检索] 章节 '{chapter_title}' 检索到 {len(result)} 字符")
        return result

    # ══════════════════════════════════════════════
    #  预加载：读取 → 切分 → 分批 → 打标记 → 格式化 → 存缓存
    # ══════════════════════════════════════════════

    def preload(
        self,
        knowledge_service,
        library_ids: Optional[List[str]] = None,
        library_docs: Optional[Dict[str, List[str]]] = None,
        batch_token_limit: int = 6000,
        progress_callback=None,
    ):
        """预加载知识库：完整读取 → 分批存缓存 → 建索引。

        Args:
            knowledge_service: KnowledgeService 实例
            library_ids: 要加载的知识库 ID 列表
            library_docs: 指定的知识库文档 {lib_id: [doc_id, ...]}
            batch_token_limit: 每个 batch 的 token 上限（应小于模型上下文预算）
            progress_callback: 进度回调

        Yields:
            dict 进度事件
        """
        import hashlib
        cache_input = str(library_ids) + str(library_docs) + str(batch_token_limit)
        new_key = hashlib.md5(cache_input.encode()).hexdigest()
        if self._loaded and self._cache_key == new_key:
            yield {
                'status': 'cached',
                'message': f'知识库已缓存（{self._total_docs}个文档，{len(self._batches)}个批次）',
                **self.stats,
            }
            return

        self.clear()
        self._cache_key = new_key
        self._batch_token_limit = batch_token_limit

        yield {'status': 'start', 'message': '开始读取知识库...'}

        # ── 第1步：读取所有文档 ──
        doc_contents_full = []

        if library_docs:
            total = sum(len(ids) for ids in library_docs.values())
            loaded = 0
            for lib_id, doc_ids in library_docs.items():
                if lib_id not in knowledge_service.LIBRARIES:
                    continue
                lib_name = knowledge_service.LIBRARIES[lib_id]['name']
                docs_index = knowledge_service._load_index(lib_id)
                doc_map = {d['id']: d for d in docs_index}
                for doc_id in doc_ids:
                    content = knowledge_service._get_cached_content(lib_id, doc_id)
                    if not content:
                        continue
                    doc_info = doc_map.get(doc_id, {})
                    filename = doc_info.get('filename', '未知文档')
                    doc_contents_full.append((doc_id, lib_id, lib_name, filename, content))
                    loaded += 1
                    if progress_callback:
                        progress_callback(loaded, total, filename, lib_name)
                    yield {'status': 'reading', 'loaded': loaded, 'total': total,
                           'filename': filename, 'lib_name': lib_name}
        else:
            if library_ids is None:
                library_ids = list(knowledge_service.LIBRARIES.keys())
            total = 0
            for lib_id in library_ids:
                if lib_id in knowledge_service.LIBRARIES:
                    total += len(knowledge_service._load_index(lib_id))
            loaded = 0
            for lib_id in library_ids:
                if lib_id not in knowledge_service.LIBRARIES:
                    continue
                lib_name = knowledge_service.LIBRARIES[lib_id]['name']
                docs = knowledge_service._load_index(lib_id)
                for doc in docs:
                    content = knowledge_service._get_cached_content(lib_id, doc['id'])
                    if not content:
                        continue
                    doc_contents_full.append(
                        (doc['id'], lib_id, lib_name, doc['filename'], content))
                    loaded += 1
                    if progress_callback:
                        progress_callback(loaded, total, doc['filename'], lib_name)
                    yield {'status': 'reading', 'loaded': loaded, 'total': total,
                           'filename': doc['filename'], 'lib_name': lib_name}

        yield {'status': 'read_done',
               'message': f'知识库读取完成：{len(doc_contents_full)} 个文档'}

        # ── 第2步：切分段落 ──
        yield {'status': 'indexing', 'message': '正在切分段落并建立索引...'}

        for doc_id, lib_id, lib_name, filename, content in doc_contents_full:
            self._total_docs += 1
            self._total_chars += len(content)
            chunks = self._split_into_chunks(content, doc_id, lib_id, lib_name, filename)
            self._chunks.extend(chunks)
            for c in chunks:
                self._total_tokens += c.tokens

        # ── 第3步：分批 + 打标记 + 格式化 + 存缓存 ──
        yield {'status': 'batching',
               'message': f'正在分批缓存（{len(self._chunks)} 个片段，每批上限 {batch_token_limit} tokens）...'}

        self._build_batches(batch_token_limit)

        self._loaded = True

        logger.info(
            "[知识库缓存] 预加载完成：%d 文档，%d 片段，%d 批次，%d 字符，~%d tokens",
            self._total_docs, len(self._chunks), len(self._batches),
            self._total_chars, self._total_tokens,
        )

        yield {
            'status': 'done',
            'message': f'知识库预加载完成（{len(self._batches)} 个批次，全量缓存无截断）',
            **self.stats,
        }

    def _build_batches(self, batch_token_limit: int):
        """将所有片段分批，每批打标记、格式化、存入缓存。"""
        current_chunks: List[KnowledgeChunk] = []
        current_tokens = 0
        batch_counter = 0

        for chunk in self._chunks:
            # 当前 batch 放不下了，先保存
            if current_tokens + chunk.tokens > batch_token_limit and current_chunks:
                self._save_batch(batch_counter, current_chunks)
                batch_counter += 1
                current_chunks = []
                current_tokens = 0

            current_chunks.append(chunk)
            current_tokens += chunk.tokens

        # 最后一批
        if current_chunks:
            self._save_batch(batch_counter, current_chunks)

    def _save_batch(self, index: int, chunks: List[KnowledgeChunk]):
        """将一批片段保存到缓存，打好标记。"""
        batch_id = f"B{index:03d}"

        # 收集标记
        all_tags = set()
        lib_names = set()
        filenames = set()
        for c in chunks:
            all_tags |= c.keywords
            lib_names.add(c.lib_name)
            filenames.add(c.filename)

        # 格式化文本（预先生成好，调用时直接取）
        formatted = self._format_batch(chunks, batch_id)
        total_tokens = sum(c.tokens for c in chunks)

        self._batches[batch_id] = {
            'id': batch_id,
            'chunks': chunks,
            'tokens': total_tokens,
            'formatted': formatted,
            'tags': all_tags,
            'lib_names': lib_names,
            'filenames': filenames,
        }
        self._batch_ids.append(batch_id)

        # 建立倒排索引：keyword → batch_id
        for tag in all_tags:
            self._tag_index[tag].add(batch_id)

    @staticmethod
    def _format_batch(chunks: List[KnowledgeChunk], batch_id: str) -> str:
        """将一批片段格式化为可直接注入 prompt 的文本。"""
        parts = []
        current_doc = ""
        for chunk in chunks:
            doc_key = f"{chunk.lib_name} - {chunk.filename}"
            if doc_key != current_doc:
                if current_doc:
                    parts.append("")
                parts.append(f"【{doc_key}】")
                current_doc = doc_key
            parts.append(chunk.text)
        return "\n".join(parts)

    # ══════════════════════════════════════════════
    #  检索：按章节关键词查索引 → 取出相关 batch
    # ══════════════════════════════════════════════

    def get_batches_for_chapter(
        self,
        chapter_title: str,
        chapter_description: str = '',
        max_tokens: int = 0,
    ) -> List[Dict[str, Any]]:
        """根据章节信息，从缓存中取出相关的 batch 列表。

        Args:
            chapter_title: 章节标题
            chapter_description: 章节描述
            max_tokens: token 预算上限，0 表示不限制（返回所有相关 batch）

        Returns:
            按相关性排序的 batch 列表，每个 batch 包含 id/tokens/formatted/tags 等
        """
        if not self._loaded:
            return []

        query = f"{chapter_title} {chapter_description}"
        query_keywords = self._extract_query_keywords(query)
        if not query_keywords:
            # 没有关键词，返回所有 batch
            return self._get_all_batches_within_budget(max_tokens)

        # 计算每个 batch 的匹配得分
        batch_scores: Dict[str, float] = defaultdict(float)

        for kw in query_keywords:
            # 精确匹配
            if kw in self._tag_index:
                for bid in self._tag_index[kw]:
                    batch_scores[bid] += 2.0
            # 子串匹配（要求子串至少3个字符，避免短词误匹配）
            if len(kw) >= 3:
                for index_kw, batch_ids in self._tag_index.items():
                    if kw != index_kw and len(index_kw) >= 3 and (kw in index_kw or index_kw in kw):
                        for bid in batch_ids:
                            batch_scores[bid] += 1.0

        if not batch_scores:
            return []

        # 按得分排序
        sorted_bids = sorted(batch_scores.keys(),
                             key=lambda bid: batch_scores[bid], reverse=True)

        # 在 token 预算内选取
        result = []
        used_tokens = 0
        for bid in sorted_bids:
            batch = self._batches[bid]
            if max_tokens > 0 and used_tokens + batch['tokens'] > max_tokens:
                continue  # 跳过放不下的，尝试后面更小的 batch
            result.append(batch)
            used_tokens += batch['tokens']

        logger.info(
            "[知识库缓存] 章节 '%s' → %d 个关键词，命中 %d/%d 个批次（%d tokens）",
            chapter_title[:20], len(query_keywords),
            len(result), len(batch_scores), used_tokens,
        )
        return result

    def get_formatted_for_chapter(
        self,
        chapter_title: str,
        chapter_description: str = '',
        max_tokens: int = 0,
    ) -> str:
        """根据章节信息，直接返回已格式化的知识库文本。

        这是最常用的调用入口：传入章节标题和描述，
        返回可直接注入 prompt 的知识库参考资料文本。

        Args:
            chapter_title: 章节标题
            chapter_description: 章节描述
            max_tokens: token 预算上限

        Returns:
            格式化后的知识库文本
        """
        batches = self.get_batches_for_chapter(
            chapter_title, chapter_description, max_tokens)
        if not batches:
            return ""

        parts = [
            "========== 知识库参考资料（必须严格遵守） ==========",
            "以下是致同会计师事务所的真实资料，生成内容时必须优先使用这些信息。",
            "严禁编造任何不存在于以下资料中的案例、人员、制度、流程等具体信息。",
            "",
        ]
        for batch in batches:
            parts.append(batch['formatted'])
            parts.append("")
        parts.append("========== 知识库参考资料结束 ==========")
        parts.append("")
        return "\n".join(parts)

    def get_overflow_batches_for_chapter(
        self,
        chapter_title: str,
        chapter_description: str = '',
        max_tokens_per_call: int = 6000,
    ) -> List[List[Dict[str, Any]]]:
        """当相关内容超出单次 prompt 预算时，返回分组后的 batch 列表。

        每组的总 token 数不超过 max_tokens_per_call，
        调用方可以逐组调用 LLM 消化。

        Args:
            chapter_title: 章节标题
            chapter_description: 章节描述
            max_tokens_per_call: 每次 LLM 调用的知识库 token 预算

        Returns:
            分组后的 batch 列表，如 [[batch1, batch2], [batch3], ...]
        """
        # 取出所有相关 batch（不限 token）
        all_batches = self.get_batches_for_chapter(
            chapter_title, chapter_description, max_tokens=0)
        if not all_batches:
            return []

        # 按 token 预算分组
        groups = []
        current_group = []
        current_tokens = 0

        for batch in all_batches:
            if current_tokens + batch['tokens'] > max_tokens_per_call and current_group:
                groups.append(current_group)
                current_group = []
                current_tokens = 0
            current_group.append(batch)
            current_tokens += batch['tokens']

        if current_group:
            groups.append(current_group)

        logger.info(
            "[知识库缓存] 章节 '%s' 溢出分组：%d 个批次 → %d 组（每组上限 %d tokens）",
            chapter_title[:20], len(all_batches), len(groups), max_tokens_per_call,
        )
        return groups

    def get_all_formatted(self) -> str:
        """获取全量知识库内容（所有 batch 拼接），用于小型知识库场景。"""
        if not self._loaded or not self._batches:
            return ""

        parts = [
            "========== 知识库参考资料（必须严格遵守） ==========",
            "以下是致同会计师事务所的真实资料，生成内容时必须优先使用这些信息。",
            "严禁编造任何不存在于以下资料中的案例、人员、制度、流程等具体信息。",
            "",
        ]
        for bid in self._batch_ids:
            parts.append(self._batches[bid]['formatted'])
            parts.append("")
        parts.append("========== 知识库参考资料结束 ==========")
        parts.append("")
        return "\n".join(parts)

    def _get_all_batches_within_budget(self, max_tokens: int) -> List[Dict[str, Any]]:
        """按顺序返回所有 batch，在 token 预算内。"""
        result = []
        used = 0
        for bid in self._batch_ids:
            batch = self._batches[bid]
            if max_tokens > 0 and used + batch['tokens'] > max_tokens:
                continue
            result.append(batch)
            used += batch['tokens']
        return result

    # ══════════════════════════════════════════════
    #  辅助方法
    # ══════════════════════════════════════════════

    def _split_into_chunks(
        self,
        content: str,
        doc_id: str,
        lib_id: str,
        lib_name: str,
        filename: str,
    ) -> List[KnowledgeChunk]:
        """将文档内容按段落切分为 KnowledgeChunk 列表。

        切分策略：
        1. 按空行分段
        2. 过短的段落（< MIN_CHUNK_CHARS）合并到上一段
        3. 过长的段落（> MAX_CHUNK_CHARS）按句号/换行再切分
        """
        if not content or not content.strip():
            return []

        # 按空行分段
        raw_paragraphs = re.split(r'\n\s*\n', content)
        # 去除空白段落
        raw_paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]

        if not raw_paragraphs:
            return []

        # 合并过短段落、拆分过长段落
        merged: List[str] = []
        buffer = ""

        for para in raw_paragraphs:
            if len(para) < self.MIN_CHUNK_CHARS:
                # 过短，合并到 buffer
                buffer = f"{buffer}\n{para}" if buffer else para
                continue

            # 先把 buffer 里积攒的短段落推出去
            if buffer:
                combined = f"{buffer}\n{para}"
                if len(combined) <= self.MAX_CHUNK_CHARS:
                    buffer = combined
                    continue
                else:
                    merged.append(buffer)
                    buffer = ""

            if len(para) > self.MAX_CHUNK_CHARS:
                # 过长段落拆分
                sub_parts = self._split_long_paragraph(para)
                merged.extend(sub_parts)
            else:
                merged.append(para)

        if buffer:
            merged.append(buffer)

        # 生成 KnowledgeChunk 对象
        chunks = []
        for text in merged:
            if text.strip():
                chunks.append(KnowledgeChunk(
                    doc_id=doc_id,
                    lib_id=lib_id,
                    lib_name=lib_name,
                    filename=filename,
                    text=text.strip(),
                ))
        return chunks

    def _split_long_paragraph(self, text: str) -> List[str]:
        """将超长段落按句号、分号、换行等拆分为多个子段落。"""
        # 按中文句号、分号、换行拆分
        sentences = re.split(r'(?<=[。；\n])', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return [text]

        parts: List[str] = []
        current = ""

        for sent in sentences:
            if len(current) + len(sent) > self.MAX_CHUNK_CHARS and current:
                parts.append(current)
                current = sent
            else:
                current = f"{current}{sent}" if current else sent

        if current:
            parts.append(current)

        return parts if parts else [text]

    @staticmethod
    def _extract_query_keywords(query: str) -> set:
        """从查询文本中提取关键词，用于匹配 batch 标记。"""
        if not query:
            return set()
        # 提取中文词组（2-6字）
        cn_words = set(re.findall(r'[\u4e00-\u9fff]{2,6}', query))
        # 提取英文单词（3字母以上）
        en_words = set(w.lower() for w in re.findall(r'[a-zA-Z]{3,}', query))
        # 去除停用词
        cn_words -= _STOP_WORDS
        return cn_words | en_words


# ── 全局单例 ──
knowledge_retriever = KnowledgeRetriever()
