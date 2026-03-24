"""回归测试：检查所有 session 的纵向加总不平 findings 数量。

用法: python debug_soe.py
"""
import json, sys
sys.path.insert(0, ".")
from app.services.table_structure_analyzer import TableStructureAnalyzer
from app.services.reconciliation_engine import ReconciliationEngine
from app.models.audit_schemas import NoteTable

sessions = [
    ("dd547903", "国企版"),
    ("99704b05", "上市版-公司2"),
    ("618178ea", "上市版-公司1"),
]

for sid, label in sessions:
    try:
        with open(f"data/sessions/{sid}/session.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"  {label} ({sid}): session not found, skipping")
        continue

    analyzer = TableStructureAnalyzer()
    engine = ReconciliationEngine()

    count = 0
    for nt_data in data.get("note_tables", []):
        nt = NoteTable(**nt_data)
        ts = analyzer._analyze_with_rules(nt)
        findings = engine.check_note_table_integrity(nt, ts)
        if findings:
            for f in findings:
                print(f"  [{label}] {nt.account_name} / {nt.section_title}")
                print(f"    {f.location}")
                print(f"    stmt={f.statement_amount}, note={f.note_amount}, diff={f.difference}")
                count += 1
    
    print(f"\n  {label} ({sid}): {count} findings\n")
    analyzer.clear_cache()
