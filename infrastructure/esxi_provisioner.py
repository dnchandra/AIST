#!/usr/bin/env python3
"""
================================================================================
  AIST: ESXi & vCenter Automated VM Provisioning & Disaster Recovery Engine
  Direct Hypervisor Lifecycle: Deploy, Clone, Scale, Destroy, and Restore
================================================================================
Enables:
  1. 100% automated VM deployment from templates directly on ESXi (independent of vCenter).
  2. Disaster recovery: If vCenter or ESXi crashes, all VMs can be restored from backup templates in minutes.
  3. All VMs provisioned with 16 GB RAM (16384 MiB) and thin-provisioned disks.
  4. Horizontal scaling: Dynamically deploy new worker VMs (RHEL10-Worker-0X, etc.).
================================================================================
"""

import os
import sys
import time
import re
import logging
import argparse
import paramiko
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import (
    ESXI_HOST, ESXI_USER, ESXI_PASS,
    VCENTER_HOST, VCENTER_USER, VCENTER_PASS,
    DATASTORE_TARGET,
    RHEL10_IP, RHEL9_IP, WIN2025_IP, WIN2019_IP
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("esxi_provisioner")

# Protected infrastructure objects and templates that MUST NEVER be destroyed or deleted
PROTECTED_OBJECTS = {
    "rhel10_template", "rhel9_template", "win2019_template", "win2025_template",
    "win2025_template_1", "win11", "ad", "client", "vcs", "san"
}


def is_protected(name: str) -> bool:
    """Check if a VM or template name is a protected permanent asset."""
    clean = name.strip().lower()
    if clean in PROTECTED_OBJECTS:
        return True
    if "template" in clean:
        return True
    return False


# Master Template Registry
# Maps template identifiers to known datastore paths on ESXi
TEMPLATES = {
    "rhel10": {
        "name": "RHEL10_Template",
        "datastore": "Base_DS",
        "dir_path": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/RHEL10_Template",
        "vmdk": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/RHEL10_Template/RHEL10_Template.vmdk",
        "vmtx": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/RHEL10_Template/RHEL10_Template.vmtx",
        "nvram": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/RHEL10_Template/RHEL10_Template.nvram",
        "default_ip": RHEL10_IP,
        "os_type": "rhel9-64",
        "default_name": "RHEL10"
    },
    "rhel9": {
        "name": "RHEL9_Template",
        "datastore": "Base_DS",
        "dir_path": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/RHEL9_Template",
        "vmdk": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/RHEL9_Template/RHEL9_Template.vmdk",
        "vmtx": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/RHEL9_Template/RHEL9_Template.vmtx",
        "nvram": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/RHEL9_Template/RHEL9_Template.nvram",
        "default_ip": RHEL9_IP,
        "os_type": "rhel9-64",
        "default_name": "RHEL9"
    },
    "win2019": {
        "name": "Win2019_Template",
        "datastore": "Base_DS",
        "dir_path": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/Win2019_Template",
        "vmdk": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/Win2019_Template/Win2019_Template.vmdk",
        "vmtx": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/Win2019_Template/Win2019_Template.vmtx",
        "nvram": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/Win2019_Template/Win2019_Template.nvram",
        "default_ip": WIN2019_IP,
        "os_type": "windows2019srv_64Guest",
        "default_name": "Win2019"
    },
    "win2025": {
        "name": "Win2025_Template",
        "datastore": "Base_DS",
        "dir_path": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/Win2025_Template",
        "vmdk": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/Win2025_Template/Win2025_Template.vmdk",
        "vmtx": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/Win2025_Template/Win2025_Template.vmtx",
        "nvram": "/vmfs/volumes/5fc3642a-c7f5399f-fd80-246e96501324/Win2025_Template/Win2025_Template.nvram",
        "default_ip": WIN2025_IP,
        "os_type": "windows2022srvNext_64Guest",
        "default_name": "Win2025"
    }
}


class ESXiProvisioner:
    """Direct VMware ESXi 8.0 Management & Fast Cloning Engine."""

    def __init__(self, host=ESXI_HOST, user=ESXI_USER, password=ESXI_PASS):
        self.host = host
        self.user = user
        self.password = password
        self._ssh: Optional[paramiko.SSHClient] = None

    def connect(self) -> bool:
        """Establish direct SSH connection to ESXi hypervisor."""
        try:
            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._ssh.connect(self.host, port=22, username=self.user, password=self.password, timeout=10)
            logger.info("Connected directly to ESXi Hypervisor at %s", self.host)
            return True
        except Exception as e:
            logger.error("Failed to connect to ESXi at %s: %s", self.host, e)
            return False

    def close(self):
        if self._ssh:
            self._ssh.close()
            self._ssh = None

    def run_cmd(self, command: str, timeout: int = 180) -> Tuple[int, str, str]:
        """Execute command on ESXi shell."""
        if not self._ssh:
            if not self.connect() or not self._ssh:
                raise ConnectionError("Not connected to ESXi host")
        stdin, stdout, stderr = self._ssh.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return exit_code, out, err

    def list_vms(self) -> List[Dict]:
        """Query all registered virtual machines from ESXi via vim-cmd."""
        code, out, err = self.run_cmd("vim-cmd vmsvc/getallvms")
        vms = []
        if code != 0:
            logger.error("vim-cmd getallvms failed: %s", err)
            return vms

        lines = out.strip().split("\n")
        if len(lines) <= 1:
            return vms

        # First line is header: Vmid Name File Guest OS Version Annotation
        for line in lines[1:]:
            parts = line.strip().split()
            if len(parts) >= 4 and parts[0].isdigit():
                vmid = parts[0]
                name = parts[1]
                vmx_file = parts[2] + " " + parts[3] if len(parts) > 3 else parts[2]
                vms.append({
                    "vmid": vmid,
                    "name": name,
                    "vmx_path": vmx_file,
                    "guest_os": parts[4] if len(parts) > 4 else "unknown"
                })
        return vms

    def get_vm_power_state(self, vmid: str) -> str:
        """Get power state for a specific VM."""
        code, out, err = self.run_cmd(f"vim-cmd vmsvc/power.getstate {vmid}")
        if "Powered on" in out:
            return "POWERED_ON"
        elif "Powered off" in out:
            return "POWERED_OFF"
        elif "Suspended" in out:
            return "SUSPENDED"
        return "UNKNOWN"

    def power_on_vm(self, vmid: str) -> bool:
        """Power on virtual machine."""
        code, out, err = self.run_cmd(f"vim-cmd vmsvc/power.on {vmid}")
        return code == 0

    def power_off_vm(self, vmid: str, force: bool = True) -> bool:
        """Power off virtual machine."""
        code, out, err = self.run_cmd(f"vim-cmd vmsvc/power.off {vmid}")
        return code == 0

    def find_vm_by_name(self, name: str) -> Optional[Dict]:
        """Locate registered VM by name."""
        vms = self.list_vms()
        for vm in vms:
            if vm["name"].lower() == name.lower():
                vm["power_state"] = self.get_vm_power_state(vm["vmid"])
                return vm
        return None

    def discover_templates(self) -> Dict[str, Dict]:
        """
        Dynamically query ESXi/vCenter storage to locate master VM templates.
        Maps canonical keys ('rhel10', 'rhel9', 'win2019', 'win2025')
        to their actual datastore paths on Base_DS.
        """
        code, out, _ = self.run_cmd("ls -d /vmfs/volumes/Base_DS/*Template* 2>/dev/null")
        if code == 0 and out.strip():
            dirs = out.strip().split()
            for d in dirs:
                base = os.path.basename(d.strip())
                base_lower = base.lower()
                key = None
                if "rhel10" in base_lower:
                    key = "rhel10"
                elif "rhel9" in base_lower:
                    key = "rhel9"
                elif "win2019" in base_lower:
                    key = "win2019"
                elif "win2025" in base_lower and not base_lower.endswith("_1"):
                    key = "win2025"

                if key and key in TEMPLATES:
                    TEMPLATES[key]["dir_path"] = d.strip()
                    TEMPLATES[key]["vmdk"] = f"{d.strip()}/{base}.vmdk"
                    TEMPLATES[key]["vmtx"] = f"{d.strip()}/{base}.vmtx"
                    TEMPLATES[key]["nvram"] = f"{d.strip()}/{base}.nvram"
        return TEMPLATES

    def clone_from_template(
        self,
        template_key: str,
        target_name: str,
        ram_mib: int = 16384,
        cpus: int = 4,
        target_ds: str = "Base_DS",
        ip_address: Optional[str] = None
    ) -> bool:
        """
        Fast-clone a complete virtual machine from a template on ESXi:
        1. Thin-clones virtual disk (.vmdk) in ~30-45s.
        2. Configures RAM (16384 MiB = 16GB) and vCPUs (4 vCPUs).
        3. Injects static IP directly into guestinfo metadata (no DHCP dependency).
        4. Copies NVRAM firmware state.
        5. Configures clean unique UUID and MAC.
        6. Registers VM with ESXi hypervisor.
        7. Powers on the virtual machine.
        """
        template_key = template_key.lower().replace("-", "").replace("_", "")
        if template_key not in TEMPLATES:
            logger.error("Unknown template '%s'. Available: %s", template_key, list(TEMPLATES.keys()))
            return False

        tpl = TEMPLATES[template_key]
        target_ip = ip_address or tpl["default_ip"]
        target_dir = f"/vmfs/volumes/{target_ds}/{target_name}"
        target_vmdk = f"{target_dir}/{target_name}.vmdk"
        target_vmx = f"{target_dir}/{target_name}.vmx"
        target_nvram = f"{target_dir}/{target_name}.nvram"

        logger.info("=== Starting Fast-Clone: %s -> %s ===", tpl['name'], target_name)
        logger.info("Target directory: %s", target_dir)
        logger.info("Static Network:   %s/24 (Gateway: 192.168.1.1, DNS: 8.8.8.8)", target_ip)
        logger.info("Allocation:       %d MiB RAM (%d GB), %d vCPUs, Thin-Provisioned", ram_mib, ram_mib // 1024, cpus)

        # Step 1: Create directory
        self.run_cmd(f"mkdir -p {target_dir}")

        # Step 2: Thin clone VMDK
        t0 = time.time()
        logger.info("[Step 1/5] Cloning virtual disk via vmkfstools (thin)...")
        code, out, err = self.run_cmd(f"vmkfstools -i {tpl['vmdk']} -d thin {target_vmdk}", timeout=300)
        if code != 0:
            logger.error("vmkfstools failed: %s %s", out, err)
            return False
        elapsed = time.time() - t0
        logger.info(" [+] Virtual disk cloned in %.1f seconds.", elapsed)

        # Step 3: Copy NVRAM firmware if present
        if tpl.get("nvram"):
            self.run_cmd(f"cp -f {tpl['nvram']} {target_nvram}")

        # Step 4: Generate .vmx file from template
        logger.info("[Step 2/5] Synthesizing customized .vmx configuration with static IP...")
        code, vmtx_content, _ = self.run_cmd(f"cat {tpl['vmtx']}")
        if code != 0 or not vmtx_content:
            logger.error("Failed to read template .vmtx: %s", tpl['vmtx'])
            return False

        # Transform template vmtx into target vmx
        vmx_lines = []
        has_numvcpus = False
        has_memsize = False
        for line in vmtx_content.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            # Update display name
            if line_str.startswith("displayName"):
                vmx_lines.append(f'displayName = "{target_name}"')
            # Update memory size (default 16GB)
            elif line_str.startswith("memSize"):
                vmx_lines.append(f'memSize = "{ram_mib}"')
                has_memsize = True
            # Update vCPU count (default 4)
            elif line_str.startswith("numvcpus"):
                vmx_lines.append(f'numvcpus = "{cpus}"')
                has_numvcpus = True
            # Point to the new cloned vmdk
            elif "scsi0:0.fileName" in line_str:
                vmx_lines.append(f'scsi0:0.fileName = "{target_name}.vmdk"')
            # Point to new nvram
            elif "nvram" in line_str and "=" in line_str:
                vmx_lines.append(f'nvram = "{target_name}.nvram"')
            # Ensure addressType is generated for ESXi automatic MAC assignment
            elif "ethernet0.addressType" in line_str:
                vmx_lines.append('ethernet0.addressType = "generated"')
            # Reset MAC and UUID generation so ESXi creates fresh unique hardware IDs
            elif any(k in line_str for k in ["generatedAddress", "uuid.bios", "uuid.location", "sched.swap.derivedName", "guestinfo."]):
                continue
            else:
                vmx_lines.append(line_str)

        if not has_numvcpus:
            vmx_lines.append(f'numvcpus = "{cpus}"')
        if not has_memsize:
            vmx_lines.append(f'memSize = "{ram_mib}"')

        # Inject auto-UUID generation directives
        vmx_lines.append('uuid.action = "create"')
        vmx_lines.append('mem.hotadd = "TRUE"')
        vmx_lines.append('vcpu.hotadd = "TRUE"')

        # Inject VMware Native Static IP via guestinfo metadata (Direct Hypervisor Method)
        net_yaml = f"""instance-id: {target_name.lower()}
local-hostname: {target_name.lower()}
network:
  version: 2
  ethernets:
    ens33:
      dhcp4: false
      dhcp6: false
      addresses:
        - {target_ip}/24
      gateway4: 192.168.1.1
      nameservers:
        addresses:
          - 8.8.8.8
          - 1.1.1.1
    Ethernet0:
      dhcp4: false
      dhcp6: false
      addresses:
        - {target_ip}/24
      gateway4: 192.168.1.1
      nameservers:
        addresses:
          - 8.8.8.8
          - 1.1.1.1
"""
        import base64
        meta_b64 = base64.b64encode(net_yaml.encode("utf-8")).decode("ascii")
        vmx_lines.append(f'guestinfo.metadata = "{meta_b64}"')
        vmx_lines.append('guestinfo.metadata.encoding = "base64"')
        vmx_lines.append(f'guestinfo.userdata = "{meta_b64}"')
        vmx_lines.append('guestinfo.userdata.encoding = "base64"')
        vmx_lines.append(f'guestinfo.interface.0.ip.0.address = "{target_ip}/24"')
        vmx_lines.append('guestinfo.interface.0.route.0.gateway = "192.168.1.1"')
        vmx_lines.append('guestinfo.dns.servers = "8.8.8.8,1.1.1.1"')

        new_vmx_content = "\n".join(vmx_lines) + "\n"

        # Write to ESXi target via SFTP (robust and native on ESXi)
        if not self._ssh:
            if not self.connect() or not self._ssh:
                raise ConnectionError("Not connected to ESXi host")
        sftp = self._ssh.open_sftp()
        with sftp.file(target_vmx, "w") as f:
            f.write(new_vmx_content)
        sftp.close()

        # Step 5: Register VM in ESXi
        logger.info("[Step 3/5] Registering VM on ESXi hypervisor...")
        time.sleep(1)
        code, reg_out, reg_err = self.run_cmd(f"vim-cmd solo/registervm {target_vmx} {target_name}")
        if code != 0:
            logger.error("Failed to register VM: %s %s", reg_out, reg_err)
            return False

        vmid = reg_out.strip()
        logger.info(" [+] VM '%s' successfully registered with VMID: %s", target_name, vmid)

        # Step 6: Power on VM
        time.sleep(2)
        logger.info("[Step 4/5] Powering on VM %s (VMID %s)...", target_name, vmid)
        code, pwr_out, pwr_err = self.run_cmd(f"vim-cmd vmsvc/power.on {vmid}")
        if code != 0:
            logger.warning("Power on returned code %d: %s %s", code, pwr_out, pwr_err)

        time.sleep(3)
        state = self.get_vm_power_state(vmid)
        logger.info("[Step 5/5] Deployment Complete! VM '%s' state: %s", target_name, state)
        return True

    def destroy_vm(self, vm_name: str, purge_datastore: bool = True) -> bool:
        """
        Completely stop, unregister, and optionally purge VM disk files from datastore.
        SAFETY GUARD: Refuses to destroy protected master templates or infrastructure VMs.
        """
        if is_protected(vm_name):
            logger.error("SAFETY GUARD: Refusing to destroy protected asset '%s'! Master templates are immutable.", vm_name)
            return False

        logger.info("=== Safely Destroying Fleet VM: %s ===", vm_name)
        matching = [v for v in self.list_vms() if v["name"].lower() == vm_name.lower()]
        for v in matching:
            vmid = v["vmid"]
            logger.info("Powering off VM %s (VMID %s)...", vm_name, vmid)
            self.power_off_vm(vmid)
            time.sleep(1)
            logger.info("Unregistering VM %s from hypervisor...", vmid)
            self.run_cmd(f"vim-cmd vmsvc/unregister {vmid}")
            self.run_cmd(f"vim-cmd vmsvc/destroy {vmid}")
            time.sleep(1)

        if purge_datastore:
            name_lower = vm_name.lower()
            if (name_lower in ["rhel10", "rhel9", "win2025", "win2019"] or name_lower.startswith(("rhel", "win"))) and not is_protected(vm_name):
                logger.info("Purging fleet VM directory from Base_DS: %s", vm_name)
                path = f"/vmfs/volumes/Base_DS/{vm_name}"
                self.run_cmd(f"rm -rf {path}")
            else:
                logger.warning("Skipping datastore purge for non-fleet name '%s'", vm_name)

        # Clean from vCenter inventory to eliminate orphaned entries
        try:
            from infrastructure.vcenter_manager import VCenterManager
            vcm = VCenterManager()
            if vcm.connect():
                vc_vm = vcm.find_vm_by_name(vm_name)
                if vc_vm:
                    vcm.delete_vm(vc_vm["vm"])
                vcm.clean_orphaned_vms()
        except Exception as e:
            logger.debug("vCenter unregister fallback: %s", e)

        logger.info(" [+] Fleet VM %s successfully destroyed and cleaned.", vm_name)
        return True

    def clean_fleet(self) -> bool:
        """
        Safe infrastructure teardown:
        Stops, unregisters, and purges ONLY the 4 managed fleet VMs:
        - RHEL10
        - RHEL9
        - Win2025
        - Win2019
        NEVER touches master templates, datastores, or core infrastructure.
        """
        fleet_vms = ["RHEL10", "RHEL9", "Win2025", "Win2019"]
        logger.info("=================================================================")
        logger.info("   AIST: Safe Fleet Teardown (Preserving All Master Templates)")
        logger.info("=================================================================")
        for vm in fleet_vms:
            logger.info("Safely cleaning fleet VM: %s", vm)
            self.destroy_vm(vm, purge_datastore=True)
        return True

    def setup_fleet(self, force_recreate: bool = False, cpus: int = 4, ram_gb: int = 16) -> bool:
        """
        Full Infrastructure Automation:
        1. Identifies master templates on Base_DS / vCenter.
        2. Clones/provisions the 4 multi-OS fleet VMs (RHEL10, RHEL9, Win2025, Win2019):
           - Configures 4 vCPUs and 16 GB RAM (16384 MiB) on each VM.
           - Sets up on high-speed Base_DS storage (thin-provisioned).
           - Injects direct static IP metadata.
        3. Powers on all VMs.
        4. Applies direct static IP network assignment (no DHCP hang).
        5. Applies firewall rules across all OS nodes for mutual communication.
        6. Verifies complete network reachability.
        """
        logger.info("=================================================================")
        logger.info("   AIST: Automated Infrastructure & VM Fleet Setup")
        logger.info("   Target Datastore: %s | vCPUs: %d | RAM: %d GB", DATASTORE_TARGET, cpus, ram_gb)
        logger.info("=================================================================")

        # Step 1: Discover & Validate Master Templates
        logger.info("\n--- [Stage 1/5] Identifying Master VM Templates on Base_DS ---")
        templates = self.discover_templates()
        required_templates = ["rhel10", "rhel9", "win2025", "win2019"]
        missing = [k for k in required_templates if k not in templates]
        if missing:
            logger.error("Missing required master templates: %s", missing)
            return False
        for k, tpl in templates.items():
            logger.info(" [+] Discovered Template [%s]: %s (OS: %s)", k, tpl["name"], tpl["os_type"])

        # Step 2: Provision Fleet VMs
        logger.info("\n--- [Stage 2/5] Provisioning Fleet VMs (%d vCPUs, %d GB RAM each) ---", cpus, ram_gb)
        fleet = [
            ("rhel10", "RHEL10", ram_gb * 1024, cpus, RHEL10_IP),
            ("rhel9", "RHEL9", ram_gb * 1024, cpus, RHEL9_IP),
            ("win2025", "Win2025", ram_gb * 1024, cpus, WIN2025_IP),
            ("win2019", "Win2019", ram_gb * 1024, cpus, WIN2019_IP),
        ]

        for tpl_key, name, ram_mib, num_cpus, ip in fleet:
            existing = self.find_vm_by_name(name)
            if existing and not force_recreate:
                logger.info(" -> VM '%s' already exists (VMID: %s, Power: %s).", name, existing["vmid"], existing.get("power_state"))
                if existing.get("power_state") != "POWERED_ON":
                    logger.info("    Powering on %s...", name)
                    self.power_on_vm(existing["vmid"])
            else:
                if existing and force_recreate:
                    logger.info("Recreating existing VM '%s'...", name)
                    self.destroy_vm(name, purge_datastore=True)
                logger.info("Cloning fresh instance of %s from template %s (%d vCPUs, %d MiB RAM)...", name, tpl_key, num_cpus, ram_mib)
                ok = self.clone_from_template(tpl_key, name, ram_mib=ram_mib, cpus=num_cpus, target_ds=DATASTORE_TARGET, ip_address=ip)
                if not ok:
                    logger.error("Failed to clone VM %s", name)
                    return False

        # Step 3: Wait for VM Boot & Guest Initialization
        logger.info("\n--- [Stage 3/5] Waiting for Guest OS Initialization ---")
        time.sleep(10)

        # Step 4: Configure Direct Static IPs
        logger.info("\n--- [Stage 4/5] Binding Direct Static IPs (No DHCP Reliance) ---")
        try:
            from infrastructure.assign_static_ips import configure_linux_static, configure_windows_static
            configure_linux_static("RHEL10", RHEL10_IP)
            configure_linux_static("RHEL9", RHEL9_IP)
            configure_windows_static("Win2025", WIN2025_IP)
            configure_windows_static("Win2019", WIN2019_IP)
        except Exception as e:
            logger.warning("Static IP binding notice: %s", e)

        # Step 5: Configure Bidirectional Firewalls
        logger.info("\n--- [Stage 5/5] Configuring Multi-OS Firewalls for Inter-Node Communication ---")
        try:
            from infrastructure.firewall_config import setup_all_firewalls
            fw_ok = setup_all_firewalls()
            logger.info("Firewall rules applied: %s", "SUCCESS" if fw_ok else "PARTIAL")
        except Exception as e:
            logger.warning("Firewall configuration notice: %s", e)

        # Final Verification
        logger.info("\n=== Infrastructure Setup Complete ===")
        all_reachable = True
        for name, ip, port in [
            ("RHEL 10", RHEL10_IP, 22),
            ("RHEL 9", RHEL9_IP, 22),
            ("Win 2025", WIN2025_IP, 5985),
            ("Win 2019", WIN2019_IP, 5985),
        ]:
            from infrastructure.assign_static_ips import is_ip_reachable
            ok = is_ip_reachable(ip, port, timeout=3.0)
            status = "REACHABLE (OK)" if ok else "UNREACHABLE (WAITING)"
            if not ok:
                all_reachable = False
            logger.info(" - %-10s [%s:%d]: %s", name, ip, port, status)

        return all_reachable

    def restore_fleet(self) -> bool:
        """
        Disaster Recovery Procedure:
        Restores the entire AIST Multi-OS Fleet (RHEL10, RHEL9, Win2025, Win2019)
        with 16 GB RAM and 4 vCPUs each from master templates.
        """
        logger.info("=================================================================")
        logger.info("   AIST: Master Disaster Recovery & Fleet Restore Starting")
        logger.info("=================================================================")
        fleet = [
            ("rhel10", "RHEL10", 16384, 4),
            ("rhel9", "RHEL9", 16384, 4),
            ("win2019", "Win2019", 16384, 4),
            ("win2025", "Win2025", 16384, 4),
        ]
        results = {}
        for tpl_key, name, ram, cpus in fleet:
            logger.info("\n--- Restoring %s (Template: %s, RAM: %d MiB, vCPUs: %d) ---", name, tpl_key, ram, cpus)
            # Destroy old if present
            self.destroy_vm(name, purge_datastore=True)
            # Clone fresh
            ok = self.clone_from_template(tpl_key, name, ram_mib=ram, cpus=cpus, target_ds="Base_DS")
            results[name] = ok

        all_ok = all(results.values())
        logger.info("\n=== Fleet Restore Summary ===")
        for vm, ok in results.items():
            logger.info(" - %-12s: %s", vm, "SUCCESS" if ok else "FAILED")
        return all_ok

    def scale_horizontal(self, template_key: str, count: int = 1, ram_mib: int = 16384) -> List[str]:
        """
        Horizontally scale additional worker nodes (e.g., RHEL10-Worker-01, RHEL10-Worker-02).
        """
        scaled_vms = []
        tpl_key = template_key.lower().replace("-", "").replace("_", "")
        prefix = f"{tpl_key.upper()}-Worker"
        existing_vms = [v["name"] for v in self.list_vms()]

        created = 0
        idx = 1
        while created < count and idx < 100:
            target_name = f"{prefix}-{idx:02d}"
            idx += 1
            if target_name in existing_vms:
                continue
            logger.info("Scaling out new instance: %s", target_name)
            ok = self.clone_from_template(tpl_key, target_name, ram_mib=ram_mib)
            if ok:
                scaled_vms.append(target_name)
                created += 1

        logger.info("Scaled out %d instances: %s", len(scaled_vms), scaled_vms)
        return scaled_vms


def main():
    parser = argparse.ArgumentParser(description="AIST Direct ESXi VM Lifecycle & DR Automation Engine")
    subparsers = parser.add_subparsers(dest="action", help="Action to execute")

    # List VMs
    subparsers.add_parser("list", help="List all registered VMs and their power states")

    # Templates
    subparsers.add_parser("templates", help="List all available VM templates")

    # Clone / Create
    create_parser = subparsers.add_parser("create", help="Create / Clone a new VM from template")
    create_parser.add_argument("--template", required=True, help="Template key: rhel10, rhel9, win2019, win2025")
    create_parser.add_argument("--name", required=True, help="Target virtual machine name")
    create_parser.add_argument("--ip", default=None, help="Static IP address to assign directly without DHCP")
    create_parser.add_argument("--ram", type=int, default=16, help="RAM in GB (default: 16)")
    create_parser.add_argument("--cpus", type=int, default=4, help="vCPU count (default: 4)")
    create_parser.add_argument("--datastore", default="Base_DS", help="Target datastore (default: Base_DS)")

    # Setup Fleet (Full Infrastructure)
    setup_parser = subparsers.add_parser("setup", help="Automated setup: clone templates to 4 VMs (4 vCPUs, 16GB RAM), bind IPs, configure firewalls")
    setup_parser.add_argument("--force", action="store_true", help="Force recreate existing VMs")

    # Clean Fleet (Safe Teardown)
    subparsers.add_parser("clean", help="Safe teardown: delete only the 4 fleet VMs, preserving templates")

    # Destroy
    destroy_parser = subparsers.add_parser("destroy", help="Destroy a VM and remove files")
    destroy_parser.add_argument("--name", required=True, help="Target virtual machine name")

    # Restore Fleet
    subparsers.add_parser("restore-fleet", help="Disaster recovery: Rebuild all 4 AIST VMs from templates")

    # Scale
    scale_parser = subparsers.add_parser("scale", help="Horizontally scale out worker VMs")
    scale_parser.add_argument("--template", required=True, help="Template key: rhel10, rhel9, win2019, win2025")
    scale_parser.add_argument("--count", type=int, default=1, help="Number of instances to create")
    scale_parser.add_argument("--ram", type=int, default=16, help="RAM in GB per instance (default: 16)")

    args = parser.parse_args()

    prov = ESXiProvisioner()
    if not prov.connect():
        sys.exit(1)

    try:
        if args.action == "list":
            vms = prov.list_vms()
            print(f"\nRegistered Virtual Machines on ESXi ({ESXI_HOST}):")
            print(f"{'VMID':<8} {'NAME':<18} {'POWER STATE':<14} {'GUEST OS':<24} {'VMX PATH'}")
            print("-" * 80)
            for vm in vms:
                state = prov.get_vm_power_state(vm['vmid'])
                print(f"{vm['vmid']:<8} {vm['name']:<18} {state:<14} {vm['guest_os']:<24} {vm['vmx_path']}")

        elif args.action == "templates":
            print(f"\nAvailable AIST Master VM Templates on ESXi:")
            print(f"{'KEY':<10} {'TEMPLATE NAME':<20} {'DATASTORE':<12} {'OS TYPE':<24} {'DEFAULT IP'}")
            print("-" * 80)
            for k, t in TEMPLATES.items():
                print(f"{k:<10} {t['name']:<20} {t['datastore']:<12} {t['os_type']:<24} {t['default_ip']}")

        elif args.action == "create":
            ram_mib = args.ram * 1024
            prov.clone_from_template(args.template, args.name, ram_mib=ram_mib, cpus=args.cpus, target_ds=args.datastore, ip_address=args.ip)

        elif args.action in ["setup", "setup-fleet"]:
            prov.setup_fleet(force_recreate=getattr(args, "force", False), cpus=4, ram_gb=16)

        elif args.action in ["clean", "clean-fleet"]:
            prov.clean_fleet()

        elif args.action == "destroy":
            prov.destroy_vm(args.name)

        elif args.action == "restore-fleet":
            prov.restore_fleet()

        elif args.action == "scale":
            ram_mib = args.ram * 1024
            prov.scale_horizontal(args.template, count=args.count, ram_mib=ram_mib)

        else:
            parser.print_help()

    finally:
        prov.close()


if __name__ == "__main__":
    main()

