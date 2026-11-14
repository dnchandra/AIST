# AIST: Enterprise Implementation Plan & Operational Reference

> **Autonomous SRE Incident Triage & Governed Self-Healing Platform v3.0**  
> VMware vSphere (`Base_DS` VMFS High-Speed Datastore) + Local RTX 5090 GPU AI Host  
> **Workspace:** `d:\2026_Projects\AIST`

---

## 1. Executive Objective

The **AIST** platform provides autonomous incident investigation, root-cause correlation, and governed self-healing across heterogeneous environments (RHEL 10, RHEL 9, Windows Server 2025, Windows Server 2019, Podman containers, and VMware vSphere 7/8).

### Safety Core Principle
**No LLM, UI client, alert payload, log line, or retrieved document may supply an executable shell command.** They can select only a reviewed, server-side allowlisted action identifier. The execution worker resolves the command from `remediation_policy.py`, executes it under least-privilege via WinRM or SSH, observes health for a mandatory 30-second verification window, and trips a circuit breaker after 3 failed attempts to escalate to an evidence-rich incident ticket.

---

## 2. Live Validation Evidence (Verified on Live Infrastructure)

All platform components have been tested against the live VMware and RTX 5090 environment:

- **Full Health Matrix (`python manage_aist.py status`):** **21/21 checks passed** (100.0% System Health), including vCenter (8 VMs discovered), Ollama (`ornith-1.5:35b` + `embeddinggemma-2` in GPU VRAM), RHEL 10, RHEL 9, Windows Server 2025, Windows Server 2019, Prometheus 3.0, Grafana 11.4, AlertManager 0.27, and Node Exporters.
- **Safety Boundary API Tests (`python scripts/test_safety_boundary.py`):** Verified that arbitrary commands, unrecognized action IDs, unapproved requests, and invalid chaos targets are strictly rejected (HTTP 404, 409, 422).
- **Monitored Self-Healing Verification:** Verified that controlled service disruptions on RHEL 10 Notification Service and Windows Server 2025 AuthGateway trigger policy-bound restarts, execute continuous health probes for 30 seconds, and record `VERIFIED` status upon sustained recovery.
- **Circuit Breaker & Escalation:** Tested escalation contract: when no approved runbook exists or after 3 consecutive failed recovery attempts, AIST marks the incident `ESCALATED`, freezes automated retries, and creates a durable ticket with attached diagnostic evidence.
- **Autonomous E2E LangGraph Triage (`python scripts/test_backend_e2e.py`):** Verified multi-agent investigation (`triage_coordinator` $\rightarrow$ `os_diagnostics_specialist` $\rightarrow$ `rca_synthesis_node` $\rightarrow$ `human_review_node`) executing against live endpoints and local `ornith-1.5:35b`.

---

## 3. Platform Architecture & Service Topology

| Host Name | VM ID | Target OS | Static Enterprise IP | Role & Services | Key Ports |
|:---|:---|:---|:---|:---|:---|
| `vm-32` | ESXi `host-9` | RHEL 10 Enterprise | `192.168.1.130` | TicketFlow REST API, Notification Service, Node Exporter | `22`, `5000`, `8080`, `9100` |
| `vm-27` | ESXi `host-9` | RHEL 9 Enterprise | `192.168.1.131` | Observability Hub: Prometheus 3.0, Grafana 11.4, Loki 3.3, Tempo 2.6, AlertManager 0.27 | `22`, `9090`, `3000`, `3100`, `3200`, `9093`, `4317`, `4318`, `9100` |
| `vm-24` | ESXi `host-9` | Windows Server 2025 | `192.168.1.132` | Auth Gateway Service (.NET HTTP/JWT), Windows Exporter | `5001`, `5985` (WinRM), `9182` |
| `vm-28` | ESXi `host-9` | Windows Server 2019 | `192.168.1.133` | Audit & DB Service, TicketFlowDB storage, Windows Exporter | `8088`, `5985` (WinRM), `1433`, `9182` |
| **Local Host** | Laptop | Windows 11 (RTX 5090) | `192.168.1.16` | AI Brain (`ornith-1.5:35b`), FastMCP 4.1.6 Server, FastAPI Backend, WebUI Console | `11434` (Ollama), `8000` (FastAPI), `3001` (WebUI Console) |

---

## 4. Governed Self-Healing Workflow

