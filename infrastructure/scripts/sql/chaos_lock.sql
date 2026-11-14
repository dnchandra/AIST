-- CHAOS-03: Simulate Exclusive Table Lock on Tickets
-- Holds an uncommitted transaction with TABLOCKX for 180 seconds
USE TicketFlowDB;
GO

BEGIN TRANSACTION;
    PRINT 'Acquiring exclusive table lock on Tickets table...';
    UPDATE Tickets WITH (TABLOCKX)
    SET UpdatedAt = SYSUTCDATETIME()
    WHERE TicketId = 1;

    PRINT 'Lock acquired. Holding transaction for 180 seconds to simulate deadlock/blocking...';
    WAITFOR DELAY '00:03:00';
COMMIT TRANSACTION;
PRINT 'Transaction committed. Lock released.';
GO
