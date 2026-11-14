#!/usr/bin/env bash
# CHAOS-01: CPU Spike Simulation on RHEL 10
# Triggers LinuxNodeHighCPU (>85%) alert in Prometheus 3.0
echo "=== [CHAOS-01] Initiating CPU Stress on Linux Node ==="
echo "Target: RHEL 10 (192.168.1.25 / 192.168.1.130)"

# Run background CPU stress for 90 seconds
(
  for i in $(seq 1 4); do
    sha256sum /dev/zero &
  done
  sleep 90
  killall sha256sum 2>/dev/null
) &

echo "CPU stress initiated in background (PID: $!). Will automatically terminate after 90 seconds."
echo "Expected AI Triage: mcp_prometheus flags HighCPU -> mcp_linux_diag identifies sha256sum -> prompts HITL to terminate."

