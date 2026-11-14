"""
AIST Notification Service
Runs on RHEL 10 (192.168.1.130:8080)
Consumes ticket events, exposes Prometheus metrics, and ships structured live logs to Loki.
"""

import os
import time
import queue
import logging
import threading
import requests
from flask import Flask, request, jsonify, Response
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notification_service")

app = Flask(__name__)

LOKI_URL = os.environ.get("LOKI_URL", "http://192.168.1.131:3100")

_log_queue = queue.Queue(maxsize=1000)

def _loki_worker():
    session = requests.Session()
    while True:
        try:
            level, message = _log_queue.get()
            now_ns = str(time.time_ns())
            payload = {
                "streams": [
                    {
                        "stream": {
                            "app": "ticketflow",
                            "service": "notification-service",
                            "os": "rhel10",
                            "level": level.upper()
                        },
                        "values": [[now_ns, message]]
                    }
                ]
            }
            session.post(f"{LOKI_URL}/loki/api/v1/push", json=payload, headers={"Content-Type": "application/json"}, timeout=2)
        except Exception:
            pass
        finally:
            _log_queue.task_done()

threading.Thread(target=_loki_worker, daemon=True, name="notify_loki_shipper").start()

def ship_log_to_loki(level: str, message: str):
    """Queue structured log message for Loki background shipper."""
    try:
        _log_queue.put_nowait((level, message))
    except queue.Full:
        pass

EVENTS_PROCESSED = Counter(
    "notification_events_processed_total",
    "Total notification events processed",
    ["event_type", "status"]
)

QUEUE_DEPTH = Gauge(
    "rabbitmq_queue_messages_ready",
    "Simulated queue messages ready",
    ["queue"]
)

QUEUE_DEPTH.labels(queue="ticket.created").set(5)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "HEALTHY",
        "service": "notification-service",
        "os": "rhel10",
        "timestamp": time.time()
    })


@app.route("/metrics", methods=["GET"])
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/api/v1/notify", methods=["POST"])
def notify():
    data = request.get_json() or {}
    ticket_id = data.get("ticket_id", 0)
    action = data.get("action", "ticket_created")
    recipient = data.get("recipient", "oncall-sre@enterprise.com")

    EVENTS_PROCESSED.labels(event_type=action, status="success").inc()
    msg = f"Notification dispatched: Ticket #{ticket_id} ({action}) -> {recipient}"
    logger.info(msg)
    ship_log_to_loki("INFO", msg)
    return jsonify({
        "success": True,
        "message": f"Notification dispatched for ticket #{ticket_id}",
        "recipient": recipient
    })


@app.route("/api/v1/chaos/backlog", methods=["POST"])
def chaos_backlog():
    QUEUE_DEPTH.labels(queue="ticket.created").set(650)
    msg = "CHAOS_INJECTION: RabbitMQ queue backlog spike triggered (>650 ready messages)"
    logger.warning(msg)
    ship_log_to_loki("WARN", msg)
    return jsonify({
        "chaos": "queue_backlog_injected",
        "queue": "ticket.created",
        "depth": 650
    })


@app.route("/api/v1/chaos/recover", methods=["POST"])
def chaos_recover():
    QUEUE_DEPTH.labels(queue="ticket.created").set(5)
    msg = "CHAOS_RECOVERY: Queue consumers scaled up; backlog drained to 5 messages"
    logger.info(msg)
    ship_log_to_loki("INFO", msg)
    return jsonify({
        "chaos": "recovered",
        "queue": "ticket.created",
        "depth": 5
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    ship_log_to_loki("INFO", f"Notification Service initialized and listening on port {port}")
    app.run(host="0.0.0.0", port=port)
