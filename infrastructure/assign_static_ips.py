"""
================================================================================
  AIST: Enterprise Static IP Provisioning & Discovery Engine
  Direct Hypervisor IP Discovery + Native Static IP Binding (No DHCP Reliance)
================================================================================
- RHEL 10: 192.168.1.130/24 (ens33)
- RHEL 9:  192.168.1.131/24 (ens33)
- Win2025: 192.168.1.132/24 (Ethernet0)
- Win2019: 192.168.1.133/24 (Ethernet0)
Gateway: 192.168.1.1, DNS: 8.8.8.8, 1.1.1.1
================================================================================
"""

import os
import sys
import time
import socket
import paramiko
import winrm

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import (
    RHEL10_IP, RHEL9_IP, WIN2025_IP, WIN2019_IP,
    LINUX_USER, LINUX_PASS, WINDOWS_USER, WINDOWS_PASS,
    ESXI_HOST, ESXI_USER, ESXI_PASS
)
from infrastructure.vcenter_manager import VCenterManager

print("=" * 75)
print("   AIST: Master Enterprise Static IP Provisioning Engine")
print("=" * 75)


def is_ip_reachable(ip: str, port: int = 22, timeout: float = 1.5) -> bool:
    """Test TCP socket reachability on target IP."""
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def discover_guest_ip(vm_name: str) -> str | None:
    """Query live IP address directly from hypervisor via VMware Tools."""
    try:
        mgr = VCenterManager()
        if mgr.connect():
            vm = mgr.find_vm_by_name(vm_name)
            if vm:
                identity = mgr.get_guest_identity(vm["vm"])
                if identity and identity.get("ip_address"):
                    return identity["ip_address"]
    except Exception:
        pass

    # ESXi CLI fallback via vim-cmd
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ESXI_HOST, port=22, username=ESXI_USER, password=ESXI_PASS, timeout=5)
        _, o, _ = c.exec_command(f"vim-cmd vmsvc/getallvms | grep -i '{vm_name}'")
        line = o.read().decode().strip()
        if line:
            vmid = line.split()[0]
            _, o, _ = c.exec_command(f"vim-cmd vmsvc/get.guest {vmid} | grep 'ipAddress ='")
            ip_line = o.read().decode().strip()
            if ip_line and '"' in ip_line:
                ip = ip_line.split('"')[1]
                c.close()
                return ip
        c.close()
    except Exception:
        pass
    return None


def configure_linux_static(vm_name: str, target_ip: str):
    print(f"\n[*] Configuring Static IP on {vm_name} (Target: {target_ip})...")
    if is_ip_reachable(target_ip, port=22):
        print(f" [+] {vm_name} is already reachable at static IP {target_ip}!")
        return True

    # Discover live dynamic IP from hypervisor
    live_ip = discover_guest_ip(vm_name)
    connect_ip = live_ip or target_ip
    print(f" -> Connecting to {vm_name} via {connect_ip}...")

    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(connect_ip, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=6)
        cmd = f"nohup sh -c 'nmcli con mod ens33 ipv4.addresses {target_ip}/24 ipv4.gateway 192.168.1.1 ipv4.dns 8.8.8.8,1.1.1.1 ipv4.method manual && nmcli con up ens33' >/dev/null 2>&1 &"
        c.exec_command(cmd)
        time.sleep(1)
        c.close()
        
        # Verify reachability on target static IP
        for _ in range(10):
            time.sleep(1)
            if is_ip_reachable(target_ip, port=22):
                print(f" [+] Successfully configured {vm_name} at static IP {target_ip}!")
                return True
        return False
    except Exception as e:
        print(f" [!] Error on {vm_name}: {e}")
        return False


def configure_windows_static(vm_name: str, target_ip: str):
    print(f"\n[*] Configuring Static IP on {vm_name} (Target: {target_ip})...")
    if is_ip_reachable(target_ip, port=5985):
        print(f" [+] {vm_name} is already reachable at static IP {target_ip}!")
        return True

    live_ip = discover_guest_ip(vm_name)
    connect_ip = live_ip or target_ip
    print(f" -> Connecting to {vm_name} via {connect_ip}...")

    try:
        s = winrm.Session(f"http://{connect_ip}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
        ps = f'''
        $w = [wmiclass]"\\\\.\\root\\cimv2:Win32_Process"
        $w.Create('powershell.exe -Command "Start-Sleep -Seconds 1; netsh interface ipv4 set address name=\\"Ethernet0\\" static {target_ip} 255.255.255.0 192.168.1.1; netsh interface ipv4 set dns name=\\"Ethernet0\\" static 8.8.8.8"')
        '''
        res = s.run_ps(ps)
        print(" [+] WMI IP transition initiated via netsh. Verifying reachability...")
        for _ in range(15):
            time.sleep(1)
            if is_ip_reachable(target_ip, port=5985):
                print(f" [+] Successfully configured {vm_name} at static IP {target_ip}!")
                return True
        return is_ip_reachable(target_ip, port=5985)
    except Exception as e:
        print(f" [!] Error on {vm_name}: {e}")
        return False


def main():
    from concurrent.futures import ThreadPoolExecutor, as_completed

    tasks = [
        ("RHEL10", configure_linux_static, "RHEL10", RHEL10_IP),
        ("RHEL9", configure_linux_static, "RHEL9", RHEL9_IP),
        ("Win2025", configure_windows_static, "Win2025", WIN2025_IP),
        ("Win2019", configure_windows_static, "Win2019", WIN2019_IP),
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(func, name, ip): name for name, func, name, ip in tasks}
        for fut in as_completed(futures):
            vm_name = futures[fut]
            try:
                fut.result()
            except Exception as e:
                print(f" [!] Static IP thread error on {vm_name}: {e}")

    print("\n[+] Verification: Testing reachability of all 4 static production IPs:")
    for name, ip, port in [
        ("RHEL 10 (Apps)", RHEL10_IP, 22),
        ("RHEL 9 (Observability)", RHEL9_IP, 22),
        ("Win 2025 (Auth/Portal)", WIN2025_IP, 5985),
        ("Win 2019 (Audit/SQL)", WIN2019_IP, 5985)
    ]:
        ok = is_ip_reachable(ip, port)
        status = "REACHABLE (OK)" if ok else "UNREACHABLE (FAIL)"
        print(f" - {name:<26} [{ip}]: {status}")


if __name__ == "__main__":
    main()
