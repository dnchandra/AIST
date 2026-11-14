package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	eventsProcessed = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "notification_events_processed_total",
			Help: "Total notification events processed",
		},
		[]string{"event_type", "status"},
	)

	queueDepth = prometheus.NewGauge(
		prometheus.GaugeOpts{
			Name: "rabbitmq_queue_messages_ready",
			Help: "Simulated queue messages ready",
			ConstLabels: prometheus.Labels{"queue": "ticket.created"},
		},
	)
)

func init() {
	prometheus.MustRegister(eventsProcessed)
	prometheus.MustRegister(queueDepth)
	queueDepth.Set(5) // default normal state
}

type NotificationEvent struct {
	TicketID  int    `json:"ticket_id"`
	Action    string `json:"action"`
	Recipient string `json:"recipient"`
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":  "HEALTHY",
		"service": "notification-service-go",
		"runtime": "podman-container",
	})
}

func notifyHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var event NotificationEvent
	if err := json.NewDecoder(r.Body).Decode(&event); err != nil {
		eventsProcessed.WithLabelValues("invalid", "error").Inc()
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	eventsProcessed.WithLabelValues(event.Action, "success").Inc()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": true,
		"message": fmt.Sprintf("Notification dispatched for ticket #%d", event.TicketID),
	})
}

func chaosBacklogHandler(w http.ResponseWriter, r *http.Request) {
	// Simulate queue depth spike for CHAOS-04
	queueDepth.Set(650)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"chaos": "queue_backlog_injected",
		"depth": 650,
	})
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	http.HandleFunc("/health", healthHandler)
	http.HandleFunc("/api/v1/notify", notifyHandler)
	http.HandleFunc("/api/v1/chaos/backlog", chaosBacklogHandler)
	http.Handle("/metrics", promhttp.Handler())

	log.Printf("Notification Service (Go) listening on port %s...", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
