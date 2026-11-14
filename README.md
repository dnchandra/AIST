# AIST: Autonomous SRE Incident Triage Platform v3.0

> **Enterprise Multi-OS SRE Incident Triage & Commercial Lending Platform**  
> Running on VMware vSphere 8.0 (`Base_DS` VMFS High-Speed Datastore) & Air-Gapped Local Workstation AI Inference (NVIDIA GeForce RTX 5090 24GB VRAM)  
> **Workspace:** `d:\2026_Projects\AIST`

---

## 0. Quick Access Directory & SRE Consoles

All primary interfaces and operational consoles can be launched and verified using `python manage_aist.py urls` or `python manage_aist.py status`:

| Console / Service | Primary Access URL | Credentials / Notes | Purpose |
|:---|:---|:---|:---|
| **🏦 LoanProcessAI Web Portal** | [`http://192.168.1.132:3000/`](http://192.168.1.132:3000/) | None (Open) | Commercial lending operations, customer loan intake, and banker underwriting cockpit (React 18 via Native C# Async Reverse Proxy). |
| **🚀 AIST SRE Frontend Cockpit** | [`http://localhost:3001/`](http://localhost:3001/) <br> *(or [`http://localhost:8000/`](http://localhost:8000/))* | None (Open) | Glassmorphic React 18 SPA, AI Copilot, Chaos Studio, Grafana Dashboards, Hybrid RAG, Rolling Logs. |
| **📖 AI Triage Backend API & Docs** | [`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs) | None (Open) | Interactive OpenAPI Swagger UI, Health Probes, FastMCP Endpoints, RAG Search API. |
| **📊 Grafana 11.4 Unified Dashboards** | [`http://192.168.1.131:3000/`](http://192.168.1.131:3000/) | `admin` / `admin` | 8 Dedicated Production SRE Dashboards (SLI/SLO, Golden Signals, AI Swarm, LoanProcessAI Business KPIs, RTX 5090 Telemetry). |
| **🎯 Prometheus 3.0 Metric Targets** | [`http://192.168.1.131:9090/targets`](http://192.168.1.131:9090/targets) | None (Open) | Metric Scrape Pool Health, PromQL Query Console, Real-time SQLite sync. |
| **🚨 AlertManager 0.27 Incident Router** | [`http://192.168.1.131:9093/`](http://192.168.1.131:9093/) | None (Open) | Active Multi-Window Burn Rate Alerts & AI Autonomous Webhook Receiver. |
| **📜 Loki 3.3 Centralized Logs** | [`http://192.168.1.131:3100/ready`](http://192.168.1.131:3100/ready) | None (Open) | Central LogQL Ingestion Aggregator for Linux & Windows Fleet Microservices. |
| **🔍 Tempo 2.6 Distributed Tracing** | [`http://192.168.1.131:3000/explore`](http://192.168.1.131:3000/explore) | `admin` / `admin` | OpenTelemetry gRPC (`:4317`) & HTTP (`:4318`) Trace Waterfall Viewer. |
| **🌐 VMware vCenter Server 8.0** | [`https://192.168.1.220/ui`](https://192.168.1.220/ui) | `administrator@vsphere.local` | ESXi 8.0 Hypervisor, `Base_DS` Datastore, Thin-Provisioned VM Lifecycle. |
| **🔬 Local AI Brain (Ollama)** | [`http://127.0.0.1:11434/api/tags`](http://127.0.0.1:11434/api/tags) | Localhost (RTX 5090) | `ornith-1.5:35b` (Reasoning LLM) & `embeddinggemma-2:740m` (Dense Neural Embeddings). |
| **📁 Rolling Log Files** | `logs/manage_aist.log`<br>`logs/aist_backend.log` | Auto-created (10MB max, 5 backups) | Dual-logged to terminal stdout and persistent rolling files in repository `logs/` folder. |

---

## 1. Executive System Overview

**AIST** (Autonomous Incident SRE Triage) is an enterprise-grade site reliability engineering platform engineered to autonomously investigate, diagnose, and propose remediations for complex multi-tier incidents across heterogeneous operating systems:
- **Red Hat Enterprise Linux 10** (`192.168.1.130`): Application & Core API Tier (LoanProcessAI REST API on port 5000, Notification Service on port 8080, Node Exporter on port 9100).
- **Red Hat Enterprise Linux 9** (`192.168.1.131`): Observability Hub (Prometheus 3.0 on port 9090, Grafana 11.4 on port 3000, Loki 3.3 on port 3100, Tempo 2.6 on port 3200, AlertManager 0.27 on port 9093).
- **Windows Server 2025** (`192.168.1.132`): Web Portal & Security Tier (LoanPortal React WebUI on port 3000 via high-concurrency Native C# Async Proxy, Auth Gateway on port 5001, Windows Exporter on port 9182, WinRM diagnostics).
- **Windows Server 2019** (`192.168.1.133`): Database & Audit Tier (TicketFlowDB transactional lock simulation, Audit Service on port 8088, Windows Exporter on port 9182, WinRM diagnostics).
- **Local Engineering Workstation** (`192.168.1.14`): Air-Gapped AI Brain (Ollama with `ornith-1.5:35b` + `embeddinggemma-2:740m` on RTX 5090 24GB VRAM, FastMCP 4.1.6 Server, FastAPI Backend on port 8000, Operations WebUI Console on port 3001).

```text
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

## 2. Infrastructure & Enterprise IP Topology

To eliminate IP collisions with corporate DHCP pools (`192.168.1.1 - 192.168.1.50`), all target VMs are assigned static IP addresses from the dedicated enterprise pool (**`192.168.1.130 - 192.168.1.133`**). All virtual machines reside exclusively on the high-speed datastore **`Base_DS` (`datastore-12`)** with thin provisioning to prevent storage over-commitment.

VMs are cloned in parallel directly from master templates in vCenter (`RHEL10_Template`, `RHEL9_Template`, `Win2025_Template`, `Win2019_Template`), ensuring master templates remain protected and unmodified.

| VM Name | Target Host | Operating System | Static Enterprise IP | Hardware Specs | Core Services | Ports Exposed |
|:---|:---|:---|:---|:---|:---|:---|
| **RHEL10** | ESXi `192.168.1.221` | RHEL 10 Enterprise | `192.168.1.130` | 4 vCPUs, 16 GB RAM | LoanProcessAI Core API, Notification Svc, Node Exporter | `22`, `5000`, `8080`, `9100` |
| **RHEL9** | ESXi `192.168.1.221` | RHEL 9 Enterprise | `192.168.1.131` | 4 vCPUs, 16 GB RAM | Observability Hub (Prometheus, Grafana, Loki, Tempo, AlertManager) | `22`, `9090`, `3000`, `3100`, `3200`, `9093`, `4317`, `4318`, `9100` |
| **Win2025** | ESXi `192.168.1.221` | Windows Server 2025 | `192.168.1.132` | 4 vCPUs, 16 GB RAM | LoanPortal WebUI (`:3000`), Auth Gateway (`:5001`), Windows Exporter, WinRM | `3000`, `5001`, `5985`, `9182` |
| **Win2019** | ESXi `192.168.1.221` | Windows Server 2019 | `192.168.1.133` | 4 vCPUs, 16 GB RAM | Audit & DB Service, TicketFlowDB storage, Windows Exporter, WinRM | `8088`, `5985`, `1433`, `9182` |
| **Local Host** | Laptop | Windows 11 (RTX 5090) | `192.168.1.14` | 24GB VRAM, 64GB RAM | Ollama Engine (`ornith-1.5:35b`), FastAPI Backend, WebUI Console | `11434`, `8000`, `3001` |

---

## 3. LoanProcessAI Commercial Lending Engine

### High-Concurrency Native C# Reverse Proxy
The LoanPortal React application on Windows Server 2025 (`192.168.1.132:3000`) is served by an in-memory compiled C# multi-threaded HTTP server (`NativePortalServer`) via `scripts/portal_server.ps1`:
- **CLR ThreadPool Dispatch**: Uses `ThreadPool.QueueUserWorkItem` to handle concurrent static asset and API requests with zero memory or runspace leaks.
- **Fast Static Delivery**: Serves compiled React production artifacts in under 10ms with explicit Content-Type headers.
- **Extended Timeout Proxy**: Forwards REST calls (`/applications`, `/cases`, `/process`, `/decide`, `/business-metrics`) to RHEL 10 (`http://192.168.1.130:5000`) with a 15-minute connection timeout to accommodate complex multi-agent LLM reasoning chains.
- **Full Body Buffering**: Correctly buffers JSON and multipart payloads, computing precise `Content-Length` headers and preventing protocol violations during PDF document uploads.

### Deterministic 5-Agent Autonomous Pre-Approval Pipeline
1. **Document Intake & Validation Agent**: Classifies uploaded PDF documents (Tax Returns, Profit & Loss, Balance Sheets, Certificate of Incorporation), extracts structured metadata.
2. **KYC Concierge & Compliance Agent**: Validates identity, owner TIN/SSN, address match, and executes OFAC/PEP sanctions screening.
3. **Financial Spreading Agent**: Calculates Debt Service Coverage Ratio (DSCR), Debt-to-Equity (D/E), current ratio, and detects cross-period anomalies.
4. **Credit Memo Drafting Agent**: Generates five-C credit analysis (Character, Capacity, Capital, Collateral, Conditions).
5. **Decision Support Agent**: Synthesizes policy checks, recommends AI GO/NO-GO verdict, and suggests pricing tier and covenants.
6. **Manager Final Sign-Off**: Human credit officer executes approval or decline, triggering the Closing Package Assembler Agent.

---

## 4. Production Grafana SRE Dashboard Catalog

All monitoring is centralized across 8 dedicated production dashboards on Grafana 11.4 (`http://192.168.1.131:3000`):

1. **`01 - AIST Multi-OS SLI, SLO & Error Budget Command Center` (`uid: aist-01-sli-slo`)**:
   - Executive SLI Gauges: Availability SLI (99.9% target), Latency SLI (p95 < 500ms), Error Budget Remaining (%).
   - Multi-OS Microservice Fleet Availability Matrix (LoanProcessAI, Auth Gateway, Audit Svc, Notification Svc, Node Exporters).
   - Multi-Window Multi-Burn-Rate (1h, 6h) time-series curves.
2. **`02 - Multi-OS Infrastructure & Server Level Health` (`uid: aist-02-server-health`)**:
   - CPU and Memory Saturation for RHEL 10, RHEL 9, Windows Server 2025, and Windows Server 2019.
   - Disk I/O throughput, active TCP connections, system uptime.
3. **`03 - LoanProcessAI Business Application & Frontend Performance` (`uid: aist-03-business-frontend`)**:
   - Frontend Availability SLA (15m window via Windows Exporter).
   - Synthetic UI Probe Latency.
   - Commercial Loan Business Intake Funnel & Portfolio Value ($M).
   - Core API Interaction Rates & Latency Percentiles (p50, p90, p99).
4. **`04 - GenAI RAG & Local LLM Engine Telemetry (RTX 5090)` (`uid: aist-04-genai-llm`)**:
   - Local AI Brain (Ollama on RTX 5090) hardware acceleration status.
   - LLM Inference Duration (ms), Swarm Invocations, Token Burn Velocity (Tokens/sec).
   - Hallucination Risk Score and RAG Document Groundedness Score.
5. **`05 - Multi-Agent Pipeline Orchestration & Workflow Health` (`uid: aist-05-multi-agent`)**:
   - Specialist Agent Stage Latency (Intake, KYC, Financial, Memo, Decision).
   - Specialist Success Reliability (%), Invocations by Specialist.
   - Cumulative Tokens Burned, Underwriting Decisions (Approved vs Pending Review).
6. **`06 - Autonomous SRE Incident Lifecycle & AI Triage Brain` (`uid: aist-06-incident-lifecycle`)**:
   - Active Incidents by Severity (P1/P2/P3), Incident MTTR.
   - Autonomous vs Human Remediation Rate, Investigation Steps Completed.
7. **`07 - Unified Live Logs & Cross-Platform Correlation Explorer` (`uid: aist-07-live-logs`)**:
   - Live stream from Loki 3.3 (`{app="ticketflow"}`).
   - Cross-platform correlation across Linux `journald` and Windows Event Logs.
   - Log ingestion rate by microservice.
8. **`08 - SRE Automation Safety & Policy Guardrails` (`uid: aist-08-automation-safety`)**:
   - Self-healing execution attempts, Circuit Breaker status.
   - Allowlisted command validation rate, unauthorized action block count.

---

## 5. Canonical Management CLI (`manage_aist.py`)

A single, unified Python orchestration CLI controls the complete platform lifecycle:

```powershell
# Activate Virtual Environment
cd d:\2026_Projects\AIST
.\.venv\Scripts\activate

# 1. Automated Infrastructure & VM Fleet Setup (Parallel Native vCenter Cloning)
python manage_aist.py setup

# 2. Deploy microservices, React bundle, C# reverse proxy, & observability
python manage_aist.py deploy

# 3. Start services across all nodes and local AI host
python manage_aist.py start all

# 4. Run automated 24-point end-to-end verification suite
python manage_aist.py status
# or alias:
python manage_aist.py test

# 5. View all service endpoints, URLs, and directory
python manage_aist.py urls

# 6. Stream live logs from any service
python manage_aist.py logs ticketflow --lines 30
python manage_aist.py logs auth --lines 30

# 7. Stop services across fleet
python manage_aist.py stop all

# 8. Safe Infrastructure Teardown (Destroys VMs while strictly preserving Master Templates)
python manage_aist.py clean-infra
```

---

## 6. End-to-End Verification & Health Matrix (24/24 Passed)

Execution of `python manage_aist.py status` confirms complete platform readiness:

```text
====================================================================================================================
TIER           | COMPONENT                      | URL / ENDPOINT                         | STATUS       | LATENCY  | RES
--------------------------------------------------------------------------------------------------------------------
AI Brain       | Ollama Server                  | http://127.0.0.1:11434/api/tags        | ONLINE       | 197.1ms  | PASS
AI Brain       | Reasoning LLM (ornith-1.5:35b) | local:RTX 5090                         | LOADED       | GPU VRAM | PASS
AI Brain       | Embedding LLM (embeddinggemma) | local:RTX 5090                         | LOADED       | GPU VRAM | PASS
Microservice   | LoanProcessAI Health (RHEL 10) | http://192.168.1.130:5000/healthz      | HTTP 200     | 36.0ms   | PASS
Microservice   | LoanProcessAI Applications     | http://192.168.1.130:5000/applications | HTTP 200     | 321.6ms  | PASS
Microservice   | LoanProcessAI Metrics (RHEL 10)| http://192.168.1.130:5000/metrics      | HTTP 200     | 35.0ms   | PASS
Microservice   | LoanPortal Frontend (Win2025)  | http://192.168.1.132:3000/             | HTTP 200     | 6.6ms    | PASS
Microservice   | Notification Service Health    | http://192.168.1.130:8080/health       | HTTP 200     | 17.8ms   | PASS
Microservice   | Notification Metrics (RHEL 10) | http://192.168.1.130:8080/metrics      | HTTP 200     | 10.7ms   | PASS
Microservice   | Auth Gateway Health (Win2025)  | http://192.168.1.132:5001/health       | HTTP 200     | 141.6ms  | PASS
Microservice   | Auth Gateway Token (Win2025)   | http://192.168.1.132:5001/api/v1/auth  | HTTP 200     | 30.3ms   | PASS
Microservice   | Auth Gateway Metrics (Win2025) | http://192.168.1.132:5001/metrics      | HTTP 200     | 6.7ms    | PASS
Microservice   | Audit & DB Service Health      | http://192.168.1.133:8088/health       | HTTP 200     | 38.5ms   | PASS
Microservice   | Audit Event Logs (Win2019)     | http://192.168.1.133:8088/api/v1/audit | HTTP 200     | 9.7ms    | PASS
Microservice   | Audit Service Metrics (Win2019)| http://192.168.1.133:8088/metrics      | HTTP 200     | 5.2ms    | PASS
Observability  | Prometheus 3.0 Dashboard       | http://192.168.1.131:9090              | HTTP 200     | 7.8ms    | PASS
Observability  | Grafana 11.4 WebUI             | http://192.168.1.131:3000              | HTTP 200     | 60.0ms   | PASS
Observability  | AlertManager 0.27 API          | http://192.168.1.131:9093              | HTTP 200     | 6.6ms    | PASS
Observability  | Node Exporter (RHEL 10)        | http://192.168.1.130:9100/metrics      | HTTP 200     | 52.8ms   | PASS
Observability  | Node Exporter (RHEL 9)         | http://192.168.1.131:9100/metrics      | HTTP 200     | 55.1ms   | PASS
Observability  | Windows Exporter (Win2025)     | http://192.168.1.132:9182/metrics      | HTTP 200     | 4652.0ms | PASS
Observability  | Windows Exporter (Win2019)     | http://192.168.1.133:9182/metrics      | HTTP 200     | 4339.4ms | PASS
FastMCP Tool   | mcp_vcenter.status             | https://192.168.1.220/api              | 8 VMs Discovered | 369.3ms  | PASS
FastMCP Tool   | mcp_linux_diag.run_ssh         | ssh://root@192.168.1.130:22            | localhost.localdomain | 620.5ms  | PASS
====================================================================================================================
 Verification Summary: 24 / 24 Tests Passed (100.0% System Health)
====================================================================================================================
```
