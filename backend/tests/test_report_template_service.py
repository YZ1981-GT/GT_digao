"""Report_Template_Service 单元测试（Task 6.7）。"""
import pytest

from app.models.audit_schemas import (
    ReportTemplateDocument,
    ReportTemplateType,
    TemplateCategory,
    TemplateTocEntry,
)
from app.services.report_template_service import ReportTemplateService

SAMPLE_MD = """# 审计报告正文
这是正文概述。

## 审计意见
我们审计了XX公司的财务报表。

## 管理层责任
管理层负责编制财务报表。

### 内部控制
管理层负责内部控制。

## 审计师责任
我们的责任是发表审计意见。
"""


class TestMarkdownParsing:
    def test_parse_sections(self):
        svc = ReportTemplateService()
        sections = svc._parse_markdown_sections(SAMPLE_MD)
        assert len(sections) >= 4
        titles = [s.title for s in sections]
        assert "审计报告正文" in titles
        assert "审计意见" in titles

    def test_section_levels(self):
        svc = ReportTemplateService()
        sections = svc._parse_markdown_sections(SAMPLE_MD)
        h1 = [s for s in sections if s.level == 1]
        h2 = [s for s in sections if s.level == 2]
        h3 = [s for s in sections if s.level == 3]
        assert len(h1) >= 1
        assert len(h2) >= 3
        assert len(h3) >= 1

    def test_section_content(self):
        svc = ReportTemplateService()
        sections = svc._parse_markdown_sections(SAMPLE_MD)
        opinion = next(s for s in sections if s.title == "审计意见")
        assert "审计" in opinion.content


class TestTemplateCRUD:
    def test_update_and_get(self):
        svc = ReportTemplateService()
        doc = svc.update_template(
            ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, SAMPLE_MD
        )
        assert isinstance(doc, ReportTemplateDocument)
        assert doc.template_type == ReportTemplateType.SOE
        assert len(doc.sections) >= 4

        cached = svc.get_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY)
        assert cached is doc
        svc.clear_cache()

    def test_empty_content_raises(self):
        svc = ReportTemplateService()
        with pytest.raises(ValueError, match="不能为空"):
            svc.update_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, "  ")

    def test_get_nonexistent_returns_none(self):
        svc = ReportTemplateService()
        # Mock storage to ensure test doesn't depend on real knowledge base data
        svc._load_from_storage = lambda *a, **kw: None
        result = svc.get_template(ReportTemplateType.LISTED, TemplateCategory.NOTES)
        assert result is None


class TestSectionRetrieval:
    def test_get_section_by_path(self):
        svc = ReportTemplateService()
        svc.update_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, SAMPLE_MD)
        # 获取实际的 section paths
        doc = svc.get_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY)
        paths = [s.path for s in doc.sections]
        # 找到包含"审计意见"的路径
        opinion_path = next(p for p in paths if "审计意见" in p)
        content = svc.get_template_section(
            ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, opinion_path
        )
        assert content is not None
        assert "审计" in content
        svc.clear_cache()

    def test_get_nonexistent_section(self):
        svc = ReportTemplateService()
        svc.update_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, SAMPLE_MD)
        content = svc.get_template_section(
            ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, "不存在的章节"
        )
        assert content is None
        svc.clear_cache()


class TestToc:
    def test_toc_structure(self):
        svc = ReportTemplateService()
        svc.update_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, SAMPLE_MD)
        toc = svc.get_template_toc(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY)
        assert len(toc) >= 4
        assert all(isinstance(e, TemplateTocEntry) for e in toc)
        svc.clear_cache()


class TestCacheInvalidation:
    def test_update_invalidates_section_cache(self):
        svc = ReportTemplateService()
        svc.update_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, SAMPLE_MD)
        doc = svc.get_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY)
        # 获取一个实际存在的 section path
        first_path = doc.sections[0].path
        svc.get_template_section(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, first_path)
        assert len(svc._section_cache) > 0

        new_md = "# 新模板\n\n## 新章节\n内容"
        svc.update_template(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, new_md)
        # 旧章节缓存应被清除
        old = svc.get_template_section(ReportTemplateType.SOE, TemplateCategory.REPORT_BODY, first_path)
        assert old is None
        svc.clear_cache()

class TestPreloadTemplates:
    """验证内置模板已预加载到知识库（原 test_preload_templates.py）。"""

    def test_builtin_templates_loaded(self):
        from app.services.knowledge_service import KnowledgeService
        ks = KnowledgeService()
        docs = ks.get_documents('report_templates')
        assert len(docs) >= 2, f"预期至少2个内置模板，实际 {len(docs)}"

    def test_template_content_accessible(self):
        from app.services.knowledge_service import KnowledgeService
        ks = KnowledgeService()
        docs = ks.get_documents('report_templates')
        for d in docs:
            content = ks.get_document_content('report_templates', d['id'])
            assert content and len(content) > 0, f"模板 {d['filename']} 内容为空"



class TestPreloadTemplates:
    """验证内置模板已预加载到知识库（原 test_preload_templates.py）。"""

    def test_builtin_templates_loaded(self):
        from app.services.knowledge_service import KnowledgeService
        ks = KnowledgeService()
        docs = ks.get_documents('report_templates')
        assert len(docs) >= 2, f"预期至少2个内置模板，实际 {len(docs)}"

    def test_template_content_accessible(self):
        from app.services.knowledge_service import KnowledgeService
        ks = KnowledgeService()
        docs = ks.get_documents('report_templates')
        for d in docs:
            content = ks.get_document_content('report_templates', d['id'])
            assert content and len(content) > 0, f"模板 {d['filename']} 内容为空"
