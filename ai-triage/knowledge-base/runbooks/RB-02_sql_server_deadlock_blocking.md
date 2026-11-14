# SRE Runbook: RB-02 - SQL Server Exclusive Lock & Deadlock Contention

## Severity: HIGH / P2
**Target Environments**: Windows Server 2019 (`192.168.1.133`)  
**Alert Triggers**: `SQLServerBlockedSessions`, `DatabaseTransactionTimeout`

---

### 1. Initial Assessment
When `sqlserver_blocked_sessions > 3` or API calls return HTTP 500 transaction deadlocks:
1. Identify blocked SPIDs and the head blocker query:
   ```sql
   SELECT 
       blocking_session_id AS Blocker_SPID,
       session_id AS Blocked_SPID,
       wait_type, wait_time, last_wait_type
   FROM sys.dm_exec_requests
   WHERE blocking_session_id <> 0;
   ```
2. Determine resource held: Check if an exclusive table lock `TABLOCKX` is held on `Tickets`.

### 2. Autonomous Diagnostic Steps
- Query Windows Server 2019 Audit Service:
  ```powershell
  Invoke-RestMethod -Uri "http://192.168.1.133:8088/api/v1/audit/logs"
  ```
- Check system event log for Event ID 1205 (Deadlock):
  ```powershell
  Get-EventLog -LogName Application -Source "*SQL*" -Newest 5
  ```

### 3. Remediation Actions
1. **Low Blast Radius**: Kill the head blocking session:
   ```sql
   KILL <blocker_spid>;
   ```
2. **Safe Automated Reset**: Call Audit Service chaos recovery endpoint:
   ```powershell
   Invoke-RestMethod -Uri "http://192.168.1.133:8088/api/v1/chaos/recover" -Method Post
   ```

