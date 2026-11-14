import os
import json
import requests

dashboards_dir = r"d:\2026_Projects\AIST\observability\grafana\dashboards"
prom_url = "http://192.168.1.131:9090/api/v1/query"

dashboard_files = sorted([f for f in os.listdir(dashboards_dir) if f.endswith(".json")])

print(f"Auditing {len(dashboard_files)} dashboards against Prometheus...\n")

for fname in dashboard_files:
    fpath = os.path.join(dashboards_dir, fname)
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    title = data.get("title", fname)
    panels = data.get("panels", [])
    print("=" * 80)
    print(f"DASHBOARD: {title} ({fname}) - {len(panels)} panels")
    print("=" * 80)

    for p in panels:
        pid = p.get("id")
        ptype = p.get("type")
        ptitle = p.get("title", "<No Title>")
        targets = p.get("targets", [])

        if ptype == "row":
            print(f"\n--- [ROW] {ptitle} ---")
            continue

        print(f"\nPanel #{pid} [{ptype}] '{ptitle}':")
        if not targets:
            print("  (No targets or not a query panel)")
            continue

        for idx, t in enumerate(targets):
            expr = t.get("expr")
            legend = t.get("legendFormat", "")
            ds = t.get("datasource", {})
            if isinstance(ds, dict):
                ds_type = ds.get("type", "unknown")
            else:
                ds_type = str(ds)

            if not expr:
                print(f"  Target #{idx+1}: [Datasource: {ds_type}] (Non-Prometheus or empty expr)")
                continue

            # Query Loki or Prometheus based on panel type or expr
            if ptype == "logs" or expr.strip().startswith("{"):
                loki_url = "http://192.168.1.131:3100/loki/api/v1/query_range"
                try:
                    res = requests.get(loki_url, params={"query": expr}, timeout=3)
                    if res.status_code == 200:
                        rdata = res.json().get("data", {})
                        results = rdata.get("result", [])
                        print(f"  Target #{idx+1}: [Loki Range Query] expr='{expr}'")
                        print(f"    Returned: {len(results)} log streams (OK)")
                    else:
                        print(f"  Target #{idx+1}: [Loki] HTTP {res.status_code} on expr='{expr}'")
                except Exception as e:
                    print(f"  Target #{idx+1}: [Loki] ERROR querying expr='{expr}': {e}")
                continue

            # Query Prometheus
            try:
                res = requests.get(prom_url, params={"query": expr}, timeout=3)
                if res.status_code == 200:
                    rdata = res.json().get("data", {})
                    results = rdata.get("result", [])
                    num_results = len(results)
                    print(f"  Target #{idx+1}: expr='{expr}'")
                    print(f"    Legend: '{legend}' | Returned: {num_results} series")
                    if num_results == 0:
                        print("    [!] WARNING: Query returned 0 series (NO DATA)!")
                    elif num_results > 1 and ptype in ["stat", "gauge"]:
                        print(f"    [!] MULTI-SERIES IN STAT/GAUGE ({num_results} series) -> Causes squeezed duplicate numbers!")
                        for s in results:
                            print(f"      Metric: {s.get('metric')} => Value: {s.get('value')}")
                    else:
                        for s in results[:2]:
                            print(f"      Metric: {s.get('metric')} => Value: {s.get('value')}")
                else:
                    print(f"  Target #{idx+1}: HTTP {res.status_code} on expr='{expr}'")
            except Exception as e:
                print(f"  Target #{idx+1}: ERROR querying expr='{expr}': {e}")