```text
Service Control / Alert / Synthetic Probe
                 |
                 v
       Persist and Deduplicate Incident (data/aist_state.db)
                 |
                 v
   Gather Bounded FastMCP Evidence (Metrics, Logs, Trace, Event Viewer, Supervisor State)
                 |
                 v
   Retrieve Current Approved Runbook + Select Policy-Bound Action ID
           |                              |
           | No valid runbook / action     | Valid low-risk action
           v                              v
   Escalate to Ticket Immediately  Queue One Remediation Attempt
                                          |
                               Execute via Least-Privilege Worker (WinRM / SSH)
                                          |
                               Observe Health for 30 Seconds
                               /             |              \
                          Healthy        Unhealthy          No Response
                            |                 |                 |
                        RESOLVED        Retry if < 3      Retry if < 3
                                              |                 |
                                              +------>=3------+
                                                         |
                                              Trip Circuit Breaker & Open Ticket
                                              with RCA, Evidence, and Action History
```

### Server-Side Remediation Catalog (`remediation_policy.py`)
- `recover_auth_gateway` (`WIN2025`): Recycles the AuthGateway process via WinRM and verifies port 5001 TCP connectivity.
- `recover_sql_lock` (`WIN2019`): Clears transactional lock contention on TicketFlowDB and verifies database responsiveness.
- `recover_notification_queue` (`RHEL10`): Restores the Notification Service queue consumer and probes `/health`.
- `stop_synthetic_cpu_stress_rhel10` (`RHEL10`): Terminates background CPU stress processes and confirms run queue normalization.
- `stop_synthetic_cpu_stress_rhel9` (`RHEL9`): Terminates CPU contention on the Observability hub.

---

## 5. Web Console Workspaces

The compiled WebUI (`http://localhost:3001`) exposes 4 purpose-built interfaces:
1. **AI SRE Copilot Chat:** Plain-English NLP conversational triage powered by `ornith-1.5:35b`. Employs automatic `<think>` reasoning stream isolation, non-duplicated chronological timeline tables, and 1-click HITL self-healing cards.
2. **Dedicated Chaos Engineering Studio:** Full-page chaos workbench featuring Multi-Stage Cascading Outages (P0) and granular target server failure matrices (`WIN2025`, `WIN2019`, `RHEL10`, `RHEL9`).
3. **Service Operations Console:** Real-time lifecycle controls (Start/Stop/Restart) backed by the durable SQLite state store (`data/aist_state.db`).
4. **Grafana Observability Portal:** Deep links to the 5 provisioned Grafana 11.4 dashboards (`aist-sli-slo`, `aist-golden-signals`, `aist-ai-triage`, `aist-live-logs`, `aist-service-ops`).

---

## 6. Canonical Unified CLI (`manage_aist.py`)

All lifecycle and verification commands are consolidated into a single Python CLI:

```bash
# 1. Launch WebUI (3001) & Backend (8000)
python manage_aist.py start

# 2. Run 21-point automated verification suite
python manage_aist.py status
# or: python manage_aist.py test

# 3. Stop all services across VMs and local processes
python manage_aist.py stop

# 4. Deploy all microservices and observability stack
python manage_aist.py deploy

# 5. Validate vCenter, Base_DS storage, and firewalls
python manage_aist.py setup

# 6. Inject chaos scenarios
python manage_aist.py chaos --scenario cpu_spike
python manage_aist.py chaos --scenario multistage_cascade

# 7. Recover all failure scenarios
python manage_aist.py recover

# 8. Clean temporary logs while preserving VM disks
python manage_aist.py clean
```

---

## 7. Production Roadmap & Promotion Gates

To promote actions from human-approved to fully autonomous execution, the following gates must be met:
1. **Durable State Migration:** Migrate `data/aist_state.db` from SQLite to PostgreSQL 16 for high-concurrency multi-operator leasing.
2. **Hybrid RAG Runbook Ingestion:** Ingest markdown runbooks into Elasticsearch 8.16+ with HNSW dense vector embeddings (`embeddinggemma-2`) and BM25 lexical search with RRF scoring.
3. **Mutual TLS & Secret Storage:** Replace plaintext environment secrets with HashiCorp Vault or AWS/GCP Secret Manager; replace HTTP WinRM and SSH passwords with client certificates and SSH key pinning.
4. **Autonomous Action Validation:** Require $\ge 20$ consecutive successful human-approved executions and zero false-positive remediation triggers in staging before enabling autonomous execution for any action.

