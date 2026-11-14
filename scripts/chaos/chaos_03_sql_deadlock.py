"""
CHAOS-03: SQL Server Exclusive Table Lock Simulation
Target: Windows Server 2019 (192.168.1.133:1433)
Holds TABLOCKX on Tickets table to induce connection pool exhaustion in Flask API
"""

import time
import pyodbc

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=192.168.1.133,1433;"
    "DATABASE=TicketFlowDB;"
    "UID=Administrator;"
    "PWD=Root@123;"
    "TrustServerCertificate=yes;"
)

print("=== [CHAOS-03] Acquiring Exclusive Table Lock on SQL Server ===")
try:
    conn = pyodbc.connect(CONN_STR, timeout=10)
    cursor = conn.cursor()
    cursor.execute("BEGIN TRANSACTION; UPDATE Tickets WITH (TABLOCKX) SET UpdatedAt = SYSUTCDATETIME() WHERE TicketId = 1;")
    print("Lock acquired! Holding transaction for 180 seconds to block all API queries...")
    time.sleep(180)
    conn.commit()
    print("Lock released successfully.")
except Exception as e:
    print("Lock simulation failed (check DB connectivity):", e)

