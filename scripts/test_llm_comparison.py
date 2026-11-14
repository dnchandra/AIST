"""
Empirical Benchmark: flint:40b vs ornith-1.5:35b for SRE Incident Triage
Runs two standardized tests:
1. Structured Tool Calling (FastMCP schema compliance & JSON accuracy)
2. Multi-tier Incident Root Cause Analysis (Reasoning depth & cascade detection)
"""

import json
import time
import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

TOOL_CALL_PROMPT = """You are an automated SRE Triage Agent.
Alert received:
{
  "alertname": "TicketApiHighLatency",
  "instance": "192.168.1.130:5000",
  "p95_latency": "4.8s",
  "threshold": "2.0s",
  "target_os": "rhel10"
}

Available MCP Tools:
- mcp_prometheus.query_range(query: str, start: str, end: str)
- mcp_linux_diag.check_systemd_status(service_name: str)
- mcp_linux_diag.get_journalctl_errors(unit: str, lines: int)
- mcp_sql.get_blocked_sql_queries()

Respond ONLY with a JSON list of tool calls you will execute to investigate this incident.
Example format:
[
  {"tool": "mcp_prometheus.query_range", "arguments": {"query": "rate(http_requests_total[2m])", "start": "-10m", "end": "now"}}
]
"""

RCA_REASONING_PROMPT = """You are an expert SRE Incident Commander.
Analyze this multi-tier incident across a hybrid Linux and Windows environment:

Observed Telemetry:
1. [22:10:00] RHEL 10: TicketFlow Flask API (192.168.1.130) p95 response times increase from 120ms to 5,200ms.
2. [22:10:15] Windows 2019: Microsoft SQL Server (192.168.1.133) sys.dm_exec_requests shows SPID 74 has held TABLOCKX on 'Tickets' table for 180 seconds in status 'RUNNING'.
3. [22:10:20] RHEL 10: Flask API error logs report: 'pyodbc.OperationalError: Connection pool exhausted (30/30 max connections reached waiting for lock)'.
4. [22:10:30] Windows 2025: Auth Gateway (192.168.1.132) reports 503 errors due to upstream API timeout.

Questions:
1. What is the root cause?
2. Which component failed FIRST?
3. What are the cascading effects?
4. What is the exact immediate remediation action?

Provide a concise, professional RCA report with these 4 sections.
"""


def test_model(model_name, prompt_name, prompt_text):
    print(f"\n=======================================================")
    print(f"Testing {model_name} on {prompt_name}...")
    print(f"=======================================================")
    
    payload = {
        "model": model_name,
        "prompt": prompt_text,
        "options": {
            "num_ctx": 16384,
            "temperature": 0.2
        },
        "stream": False
    }
    
    start_time = time.time()
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        duration = time.time() - start_time
        data = resp.json()
        response_text = data.get("response", "")
        eval_count = data.get("eval_count", 0)
        eval_duration_sec = data.get("eval_duration", 1) / 1e9
        tok_per_sec = eval_count / eval_duration_sec if eval_duration_sec > 0 else 0
        
        print(f"Success! Total Time: {duration:.2f}s | Speed: {tok_per_sec:.1f} tokens/sec | Tokens: {eval_count}")
        print("\n--- Model Response ---")
        print(response_text[:1200] + ("..." if len(response_text) > 1200 else ""))
        
        return {
            "model": model_name,
            "prompt": prompt_name,
            "duration": duration,
            "tok_per_sec": tok_per_sec,
            "tokens": eval_count,
            "response": response_text
        }
    except Exception as e:
        print(f"Error testing {model_name}: {e}")
        return None


if __name__ == "__main__":
    results = []
    
    # Run Tool Calling Test
    r1 = test_model("flint:40b", "Tool Calling Test", TOOL_CALL_PROMPT)
    r2 = test_model("ornith-1.5:35b", "Tool Calling Test", TOOL_CALL_PROMPT)
    
    # Run RCA Reasoning Test
    r3 = test_model("flint:40b", "RCA Reasoning Test", RCA_REASONING_PROMPT)
    r4 = test_model("ornith-1.5:35b", "RCA Reasoning Test", RCA_REASONING_PROMPT)
    
    print("\n\n" + "="*70)
    print("FINAL BENCHMARK SUMMARY")
    print("="*70)
    for r in [r1, r2, r3, r4]:
        if r:
            print(f"{r['model']:<18} | {r['prompt']:<20} | Time: {r['duration']:>5.2f}s | Speed: {r['tok_per_sec']:>5.1f} tok/s")
