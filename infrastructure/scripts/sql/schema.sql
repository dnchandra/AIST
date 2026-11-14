-- AIST Enterprise Database Schema
-- Microsoft SQL Server 2019 / 2022 Express (Windows Server 2019)

IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'TicketFlowDB')
BEGIN
    CREATE DATABASE TicketFlowDB;
END
GO

USE TicketFlowDB;
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Tickets')
BEGIN
    CREATE TABLE Tickets (
        TicketId INT IDENTITY(1,1) PRIMARY KEY,
        Title NVARCHAR(255) NOT NULL,
        Priority NVARCHAR(50) NOT NULL DEFAULT 'MEDIUM',
        Status NVARCHAR(50) NOT NULL DEFAULT 'OPEN',
        AssignedTo NVARCHAR(100),
        CreatedAt DATETIME2 DEFAULT SYSUTCDATETIME(),
        UpdatedAt DATETIME2 DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AuditLogs')
BEGIN
    CREATE TABLE AuditLogs (
        AuditId INT IDENTITY(1,1) PRIMARY KEY,
        TicketId INT,
        Action NVARCHAR(100) NOT NULL,
        ExecutedBy NVARCHAR(100) NOT NULL,
        Timestamp DATETIME2 DEFAULT SYSUTCDATETIME()
    );
END
GO

-- Seed baseline records
IF NOT EXISTS (SELECT 1 FROM Tickets)
BEGIN
    INSERT INTO Tickets (Title, Priority, Status, AssignedTo) VALUES
    ('VPN gateway packet loss', 'HIGH', 'OPEN', 'infra-team'),
    ('Slow database queries on SQL Server', 'CRITICAL', 'IN_PROGRESS', 'dba-team'),
    ('IIS AppPool memory leak', 'MEDIUM', 'RESOLVED', 'windows-ops');
END
GO
