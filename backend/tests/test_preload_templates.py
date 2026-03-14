"""Test that built-in templates are preloaded into the knowledge base."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.knowledge_service import KnowledgeService

ks = KnowledgeService()
docs = ks.get_documents('report_templates')
print(f"Templates in report_templates library: {len(docs)}")
for d in docs:
    print(f"  - {d['filename']} (id={d['id']}, size={d['size']})")

# Verify content is accessible
for d in docs:
    content = ks.get_document_content('report_templates', d['id'])
    if content:
        print(f"  Content loaded for {d['filename']}: {len(content)} chars, starts with: {content[:60]}...")
    else:
        print(f"  ERROR: No content for {d['filename']}")

print("\nPreload test passed!" if len(docs) >= 2 else "\nWARNING: Expected at least 2 templates")
