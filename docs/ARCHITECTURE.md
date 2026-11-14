# AIST: Enterprise Multi-OS SRE & LoanProcessAI Architecture Reference

> **Autonomous Incident SRE Triage & Commercial Lending Platform v3.0**  
> Running on VMware vSphere 8.0 (`Base_DS` VMFS High-Speed Datastore) & Air-Gapped Local RTX 5090 GPU AI Host  
> **Workspace:** `d:\2026_Projects\AIST`

---

## 1. Enterprise Multi-OS Fleet Topology

To prevent IP collisions with corporate DHCP ranges (`192.168.1.1 - 192.168.1.50`), the fleet is allocated static enterprise IP addresses in the dedicated `192.168.1.130 - 192.168.1.133` subnet. All virtual machine disks (`.vmdk`) reside exclusively on high-speed datastore **`Base_DS` (`datastore-12`)** with thin provisioning.

VMs are automatically provisioned in parallel via native VMware vCenter cloning from dedicated master templates, leaving master templates completely intact.

| Host Name | VM ID | Operating System | Static Enterprise IP | Hardware Specs | Primary Workloads & Services | Ports Exposed |
|:---|:---|:---|:---|:---|:---|:---|
| **RHEL10** | `vm-2006` | Red Hat Enterprise Linux 10 | `192.168.1.130` | 4 vCPUs, 16 GB RAM | LoanProcessAI Core REST API (`systemd: aist-ticketflow`), Notification Service (`:8080`), Node Exporter (`:9100`) | `22` (SSH), `5000` (API), `8080`, `9100` |
| **RHEL9** | `vm-2007` | Red Hat Enterprise Linux 9 | `192.168.1.131` | 4 vCPUs, 16 GB RAM | Observability Hub: Prometheus 3.0, Grafana 11.4, Loki 3.3, Tempo 2.6, AlertManager 0.27, Node Exporter | `22` (SSH), `9090` (Prom), `3000` (Grafana), `3100` (Loki), `9093` (Alerts), `9100` |
| **Win2025** | `vm-2008` | Windows Server 2025 Datacenter | `192.168.1.132` | 4 vCPUs, 16 GB RAM | LoanPortal WebUI (`:3000` via Native C# Async Proxy), Auth Gateway (`:5001`), Windows Exporter (`:9182`), WinRM | `3000` (WebUI), `5001` (Auth), `5985` (WinRM), `9182` |
| **Win2019** | `vm-2009` | Windows Server 2019 Datacenter | `192.168.1.133` | 4 vCPUs, 16 GB RAM | Audit & Transaction Service (`:8088`), SQL Lock Simulator, Windows Exporter (`:9182`), WinRM | `8088` (Audit), `5985` (WinRM), `1433` (SQL), `9182` |
| **Local AI Host** | Localhost | Windows 11 Pro (Laptop) | `192.168.1.14` | RTX 5090 (24GB VRAM), 64GB RAM | Ollama Server (`ornith-1.5:35b` + `embeddinggemma-2`), FastAPI SRE Backend (`:8000`), SRE Cockpit (`:3001`), FastMCP Tools | `11434` (Ollama), `8000` (SRE API), `3001` (Cockpit) |

```
                                  +-------------------------------------------------------------+
                                  |            AIST LOCAL AI WORKSTATION (RTX 5090)             |
                                  |                                                             |
                                  |  +--------------------+   +-------------------------------+  |
                                  |  |   Ollama Engine    |   |  FastAPI Backend & SRE WebUI  |  |
                                  |  |   ornith-1.5:35b   |<--|    http://127.0.0.1:8000/     |  |
                                  |  | embeddinggemma-2   |   |    http://localhost:3001/     |  |
                                  |  +--------------------+   +---------------+---------------+  |
                                  |                                           |                  |
                                  |                           +---------------+---------------+  |
                                  |                           |    LangGraph 0.2 Agent Swarm  |  |
                                  |                           |    FastMCP 4.1.6 Tool Protocol|  |
                                  |                           +---------------+---------------+  |
                                  +-------------------------------------------|-----------------+
                                                                              |
                                     +----------------------------------------+---------------------------------------+
                                     |                                        |                                       |
                                     v                                        v                                       v
                     +-------------------------------+        +-------------------------------+       +-------------------------------+
                     |    RHEL 10 (192.168.1.130)    |        |     RHEL 9 (192.168.1.131)    |       |    Win 2025 (192.168.1.132)   |
                     |  - LoanProcessAI API (:5000)  |        |  - Prometheus 3.0 (:9090)     |       |  - LoanPortal WebUI (:3000)   |
                     |  - SQLite /opt/aist/data/     |<-------|  - Grafana 11.4   (:3000)     |       |    (Native C# Reverse Proxy)  |
                     |  - Notification Svc  (:8080)  | Scrapes|  - AlertManager   (:9093)     |       |  - Auth Gateway     (:5001)   |
                     |  - Node Exporter     (:9100)  |        |  - Loki 3.3 Logs  (:3100)     |       |  - WinRM Management (:5985)   |
                     +-------------------------------+        |  - Tempo Traces   (:3200)     |       +-------------------------------+
                                     |                        +---------------+---------------+                       |
                                     |                                        | Alerts                                v
                                     +----------------------------------------+---------------------->+-------------------------------+
                                                                              | Webhook               |    Win 2019 (192.168.1.133)   |
                                                                              v                       |  - Audit Service     (:8088)  |
                                                                    (AI Triage Webhook)               |  - TicketFlowDB Storage       |
                                                                                                      |  - WinRM Management (:5985)   |
                                                                                                      +-------------------------------+
                                                                                                                      ^
                                                                                                                      |
                                          +---------------------------------------------------------------------------+
                                          | VMware vSphere ESXi 192.168.1.221 / vCenter 192.168.1.220                 |
                                          | Target Datastore: Base_DS (High-Speed VMFS, 4 vCPUs / 16 GB RAM per VM)   |
                                          +---------------------------------------------------------------------------+
```

---

## 2. LoanProcessAI Commercial Lending Architecture

LoanProcessAI is an enterprise commercial lending orchestration system deployed across RHEL 10 and Windows Server 2025:

### 2.1 High-Performance Native C# Reverse Proxy (`portal_server.ps1`)
Hosted on Windows Server 2025 (`192.168.1.132:3000`), the portal server uses an in-memory compiled C# HTTP server (`NativePortalServer`) via CLR `ThreadPool.QueueUserWorkItem`:
* **Zero Thread / Runspace Leaks**: Completely replaces older PowerShell runspace pooling that leaked under load.
* **Sub-10ms Static Asset Serving**: Directly delivers compiled React 18 production artifacts (`main.js`, `main.css`, images) with explicit HTTP MIME mapping and caching headers.
* **Resilient API Proxying**: Forwards REST routes (`/applications`, `/cases`, `/process`, `/decide`, `/business-metrics`, `/customers`) to RHEL 10 (`http://192.168.1.130:5000`) with a 15-minute connection timeout to accommodate complex multi-agent reasoning without 502/504 errors.
* **Full Body Buffering**: Buffers entity bodies for JSON and `multipart/form-data` document uploads, guaranteeing exact `Content-Length` headers and preventing protocol violation exceptions.

### 2.2 Core Backend & Dual-Key State Machine
Hosted on RHEL 10 (`192.168.1.130:5000`), the FastAPI service manages commercial loan underwriting data:
* **Dual-Key Lookup**: Functions seamlessly support queries by `case_id` (`CASE-XXXXXXXX`) or `application_id` (`APP-XXXXXXXX`), eliminating lookup mismatches across navigation flows.
* **SQLite Persistence**: Stores borrower records, financials, uploaded PDFs, and agent evaluation markdowns in `/opt/aist/loanprocessai/data/loan_origination.db`.
* **Instant Prometheus Sync**: Clears and recomputes `loan_applications_total` and `loan_portfolio_volume_dollars` gauges on every Prometheus scrape, ensuring application deletions and updates reflect live within seconds.

---

## 3. Autonomous Multi-Agent AI Pipeline (RTX 5090 Air-Gapped)

Underwriting intelligence is executed locally on the host's NVIDIA GeForce RTX 5090 GPU (24GB VRAM) via Ollama using `ornith-1.5:35b` (Q4_K_M quantized) and `embeddinggemma-2:740m`:

```
 [Borrower Intake]
         │
         ▼
 [1. Document Intake & Validation Agent] ───────► Classifies documents (W-2, Tax Returns, Financial Statements, EIN)
         │                                       Extracts balance sheets, income statements, entity structure
         ▼
 [2. KYC Concierge & Screening Agent]    ───────► Validates identity, owner SSN/TIN, address verification
         │                                       OFAC/PEP sanctions screening, corporate standing
         ▼
 [3. Financial Spreading Agent]          ───────► Computes DSCR, D/E leverage, current ratio, EBITDA margin
         │                                       Runs ML-based financial anomaly detection across fiscal periods
         ▼
 [4. Credit Memo Drafting Agent]         ───────► Synthesizes 5-C credit analysis (Character, Capacity, Capital,
         │                                       Collateral, Conditions) into a cohesive narrative memo
         ▼
 [5. Decision Support Agent]             ───────► Policy check synthesis, pricing tier, risk rating (BBB+),
         │                                       Automated AI GO / NO-GO recommendation
         ▼
 [6. Human Credit Officer Sign-Off]      ───────► Reviewer verifies findings, inputs notes, and issues approval
         │
         ▼
 [Closing Package Assembler Agent]       ───────► Generates formal loan agreements, security agreements, covenants
```

All 5 agent outputs are persisted in markdown and JSON format, enabling instant hydration and review in the Banker Cockpit.

---

## 4. Production Grafana SRE Dashboard Catalog

The platform mounts 8 dedicated production dashboards on Grafana 11.4 (`http://192.168.1.131:3000`), adhering to modern Google SRE practices with zero capstone or legacy artifacts:

| # | Dashboard Name | UID | Core Visualizations & Focus |
|:---|:---|:---|:---|
| **01** | **AIST Multi-OS SLI, SLO & Error Budget Command Center** | `aist-01-sli-slo` | Executive 3-Nines Availability SLI (99.9%), p95 Latency SLI (<500ms), Error Budget Remaining (%), Multi-Window Burn Rate (1h, 6h), Multi-OS Fleet Status Matrix. |
| **02** | **Multi-OS Infrastructure & Server Level Health** | `aist-02-server-health` | CPU & Memory Saturation across RHEL 10, RHEL 9, Win2025, Win2019; Disk I/O & Network throughput; System uptime. |
| **03** | **LoanProcessAI Business Application & Frontend Performance** | `aist-03-business-frontend` | Frontend Availability SLA (15m window via Windows Exporter), Synthetic UI Probe Latency, Commercial Loan Funnel, Portfolio Volume ($M), API Latency Percentiles (p50/p90/p99). |
| **04** | **GenAI RAG & Local LLM Engine Telemetry (RTX 5090)** | `aist-04-genai-llm` | RTX 5090 GPU acceleration status, LLM Inference Duration (ms), Swarm Invocations, Token Burn Velocity (Tokens/sec), Hallucination Risk Score, RAG Groundedness Score. |
| **05** | **Multi-Agent Pipeline Orchestration & Workflow Health** | `aist-05-multi-agent` | Specialist Stage Latency (Intake, KYC, Financial, Memo, Decision), Specialist Success Reliability (%), Invocations by Specialist, Cumulative Tokens Burned, Underwriting Decisions. |
| **06** | **Autonomous SRE Incident Lifecycle & AI Triage Brain** | `aist-06-incident-lifecycle` | Active Incidents by Severity (P1/P2/P3), Incident MTTR, Autonomous vs Human Remediation Rate, Investigation Steps Completed. |
| **07** | **Unified Live Logs & Cross-Platform Correlation Explorer** | `aist-07-live-logs` | Live log stream from Loki 3.3 (`{app="ticketflow"}`), cross-platform correlation across Linux `journald` and Windows Event Logs, log ingestion rates by service. |
| **08** | **SRE Automation Safety & Policy Guardrails** | `aist-08-automation-safety` | Self-healing execution attempts, Circuit Breaker trips, allowlisted command validation rate, unauthorized action block count. |

---

## 5. FastMCP 4.1.6 Enterprise Diagnostics & Tools

The platform implements FastMCP using official MCP specifications, exposing vetted tools to the AI reasoning engine:

1. **`mcp_windows_diag.event_logs`**: Extracts Warning, Error, and Critical events from Windows Server 2025 / 2019 channels (`Application`, `System`, `Security`).
2. **`mcp_windows_diag.iis_status`**: Probes Windows processes, worker processes, and TCP listener state (`:3000`, `:5001`, `:8088`).
3. **`mcp_windows_diag.os_patching`**: Inspects OS version, last boot time, uptime, and installed security hotfixes.
4. **`mcp_windows_diag.disk_info`**: Queries volume capacity, free space, and storage health.
5. **`mcp_linux_diag.run_ssh`**: Executes read-only system diagnostics on RHEL 10 / RHEL 9 (CPU, memory, journal logs).
6. **`mcp_prometheus.query`**: Queries live Prometheus metrics and SLI compliance.
7. **`mcp_loki.query_logs`**: Executes LogQL range queries across cross-platform log streams.
8. **`mcp_vcenter.status`**: Inspects VMware vCenter 8.0 for VM inventory, power state, and datastore allocation.

---

## 6. Governed Self-Healing & Safety Boundaries

To prevent unauthorized, unsafe, or destructive actions:
* **Allowlisted Action Catalog**: The AI agent cannot execute arbitrary shell commands. It selects pre-vetted Action IDs (e.g., `recover_auth_gateway`, `recover_loan_portal`) mapped server-side in `remediation_policy.py`.
* **Monitored 30s Stability Probe**: Following any remediation action, a synthetic probe monitors service health for 30 seconds.
* **Circuit Breaker**: If three consecutive remediation attempts fail, the circuit breaker trips, halting further automated interventions and paging an SRE engineer.
