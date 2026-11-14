"""
CHAOS-04: RabbitMQ Queue Backlog Simulation
Target: Notification Service on RHEL 10 (192.168.1.130:8080)
Injects 650 backlog messages into ticket.created to trigger NotificationQueueBacklogHigh alert
"""

import requests

url = "http://192.168.1.130:8080/api/v1/chaos/backlog"
print("=== [CHAOS-04] Injecting RabbitMQ Queue Backlog ===")
try:
    resp = requests.post(url, timeout=5)
    print("Injected backlog successfully:", resp.json())
    print("Expected AI Triage: Prometheus fires queue alert -> AI investigates consumer status -> suggests worker restart.")
except Exception as e:
    print("Failed to reach notification service:", e)

