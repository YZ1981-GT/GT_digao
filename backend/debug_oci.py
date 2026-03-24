"""Debug: 分析上市版 其他综合收益 的 amount_inconsistency findings."""
import json, sys
sys.path.insert(0, ".")
from app.services.table_structure_analyzer import TableStructureAnalyzer
from app.services.reconciliation_engine import ReconciliationEngine
from app.models.audit_schemas import NoteTable, StatementItem, MatchingMap, MatchingEntry

sid = "99704b05"
with open(f"data/sessions/{sid}/session.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# 找到其他综合收益相关的附注表
print("=== 其他综合收益相关附注表 ===")
notes = []
for nt_data in data.get("note_tables", []):
    nt = NoteTable(**nt_data)
    title = (nt.account_name or "") + (nt.section_title or "")
    if "综合收益" in title:
        notes.append(nt)
        print(f"\n  ID: {nt.id}")
        print(f"  account_name: {nt.account_name}")
        print(f"  section_title: {nt.section_title}")
        print(f"  headers: {nt.headers}")
        if nt.rows:
            for i, row in enumerate(nt.rows):
                print(f"    row[{i}]: {row}")

# 找到其他综合收益相关的报表科目
print("\n\n=== 其他综合收益相关报表科目 ===")
items = [StatementItem(**i) for i in data.get("statement_items", [])]
oci_items = []
for item in items:
    if "综合收益" in (item.account_name or ""):
        oci_items.append(item)
        print(f"\n  ID: {item.id}")
        print(f"  account_name: {item.account_name}")
        print(f"  statement_type: {item.statement_type}")
        print(f"  closing_balance: {item.closing_balance}")
        print(f"  opening_balance: {item.opening_balance}")
        print(f"  is_sub_item: {item.is_sub_item}")

# 找到 matching_map 中的匹配关系
print("\n\n=== Matching Map 中的 OCI 匹配 ===")
mm = MatchingMap(**data["matching_map"]) if data.get("matching_map") else None
if mm:
    item_map = {i.id: i for i in items}
    note_map = {n.id: n for n in [NoteTable(**nd) for nd in data.get("note_tables", [])]}
    for entry in mm.entries:
        item = item_map.get(entry.statement_item_id)
        if item and "综合收益" in (item.account_name or ""):
            print(f"\n  Item: {item.account_name} (closing={item.closing_balance}, opening={item.opening_balance})")
            print(f"  Matched notes: {entry.note_table_ids}")
            for nid in (entry.note_table_ids or []):
                n = note_map.get(nid)
                if n:
                    print(f"    -> {n.account_name} / {n.section_title}")

# 运行 check_amount_consistency 看结果
print("\n\n=== check_amount_consistency 结果 ===")
analyzer = TableStructureAnalyzer()
engine = ReconciliationEngine()
all_notes = [NoteTable(**nd) for nd in data.get("note_tables", [])]
ts_map = {}
for nt in all_notes:
    ts = analyzer._analyze_with_rules(nt)
    ts_map[nt.id] = ts

if mm:
    findings = engine.check_amount_consistency(mm, items, all_notes, ts_map, template_type="listed")
    oci_findings = [f for f in findings if "综合收益" in (f.account_name or "")]
    print(f"\n  OCI findings: {len(oci_findings)}")
    for f in oci_findings:
        print(f"\n  category: {f.category}")
        print(f"  account_name: {f.account_name}")
        print(f"  location: {f.location}")
        print(f"  description: {f.description}")
        print(f"  stmt_amount: {f.statement_amount}, note_amount: {f.note_amount}, diff: {f.difference}")
