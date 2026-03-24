"""Debug: 分析上市版 未分配利润 的 findings."""
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

print("=== 未分配利润相关附注表 ===")
for nt_data in data.get("note_tables", []):
    nt = NoteTable(**nt_data)
    if not engine._is_undistributed_profit_table(nt):
        continue
    
    print(f"\n  ID: {nt.id}")
    print(f"  account_name: {nt.account_name}")
    print(f"  section_title: {nt.section_title}")
    print(f"  headers: {nt.headers}")
    if nt.rows:
        for i, row in enumerate(nt.rows):
            print(f"    row[{i}]: {row}")
    
    ts = analyzer._analyze_with_rules(nt)
    findings = engine.check_undistributed_profit(nt, ts)
    print(f"\n  Findings: {len(findings)}")
    for f in findings:
        print(f"    location: {f.location}")
        print(f"    description: {f.description}")
        print(f"    stmt={f.statement_amount}, note={f.note_amount}, diff={f.difference}")
    
    # 手动分析行标签
    print(f"\n  === 行标签分析 ===")
    for ri, row in enumerate(nt.rows):
        label = str(row[0] if row else "").strip()
        clean = label.replace(" ", "").replace("\u3000", "")
        vals = [_safe_float(row[ci]) if ci < len(row) else None for ci in range(1, len(nt.headers or []))]
        print(f"    [{ri}] '{label}' -> clean='{clean}' vals={vals}")
        
        # 检查匹配
        flags = []
        if "调整后" in clean and ("期初未分配利润" in clean or "期初未分配" in clean):
            flags.append("OPENING(调整后)")
        elif "期初未分配利润" in clean or "期初未分配" in clean:
            flags.append("OPENING")
        if "期末未分配利润" in clean or "期末未分配" in clean:
            flags.append("CLOSING")
        if clean.startswith("加") or clean.startswith("加：") or clean.startswith("加:"):
            flags.append("ADD_START")
        if clean.startswith("减") or clean.startswith("减：") or clean.startswith("减:"):
            flags.append("SUB_START")
        if flags:
            print(f"         FLAGS: {flags}")
