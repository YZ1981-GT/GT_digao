"""Debug: 分析上市版 坏账准备ECL表 的 reconciliation_error findings."""
import json, sys
sys.path.insert(0, ".")
from app.services.table_structure_analyzer import TableStructureAnalyzer
from app.services.reconciliation_engine import ReconciliationEngine
from app.models.audit_schemas import NoteTable

sid = "99704b05"
with open(f"data/sessions/{sid}/session.json", "r", encoding="utf-8") as f:
    data = json.load(f)

analyzer = TableStructureAnalyzer()
engine = ReconciliationEngine()

print("=== 坏账准备相关附注表 ===")
for nt_data in data.get("note_tables", []):
    nt = NoteTable(**nt_data)
    title = (nt.account_name or "") + (nt.section_title or "")
    if "计提" in title and "转回" in title and "坏账" in title:
        print(f"\n  ID: {nt.id}")
        print(f"  account_name: {nt.account_name}")
        print(f"  section_title: {nt.section_title}")
        print(f"  headers: {nt.headers}")
        if nt.rows:
            for i, row in enumerate(nt.rows):
                print(f"    row[{i}]: {row}")
        
        ts = analyzer._analyze_with_rules(nt)
        print(f"\n  TableStructure:")
        print(f"    total_row_indices: {ts.total_row_indices}")
        print(f"    columns: {[(c.col_index, c.semantic) for c in ts.columns]}")
        print(f"    rows: {[(r.row_index, r.role, r.sign, r.label) for r in ts.rows]}")
        if ts.has_balance_formula:
            print(f"    has_balance_formula: True")
        
        findings = engine.check_note_table_integrity(nt, ts)
        ecl_findings = engine.check_ecl_three_stage_table(nt, ts)
        print(f"\n  Integrity findings: {len(findings)}")
        for f in findings:
            print(f"    {f.location}")
            print(f"    {f.description}")
            print(f"    stmt={f.statement_amount}, note={f.note_amount}, diff={f.difference}")
        print(f"  ECL findings: {len(ecl_findings)}")
        for f in ecl_findings:
            print(f"    {f.location}")
            print(f"    {f.description}")
            print(f"    stmt={f.statement_amount}, note={f.note_amount}, diff={f.difference}")
        
        # 手动逐列验证
        if len(nt.headers or []) >= 5 and "阶段" in str(nt.headers):
            print(f"\n  === 手动逐列验证 ===")
            from app.services.reconciliation_engine import _safe_float
            for ci in range(1, len(nt.headers)):
                col_name = nt.headers[ci]
                opening = None
                movement = 0.0
                closing = None
                details = []
                for ri, row in enumerate(nt.rows or []):
                    if not row or ci >= len(row):
                        continue
                    label = str(row[0] or "").strip()
                    val = _safe_float(row[ci])
                    if "期初余额" in label and "在本期" not in label:
                        opening = val
                        details.append(f"    期初: {val}")
                    elif "期末余额" in label:
                        closing = val
                        details.append(f"    期末: {val}")
                    elif val is not None:
                        details.append(f"    {label}: {val}")
                        # 模拟代码逻辑
                        stripped = label.lstrip("-–—\u2014\u2013 \u3000")
                        if stripped.startswith("转入第") or stripped.startswith("转回第"):
                            details[-1] += " [SKIP: 阶段转移明细]"
                        elif "期初" in label:
                            movement += val
                            details[-1] += f" [+变动(期初在本期)]"
                        elif any(kw in label for kw in ["转回", "转销", "核销", "减少", "冲销"]):
                            movement -= val
                            details[-1] += f" [-变动]"
                        else:
                            movement += val
                            details[-1] += f" [+变动]"
                if opening is not None and closing is not None:
                    expected = round(opening + movement, 2)
                    diff = round(expected - closing, 2)
                    print(f"\n  列 {ci}: {col_name}")
                    for d in details:
                        print(d)
                    print(f"    expected = {opening} + {movement} = {expected}")
                    print(f"    actual closing = {closing}")
                    print(f"    diff = {diff}")
                    print(f"    平? {'YES' if abs(diff) < 0.01 else 'NO'}")
