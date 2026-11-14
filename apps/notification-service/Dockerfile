FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY go.mod ./
RUN go mod download || true

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o notification-service main.go

FROM alpine:3.19
WORKDIR /app
COPY --from=builder /app/notification-service .

EXPOSE 8080
CMD ["./notification-service"]
