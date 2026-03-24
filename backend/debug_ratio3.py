"""Debug: 分析比例列误判 + 存货跌价准备选取问题。"""
import json, sys
sys.path.insert(0, ".")
from app.services.table_structure_analyzer import TableStructureAnalyzer
from app.services.reconciliation_engine import ReconciliationEngine, _safe_float
from app.models.audit_schemas import NoteTable

sessions = [
    ("618178ea", "上市版-公司1"),
    ("99704b05", "上市版-公司2"),
]

for sid, label in sessions:
    with open(f"data/sessions/{sid}/session.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    analyzer = TableStructureAnalyzer()
    engine = ReconciliationEngine()

    print(f"\n{'='*60}")
    print(f"  {label} ({sid})")
    print(f"{'='*60}")

    # 1. 找比例列误判的表
    print("\n--- 比例列 findings ---")
    for nt_data in data.get("note_tables", []):
        nt = NoteTable(**nt_data)
        ts = analyzer._analyze_with_rules(nt)
        findings = engine.check_ratio_columns(nt, ts)
        if findings:
            print(f"\n  [{nt.account_name}] {nt.section_title}")
            print(f"  headers: {nt.headers}")
            for i, row in enumerate(nt.rows or []):
                print(f"    row[{i}]: {row}")
            print(f"  total_row_indices: {ts.total_row_indices}")
            for f in findings:
                print(f"  FINDING: {f.description}")

    # 2. 存货跨表核对
    print("\n--- 存货跨表核对 findings ---")
    all_notes = [NoteTable(**nd) for nd in data.get("note_tables", [])]
    ts_map = {}
    for nt in all_notes:
        ts_map[nt.id] = analyzer._analyze_with_rules(nt)
    
    cross_findings = engine.check_cross_table_consistency(all_notes, ts_map)
    for f in cross_findings:
        if "存货" in (f.account_name or "") or "跌价" in (f.description or ""):
            print(f"\n  [{f.account_name}] {f.description}")
            print(f"  location: {f.location}")

    # 3. 打印存货相关表的详细数据
    print("\n--- 存货相关附注表 ---")
    for nt in all_notes:
        acct = nt.account_name or ""
        title = nt.section_title or ""
        if "存货" in acct or "存货" in title:
            ts = ts_map.get(nt.id)
            print(f"\n  [{acct}] {title}")
            print(f"  headers: {nt.headers}")
            for i, row in enumerate(nt.rows or []):
                print(f"    row[{i}]: {row}")
            if ts:
                print(f"  total_row_indices: {ts.total_row_indices}")

    analyzer.clear_cache()
