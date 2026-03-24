"""Debug: 找所有session中的比例列findings。"""
import json, sys, os
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
        continue

    analyzer = TableStructureAnalyzer()
    engine = ReconciliationEngine()

    print(f"\n{'='*60}")
    print(f"  {label} ({sid})")
    print(f"{'='*60}")
    
    count = 0
    for nt_data in data.get("note_tables", []):
        nt = NoteTable(**nt_data)
        ts = analyzer._analyze_with_rules(nt)
        findings = engine.check_ratio_columns(nt, ts)
        for f in findings:
            count += 1
            print(f"\n  [{nt.account_name}] {f.description}")
    
    print(f"\n  Total ratio findings: {count}")
    analyzer.clear_cache()
