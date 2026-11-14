"""
vCenter & ESXi Automation Engine for AIST
Provides helper functions for VM lifecycle, cloning, power state, and guest inspection
via VMware vCenter REST API.
"""

import json
import logging
import os
import sys
import urllib3
import requests
from typing import Any, Dict, List, Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("vcenter_manager")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from config import VCENTER_HOST, VCENTER_USER, VCENTER_PASS, DATASTORE_TARGET
except ImportError:
    VCENTER_HOST = os.environ.get("VCENTER_HOST", "192.168.1.220")
    VCENTER_USER = os.environ.get("VCENTER_USER", "Administrator@vsphere.local")
    VCENTER_PASS = os.environ.get("VCENTER_PASS", "Root@123")
    DATASTORE_TARGET = os.environ.get("DATASTORE_TARGET", "Base_DS")
BASE_URL = f"https://{VCENTER_HOST}/api"


PROTECTED_OBJECTS = {
    "rhel10_template", "rhel9_template", "win2019_template", "win2025_template",
    "win2025_template_1", "win11", "ad", "client", "vcs", "san"
}


def is_protected(name: str) -> bool:
    clean = name.strip().lower()
    if clean in PROTECTED_OBJECTS:
        return True
    if "template" in clean:
        return True
    return False


class VCenterManager:
    def __init__(self, host=VCENTER_HOST, user=VCENTER_USER, password=VCENTER_PASS):
        self.host = host
        self.user = user
        self.password = password
        self.base_url = f"https://{self.host}/api"
        self.session_id = None
        self.headers = {"Content-Type": "application/json"}

    def connect(self):
        """Authenticate with vCenter and obtain session token."""
        url = f"{self.base_url}/session"
        try:
            resp = requests.post(
                url,
                auth=(self.user, self.password),
                verify=False,
                timeout=15
            )
            resp.raise_for_status()
            self.session_id = resp.json()
            self.headers["vmware-api-session-id"] = self.session_id
            logger.info("Successfully authenticated to vCenter %s", self.host)
            return True
        except Exception as e:
            logger.error("Authentication to vCenter failed: %s", e)
            return False

    def list_vms(self):
        """List all virtual machines and templates."""
        url = f"{self.base_url}/vcenter/vm"
        resp = requests.get(url, headers=self.headers, verify=False, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_vm_details(self, vm_id):
        """Retrieve detailed hardware and power state of a specific VM."""
        url = f"{self.base_url}/vcenter/vm/{vm_id}"
        resp = requests.get(url, headers=self.headers, verify=False, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def set_power_state(self, vm_id, action="start"):
        """Perform power operations: start, stop, suspend, reset."""
        url = f"{self.base_url}/vcenter/vm/{vm_id}/power?action={action}"
        resp = requests.post(url, headers=self.headers, verify=False, timeout=30)
        resp.raise_for_status()
        logger.info("Executed power action '%s' on VM %s", action, vm_id)
        return True

    def delete_vm(self, vm_id: str) -> bool:
        """Delete/unregister VM cleanly from vCenter inventory with safety guard."""
        try:
            # Safety check: do not delete templates or protected infrastructure
            vms = self.list_vms()
            target_vm = next((v for v in vms if v.get("vm") == vm_id), None)
            if target_vm:
                name = target_vm.get("name", "")
                if is_protected(name):
                    logger.error("SAFETY GUARD: Refusing to delete protected vCenter VM '%s' (%s)!", name, vm_id)
                    return False

            url = f"{self.base_url}/vcenter/vm/{vm_id}"
            resp = requests.delete(url, headers=self.headers, verify=False, timeout=15)
            logger.info("Deleted/unregistered VM %s from vCenter: HTTP %s", vm_id, resp.status_code)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning("Failed to delete VM %s from vCenter: %s", vm_id, e)
            return False

    def clean_orphaned_vms(self) -> List[str]:
        """Detect and remove any orphaned or stale test VMs from vCenter inventory."""
        cleaned = []
        try:
            vms = self.list_vms()
            for vm in vms:
                name = vm.get("name", "")
                vm_id = vm.get("vm", "")
                if "(orphaned)" in name.lower() or "scaletest" in name.lower():
                    logger.info("Cleaning orphaned VM from vCenter: %s (%s)", name, vm_id)
                    if self.delete_vm(vm_id):
                        cleaned.append(name)
        except Exception as e:
            logger.warning("Error cleaning orphaned VMs: %s", e)
        return cleaned

    def list_datastores(self):
        """List all datastores with capacity and free space."""
        url = f"{self.base_url}/vcenter/datastore"
        resp = requests.get(url, headers=self.headers, verify=False, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def list_customization_specs(self):
        """List all registered vSphere Guest Customization Specifications."""
        url = f"{self.base_url}/vcenter/guest/customization-specs"
        resp = requests.get(url, headers=self.headers, verify=False, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def create_customization_spec(
        self,
        name: str,
        ip_address: str,
        gateway: str = "192.168.1.1",
        prefix: int = 24,
        dns_servers: list | None = None,
        os_type: str = "LINUX",
        hostname: str | None = None
    ) -> bool:
        """
        Create a vSphere 8 Customization Specification with Static IP.
        Eliminates DHCP dependency by injecting static IP before guest network initialization.
        """
        dns_servers = dns_servers or ["8.8.8.8", "1.1.1.1"]
        hostname = hostname or name.lower().replace("_", "-")

        if os_type.upper() == "LINUX":
            config_spec = {
                "type": "LINUX_PREP",
                "linux_config": {
                    "domain": "aist.local",
                    "hostname": {"type": "FIXED", "fixed_name": hostname}
                }
            }
        else:
            config_spec = {
                "type": "WINDOWS_PREP",
                "windows_config": {
                    "sysprep": {
                        "gui_unattended": {"auto_logon": False, "auto_logon_count": 1, "time_zone": 85},
                        "user_data": {
                            "computer_name": {"type": "FIXED", "fixed_name": hostname.upper()},
                            "full_name": "Administrator",
                            "organization": "AIST",
                            "product_key": ""
                        }
                    }
                }
            }

        payload = {
            "name": name,
            "description": f"AIST Native Static IP Spec ({ip_address}/{prefix})",
            "spec": {
                "global_DNS_settings": {
                    "dns_servers": dns_servers,
                    "dns_suffix_list": ["aist.local"]
                },
                "interfaces": [
                    {
                        "adapter": {
                            "ipv4": {
                                "type": "STATIC",
                                "ip_address": ip_address,
                                "prefix": prefix,
                                "gateways": [gateway]
                            }
                        }
                    }
                ],
                "configuration_spec": config_spec
            }
        }

        url = f"{self.base_url}/vcenter/guest/customization-specs"
        resp = requests.post(url, headers=self.headers, json=payload, verify=False, timeout=20)
        if resp.status_code in [200, 201]:
            logger.info("Customization spec '%s' (%s) registered in vCenter", name, ip_address)
            return True
        logger.error("Failed to create customization spec: %s %s", resp.status_code, resp.text)
        return False

    def get_guest_identity(self, vm_id: str):
        """Retrieve live Guest OS identity and IP via VMware Tools."""
        url = f"{self.base_url}/vcenter/vm/{vm_id}/guest/identity"
        resp = requests.get(url, headers=self.headers, verify=False, timeout=10)
        return resp.json() if resp.status_code == 200 else None

    def get_guest_interfaces(self, vm_id: str):
        """Retrieve network interfaces and assigned IPs via VMware Tools."""
        url = f"{self.base_url}/vcenter/vm/{vm_id}/guest/networking/interfaces"
        resp = requests.get(url, headers=self.headers, verify=False, timeout=10)
        return resp.json() if resp.status_code == 200 else None

    def list_hosts(self):
        """List ESXi compute hosts."""
        url = f"{self.base_url}/vcenter/host"
        resp = requests.get(url, headers=self.headers, verify=False, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def list_networks(self):
        """List virtual network portgroups."""
        url = f"{self.base_url}/vcenter/network"
        resp = requests.get(url, headers=self.headers, verify=False, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def find_vm_by_name(self, name):
        """Search VM by name."""
        vms = self.list_vms()
        for vm in vms:
            if vm.get("name") == name:
                return vm
        return None


if __name__ == "__main__":
    mgr = VCenterManager()
    if mgr.connect():
        vms = mgr.list_vms()
        print(f"\nFound {len(vms)} VMs on vCenter:")
        for vm in vms:
            print(f" - [{vm.get('vm')}] {vm.get('name'):<15} Power: {vm.get('power_state'):<12} "
                  f"CPUs: {vm.get('cpu_count')} RAM: {vm.get('memory_size_MiB')}MB")
        
        print("\nDatastores:")
        for ds in mgr.list_datastores():
            free_gb = ds.get('free_space', 0) / (1024**3)
            cap_gb = ds.get('capacity', 0) / (1024**3)
            print(f" - [{ds.get('datastore')}] {ds.get('name'):<12} Free: {free_gb:.1f}GB / {cap_gb:.1f}GB")

