"""知识库管理服务"""
import json
import os
import re
import uuid
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 缓存最大文档数量，超过后最早加载的文档会被移除
MAX_CACHE_DOCS = 300


class KnowledgeService:
    """知识库管理服务 - 管理7个审计专用知识库，缓存与文件完全同步"""

    # 知识库定义（审计底稿复核专用）
    LIBRARIES = {
        'workpaper_templates': {'name': '底稿模板库', 'desc': '事务所审计底稿模板，用于格式规范性复核和底稿编制参考'},
        'audit_regulations': {'name': '监管规定库', 'desc': '证监会、财政部等监管机构发布的审计相关法规和规定'},
        'accounting_standards': {'name': '会计准则库', 'desc': '中国企业会计准则、审计准则及相关应用指南'},
        'quality_standards': {'name': '质控标准库', 'desc': '事务所质量控制标准、复核检查要点和质控流程规范'},
        'audit_procedures': {'name': '审计程序库', 'desc': '各业务循环标准审计程序、穿行测试和实质性测试指引'},
        'industry_guidelines': {'name': '行业指引库', 'desc': '各行业审计特殊考虑事项、行业风险提示和审计关注要点'},
        'prompt_library': {'name': '提示词库', 'desc': '审计复核提示词模板，按会计科目分类管理预置和自定义提示词'},
    }

    def __init__(self):
        # 内容缓存: {library_id: {doc_id: content}}
        self._content_cache: Dict[str, Dict[str, str]] = {}
        self.base_dir = os.path.join(os.path.expanduser("~"), ".gt_audit_helper", "knowledge")
        os.makedirs(self.base_dir, exist_ok=True)
        # 为每个库创建目录和索引
        for lib_id in self.LIBRARIES:
            lib_dir = os.path.join(self.base_dir, lib_id)
            os.makedirs(lib_dir, exist_ok=True)
            index_file = os.path.join(lib_dir, "index.json")
            if not os.path.exists(index_file):
                with open(index_file, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False)
            # 初始化缓存并预加载已有文档
            self._content_cache[lib_id] = {}
            self._preload_cache(lib_id)

    @staticmethod
    def _validate_doc_id(doc_id: str) -> str:
        """校验 doc_id 防止路径遍历攻击，返回安全的 doc_id"""
        # doc_id 应该是 uuid 格式，只允许字母数字和连字符
        if not doc_id or not re.match(r'^[a-zA-Z0-9\-]+$', doc_id):
            raise ValueError(f"非法的文档ID: {doc_id}")
        # 额外确保不包含路径分隔符
        if os.sep in doc_id or '/' in doc_id or '..' in doc_id:
            raise ValueError(f"非法的文档ID: {doc_id}")
        return doc_id

    def _preload_cache(self, library_id: str) -> None:
        """预加载知识库文档到缓存（启动时调用），受 MAX_CACHE_DOCS 限制"""
        docs = self._load_index(library_id)
        loaded = 0
        for doc in docs:
            # 每次循环重新计算总缓存数（包含本轮已加载的）
            total_cached = sum(len(v) for v in self._content_cache.values())
            if total_cached >= MAX_CACHE_DOCS:
                logger.warning(
                    "[知识库] 缓存已达上限 %d，%s 剩余 %d 个文档未加载",
                    MAX_CACHE_DOCS, self.LIBRARIES[library_id]['name'], len(docs) - loaded
                )
                break
            content_file = os.path.join(self.base_dir, library_id, f"{doc['id']}.txt")
            if os.path.exists(content_file):
                try:
                    with open(content_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # 兼容旧版：剥离 AI 处理添加的头部，还原原始内容
                    content = self._strip_ai_header(content)
                    self._content_cache[library_id][doc['id']] = content
                    loaded += 1
                except Exception as e:
                    logger.error("[知识库] 加载文档 %s 失败: %s", doc['id'], e)
        if loaded:
            logger.info("[知识库] %s 已加载 %d 个文档到缓存", self.LIBRARIES[library_id]['name'], loaded)

    @staticmethod
    def _strip_ai_header(content: str) -> str:
        """剥离旧版 process_document_with_ai 添加的头部信息，还原原始文档内容。

        旧格式形如：
            【文档来源：xxx】
            【AI整理时间：xxx】
            【摘要】xxx
            ==================================================
            【以下为原始文档全文】
            ==================================================

            <原始内容>
        """
        # 方式1：有明确的"以下为原始文档全文"分隔符
        marker = '【以下为原始文档全文】'
        idx = content.find(marker)
        if idx != -1:
            after = content[idx + len(marker):]
            lines = after.split('\n')
            start = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == '' or set(stripped) == {'='}:
                    start = i + 1
                else:
                    break
            return '\n'.join(lines[start:])

        # 方式2：开头是【文档来源：xxx】标记（无"以下为原始文档全文"分隔符的简化格式）
        if not content.startswith('【文档来源：'):
            return content

        lines = content.split('\n')
        # 已知的 AI 头部标记前缀
        ai_header_prefixes = ('【文档来源：', '【AI整理时间：', '【AI编辑时间：', '【摘要】')
        start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            # 匹配已知的 AI 标记行
            if any(stripped.startswith(p) for p in ai_header_prefixes):
                start = i + 1
                continue
            # 匹配 === 分隔线
            if stripped and set(stripped) == {'='}:
                start = i + 1
                continue
            # 空行（在标记区域内跳过）
            if stripped == '' and start > 0:
                start = i + 1
                continue
            # 遇到普通内容行，停止
            break

        if start > 0:
            return '\n'.join(lines[start:])

        return content

    def _get_cached_content(self, library_id: str, doc_id: str) -> Optional[str]:
        """从缓存获取文档内容，缓存未命中时按需加载"""
        doc_id = self._validate_doc_id(doc_id)
        cached = self._content_cache.get(library_id, {}).get(doc_id)
        if cached is not None:
            return cached
        # 按需加载
        content_file = os.path.join(self.base_dir, library_id, f"{doc_id}.txt")
        if os.path.exists(content_file):
            try:
                with open(content_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 兼容旧版：剥离 AI 处理添加的头部，还原原始内容
                content = self._strip_ai_header(content)
                if library_id not in self._content_cache:
                    self._content_cache[library_id] = {}
                self._content_cache[library_id][doc_id] = content
                return content
            except Exception as e:
                logger.error("[知识库] 按需加载文档 %s/%s 失败: %s", library_id, doc_id, e)
        return None

    def get_document_content(self, library_id: str, doc_id: str) -> Optional[str]:
        """获取文档内容（供预览使用）"""
        if library_id not in self.LIBRARIES:
            return None
        return self._get_cached_content(library_id, doc_id)

    def get_libraries(self) -> Dict:
        """获取所有知识库信息，返回结构化字典"""
        total_cached = sum(len(v) for v in self._content_cache.values())
        result = []
        for lib_id, info in self.LIBRARIES.items():
            docs = self._load_index(lib_id)
            cached_count = len(self._content_cache.get(lib_id, {}))
            result.append({
                'id': lib_id,
                'name': info['name'],
                'desc': info['desc'],
                'doc_count': len(docs),
                'cached_count': cached_count,
            })
        return {
            'libraries': result,
            'total_cached': total_cached,
            'max_cache': MAX_CACHE_DOCS,
        }

    def get_documents(self, library_id: str) -> List[Dict]:
        """获取某个知识库的所有文档"""
        if library_id not in self.LIBRARIES:
            raise ValueError(f"未知的知识库: {library_id}")
        return self._load_index(library_id)

    def add_document(self, library_id: str, filename: str, content: str) -> Dict:
        """添加文档到知识库"""
        if library_id not in self.LIBRARIES:
            raise ValueError(f"未知的知识库: {library_id}")

        # 检查缓存是否接近上限并发出警告
        total_cached = sum(len(v) for v in self._content_cache.values())
        if total_cached >= MAX_CACHE_DOCS:
            logger.warning(
                f"[知识库] 缓存已达上限 {MAX_CACHE_DOCS} 个文档，"
                f"新文档 '{filename}' 将不会被缓存，可能影响生成速度"
            )

        doc_id = str(uuid.uuid4())[:8]
        doc = {
            'id': doc_id,
            'filename': filename,
            'size': len(content),
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }

        # 保存文档内容
        content_file = os.path.join(self.base_dir, library_id, f"{doc_id}.txt")
        with open(content_file, 'w', encoding='utf-8') as f:
            f.write(content)

        # 更新索引
        docs = self._load_index(library_id)
        docs.append(doc)
        self._save_index(library_id, docs)

        # 更新缓存
        if library_id in self._content_cache:
            self._content_cache[library_id][doc_id] = content

        return doc

    def delete_document(self, library_id: str, doc_id: str) -> bool:
        """删除文档"""
        if library_id not in self.LIBRARIES:
            return False
        doc_id = self._validate_doc_id(doc_id)
        docs = self._load_index(library_id)
        docs = [d for d in docs if d['id'] != doc_id]
        self._save_index(library_id, docs)
        content_file = os.path.join(self.base_dir, library_id, f"{doc_id}.txt")
        if os.path.exists(content_file):
            os.remove(content_file)
        
        # 从缓存中删除
        if library_id in self._content_cache and doc_id in self._content_cache[library_id]:
            del self._content_cache[library_id][doc_id]
        
        return True

    def search_knowledge(self, library_ids: List[str], query: str, max_chars: int = 30000) -> str:
        """从指定知识库中搜索与query相关的内容，返回拼接文本（使用缓存）
        
        搜索策略：遍历所有选中知识库的所有文档，每个文档都会被检索。
        - 有关键词时：优先展示包含关键词的段落，没有匹配段落则展示文档摘要
        - 无关键词时：展示每个文档的前部分内容
        """
        all_content = []
        
        # 改进关键词提取：按空格分割，过滤短词和停用词
        stop_words = {'的', '和', '与', '或', '在', '是', '有', '为', '等', '及', '对', '中', '上', '下', '了', '着', '过', '到', '从', '向', '把', '被', '让', '给', '用', '以', '按', '将', '能', '可', '要', '会', '应'}
        raw_keywords = query.replace('，', ' ').replace(',', ' ').replace('、', ' ').split()
        keywords = [w.strip() for w in raw_keywords if w.strip() and len(w.strip()) >= 2 and w.strip() not in stop_words]
        
        # 如果用户输入的是一个完整短语（没有空格分隔），也作为整体关键词
        query_trimmed = query.strip()
        if query_trimmed and query_trimmed not in keywords and len(query_trimmed) >= 2:
            keywords.insert(0, query_trimmed)
        
        logger.info(f"[知识库搜索] 查询: {query[:50]} 关键词: {keywords[:10]}")
        
        # 每个文档的最大展示字符数
        per_doc_max = 3000
        
        for lib_id in library_ids:
            if lib_id not in self.LIBRARIES:
                continue
            docs = self._load_index(lib_id)
            lib_name = self.LIBRARIES[lib_id]['name']
            
            for doc in docs:
                # 从缓存读取内容
                text = self._get_cached_content(lib_id, doc['id'])
                if not text:
                    continue
                
                if not keywords:
                    # 无关键词时返回文档前部分
                    preview = text[:per_doc_max] if len(text) > per_doc_max else text
                    all_content.append(f"【{lib_name} - {doc['filename']}】\n{preview}")
                    continue
                
                # 计算文档相关性得分
                text_lower = text.lower()
                match_count = sum(1 for kw in keywords if kw.lower() in text_lower)
                
                if match_count > 0:
                    # 有匹配，提取相关段落
                    paragraphs = text.split('\n')
                    relevant = []
                    total_len = 0
                    for p in paragraphs:
                        p = p.strip()
                        if not p:
                            continue
                        # 段落中包含任意关键词
                        if any(kw.lower() in p.lower() for kw in keywords):
                            relevant.append(p)
                            total_len += len(p)
                            if total_len >= per_doc_max:
                                break
                    
                    if relevant:
                        content = '\n'.join(relevant)
                        all_content.append(f"【{lib_name} - {doc['filename']}】(匹配{match_count}个关键词)\n{content}")
                    else:
                        # 文档整体包含关键词但没有单独段落匹配（关键词可能跨段落），展示文档摘要
                        preview = text[:per_doc_max] if len(text) > per_doc_max else text
                        all_content.append(f"【{lib_name} - {doc['filename']}】(匹配{match_count}个关键词，展示摘要)\n{preview}")
                    
                    logger.info(f"[知识库搜索] 匹配文档: {doc['filename']} ({match_count}个关键词, {len(relevant)}段)")

        combined = '\n\n'.join(all_content)
        logger.info(f"[知识库搜索] 共匹配 {len(all_content)} 个文档，内容长度: {len(combined)} 字符")
        
        if len(combined) > max_chars:
            combined = combined[:max_chars] + '\n...(内容已截断)'
        return combined

    def get_all_knowledge_summary(self, max_chars_per_lib: int = 3000) -> str:
        """获取所有知识库的内容摘要，供AI参考"""
        summaries = []
        for lib_id, info in self.LIBRARIES.items():
            docs = self._load_index(lib_id)
            if not docs:
                continue
            lib_content = []
            total_chars = 0
            for doc in docs:
                # 使用缓存读取，与其他方法保持一致
                text = self._get_cached_content(lib_id, doc['id'])
                if text:
                    remaining = max_chars_per_lib - total_chars
                    if remaining <= 0:
                        break
                    if len(text) > remaining:
                        text = text[:remaining] + '...'
                    lib_content.append(f"[{doc['filename']}]\n{text}")
                    total_chars += len(text)
            if lib_content:
                summaries.append(f"=== {info['name']} ===\n" + '\n\n'.join(lib_content))
        return '\n\n'.join(summaries)

    def get_selected_knowledge(self, library_docs: Dict[str, List[str]], progress_callback=None) -> str:
        """根据选中的知识库和文档ID读取内容
        
        Args:
            library_docs: 字典，key为知识库ID，value为该库中选中的文档ID列表
            progress_callback: 可选回调函数 (loaded_count, total_count, filename, lib_name) -> None
        """
        all_content = []
        total_docs = 0
        total_chars = 0
        
        # 先统计总文档数
        doc_total = sum(len(ids) for lib_id, ids in library_docs.items() if lib_id in self.LIBRARIES)
        doc_loaded = 0
        
        for lib_id, doc_ids in library_docs.items():
            if lib_id not in self.LIBRARIES:
                continue
            
            info = self.LIBRARIES[lib_id]
            lib_content = []
            
            for doc_id in doc_ids:
                # 从缓存读取指定文档
                text = self._get_cached_content(lib_id, doc_id)
                if text:
                    # 获取文档信息
                    docs = self._load_index(lib_id)
                    doc_info = next((d for d in docs if d['id'] == doc_id), None)
                    filename = doc_info['filename'] if doc_info else '未知文档'
                    
                    lib_content.append(f"【文档：{filename}】\n{text}")
                    total_docs += 1
                    total_chars += len(text)
                    doc_loaded += 1
                    
                    if progress_callback:
                        progress_callback(doc_loaded, doc_total, filename, info['name'])
            
            if lib_content:
                all_content.append(f"\n{'='*50}\n📚 {info['name']}\n{'='*50}\n" + '\n\n'.join(lib_content))
        
        logger.info(f"[知识库] 已读取选中文档: {total_docs}个文档, {total_chars}字符, 来自{len([c for c in all_content if c])}个知识库")
        return '\n\n'.join(all_content)

    def get_all_knowledge_full(self, library_ids: List[str] = None, progress_callback=None) -> str:
        """获取所有知识库文档的完整内容，不截断
        
        Args:
            library_ids: 要读取的知识库ID列表，如果为None则读取所有知识库
            progress_callback: 可选回调函数 (loaded_count, total_count, filename, lib_name) -> None
        """
        all_content = []
        total_docs = 0
        total_chars = 0
        
        # 如果没有指定库ID，则使用所有库
        if library_ids is None:
            library_ids = list(self.LIBRARIES.keys())
        
        # 先统计总文档数
        doc_total = 0
        for lib_id in library_ids:
            if lib_id in self.LIBRARIES:
                docs = self._load_index(lib_id)
                doc_total += len([d for d in docs if self._get_cached_content(lib_id, d['id'])])
        doc_loaded = 0
        
        for lib_id in library_ids:
            if lib_id not in self.LIBRARIES:
                continue
                
            info = self.LIBRARIES[lib_id]
            docs = self._load_index(lib_id)
            if not docs:
                continue
            
            lib_content = []
            for doc in docs:
                # 优先从缓存读取
                text = self._get_cached_content(lib_id, doc['id'])
                if text:
                    lib_content.append(f"【文档：{doc['filename']}】\n{text}")
                    total_docs += 1
                    total_chars += len(text)
                    doc_loaded += 1
                    
                    if progress_callback:
                        progress_callback(doc_loaded, doc_total, doc['filename'], info['name'])
            
            if lib_content:
                all_content.append(f"\n{'='*50}\n📚 {info['name']}\n{'='*50}\n" + '\n\n'.join(lib_content))
        
        logger.info(f"[知识库] 已读取选中内容: {total_docs}个文档, {total_chars}字符, 来自{len([c for c in all_content if c])}个知识库")
        return '\n\n'.join(all_content)

    def _load_index(self, library_id: str) -> List[Dict]:
        index_file = os.path.join(self.base_dir, library_id, "index.json")
        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def _save_index(self, library_id: str, docs: List[Dict]):
        index_file = os.path.join(self.base_dir, library_id, "index.json")
        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)


# 全局实例
knowledge_service = KnowledgeService()
