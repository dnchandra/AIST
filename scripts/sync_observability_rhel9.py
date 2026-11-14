import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import paramiko
from config import RHEL9_IP, LINUX_USER, LINUX_PASS

def upload_directory_sftp(sftp, local_dir, remote_dir):
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass

    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir}/{item}".replace("\\", "/")
        if os.path.isdir(local_path):
            if item in [".git", "__pycache__", "dashboards_backup"]:
                continue
            upload_directory_sftp(sftp, local_path, remote_path)
        else:
            try:
                sftp.put(local_path, remote_path)
            except Exception as e:
                print(f"Error uploading {local_path}: {e}")

print("=" * 70)
print(f"Syncing Observability Stack & Dashboards to RHEL 9 ({RHEL9_IP})")
print("=" * 70)

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(RHEL9_IP, 22, LINUX_USER, LINUX_PASS, timeout=10)

# 1. Clean remote dashboards directory first so no stale json files remain
print("[1/4] Cleaning remote dashboard files on RHEL 9...")
c.exec_command("rm -rf /opt/aist/observability/grafana/dashboards/*")

# 2. Upload updated observability files
print("[2/4] Uploading updated observability files via SFTP...")
sftp = c.open_sftp()
upload_directory_sftp(sftp, os.path.join(BASE_DIR, "observability"), "/opt/aist/observability")
sftp.close()

# 3. Reset Grafana cache & recreate container so 'json' folder is removed
print("[3/4] Re-provisioning Grafana with clean 'AIST' folder...")
clean_cmd = """
cd /opt/aist/observability
podman stop aist-grafana 2>/dev/null || true
podman rm aist-grafana 2>/dev/null || true
podman volume rm -f observability_grafana_data aist-observability_grafana_data grafana_data 2>/dev/null || true
podman stop aist-prometheus aist-alertmanager 2>/dev/null || true
podman rm aist-prometheus aist-alertmanager 2>/dev/null || true
docker-compose -f docker-compose.observability.yml up -d
"""
_, out, err = c.exec_command(clean_cmd)
print(out.read().decode().strip())

# 4. Wait for containers and verify
print("[4/4] Verifying Grafana and Prometheus startup...")
time.sleep(6)
_, ps_out, _ = c.exec_command("podman ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")
print(ps_out.read().decode().strip())

c.close()
print("\n[+] Observability stack sync complete.")

