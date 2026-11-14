# SRE Runbook: RB-05 - TicketFlow API Latency Degradation

## Severity: HIGH / P2
**Target Environments**: Red Hat Enterprise Linux 10 (`192.168.1.130`)  
**Alert Triggers**: `TicketApiHighLatency`, `p95 > 2.0s`

---

### 1. Initial Assessment
When TicketFlow API latency spikes above 2000ms:
1. Verify database dependency response time on Windows Server 2019 (`192.168.1.133:8088`).
2. Check active connection pool count on Flask API:
   ```bash
   curl -s http://192.168.1.130:5000/metrics | grep db_connection_pool
   ```

### 2. Autonomous Diagnostic Steps
- Trace latency breakdown via Prometheus histogram:
   ```promql
   histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[2m])) by (le))
   ```
- Query Linux system resource load on RHEL 10.

### 3. Remediation Actions
1. **Low Blast Radius**: Recycle TicketFlow API worker processes:
   ```bash
   pkill -f 'ticketflow-api/main.py'
   nohup /opt/aist/venv/bin/python3 /opt/aist/ticketflow-api/main.py > /opt/aist/ticketflow-api/api.log 2>&1 &
   ```
2. **Clear Upstream Deadlocks**: If root cause is SQL lock contention, execute RB-02.

