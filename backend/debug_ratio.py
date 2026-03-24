"""Debug: 分析上市版 比例列校验 的 findings."""
import json, sys
sys.path.insert(0, ".")
from app.services.table_structure_analyzer import TableStructureAnalyzer
from app.services.reconciliation_engine import ReconciliationEngine, _safe_float
from app.models.audit_schemas import NoteTable

sid = "99704b05"
with open(f"data/sessions/{sid}/session.json", "r", encoding="utf-8") as f:
    data = json.load(f)

analyzer = TableStructureAnalyzer()
engine = ReconciliationEngine()

print("=== 所有比例列校验 findings ===")
for nt_data in data.get("note_tables", []):
    nt = NoteTable(**nt_data)
    ts = analyzer._analyze_with_rules(nt)
    findings = engine.check_ratio_columns(nt, ts)
    if findings:
        acct = nt.account_name or ""
        print(f"\n  === {acct} / {nt.section_title} ===")
        print(f"  ID: {nt.id}")
        print(f"  headers: {nt.headers}")
        for i, row in enumerate(nt.rows or []):
            print(f"    row[{i}]: {row}")
        print(f"  total_row_indices: {ts.total_row_indices}")
        print(f"  rows: {[(r.row_index, r.role, r.label) for r in ts.rows]}")
        print(f"\n  Findings ({len(findings)}):")
        for f in findings:
            print(f"    {f.location}")
            print(f"    {f.description}")

# 看截图中提到的应收账款表
print("\n\n=== 应收账款相关附注表（含比例列）===")
for nt_data in data.get("note_tables", []):
    nt = NoteTable(**nt_data)
    acct = nt.account_name or ""
    title = nt.section_title or ""
    if "应收账款" in acct or "应收账款" in title:
        has_ratio = any(any(kw in str(h) for kw in ["比例", "%", "占比", "百分比", "预期信用损失率", "计提比例"]) for h in (nt.headers or []))
        if has_ratio:
            ts = analyzer._analyze_with_rules(nt)
            print(f"\n  === {acct} / {title} ===")
            print(f"  ID: {nt.id}")
            print(f"  headers: {nt.headers}")
            for i, row in enumerate(nt.rows or []):
                print(f"    row[{i}]: {row}")
            print(f"  total_row_indices: {ts.total_row_indices}")
            print(f"  rows: {[(r.row_index, r.role, r.label) for r in ts.rows]}")

# 看存货相关
print("\n\n=== 存货相关附注表 ===")
for nt_data in data.get("note_tables", []):
    nt = NoteTable(**nt_data)
    acct = nt.account_name or ""
    title = nt.section_title or ""
    if "存货" in acct or "存货" in title:
        print(f"\n  === {acct} / {title} ===")
        print(f"  headers: {nt.headers}")
        for i, row in enumerate(nt.rows or []):
            print(f"    row[{i}]: {row}")
