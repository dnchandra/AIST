# SRE Runbook: RB-01 - Linux CPU & Memory Saturation Triage

## Severity: CRITICAL / P1
**Target Environments**: Red Hat Enterprise Linux 10 (`192.168.1.130`), RHEL 9 (`192.168.1.131`)  
**Alert Triggers**: `LinuxNodeHighCPU`, `LinuxNodeMemoryExhaustion`

---

### 1. Initial Assessment
When Linux host CPU exceeds 85% or load average exceeds core count:
1. Identify the top CPU-consuming processes:
   ```bash
   ps -eo pid,ppid,user,%cpu,%mem,cmd --sort=-%cpu | head -10
   ```
2. Check memory and swap starvation:
   ```bash
   free -m
   vmstat 1 5
   ```

### 2. Autonomous Diagnostic Steps
- Run `uptime` to evaluate 1m, 5m, 15m load trends.
- Check if runaway threads belong to `ticketflow-api` or a rogue background task:
   ```bash
   top -b -n 1 | head -15
   ```

### 3. Remediation Actions
1. **Low Blast Radius**: Throttle or terminate runaway CPU process:
   ```bash
   kill -TERM <pid>
   ```
2. **Service Recovery**: If the application worker is saturated:
   ```bash
   systemctl restart ticketflow-api
   ```
3. **Escalation**: If load persists due to external DDoS or kernel lockup, page Infrastructure On-Call.

