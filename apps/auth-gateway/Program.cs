using System.Diagnostics.Metrics;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var builder = WebApplication.CreateBuilder(args);

// Metrics
var meter = new Meter("AIST.AuthGateway", "1.0.0");
var authAttemptsCounter = meter.CreateCounter<long>("auth_attempts_total", "count", "Total authentication attempts");
var authFailuresCounter = meter.CreateCounter<long>("auth_failures_total", "count", "Total failed authentication attempts");

builder.Services.AddEndpointsApiExplorer();

var app = builder.Build();

app.MapGet("/health", () => Results.Ok(new {
    status = "HEALTHY",
    service = "auth-gateway",
    runtime = ".NET 9.0",
    os = "Windows Server 2025",
    timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds()
}));

app.MapPost("/api/v1/auth/login", (LoginRequest req) => {
    authAttemptsCounter.Add(1);
    
    if (req.Username == "admin" && req.Password == "Root@123")
    {
        var token = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes($"aist_jwt_{req.Username}_{DateTime.UtcNow.Ticks}"));
        return Results.Ok(new {
            token = token,
            expires_in = 3600,
            user = new { username = req.Username, role = "SRE_Admin" }
        });
    }

    authFailuresCounter.Add(1);
    return Results.Unauthorized();
});

// Chaos endpoint: Simulates AppPool / Service crash (CHAOS-02)
app.MapPost("/api/v1/chaos/crash", () => {
    Console.WriteLine("[CHAOS] Fatal crash triggered by chaos engineer. Terminating worker process...");
    Environment.FailFast("CHAOS-02: Simulated unhandled exception causing AppPool crash.");
    return Results.StatusCode(500);
});

app.Run("http://0.0.0.0:5001");

record LoginRequest(string Username, string Password);
