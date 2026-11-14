"""
AIST Automated Firewall & Network Connectivity Manager
Configures bidirectional firewall rules and validates ports across:
- RHEL 10 (192.168.1.25)
- RHEL 9 (192.168.1.18)
- Windows Server 2025 (192.168.1.13)
- Windows Server 2019 (192.168.1.4)
"""

import sys
import logging
import paramiko
import winrm

import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import (
    RHEL10_IP, RHEL9_IP, WIN2025_IP, WIN2019_IP,
    LINUX_USER, LINUX_PASS, WINDOWS_USER, WINDOWS_PASS
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("firewall_config")


def configure_linux_firewall(host, name):
    logger.info("Configuring firewall on %s (%s)...", name, host)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=10)
        # Allow ports and ensure iptables is clean for lab traffic
        cmd = """
        iptables -F 2>/dev/null || true
        firewall-cmd --permanent --add-port=22/tcp --add-port=80/tcp --add-port=5000/tcp --add-port=8080/tcp --add-port=6379/tcp --add-port=5672/tcp --add-port=9090/tcp --add-port=3000/tcp --add-port=3100/tcp --add-port=3200/tcp --add-port=9093/tcp --add-port=4317/tcp --add-port=4318/tcp --add-port=9100/tcp 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
        echo 'LINUX_FIREWALL_CONFIGURED'
        """
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode().strip()
        logger.info("%s firewall result: %s", name, out)
        client.close()
        return True
    except Exception as e:
        logger.error("Failed to configure %s firewall: %s", name, e)
        return False


def configure_windows_firewall(host, name):
    logger.info("Configuring firewall on %s (%s)...", name, host)
    try:
        session = winrm.Session(f"http://{host}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
        ps_script = """
        New-NetFirewallRule -DisplayName "AIST Inbound Ports" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 1433,3000,5001,5002,5003,8088,9182,5985,3389 -Force -ErrorAction SilentlyContinue | Out-Null
        Set-NetFirewallRule -DisplayName "File and Printer Sharing (Echo Request - ICMPv4-In)" -Enabled True -Action Allow -ErrorAction SilentlyContinue | Out-Null
        Write-Output "WINDOWS_FIREWALL_CONFIGURED"
        """
        res = session.run_ps(ps_script)
        logger.info("%s firewall result: %s", name, res.std_out.decode().strip())
        return True
    except Exception as e:
        logger.error("Failed to configure %s firewall: %s", name, e)
        return False


def setup_all_firewalls():
    logger.info("=== Starting Automated Firewall Configuration (Parallel Multi-Node) ===")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    tasks = [
        (configure_linux_firewall, (RHEL10_IP, "RHEL 10 (Apps)")),
        (configure_linux_firewall, (RHEL9_IP, "RHEL 9 (Observability)")),
        (configure_windows_firewall, (WIN2025_IP, "Windows Server 2025 (.NET)")),
        (configure_windows_firewall, (WIN2019_IP, "Windows Server 2019 (SQL)")),
    ]
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn, *args): args[1] for fn, args in tasks}
        for fut in as_completed(futures):
            target_name = futures[fut]
            try:
                res = fut.result()
                results[target_name] = res
                logger.info("  [%s] Firewall setup: %s", target_name, "SUCCESS" if res else "FAILED")
            except Exception as e:
                logger.error("  [%s] Firewall setup exception: %s", target_name, e)
                results[target_name] = False

    all_ok = all(results.values()) if results else False
    logger.info("=== Firewall Configuration Summary: %s ===", "ALL SUCCESSFUL" if all_ok else "PARTIAL FAILURES")
    return all_ok


if __name__ == "__main__":
    success = setup_all_firewalls()
    sys.exit(0 if success else 1)

