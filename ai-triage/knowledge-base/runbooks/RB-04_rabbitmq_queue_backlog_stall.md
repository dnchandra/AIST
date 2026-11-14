# SRE Runbook: RB-04 - RabbitMQ Message Queue Backlog & Consumer Stall

## Severity: WARNING / P3
**Target Environments**: Red Hat Enterprise Linux 10 (`192.168.1.130`)  
**Alert Triggers**: `NotificationQueueBacklogHigh`, `rabbitmq_queue_messages_ready > 500`

---

### 1. Initial Assessment
When `ticket.created` queue depth spikes above 500 messages:
1. Verify if the consumer daemon is active on RHEL 10:
   ```bash
   ps aux | grep service.py
   ```
2. Check Notification Service logs:
   ```bash
   cat /opt/aist/notification-service/service.log | tail -n 25
   ```

### 2. Autonomous Diagnostic Steps
- Query Prometheus for queue ingestion rate vs drain rate:
   ```promql
   rate(notification_events_processed_total[2m])
   ```

### 3. Remediation Actions
1. **Low Blast Radius**: Call recovery endpoint to clear backlog:
   ```bash
   curl -X POST http://192.168.1.130:8080/api/v1/chaos/recover
   ```
2. **Restart Consumer Service**:
   ```bash
   nohup /opt/aist/venv/bin/python3 /opt/aist/notification-service/service.py > /opt/aist/notification-service/service.log 2>&1 &
   ```

