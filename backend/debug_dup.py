"""Debug: find all findings related to 其他流动负债 in 上市版."""
import json, sys
sys.path.insert(0, ".")
from app.services.table_structure_analyzer import TableStructureAnalyzer
from app.services.reconciliation_engine import ReconciliationEngine
from app.models.audit_schemas import NoteTable

sid = "99704b05"
with open(f"data/sessions/{sid}/session.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# Check findings.json if it exists
try:
    with open(f"data/sessions/{sid}/findings.json", "r", encoding="utf-8") as f:
        findings_data = json.load(f)
    
    print("=== All findings from findings.json ===")
    for i, f in enumerate(findings_data):
        acct = f.get("account_name", "")
        loc = f.get("location", "")
        desc = f.get("description", "")[:100]
        cat = f.get("category", "")
        if "其他流动负债" in acct or "其他流动负债" in loc or "其他流动负债" in desc:
            print(f"\n  [{i}] category={cat}")
            print(f"    account={acct}")
            print(f"    location={loc}")
            print(f"    desc={desc}")
            print(f"    stmt={f.get('statement_amount')}, note={f.get('note_amount')}, diff={f.get('difference')}")
except FileNotFoundError:
    print("No findings.json found")

# Also check what check_note_table_integrity produces
print("\n\n=== check_note_table_integrity findings ===")
analyzer = TableStructureAnalyzer()
engine = ReconciliationEngine()

for nt_data in data.get("note_tables", []):
    nt = NoteTable(**nt_data)
    if "其他流动负债" not in (nt.account_name or ""):
        continue
    
    ts = analyzer._analyze_with_rules(nt)
    findings = engine.check_note_table_integrity(nt, ts)
    
    print(f"\n  Table: {nt.account_name} / {nt.section_title}")
    print(f"  Findings: {len(findings)}")
    for f in findings:
        print(f"    {f.location}")
        print(f"    stmt={f.statement_amount}, note={f.note_amount}, diff={f.difference}")
