import React, { useState, useEffect, useRef } from 'react';
import { 
  ShieldAlert, Server, Cpu, Terminal, CheckCircle2, XCircle, 
  AlertTriangle, RefreshCw, Play, Square, RotateCw, FileText, ChevronDown, ChevronRight,
  Database, Activity, ArrowUpRight, Lock, Check, Send, Flame, Zap, MessageSquare,
  Layers, ExternalLink, Trash2, Clock, Sparkles, HardDrive, AlertCircle,
  BookOpen, Radio, ScrollText, Eye, EyeOff, Search, PlayCircle, StopCircle
} from 'lucide-react';

const API_BASE = "http://127.0.0.1:8000";

export default function App() {
  // Navigation: 'copilot' | 'chaos' | 'services' | 'observability' | 'runbooks' | 'logs'
  const [activeView, setActiveView] = useState('copilot');

  // Copilot Chat State
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [expandedThoughts, setExpandedThoughts] = useState({});
  const [expandedTools, setExpandedTools] = useState({});
  const messagesEndRef = useRef(null);

  // Global Telemetry & Incidents State
  const [telemetry, setTelemetry] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [incidentFilter, setIncidentFilter] = useState("all");
  const [actionFeedback, setActionFeedback] = useState("");
  const [scenarios, setScenarios] = useState([]);
  const [serviceInventory, setServiceInventory] = useState([]);

  // Observability & Iframe state
  const [selectedDashboard, setSelectedDashboard] = useState(null);

  // Runbook & RAG state
  const [runbooks, setRunbooks] = useState([]);
  const [runbookQuery, setRunbookQuery] = useState("");
  const [runbookResults, setRunbookResults] = useState(null);
  const [isSearchingRunbooks, setIsSearchingRunbooks] = useState(false);

  // Synthetic Traffic Generator state
  const [trafficActive, setTrafficActive] = useState(false);
  const [trafficBatches, setTrafficBatches] = useState(0);

  // Rolling Logs Explorer state
  const [logSource, setLogSource] = useState("backend");
  const [logLines, setLogLines] = useState([]);
  const [logLoading, setLogLoading] = useState(false);

  // Auto-scroll chat
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isThinking]);

  // Fetch telemetry snapshot
  const fetchTelemetry = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/telemetry/overview`);
      if (res.ok) {
        const data = await res.json();
        setTelemetry(data);
      }
    } catch (e) {
      console.warn("Backend telemetry error:", e);
    }
  };

  // Fetch real incidents
  const fetchIncidents = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/triage/incidents`);
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
      }
    } catch (e) {
      console.warn("Could not fetch incidents:", e);
    }
  };

  // Fetch Copilot chat history
  const fetchCopilotHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/copilot/history`);
      if (res.ok) {
        const data = await res.json();
        if (data && data.length > 0) {
          setMessages(data);
        }
      }
    } catch (e) {
      console.warn("Could not fetch copilot history:", e);
    }
  };

  // Fetch available chaos scenarios
  const fetchScenarios = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/chaos/scenarios`);
      if (res.ok) {
        const data = await res.json();
        setScenarios(data);
      }
    } catch (e) {
      console.warn("Could not fetch scenarios:", e);
    }
  };

  const fetchServices = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/services`);
      if (res.ok) setServiceInventory(await res.json());
    } catch (e) {
      console.warn("Could not fetch service inventory:", e);
    }
  };

  const fetchRunbooks = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/runbooks`);
      if (res.ok) {
        const data = await res.json();
        setRunbooks(data.runbooks || []);
      }
    } catch (e) {
      console.warn("Could not fetch runbooks:", e);
    }
  };

  const handleSearchRunbooks = async (q) => {
    const query = q !== undefined ? q : runbookQuery;
    if (!query.trim()) {
      setRunbookResults(null);
      return;
    }
    setIsSearchingRunbooks(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/runbooks/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, k: 4, vector_weight: 0.6 })
      });
      if (res.ok) {
        const data = await res.json();
        setRunbookResults(data.results || []);
      }
    } catch (e) {
      console.warn("Runbook search error:", e);
    } finally {
      setIsSearchingRunbooks(false);
    }
  };

  const fetchTrafficStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/traffic/status`);
      if (res.ok) {
        const data = await res.json();
        setTrafficActive(data.active);
        setTrafficBatches(data.stats?.total_batches || 0);
      }
    } catch (e) {
      console.warn("Traffic status probe error:", e);
    }
  };

  const toggleTraffic = async () => {
    try {
      const endpoint = trafficActive ? "stop" : "start";
      const res = await fetch(`${API_BASE}/api/v1/traffic/${endpoint}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const nowActive = data.status === "started" || data.status === "already_running";
        setTrafficActive(nowActive);
        setActionFeedback(nowActive ? "🚀 Continuous synthetic traffic started (Loki & Prom streaming)." : "🛑 Synthetic traffic stopped.");
        setTimeout(() => setActionFeedback(""), 4000);
      }
    } catch (e) {
      console.warn("Toggle traffic error:", e);
    }
  };

  const fetchLogTail = async (source = logSource) => {
    setLogLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/logs/tail?source=${source}&lines=75`);
      if (res.ok) {
        const data = await res.json();
        setLogLines(data.lines || []);
      }
    } catch (e) {
      console.warn("Could not fetch log tail:", e);
    } finally {
      setLogLoading(false);
    }
  };

  useEffect(() => {
    fetchTelemetry();
    fetchIncidents();
    fetchCopilotHistory();
    fetchScenarios();
    fetchServices();
    fetchRunbooks();
    fetchTrafficStatus();
    const interval = setInterval(() => {
      fetchTelemetry();
      fetchIncidents();
      fetchServices();
      fetchTrafficStatus();
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (activeView === 'logs') {
      fetchLogTail(logSource);
      const logInt = setInterval(() => fetchLogTail(logSource), 3000);
      return () => clearInterval(logInt);
    }
  }, [activeView, logSource]);

  // Send query to Copilot
  const handleSendMessage = async (customQuery) => {
    const queryToSend = customQuery || inputMessage;
    if (!queryToSend.trim()) return;

    // Optimistically append user message
    const tempUserMsg = {
      id: `user-${Date.now()}`,
      role: "user",
      content: queryToSend,
      timestamp: Date.now() / 1000
    };
    setMessages(prev => [...prev, tempUserMsg]);
    setInputMessage("");
    setIsThinking(true);

    try {
      const res = await fetch(`${API_BASE}/api/v1/copilot/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: queryToSend, session_id: "default" })
      });
      if (res.ok) {
        const botMsg = await res.json();
        setMessages(prev => [...prev, botMsg]);
      } else {
        const err = await res.text();
        setMessages(prev => [...prev, {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: `⚠️ **Inference Error:** Failed to generate response (${res.status}): ${err}`,
          timestamp: Date.now() / 1000
        }]);
      }
    } catch (e) {
      setMessages(prev => [...prev, {
        id: `err-${Date.now()}`,
        role: "assistant",
        content: `⚠️ **Connection Error:** Could not contact AIST backend: ${e.message}`,
        timestamp: Date.now() / 1000
      }]);
    } finally {
      setIsThinking(false);
      fetchIncidents();
      fetchTelemetry();
    }
  };

  // Clear Chat History
  const handleClearHistory = async () => {
    try {
      await fetch(`${API_BASE}/api/v1/copilot/history`, { method: "DELETE" });
      fetchCopilotHistory();
    } catch (e) {
      console.warn("Error clearing history:", e);
    }
  };

  // Execute 1-Click Remediation / Self-Healing Action
  const handleExecuteCopilotAction = async (action) => {
    if (!action) return;
    const confirmed = window.confirm(`Approve '${action.title}' on ${action.target_server}? This changes the target system.`);
    if (!confirmed) return;
    setActionFeedback(`Executing approved action '${action.title}' on ${action.target_server}...`);
    try {
      const res = await fetch(`${API_BASE}/api/v1/copilot/execute_action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action_id: action.id,
          approved: true,
          session_id: "default"
        })
      });
      if (res.ok) {
        const data = await res.json();
        setActionFeedback(`Action Executed Successfully on ${data.server}`);
        fetchCopilotHistory();
        fetchIncidents();
        setTimeout(fetchTelemetry, 1500);
      }
    } catch (e) {
      setActionFeedback(`Action Execution Failed: ${e.message}`);
    }
  };

  // Resolve single incident and normalize system
  const handleResolveIncident = async (incidentId) => {
    setActionFeedback(`Resolving incident ${incidentId}...`);
    try {
      const res = await fetch(`${API_BASE}/api/v1/triage/incident/${incidentId}/resolve`, { method: "POST" });
      if (res.ok) {
        setActionFeedback(`Incident ${incidentId} resolved. System normalized.`);
        fetchIncidents();
        setTimeout(fetchTelemetry, 1000);
      }
    } catch (e) {
      setActionFeedback(`Error resolving incident: ${e.message}`);
    }
  };

  // Normalize all firing incidents back to operational state
  const handleNormalizeAllIncidents = async () => {
    if (!window.confirm("Normalize all firing alerts and return all systems to operational status?")) return;
    setActionFeedback("Normalizing all fleet alerts...");
    try {
      const res = await fetch(`${API_BASE}/api/v1/triage/incidents/normalize_all`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setActionFeedback(`All systems normalized (${data.normalized_count || 0} alerts cleared).`);
        fetchIncidents();
        setTimeout(fetchTelemetry, 1000);
      }
    } catch (e) {
      setActionFeedback(`Error normalizing alerts: ${e.message}`);
    }
  };

  // Switch to Copilot chat and launch active investigation
  const handleInvestigateIncident = (inc) => {
    setActiveView('copilot');
    handleSendMessage(`Investigate incident ${inc.incident_id}: ${inc.summary || inc.alertname} on ${inc.target_os}. Use approved FastMCP tools to diagnose root cause and recommend remediation.`);
  };

  // Trigger Targeted Chaos Failure
  const handleTriggerChaos = async (scenarioId, targetServer, autoNavigateToCopilot = false) => {
    setActionFeedback(`Injecting '${scenarioId}' on ${targetServer}...`);
    try {
      const res = await fetch(`${API_BASE}/api/v1/chaos/trigger`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario: scenarioId,
          target_server: targetServer
        })
      });
      if (res.ok) {
        const data = await res.json();
        setActionFeedback(`Active: ${data.summary || 'Failure Injected'}`);
        setTimeout(fetchIncidents, 1000);
        if (autoNavigateToCopilot) {
          setActiveView('copilot');
          handleSendMessage(`Investigate the newly injected failure '${scenarioId}' on ${targetServer}. Check event logs and system metrics.`);
        }
      }
    } catch (e) {
      setActionFeedback(`Chaos Injection Error: ${e.message}`);
    }
  };

  // Service Lifecycle Control (Start/Stop/Restart)
  const handleServiceControl = async (server, service, action) => {
    const reason = window.prompt(`Reason for ${action} on ${service}:`);
    if (!reason || reason.trim().length < 3) return;
    if (!window.confirm(`Confirm ${action} for ${service} on ${server}? The action will be audited.`)) return;
    setActionFeedback(`${action.toUpperCase()}ing ${service} on ${server}...`);
    try {
      const res = await fetch(`${API_BASE}/api/v1/services/operations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ service_id: service, action, reason, requested_by: "web-operator" })
      });
      if (res.ok) {
        setActionFeedback(`Completed: ${service} ${action}ed on ${server}; operation recorded.`);
        fetchServices();
        setTimeout(fetchTelemetry, 1200);
      } else {
        const detail = await res.text();
        setActionFeedback(`Service operation rejected: ${detail}`);
      }
    } catch (e) {
      setActionFeedback(`Service Control Error: ${e.message}`);
    }
  };

  // Suggested quick prompts for the user
  const quickPrompts = [
    "Is there any problem on Windows servers? List all critical issues from Event Viewer from server",
    "Check IIS application pools and AuthGateway status on Windows Server 2025",
    "List critical Event Viewer issues on Win2019 (last 24 hours)",
    "Inspect CPU usage, load average, and top processes on RHEL 10 and RHEL 9",
    "Are there any active Prometheus alerts firing right now?"
  ];

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      
      {/* Top Header & View Navigator */}
      <header className="h-14 border-b border-slate-800 bg-slate-900/95 px-6 flex items-center justify-between shrink-0 shadow-sm z-10">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <ShieldAlert className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-wide flex items-center gap-2">
                AIST <span className="text-[10px] px-2 py-0.5 rounded bg-indigo-950 text-indigo-400 border border-indigo-800 font-mono">v3.0 Production</span>
              </h1>
            </div>
          </div>

          {/* Primary View Switcher Tabs */}
          <nav className="flex items-center gap-1 bg-slate-950/80 p-1 rounded-lg border border-slate-800">
            <button
              onClick={() => setActiveView('copilot')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-all ${
                activeView === 'copilot' 
                  ? 'bg-indigo-600 text-white shadow' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" /> AI SRE Copilot
            </button>

            <button
              onClick={() => setActiveView('incidents')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-all ${
                activeView === 'incidents' 
                  ? 'bg-amber-600 text-white shadow font-semibold' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <AlertTriangle className="w-3.5 h-3.5 text-amber-300" /> Incidents &amp; Alerts
              {incidents.filter(i => i.status !== 'RESOLVED' && i.alert_status === 'firing').length > 0 && (
                <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-rose-500 text-white">
                  {incidents.filter(i => i.status !== 'RESOLVED' && i.alert_status === 'firing').length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveView('chaos')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-all ${
                activeView === 'chaos' 
                  ? 'bg-rose-600 text-white shadow' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Flame className="w-3.5 h-3.5 text-amber-300" /> Chaos Studio
            </button>

            <button
              onClick={() => setActiveView('services')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-all ${
                activeView === 'services' 
                  ? 'bg-emerald-600 text-white shadow' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Zap className="w-3.5 h-3.5 text-emerald-300" /> Service Operations
            </button>

            <button
              onClick={() => setActiveView('observability')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-all ${
                activeView === 'observability' 
                  ? 'bg-cyan-600 text-white shadow' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Activity className="w-3.5 h-3.5 text-cyan-300" /> Observability (9 Dashboards)
            </button>

            <button
              onClick={() => setActiveView('runbooks')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-all ${
                activeView === 'runbooks' 
                  ? 'bg-amber-600 text-white shadow' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <BookOpen className="w-3.5 h-3.5 text-amber-300" /> Runbooks &amp; RAG
            </button>

            <button
              onClick={() => setActiveView('logs')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-all ${
                activeView === 'logs' 
                  ? 'bg-violet-600 text-white shadow' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <ScrollText className="w-3.5 h-3.5 text-violet-300" /> Rolling Logs
            </button>
          </nav>
        </div>

        {/* System Badges & Telemetry */}
        <div className="flex items-center gap-2.5 text-xs">
          {/* Traffic Generator Toggle */}
          <button
            onClick={toggleTraffic}
            title="Toggle Continuous Synthetic Multi-OS Load Generator"
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border text-xs font-mono transition ${
              trafficActive
                ? 'bg-cyan-950/90 border-cyan-500 text-cyan-300 shadow-[0_0_12px_rgba(6,182,212,0.3)]'
                : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:text-slate-200'
            }`}
          >
            {trafficActive ? (
              <>
                <Radio className="w-3 h-3 text-cyan-400 animate-pulse" />
                <span>TRAFFIC: LIVE ({trafficBatches})</span>
              </>
            ) : (
              <>
                <PlayCircle className="w-3 h-3 text-slate-400" />
                <span>TRAFFIC: IDLE</span>
              </>
            )}
          </button>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800/80 border border-slate-700">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span className="text-slate-400">AI Brain:</span>
            <span className="font-mono text-slate-200">ornith-1.5:35b (RTX 5090)</span>
          </div>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800/80 border border-slate-700">
            <Activity className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-slate-400">FastMCP:</span>
            <span className="font-mono text-emerald-400 font-semibold">4.1.6 Active</span>
          </div>

          {incidents.length > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-rose-950/80 border border-rose-700 text-rose-300 animate-pulse">
              <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
              <span className="font-bold">{incidents.length} Firing</span>
            </div>
          )}
        </div>
      </header>

      {/* Global Feedback Toast */}
      {actionFeedback && (
        <div className="px-6 py-2 bg-indigo-950/90 border-b border-indigo-800 text-xs font-mono text-indigo-200 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Sparkles className="w-3.5 h-3.5 text-indigo-400 animate-spin" />
            {actionFeedback}
          </span>
          <button onClick={() => setActionFeedback("")} className="text-slate-400 hover:text-white">✕</button>
        </div>
      )}

      {/* ========================================================================
          VIEW 1: AI SRE COPILOT CHAT (CONVERSATIONAL NLP & AUTONOMOUS TRIAGE)
      ======================================================================== */}
      {activeView === 'copilot' && (
        <div className="flex-1 flex flex-col bg-slate-950 overflow-hidden">
            
            {/* Chat Header */}
            <div className="h-12 border-b border-slate-800 bg-slate-900/40 px-6 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-indigo-400" />
                <h3 className="text-xs font-semibold text-slate-200">
                  Autonomous SRE Copilot &amp; FastMCP Investigation Stream
                </h3>
              </div>
              <button 
                onClick={handleClearHistory}
                className="text-slate-400 hover:text-rose-400 p-1 text-xs flex items-center gap-1"
                title="Clear Chat History"
              >
                <Trash2 className="w-3.5 h-3.5" /> Clear History
              </button>
            </div>

            {/* Message Thread */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {messages.map((msg, idx) => (
                <div key={msg.id || idx} className="space-y-3">
                  
                  {/* User Message */}
                  {msg.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="max-w-2xl bg-indigo-600/90 text-white p-3.5 rounded-2xl rounded-tr-sm shadow text-xs leading-relaxed">
                        <p className="font-sans whitespace-pre-wrap">{msg.content}</p>
                      </div>
                    </div>
                  ) : (
                    /* Assistant Message */
                    <div className="flex justify-start">
                      <div className="max-w-3xl w-full bg-slate-900 border border-slate-800 p-5 rounded-2xl rounded-tl-sm shadow space-y-4 text-xs">
                        
                        {/* Agent Reasoning Stream Accordion */}
                        {msg.thought && (
                          <div className="rounded-lg border border-slate-800 bg-slate-950/60 overflow-hidden">
                            <button
                              onClick={() => setExpandedThoughts(prev => ({ ...prev, [idx]: !prev[idx] }))}
                              className="w-full px-3.5 py-2 bg-slate-850 flex items-center justify-between text-xs text-indigo-300 font-mono"
                            >
                              <span className="flex items-center gap-2">
                                <Terminal className="w-3.5 h-3.5 text-indigo-400" />
                                Agent Deep Reasoning Stream (ornith-1.5:35b on RTX 5090)
                              </span>
                              {expandedThoughts[idx] ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                            </button>
                            {expandedThoughts[idx] && (
                              <div className="p-3 text-[11px] font-mono text-slate-400 whitespace-pre-wrap leading-relaxed max-h-56 overflow-y-auto bg-slate-950">
                                {msg.thought}
                              </div>
                            )}
                          </div>
                        )}

                        {/* Executed FastMCP Tools Accordion */}
                        {msg.tools && msg.tools.length > 0 && (
                          <div className="rounded-lg border border-slate-800 bg-slate-950/60 overflow-hidden">
                            <button
                              onClick={() => setExpandedTools(prev => ({ ...prev, [idx]: !prev[idx] }))}
                              className="w-full px-3.5 py-2 bg-slate-850 flex items-center justify-between text-xs text-emerald-300 font-mono"
                            >
                              <span className="flex items-center gap-2">
                                <Activity className="w-3.5 h-3.5 text-emerald-400" />
                                FastMCP Autonomously Executed Tools ({msg.tools.length})
                              </span>
                              {expandedTools[idx] ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                            </button>
                            {expandedTools[idx] && (
                              <div className="p-3 space-y-2 bg-slate-950">
                                {msg.tools.map((t, tidx) => (
                                  <div key={tidx} className="p-2 rounded bg-slate-900 border border-slate-800 font-mono text-[11px]">
                                    <div className="flex items-center justify-between text-emerald-400 font-semibold mb-1">
                                      <span>&gt; {t.tool}</span>
                                      <span className="text-slate-400 text-[10px]">{t.target}</span>
                                    </div>
                                    <span className="text-slate-300">{t.summary}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}

                        {/* Main Markdown Content */}
                        <div className="text-slate-200 leading-relaxed space-y-3 font-sans whitespace-pre-wrap">
                          {msg.content}
                        </div>

                        {/* 1-Click Self-Healing & Human-in-the-Loop Action Card */}
                        {msg.action && (
                          <div className="p-4 rounded-xl border border-amber-600/60 bg-amber-950/30 shadow-md space-y-3 mt-4">
                            <div className="flex items-start justify-between">
                              <div className="flex items-center gap-2">
                                <Lock className="w-4 h-4 text-amber-400" />
                                <h4 className="text-xs font-bold text-amber-300 uppercase tracking-wider">
                                  {msg.action.title || "Proposed Remediation Action"}
                                </h4>
                              </div>
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-900/60 text-amber-300 border border-amber-700">
                                {msg.action.auto_heal_eligible ? "⚡ Self-Healing Ready" : "Requires HITL Approval"}
                              </span>
                            </div>

                            <p className="text-[11px] font-mono bg-slate-950 p-2.5 rounded border border-slate-800 text-slate-200 select-all">
                              Runbook: {msg.action.runbook_id || "not assigned"}. The server resolves this approved action from its remediation catalog.
                              {msg.action.command}
                            </p>

                            <div className="flex items-center gap-4 text-[11px] text-slate-400">
                              <span>Target Server: <strong className="text-emerald-400 font-mono">{msg.action.target_server}</strong></span>
                              <span>Blast Radius: <strong className="text-amber-400">{msg.action.blast_radius}</strong></span>
                            </div>

                            <div className="flex items-center gap-3 pt-1">
                              <button
                                onClick={() => handleExecuteCopilotAction(msg.action)}
                                className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow"
                              >
                                <Check className="w-3.5 h-3.5" /> Approve &amp; Execute via FastMCP
                              </button>
                            </div>
                          </div>
                        )}

                      </div>
                    </div>
                  )}

                </div>
              ))}

              {/* Thinking Indicator */}
              {isThinking && (
                <div className="flex justify-start">
                  <div className="bg-slate-900 border border-indigo-900/60 p-4 rounded-2xl rounded-tl-sm flex items-center gap-3 text-xs text-indigo-300">
                    <RefreshCw className="w-4 h-4 text-indigo-400 animate-spin" />
                    <span className="font-mono">
                      Querying FastMCP Tools &amp; Synthesizing with ornith-1.5:35b on RTX 5090...
                    </span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Quick Prompt Pills */}
            <div className="px-6 py-2 border-t border-slate-800 bg-slate-900/30 flex items-center gap-2 overflow-x-auto text-xs shrink-0">
              <span className="text-slate-400 shrink-0 text-[11px]">Suggestions:</span>
              {quickPrompts.map((qp, qidx) => (
                <button
                  key={qidx}
                  onClick={() => handleSendMessage(qp)}
                  className="px-2.5 py-1 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] border border-slate-700 whitespace-nowrap transition"
                >
                  {qp}
                </button>
              ))}
            </div>

            {/* Chat Input Bar */}
            <div className="p-4 border-t border-slate-800 bg-slate-900/70 shrink-0">
              <form onSubmit={(e) => { e.preventDefault(); handleSendMessage(); }} className="flex gap-2">
                <input
                  type="text"
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  placeholder="Ask SRE Copilot in plain English (e.g. 'Is there any problem on Windows servers? List all critical issues from Event Viewer from server')..."
                  className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-sans"
                  disabled={isThinking}
                />
                <button
                  type="submit"
                  disabled={isThinking || !inputMessage.trim()}
                  className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold flex items-center gap-1.5 shadow"
                >
                  {isThinking ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  Ask Copilot
                </button>
              </form>
            </div>

          </div>
        )}

      {/* ========================================================================
          VIEW: ENTERPRISE INCIDENTS & ALERT COMMAND CENTER
      ======================================================================== */}
      {activeView === 'incidents' && (
        <div className="flex-1 flex flex-col bg-slate-950 p-8 space-y-6 overflow-y-auto">
          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-800">
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <AlertTriangle className="w-6 h-6 text-amber-400" /> Enterprise Incident &amp; Alert Command Center
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Active multi-OS Prometheus &amp; AlertManager alerts, triage states, and automated remediation lifecycle.
              </p>
            </div>

            <div className="flex items-center gap-2.5">
              <button
                onClick={handleNormalizeAllIncidents}
                className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow transition"
                title="Resolve and normalize all firing alerts"
              >
                <CheckCircle2 className="w-3.5 h-3.5" /> Normalize All Alerts
              </button>
              <a 
                href="http://192.168.1.131:9093" 
                target="_blank" 
                rel="noreferrer"
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium flex items-center gap-1.5 transition"
              >
                <ExternalLink className="w-3.5 h-3.5" /> AlertManager (192.168.1.131:9093)
              </a>
              <button 
                onClick={fetchIncidents} 
                className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 text-xs transition" 
                title="Refresh Incidents"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Metric KPI Gauges */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 flex items-center justify-between">
              <div>
                <div className="text-[11px] font-mono uppercase text-slate-400">Active Firing Alerts</div>
                <div className={`text-2xl font-bold mt-1 font-mono ${
                  incidents.filter(i => i.status !== 'RESOLVED' && i.alert_status === 'firing').length > 0 ? 'text-rose-400' : 'text-emerald-400'
                }`}>
                  {incidents.filter(i => i.status !== 'RESOLVED' && i.alert_status === 'firing').length}
                </div>
              </div>
              <AlertCircle className={`w-8 h-8 ${
                incidents.filter(i => i.status !== 'RESOLVED' && i.alert_status === 'firing').length > 0 ? 'text-rose-500/40' : 'text-emerald-500/40'
              }`} />
            </div>

            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 flex items-center justify-between">
              <div>
                <div className="text-[11px] font-mono uppercase text-slate-400">Awaiting Human Approval</div>
                <div className="text-2xl font-bold mt-1 font-mono text-amber-400">
                  {incidents.filter(i => i.status === 'AWAITING_HUMAN_APPROVAL').length}
                </div>
              </div>
              <Lock className="w-8 h-8 text-amber-500/40" />
            </div>

            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 flex items-center justify-between">
              <div>
                <div className="text-[11px] font-mono uppercase text-slate-400">Resolved Today</div>
                <div className="text-2xl font-bold mt-1 font-mono text-emerald-400">
                  {incidents.filter(i => i.status === 'RESOLVED').length}
                </div>
              </div>
              <CheckCircle2 className="w-8 h-8 text-emerald-500/40" />
            </div>

            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 flex items-center justify-between">
              <div>
                <div className="text-[11px] font-mono uppercase text-slate-400">Autonomous MTTR</div>
                <div className="text-2xl font-bold mt-1 font-mono text-indigo-400">42.5s</div>
              </div>
              <Clock className="w-8 h-8 text-indigo-500/40" />
            </div>
          </div>

          {/* Filter Bar */}
          <div className="flex items-center gap-2">
            {[
              { id: 'all', label: `All Incidents (${incidents.length})` },
              { id: 'firing', label: `Active / Firing (${incidents.filter(i => i.status !== 'RESOLVED' && i.alert_status === 'firing').length})` },
              { id: 'approval', label: `Awaiting Approval (${incidents.filter(i => i.status === 'AWAITING_HUMAN_APPROVAL').length})` },
              { id: 'resolved', label: `Resolved (${incidents.filter(i => i.status === 'RESOLVED').length})` }
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setIncidentFilter(tab.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono transition ${
                  incidentFilter === tab.id
                    ? 'bg-amber-600 text-white shadow font-semibold'
                    : 'bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Incidents List Grid */}
          <div className="space-y-3">
            {(() => {
              const filtered = incidents.filter(inc => {
                if (incidentFilter === 'firing') return inc.status !== 'RESOLVED' && inc.alert_status === 'firing';
                if (incidentFilter === 'approval') return inc.status === 'AWAITING_HUMAN_APPROVAL';
                if (incidentFilter === 'resolved') return inc.status === 'RESOLVED';
                return true;
              });

              if (filtered.length === 0) {
                return (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-12 text-center space-y-3">
                    <CheckCircle2 className="w-10 h-10 text-emerald-500/80 mx-auto" />
                    <h3 className="text-base font-semibold text-white">All Systems Operational</h3>
                    <p className="text-xs text-slate-400 max-w-md mx-auto">
                      No incidents matching this filter. You can trigger simulated failures in Chaos Studio or investigate systems in AI SRE Copilot.
                    </p>
                  </div>
                );
              }

              return filtered.map((inc) => {
                const isResolved = inc.status === 'RESOLVED';
                const isAwaiting = inc.status === 'AWAITING_HUMAN_APPROVAL';
                const remediation = inc.interrupt || inc.state?.proposed_remediation;

                return (
                  <div
                    key={inc.incident_id}
                    className={`p-5 rounded-xl border transition space-y-4 ${
                      isResolved
                        ? 'border-emerald-900/60 bg-emerald-950/10'
                        : isAwaiting
                        ? 'border-amber-500/80 bg-amber-950/20 shadow-lg'
                        : 'border-rose-900/80 bg-slate-900/70'
                    }`}
                  >
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-2">
                      <div className="flex items-center gap-3">
                        <span className="text-xs font-mono font-bold text-indigo-400 px-2 py-0.5 rounded bg-slate-800">
                          {inc.incident_id}
                        </span>
                        <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded border ${
                          inc.severity === 'critical'
                            ? 'bg-rose-950 text-rose-300 border-rose-800'
                            : 'bg-amber-950 text-amber-300 border-amber-800'
                        }`}>
                          {inc.severity || 'warning'}
                        </span>
                        <span className={`text-[10px] font-mono px-2 py-0.5 rounded uppercase font-semibold ${
                          isResolved
                            ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                            : isAwaiting
                            ? 'bg-amber-950 text-amber-200 border border-amber-700 animate-pulse'
                            : 'bg-rose-950 text-rose-300 border border-rose-800 animate-pulse'
                        }`}>
                          {isResolved ? 'RESOLVED / NORMAL' : isAwaiting ? 'AWAITING APPROVAL' : 'FIRING'}
                        </span>
                        <span className="text-[10px] font-mono text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
                          Host: {inc.target_os || 'Multi-OS'}
                        </span>
                      </div>

                      <div className="text-[11px] text-slate-500 font-mono">
                        {inc.created_at ? new Date(inc.created_at * 1000).toLocaleTimeString() : 'Recent'}
                      </div>
                    </div>

                    <div>
                      <h3 className="text-sm font-bold text-white">{inc.summary || inc.alertname}</h3>
                      {inc.description && (
                        <p className="text-xs text-slate-300 mt-1">{inc.description}</p>
                      )}
                      {inc.resolution_note && (
                        <div className="text-xs text-emerald-400 font-mono mt-1.5 flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> {inc.resolution_note}
                        </div>
                      )}
                    </div>

                    {/* Proposed remediation box */}
                    {remediation && !isResolved && (
                      <div className="p-3.5 rounded-lg border border-amber-500/40 bg-amber-950/30 space-y-2">
                        <div className="flex items-center justify-between text-xs text-amber-300 font-semibold">
                          <span>⚡ Proposed Remediation: {remediation.title || remediation.action || 'Remediation Action'}</span>
                          <span className="text-[10px] font-mono text-amber-400">Blast Radius: {remediation.blast_radius || 'Low'}</span>
                        </div>
                        {remediation.command && (
                          <code className="block text-[11px] font-mono bg-black/60 p-2 rounded text-slate-200">
                            {remediation.command}
                          </code>
                        )}
                        <div className="pt-1">
                          <button
                            onClick={() => handleExecuteCopilotAction({
                              id: remediation.action_id || remediation.id,
                              title: remediation.title || remediation.action,
                              target_server: remediation.target || inc.target_os,
                              command: remediation.command,
                              runbook_id: remediation.runbook_id || "RB-01"
                            })}
                            className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow transition"
                          >
                            <Check className="w-3.5 h-3.5" /> Approve &amp; Execute via FastMCP
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Actions row */}
                    <div className="flex items-center gap-3 pt-2 border-t border-slate-800">
                      <button
                        onClick={() => handleInvestigateIncident(inc)}
                        className="px-3.5 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center gap-1.5 transition shadow"
                      >
                        <Search className="w-3.5 h-3.5" /> Investigate in Copilot
                      </button>

                      {!isResolved && (
                        <button
                          onClick={() => handleResolveIncident(inc.incident_id)}
                          className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-emerald-950 text-slate-300 hover:text-emerald-300 border border-slate-700 hover:border-emerald-600 text-xs font-semibold flex items-center gap-1.5 transition"
                        >
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Resolve &amp; Return to Normal
                        </button>
                      )}
                    </div>
                  </div>
                );
              });
            })()}
          </div>
        </div>
      )}

      {/* ========================================================================
          VIEW 3: DEDICATED CHAOS ENGINEERING STUDIO (FULL PAGE WORKSPACE)
      ======================================================================== */}
      {activeView === 'chaos' && (
        <div className="flex-1 flex flex-col overflow-y-auto bg-slate-950 p-8 space-y-8">
          
          {/* Header Banner */}
          <div className="flex items-center justify-between border-b border-slate-800 pb-5">
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2.5">
                <Flame className="w-6 h-6 text-rose-500" /> Chaos Engineering Studio &amp; Multi-OS Failure Simulator
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Inject targeted individual failures or complex multi-stage cascading outages across Windows and Linux fleets.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setActiveView('copilot')}
                className="px-4 py-2 rounded-lg bg-indigo-600/80 hover:bg-indigo-600 text-white text-xs font-semibold flex items-center gap-2 shadow"
              >
                <MessageSquare className="w-4 h-4" /> Open in SRE Copilot Chat
              </button>
              <button
                onClick={() => handleTriggerChaos('recover', 'ALL')}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-2 shadow"
              >
                <CheckCircle2 className="w-4 h-4" /> Recover All Failure Scenarios
              </button>
            </div>
          </div>

          {/* SECTION 1: MULTI-STAGE & CASCADING FAILURE SCENARIOS */}
          <div className="space-y-4">
            <span className="text-xs font-bold uppercase tracking-wider text-rose-400 flex items-center gap-2">
              <Layers className="w-4 h-4" /> 1. Multi-Stage &amp; Cascading Chaos Workflows
            </span>
            
            <div className="p-6 rounded-xl border border-rose-900/60 bg-rose-950/20 space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-sm font-bold text-rose-300 flex items-center gap-2">
                    ⚡ Multi-Tier Outage Cascade (P0 Disaster Scenario)
                  </h3>
                  <p className="text-xs text-slate-400 mt-1 max-w-2xl leading-relaxed">
                    Orchestrates a realistic enterprise multi-system failure across both OS tiers to evaluate cross-platform correlation:
                  </p>
                </div>
                <button
                  onClick={() => handleTriggerChaos('multistage_cascade', 'MULTI-OS', true)}
                  className="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold shadow flex items-center gap-2"
                >
                  <Flame className="w-4 h-4" /> Launch Multi-Stage Cascade &amp; Triage
                </button>
              </div>

              {/* Cascade Workflow Steps */}
              <div className="grid grid-cols-3 gap-4 pt-2">
                <div className="p-3.5 rounded-lg border border-slate-800 bg-slate-900/80 space-y-1">
                  <span className="text-[10px] font-mono text-amber-400 font-bold uppercase block">Stage 1: Linux Tier</span>
                  <h4 className="text-xs font-semibold text-slate-200">RHEL 10 CPU Saturation Spike</h4>
                  <p className="text-[11px] text-slate-400">Rogue stress processes exhaust run queue on TicketFlow API node.</p>
                </div>
                <div className="p-3.5 rounded-lg border border-slate-800 bg-slate-900/80 space-y-1">
                  <span className="text-[10px] font-mono text-rose-400 font-bold uppercase block">Stage 2: Windows Tier</span>
                  <h4 className="text-xs font-semibold text-slate-200">Win2025 AuthGateway Crash</h4>
                  <p className="text-[11px] text-slate-400">Worker process w3wp.exe crashes, producing HTTP 503 errors.</p>
                </div>
                <div className="p-3.5 rounded-lg border border-slate-800 bg-slate-900/80 space-y-1">
                  <span className="text-[10px] font-mono text-purple-400 font-bold uppercase block">Stage 3: Database Tier</span>
                  <h4 className="text-xs font-semibold text-slate-200">Win2019 SQL Table Lock Deadlock</h4>
                  <p className="text-[11px] text-slate-400">Exclusive TABLOCKX contention blocks transactional query SPIDs.</p>
                </div>
              </div>
            </div>
          </div>

          {/* SECTION 2: TARGET SERVER SELECTION & FAILURE MATRIX */}
          <div className="space-y-4">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <Server className="w-4 h-4 text-indigo-400" /> 2. Targeted Multi-OS Failure Matrix (Select Desired Host)
            </span>

            <div className="grid grid-cols-2 gap-6">
              
              {/* Card 1: IIS AppPool / Auth Service Crash */}
              <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-rose-400 flex items-center gap-1.5">
                    💥 IIS AppPool / Auth Service Crash
                  </h4>
                  <span className="text-[10px] font-mono bg-slate-800 text-slate-300 px-2 py-0.5 rounded">
                    Windows Tier
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  Terminates the worker process and causes HTTP 503 Service Unavailable errors. Select target Windows host:
                </p>
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <button
                    onClick={() => handleTriggerChaos('iis_crash', 'WIN2025', true)}
                    className="p-2.5 rounded-lg bg-rose-950/60 hover:bg-rose-900 border border-rose-800 text-rose-200 text-xs font-medium text-left transition"
                  >
                    <span className="block font-bold">Crash Win2025 (.132)</span>
                    <span className="text-[10px] text-rose-300/80">AuthGateway :5001</span>
                  </button>
                  <button
                    onClick={() => handleTriggerChaos('iis_crash', 'WIN2019', true)}
                    className="p-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium text-left transition"
                  >
                    <span className="block font-bold">Crash Win2019 (.133)</span>
                    <span className="text-[10px] text-slate-400">Legacy WCF :8088</span>
                  </button>
                </div>
              </div>

              {/* Card 2: SQL Server Exclusive Lock Deadlock */}
              <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-purple-400 flex items-center gap-1.5">
                    🔒 SQL Server Exclusive Lock Deadlock
                  </h4>
                  <span className="text-[10px] font-mono bg-slate-800 text-slate-300 px-2 py-0.5 rounded">
                    Windows Tier
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  Simulates SPID holding exclusive table lock (TABLOCKX), blocking query threads in TicketFlowDB:
                </p>
                <div className="pt-2">
                  <button
                    onClick={() => handleTriggerChaos('sql_deadlock', 'WIN2019', true)}
                    className="w-full p-2.5 rounded-lg bg-purple-950/60 hover:bg-purple-900 border border-purple-800 text-purple-200 text-xs font-medium text-left transition"
                  >
                    <span className="block font-bold">Inject SQL Deadlock on Win2019 (.133)</span>
                    <span className="text-[10px] text-purple-300/80">TicketFlowDB Lock Contention</span>
                  </button>
                </div>
              </div>

              {/* Card 3: CPU Saturation Spike */}
              <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-amber-400 flex items-center gap-1.5">
                    🔥 CPU Saturation Spike (&gt;95%)
                  </h4>
                  <span className="text-[10px] font-mono bg-slate-800 text-slate-300 px-2 py-0.5 rounded">
                    Linux Tier
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  Injects synthetic background load to trigger run queue alert and latency degradation:
                </p>
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <button
                    onClick={() => handleTriggerChaos('cpu_spike', 'RHEL10', true)}
                    className="p-2.5 rounded-lg bg-amber-950/60 hover:bg-amber-900 border border-amber-800 text-amber-200 text-xs font-medium text-left transition"
                  >
                    <span className="block font-bold">Stress RHEL 10 (.130)</span>
                    <span className="text-[10px] text-amber-300/80">TicketFlow App Node</span>
                  </button>
                  <button
                    onClick={() => handleTriggerChaos('cpu_spike', 'RHEL9', true)}
                    className="p-2.5 rounded-lg bg-amber-950/60 hover:bg-amber-900 border border-amber-800 text-amber-200 text-xs font-medium text-left transition"
                  >
                    <span className="block font-bold">Stress RHEL 9 (.131)</span>
                    <span className="text-[10px] text-amber-300/80">Observability Hub</span>
                  </button>
                </div>
              </div>

              {/* Card 4: Queue Backlog & Core API Outage */}
              <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-cyan-400 flex items-center gap-1.5">
                    📦 Message Queue &amp; API Outage
                  </h4>
                  <span className="text-[10px] font-mono bg-slate-800 text-slate-300 px-2 py-0.5 rounded">
                    Linux Tier
                  </span>
                </div>
                <p className="text-xs text-slate-400">
                  Spikes ready queue depth or triggers connection pool HTTP 500 error storms:
                </p>
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <button
                    onClick={() => handleTriggerChaos('queue_backlog', 'RHEL10', true)}
                    className="p-2.5 rounded-lg bg-cyan-950/60 hover:bg-cyan-900 border border-cyan-800 text-cyan-200 text-xs font-medium text-left transition"
                  >
                    <span className="block font-bold">Queue Backlog Spike</span>
                    <span className="text-[10px] text-cyan-300/80">RHEL 10 (:8080) &gt;650 msgs</span>
                  </button>
                  <button
                    onClick={() => handleTriggerChaos('ticket_500', 'RHEL10', true)}
                    className="p-2.5 rounded-lg bg-rose-950/60 hover:bg-rose-900 border border-rose-800 text-rose-200 text-xs font-medium text-left transition"
                  >
                    <span className="block font-bold">HTTP 500 API Spike</span>
                    <span className="text-[10px] text-rose-300/80">TicketFlow Core API</span>
                  </button>
                </div>
              </div>

            </div>
          </div>

        </div>
      )}

      {/* ========================================================================
          VIEW 3: SERVICE OPERATIONS (START / STOP / RESTART CONTROLS)
      ======================================================================== */}
      {activeView === 'services' && (
        <div className="flex-1 flex flex-col overflow-y-auto bg-slate-950 p-8 space-y-6">
          <div className="border-b border-slate-800 pb-5">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Zap className="w-6 h-6 text-emerald-400" /> Multi-OS Service Operations &amp; Lifecycle Management
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Direct daemon and process management across RHEL 10, RHEL 9, Windows Server 2025, and Windows Server 2019.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-6">
            
            {/* Service 1: TicketFlow Flask Core API */}
            <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-semibold text-white">TicketFlow Core API (:5000)</h4>
                  <span className="text-xs text-slate-400 font-mono">Host: RHEL 10 Enterprise (192.168.1.130)</span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold">
                  RUNNING
                </span>
              </div>
              <p className="text-xs text-slate-400">Core RESTful API handling ticket lifecycle operations and Prometheus metrics.</p>
              <div className="grid grid-cols-3 gap-2 pt-2">
                <button
                  onClick={() => handleServiceControl('RHEL10', 'ticketflow-api', 'start')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <Play className="w-3.5 h-3.5" /> Start
                </button>
                <button
                  onClick={() => handleServiceControl('RHEL10', 'ticketflow-api', 'stop')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-rose-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <Square className="w-3.5 h-3.5" /> Stop
                </button>
                <button
                  onClick={() => handleServiceControl('RHEL10', 'ticketflow-api', 'restart')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-indigo-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <RotateCw className="w-3.5 h-3.5" /> Restart
                </button>
              </div>
            </div>

            {/* Service 2: Notification Service */}
            <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-semibold text-white">Notification Service (:8080)</h4>
                  <span className="text-xs text-slate-400 font-mono">Host: RHEL 10 Enterprise (192.168.1.130)</span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold">
                  RUNNING
                </span>
              </div>
              <p className="text-xs text-slate-400">RabbitMQ event consumer and dispatcher for ticket creation events.</p>
              <div className="grid grid-cols-3 gap-2 pt-2">
                <button
                  onClick={() => handleServiceControl('RHEL10', 'notification-service', 'start')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <Play className="w-3.5 h-3.5" /> Start
                </button>
                <button
                  onClick={() => handleServiceControl('RHEL10', 'notification-service', 'stop')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-rose-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <Square className="w-3.5 h-3.5" /> Stop
                </button>
                <button
                  onClick={() => handleServiceControl('RHEL10', 'notification-service', 'restart')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-indigo-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <RotateCw className="w-3.5 h-3.5" /> Restart
                </button>
              </div>
            </div>

            {/* Service 3: Auth Gateway (.NET / IIS) */}
            <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-semibold text-white">Auth Gateway Service (:5001)</h4>
                  <span className="text-xs text-slate-400 font-mono">Host: Windows Server 2025 (192.168.1.132)</span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold">
                  RUNNING
                </span>
              </div>
              <p className="text-xs text-slate-400">Native Windows Security &amp; JWT Token Gateway with WinRM management.</p>
              <div className="grid grid-cols-3 gap-2 pt-2">
                <button
                  onClick={() => handleServiceControl('WIN2025', 'auth-gateway', 'start')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <Play className="w-3.5 h-3.5" /> Start
                </button>
                <button
                  onClick={() => handleServiceControl('WIN2025', 'auth-gateway', 'stop')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-rose-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <Square className="w-3.5 h-3.5" /> Stop
                </button>
                <button
                  onClick={() => handleServiceControl('WIN2025', 'auth-gateway', 'restart')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-indigo-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <RotateCw className="w-3.5 h-3.5" /> Restart
                </button>
              </div>
            </div>

            {/* Service 4: Audit & DB Service */}
            <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-semibold text-white">Audit &amp; DB Service (:8088)</h4>
                  <span className="text-xs text-slate-400 font-mono">Host: Windows Server 2019 (192.168.1.133)</span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold">
                  RUNNING
                </span>
              </div>
              <p className="text-xs text-slate-400">TicketFlowDB persistence service and transaction audit log provider.</p>
              <div className="grid grid-cols-3 gap-2 pt-2">
                <button
                  onClick={() => handleServiceControl('WIN2019', 'audit-service', 'start')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <Play className="w-3.5 h-3.5" /> Start
                </button>
                <button
                  onClick={() => handleServiceControl('WIN2019', 'audit-service', 'stop')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-rose-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <Square className="w-3.5 h-3.5" /> Stop
                </button>
                <button
                  onClick={() => handleServiceControl('WIN2019', 'audit-service', 'restart')}
                  className="py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-indigo-300 border border-slate-700 rounded-lg flex items-center justify-center gap-1.5"
                >
                  <RotateCw className="w-3.5 h-3.5" /> Restart
                </button>
              </div>
            </div>

          </div>

          <div className="p-5 rounded-xl border border-indigo-800/70 bg-slate-900/70 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-indigo-300">Policy-Managed Service Inventory</h3>
                <p className="text-xs text-slate-400 mt-1">Every operation is audited. Services without a named supervisor remain observe-only until their production control contract is configured.</p>
              </div>
              <button onClick={fetchServices} className="text-xs text-indigo-300 hover:text-white flex items-center gap-1"><RefreshCw className="w-3.5 h-3.5" /> Refresh</button>
            </div>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              {serviceInventory.map((service) => (
                <div key={service.id} className="border border-slate-700 rounded-lg p-3 bg-slate-950/60">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold text-white">{service.name}</div>
                      <div className="text-[10px] text-slate-400 font-mono mt-1">{service.server} · {service.kind} · owner: {service.owner}</div>
                    </div>
                    <span className={`text-[10px] px-2 py-0.5 rounded border ${service.desired_state === 'STOPPED' ? 'text-rose-300 border-rose-800 bg-rose-950/40' : 'text-emerald-300 border-emerald-800 bg-emerald-950/40'}`}>{service.desired_state}</span>
                  </div>
                  <div className="mt-2 text-[10px] text-slate-400">Runbook: {service.runbook_id || 'not configured'} · Circuit: {service.circuit_state}</div>
                  {service.control_notice && <div className="mt-2 text-[10px] text-amber-300">{service.control_notice}</div>}
                  {service.supported_operations?.length > 0 && (
                    <div className="flex gap-2 mt-3">
                      {['start', 'stop', 'restart'].map((action) => (
                        <button key={action} onClick={() => handleServiceControl(service.server, service.id, action)} className="px-2 py-1 rounded text-[10px] border border-slate-700 hover:border-indigo-500 text-slate-300">{action}</button>
                      ))}
                      <button onClick={() => { setActiveView('copilot'); handleSendMessage(`Investigate ${service.name} on ${service.server}. Use the approved runbook ${service.runbook_id || 'if available'} and report evidence.`); }} className="px-2 py-1 rounded text-[10px] border border-indigo-800 hover:border-indigo-500 text-indigo-300">Investigate</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================
          VIEW 4: OBSERVABILITY & GRAFANA COMMAND CENTER (9 DASHBOARDS)
      ======================================================================== */}
      {activeView === 'observability' && (
        <div className="flex-1 flex flex-col overflow-y-auto bg-slate-950 p-8 space-y-6">
          <div className="border-b border-slate-800 pb-5 flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <Activity className="w-6 h-6 text-cyan-400" /> Observability Command Center (Grafana 11.4 &amp; Prometheus 3.0)
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                9 production SRE dashboards provisioned on RHEL 9 (192.168.1.131) with Prometheus, Loki, and Tempo.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <a 
                href="http://192.168.1.131:3000" 
                target="_blank" 
                rel="noreferrer"
                className="px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow"
              >
                <ExternalLink className="w-3.5 h-3.5" /> Open Grafana
              </a>
              <a 
                href="http://192.168.1.131:9090/targets" 
                target="_blank" 
                rel="noreferrer"
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium flex items-center gap-1.5"
              >
                Prometheus Targets
              </a>
            </div>
          </div>

          {/* Embedded Dashboard Preview Iframe */}
          {selectedDashboard && (
            <div className="rounded-xl border border-cyan-500/50 bg-slate-900/90 p-4 space-y-3 shadow-2xl">
              <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping"></span>
                  <span className="text-xs font-mono text-cyan-300 font-bold">EMBEDDED LIVE DASHBOARD VIEWER</span>
                  <span className="text-xs text-slate-400 font-mono">({selectedDashboard.title})</span>
                </div>
                <div className="flex items-center gap-2">
                  <a 
                    href={selectedDashboard.url} 
                    target="_blank" 
                    rel="noreferrer"
                    className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
                  >
                    Open in Tab <ExternalLink className="w-3 h-3" />
                  </a>
                  <button 
                    onClick={() => setSelectedDashboard(null)}
                    className="text-xs px-2 py-1 bg-slate-800 hover:bg-rose-900/80 text-slate-300 hover:text-rose-200 rounded border border-slate-700"
                  >
                    Close Preview
                  </button>
                </div>
              </div>
              <iframe 
                src={`${selectedDashboard.url}?kiosk=tv&theme=dark`} 
                title={selectedDashboard.title}
                className="w-full h-[540px] rounded-lg border border-slate-800 bg-slate-950"
              />
            </div>
          )}

          {/* 9 SRE Dashboards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            
            {[
              {
                id: "01",
                title: "01 - SLI / SLO & Error Budget Command Center",
                url: "http://192.168.1.131:3000/d/aist-01-sli-slo",
                badge: "SRE Reliability",
                badgeColor: "border-emerald-800 text-emerald-300 bg-emerald-950/40",
                desc: "3-nines availability (99.9%), 99.0% latency SLA (<500ms), 30-day error budget depletion curves & multi-window alerting."
              },
              {
                id: "02",
                title: "02 - Server Level & Infrastructure Health",
                url: "http://192.168.1.131:3000/d/aist-02-server-health",
                badge: "Fleet Infrastructure",
                badgeColor: "border-blue-800 text-blue-300 bg-blue-950/40",
                desc: "Real-time CPU, RAM, disk, network, and uptime telemetry for RHEL 10, RHEL 9, Win 2025, and Win 2019."
              },
              {
                id: "03",
                title: "03 - Business Application & Frontend Performance",
                url: "http://192.168.1.131:3000/d/aist-03-business-frontend",
                badge: "Business & Web",
                badgeColor: "border-cyan-800 text-cyan-300 bg-cyan-950/40",
                desc: "LoanProcessAI web portal availability, route invocations, user pass/fail auth rates, and loan pipeline."
              },
              {
                id: "04",
                title: "04 - GenAI RAG & Local LLM Telemetry (RTX 5090)",
                url: "http://192.168.1.131:3000/d/aist-04-genai-llm",
                badge: "AI Brain & LLM",
                badgeColor: "border-indigo-800 text-indigo-300 bg-indigo-950/40",
                desc: "Ollama RTX 5090 inference latency, token throughput, vector search time, and LLM-as-a-judge scores."
              },
              {
                id: "05",
                title: "05 - Multi-Agent Workflow Health & Orchestration",
                url: "http://192.168.1.131:3000/d/aist-05-multi-agent",
                badge: "Multi-Agent Fleet",
                badgeColor: "border-purple-800 text-purple-300 bg-purple-950/40",
                desc: "Intake, KYC, Financial, Decision, and Closing agent step executions, execution duration, and failure rates."
              },
              {
                id: "06",
                title: "06 - Incident Lifecycle & MTTR (Autonomous SRE)",
                url: "http://192.168.1.131:3000/d/aist-06-incident-lifecycle",
                badge: "MTTR & Lifecycle",
                badgeColor: "border-amber-800 text-amber-300 bg-amber-950/40",
                desc: "Mean Time to Detect (MTTD), Mean Time to Resolve (MTTR), active alert velocity & automated remediation."
              },
              {
                id: "07",
                title: "07 - Unified Live Logs Explorer (Loki 3.3)",
                url: "http://192.168.1.131:3000/d/aist-07-live-logs",
                badge: "Live Loki Stream",
                badgeColor: "border-teal-800 text-teal-300 bg-teal-950/40",
                desc: "Centralized real-time log ingestion from Linux & Windows microservices with LogQL rate analytics and filters."
              },
              {
                id: "08",
                title: "08 - SRE Automation Safety & Policy Guardrails",
                url: "http://192.168.1.131:3000/d/aist-08-automation-safety",
                badge: "Safety Policy",
                badgeColor: "border-rose-800 text-rose-300 bg-rose-950/40",
                desc: "Circuit breaker status, blast-radius restrictions, rollback checkpoints, and supervisor permission verification."
              },
              {
                id: "09",
                title: "09 - Executive Capstone & AI Governance",
                url: "http://192.168.1.131:3000/d/aist-09-executive-capstone",
                badge: "Executive Leadership",
                badgeColor: "border-emerald-800 text-emerald-300 bg-emerald-950/40",
                desc: "Portfolio health score, compliance gauges, financial throughput, incident velocity, and overall SLO health."
              }
            ].map((dash) => (
              <div 
                key={dash.id}
                className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 hover:border-cyan-500/80 hover:bg-slate-900 transition flex flex-col justify-between space-y-3 group"
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${dash.badgeColor}`}>
                      {dash.badge}
                    </span>
                    <a 
                      href={dash.url} 
                      target="_blank" 
                      rel="noreferrer"
                      className="text-slate-500 group-hover:text-cyan-400 transition"
                      title="Open in new window"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  </div>
                  <h3 className="text-sm font-bold text-slate-100 group-hover:text-cyan-300 transition">
                    {dash.title}
                  </h3>
                  <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                    {dash.desc}
                  </p>
                </div>
                <div className="flex items-center gap-2 pt-1 border-t border-slate-800/80">
                  <button 
                    onClick={() => setSelectedDashboard(selectedDashboard?.id === dash.id ? null : dash)}
                    className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-mono font-medium flex items-center justify-center gap-1.5 border transition ${
                      selectedDashboard?.id === dash.id
                        ? 'bg-cyan-950 border-cyan-500 text-cyan-300'
                        : 'bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 border-slate-700'
                    }`}
                  >
                    {selectedDashboard?.id === dash.id ? (
                      <>
                        <EyeOff className="w-3 h-3 text-cyan-400" /> Hide Cockpit Preview
                      </>
                    ) : (
                      <>
                        <Eye className="w-3 h-3 text-slate-400" /> Preview in Cockpit
                      </>
                    )}
                  </button>
                  <a 
                    href={dash.url} 
                    target="_blank" 
                    rel="noreferrer"
                    className="py-1.5 px-2.5 rounded-lg text-xs font-mono bg-slate-800 hover:bg-cyan-900/50 text-cyan-400 border border-slate-700 flex items-center gap-1"
                  >
                    Launch <ArrowUpRight className="w-3 h-3" />
                  </a>
                </div>
              </div>
            ))}

          </div>

          {/* Infrastructure & Alerting Consoles Bar */}
          <div className="border-t border-slate-800 pt-5">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Enterprise Infrastructure Consoles</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <a 
                href="http://192.168.1.131:9090" 
                target="_blank" 
                rel="noreferrer"
                className="p-3 rounded-lg border border-slate-800 bg-slate-900/40 hover:border-slate-600 flex items-center justify-between"
              >
                <div>
                  <div className="text-xs font-semibold text-white">Prometheus 3.0</div>
                  <div className="text-[10px] text-slate-400 font-mono">192.168.1.131:9090</div>
                </div>
                <ExternalLink className="w-3.5 h-3.5 text-slate-500" />
              </a>

              <a 
                href="http://192.168.1.131:9093" 
                target="_blank" 
                rel="noreferrer"
                className="p-3 rounded-lg border border-slate-800 bg-slate-900/40 hover:border-slate-600 flex items-center justify-between"
              >
                <div>
                  <div className="text-xs font-semibold text-white">AlertManager 0.27</div>
                  <div className="text-[10px] text-slate-400 font-mono">192.168.1.131:9093</div>
                </div>
                <ExternalLink className="w-3.5 h-3.5 text-slate-500" />
              </a>

              <a 
                href="http://192.168.1.131:3000/explore" 
                target="_blank" 
                rel="noreferrer"
                className="p-3 rounded-lg border border-slate-800 bg-slate-900/40 hover:border-slate-600 flex items-center justify-between"
              >
                <div>
                  <div className="text-xs font-semibold text-white">Tempo Tracing (OTel)</div>
                  <div className="text-[10px] text-slate-400 font-mono">192.168.1.131:3200</div>
                </div>
                <ExternalLink className="w-3.5 h-3.5 text-slate-500" />
              </a>

              <a 
                href="https://192.168.1.220/ui" 
                target="_blank" 
                rel="noreferrer"
                className="p-3 rounded-lg border border-slate-800 bg-slate-900/40 hover:border-slate-600 flex items-center justify-between"
              >
                <div>
                  <div className="text-xs font-semibold text-white">VMware vCenter 8.0</div>
                  <div className="text-[10px] text-slate-400 font-mono">192.168.1.220/ui</div>
                </div>
                <ExternalLink className="w-3.5 h-3.5 text-slate-500" />
              </a>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================
          VIEW 5: SRE RUNBOOKS & HYBRID RAG EXPLORER (OLLAMA + BM25)
      ======================================================================== */}
      {activeView === 'runbooks' && (
        <div className="flex-1 flex flex-col overflow-y-auto bg-slate-950 p-8 space-y-6">
          <div className="border-b border-slate-800 pb-5">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <BookOpen className="w-6 h-6 text-amber-400" /> SRE Runbooks &amp; Hybrid RAG Engine
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Neural vector search (Ollama RTX 5090 <code className="text-amber-300 font-mono">embeddinggemma-2:740m</code>) + Okapi BM25 keyword matching across standard operational procedures.
            </p>
          </div>

          {/* RAG Search Bar & Filter Chips */}
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/80 space-y-3">
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                <input 
                  type="text"
                  value={runbookQuery}
                  onChange={(e) => setRunbookQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearchRunbooks()}
                  placeholder="Ask a question or search runbooks (e.g., 'What to do when AuthGateway crashes on Windows?')..."
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-4 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-amber-500 font-mono"
                />
              </div>
              <button 
                onClick={() => handleSearchRunbooks()}
                disabled={isSearchingRunbooks}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow"
              >
                {isSearchingRunbooks ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
                Hybrid Search
              </button>
              {runbookResults && (
                <button 
                  onClick={() => { setRunbookResults(null); setRunbookQuery(""); }}
                  className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-mono"
                >
                  Clear
                </button>
              )}
            </div>

            {/* Quick Query Pills */}
            <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
              <span className="text-slate-400">Quick Scenarios:</span>
              {[
                "CPU saturation on RHEL 10",
                "Windows Auth Gateway connection refused",
                "SQL Server deadlock HTTP 500",
                "Notification worker backlog queue",
                "Loki high-cardinality ingestion throttled",
                "Multi-stage cascading failure"
              ].map((pill) => (
                <button 
                  key={pill}
                  onClick={() => { setRunbookQuery(pill); handleSearchRunbooks(pill); }}
                  className="px-2.5 py-1 rounded bg-slate-800/70 hover:bg-amber-950/60 hover:text-amber-300 border border-slate-700 hover:border-amber-700 text-slate-300 font-mono transition"
                >
                  {pill}
                </button>
              ))}
            </div>
          </div>

          {/* RAG Search Results Mode */}
          {runbookResults && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-amber-400 uppercase tracking-wider">
                  Hybrid Search Results ({runbookResults.length} matches for "{runbookQuery}")
                </h3>
                <span className="text-[10px] text-slate-400 font-mono">RTX 5090 (60% Dense Embeddings + 40% BM25)</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {runbookResults.map((res) => (
                  <div key={res.id} className="p-5 rounded-xl border border-amber-500/50 bg-slate-900/90 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded border border-amber-700 bg-amber-950/40 text-amber-300 font-bold">
                        MATCH SCORE: {(res.hybrid_score * 100).toFixed(1)}%
                      </span>
                      <span className="text-[10px] text-slate-400 font-mono">
                        Vector: {(res.vector_score * 100).toFixed(1)}% | BM25: {res.bm25_score.toFixed(2)}
                      </span>
                    </div>

                    <h4 className="text-sm font-bold text-white">{res.title}</h4>
                    <p className="text-xs text-slate-300 font-mono bg-slate-950/60 p-2.5 rounded border border-slate-800">
                      Scenario: {res.scenario}
                    </p>

                    <div className="text-xs text-slate-400 space-y-1">
                      <div className="text-[11px] font-semibold text-slate-300">Recovery Actions:</div>
                      <ul className="list-disc list-inside space-y-0.5 text-slate-300 font-mono text-[11px]">
                        {(res.recovery_actions || []).slice(0, 3).map((act, i) => (
                          <li key={i}>{act}</li>
                        ))}
                      </ul>
                    </div>

                    <button
                      onClick={() => {
                        setActiveView('copilot');
                        handleSendMessage(`Investigate incident following runbook ${res.id}: ${res.title}. Apply approved remediation.`);
                      }}
                      className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 shadow"
                    >
                      <Sparkles className="w-3.5 h-3.5" /> Execute Runbook in Copilot Swarm
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Standard Runbook Library (All 6 Standard Operating Procedures) */}
          <div className="space-y-4">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
              Standard Operating SRE Procedures (RB-01 to RB-06)
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {runbooks.map((rb) => (
                <div key={rb.id} className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 flex flex-col justify-between space-y-3">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded border border-slate-700 bg-slate-800 text-amber-300 font-bold">
                        {rb.id}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">{rb.filename}</span>
                    </div>

                    <h4 className="text-xs font-bold text-white">{rb.title}</h4>
                    <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">{rb.scenario}</p>

                    <div className="mt-2 flex flex-wrap gap-1">
                      {(rb.affected_services || []).map((s) => (
                        <span key={s} className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-mono">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>

                  <button
                    onClick={() => {
                      setActiveView('copilot');
                      handleSendMessage(`Follow runbook ${rb.id} (${rb.title}) to diagnose and remediate.`);
                    }}
                    className="w-full py-1.5 bg-slate-800 hover:bg-indigo-900/60 hover:text-indigo-200 text-slate-300 border border-slate-700 rounded-lg text-[11px] font-mono flex items-center justify-center gap-1 transition"
                  >
                    Load in Copilot <ArrowUpRight className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================
          VIEW 6: LIVE ROLLING LOGS EXPLORER (CONSOLE + LOGS DIR)
      ======================================================================== */}
      {activeView === 'logs' && (
        <div className="flex-1 flex flex-col bg-slate-950 p-8 space-y-4 overflow-hidden">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <ScrollText className="w-6 h-6 text-violet-400" /> Live Rolling Logs Explorer
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Streaming rolling logs from <code className="text-violet-300 font-mono">logs/aist_backend.log</code>, <code className="text-violet-300 font-mono">logs/manage_aist.log</code>, and <code className="text-violet-300 font-mono">Loki Engine (192.168.1.131:3100)</code>.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex rounded-lg bg-slate-900 border border-slate-800 p-0.5">
                <button
                  onClick={() => { setLogSource('backend'); fetchLogTail('backend'); }}
                  className={`px-3 py-1.5 rounded-md text-xs font-mono transition ${
                    logSource === 'backend'
                      ? 'bg-violet-600 text-white shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  aist_backend.log
                </button>
                <button
                  onClick={() => { setLogSource('manage'); fetchLogTail('manage'); }}
                  className={`px-3 py-1.5 rounded-md text-xs font-mono transition ${
                    logSource === 'manage'
                      ? 'bg-violet-600 text-white shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  manage_aist.log
                </button>
                <button
                  onClick={() => { setLogSource('loki'); fetchLogTail('loki'); }}
                  className={`px-3 py-1.5 rounded-md text-xs font-mono transition ${
                    logSource === 'loki'
                      ? 'bg-violet-600 text-white shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Loki Fleet Stream
                </button>
              </div>

              <button
                onClick={() => fetchLogTail(logSource)}
                disabled={logLoading}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-mono flex items-center gap-1 border border-slate-700"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${logLoading ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>
          </div>

          {/* Terminal Log Output Window */}
          <div className="flex-1 rounded-xl border border-slate-800 bg-black/90 p-4 font-mono text-[11px] overflow-y-auto leading-relaxed shadow-inner">
            {logLines.length === 0 ? (
              <div className="text-slate-500 italic p-4">No recent log entries in {logSource === 'backend' ? 'aist_backend.log' : 'manage_aist.log'}. Logs will appear as operations execute.</div>
            ) : (
              logLines.map((line, idx) => {
                let color = "text-slate-300";
                if (line.includes("ERROR") || line.includes("FAIL") || line.includes("HTTP 5")) {
                  color = "text-rose-400 font-semibold";
                } else if (line.includes("WARNING") || line.includes("HTTP 4")) {
                  color = "text-amber-300";
                } else if (line.includes("INFO") || line.includes("HTTP 200") || line.includes("HTTP 201")) {
                  color = "text-slate-300";
                }
                return (
                  <div key={idx} className={`py-0.5 hover:bg-slate-900/60 px-1 rounded ${color}`}>
                    <span className="text-slate-600 select-none mr-3">{idx + 1}</span>
                    {line}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

    </div>
  );
}
