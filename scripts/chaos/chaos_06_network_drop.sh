#!/usr/bin/env bash
# CHAOS-06: Network Partition (Drop Traffic to SQL Server Port 1433)
# Simulates cross-VM firewall drop between RHEL 10 and Windows 2019
echo "=== [CHAOS-06] Simulating Network Partition to SQL Server ==="
echo "Adding iptables rule to drop outbound packets to 192.168.1.133:1433..."

iptables -A OUTPUT -p tcp -d 192.168.1.133 --dport 1433 -j DROP
echo "Rule added! Flask API will now fail with pyodbc connection timeout."
echo ""
echo "To revert network partition:"
echo "iptables -D OUTPUT -p tcp -d 192.168.1.133 --dport 1433 -j DROP"

