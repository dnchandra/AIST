# SRE Runbook: RB-06 - VMware vSphere Datastore & Hypervisor I/O Pressure

## Severity: CRITICAL / P1
**Target Environments**: VMware vCenter (`192.168.1.220`) / ESXi (`192.168.1.221`)  
**Alert Triggers**: `DatastoreFreeSpaceLow`, `DatastoreHighIOPressure`

---

### 1. Initial Assessment
When VMFS Datastore free space drops below 15% or latency exceeds 25ms:
1. Query datastore capacity via FastMCP:
   ```python
   tool_query_vcenter()
   ```
2. Verify that all 4 active VMs are consolidated on `Base_DS` (`datastore-12`) using Thin Provisioning.

### 2. Autonomous Diagnostic Steps
- Inspect external storage devices: Ensure unneeded high-latency USB datastores are unmounted or disconnected.
- Check VM disk usage:
   ```bash
   df -h /
   ```

### 3. Remediation Actions
1. **Low Blast Radius**: Prune orphaned VM snapshots and temporary logs:
   ```bash
   rm -rf /opt/aist/*/*.log
   ```
2. **Datastore Storage vMotion**: Relocate non-critical workloads away from `Base_DS`.

