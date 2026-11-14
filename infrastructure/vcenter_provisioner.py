#!/usr/bin/env python3
"""
================================================================================
  AIST: vCenter Native Automated VM Provisioning & Disaster Recovery Engine
  Native vSphere API: Clone, Scale, Destroy, and Restore via vCenter
================================================================================
Key Advantages:
  1. 100% native vCenter SOAP API (CloneVM_Task) via pyVmomi.
  2. Master templates are NEVER touched, converted, renamed, or deleted.
  3. All VMs provisioned with 4 vCPUs, 16 GB RAM (16384 MiB) thin-provisioned on Base_DS.
  4. Horizontal scaling: Dynamically clone worker VMs (e.g. RHEL10-Worker-01).
  5. Multi-layer safety guard preventing accidental deletion of templates or core infrastructure.
================================================================================
"""

import os
import sys
import time
import ssl
import logging
from typing import Any, Dict, List, Optional, Tuple, cast
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import (
    VCENTER_HOST, VCENTER_USER, VCENTER_PASS,
    DATASTORE_TARGET,
    RHEL10_IP, RHEL9_IP, WIN2025_IP, WIN2019_IP
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("vcenter_provisioner")

# Protected infrastructure objects and templates that MUST NEVER be destroyed or modified
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


# Canonical Master Template Mapping
TEMPLATES = {
    "rhel10": {
        "name": "RHEL10_Template",
        "default_name": "RHEL10",
        "default_ip": RHEL10_IP,
        "os_type": "rhel9-64",
        "datastore": "Base_DS"
    },
    "rhel9": {
        "name": "RHEL9_Template",
        "default_name": "RHEL9",
        "default_ip": RHEL9_IP,
        "os_type": "rhel9-64",
        "datastore": "Base_DS"
    },
    "win2019": {
        "name": "Win2019_Template",
        "default_name": "Win2019",
        "default_ip": WIN2019_IP,
        "os_type": "windows2019srv_64Guest",
        "datastore": "Base_DS"
    },
    "win2025": {
        "name": "Win2025_Template",
        "default_name": "Win2025",
        "default_ip": WIN2025_IP,
        "os_type": "windows2022srvNext_64Guest",
        "datastore": "Base_DS"
    }
}


class VCenterProvisioner:
    """Native VMware vCenter 8.0 Management & Fast Cloning Engine."""

    def __init__(self, host=VCENTER_HOST, user=VCENTER_USER, password=VCENTER_PASS):
        self.host = host
        self.user = user
        self.password = password
        self.si: Optional[vim.ServiceInstance] = None
        self.content: Optional[vim.ServiceInstanceContent] = None

    def connect(self) -> bool:
        """Authenticate directly to vCenter Server via vSphere Web Services API."""
        try:
            s_ctx = ssl._create_unverified_context()
            self.si = SmartConnect(host=self.host, user=self.user, pwd=self.password, sslContext=s_ctx)
            if self.si:
                self.content = self.si.RetrieveContent()
            logger.info("Connected directly to vCenter Server at %s", self.host)
            return True
        except Exception as e:
            logger.error("Failed to connect to vCenter at %s: %s", self.host, e)
            return False

    def close(self):
        """Disconnect session."""
        if self.si:
            try:
                Disconnect(self.si)
            except Exception:
                pass
            self.si = None
            self.content = None

    def _ensure_connected(self) -> vim.ServiceInstanceContent:
        if not self.si or not self.content:
            if not self.connect() or not self.content:
                raise ConnectionError(f"Cannot connect to vCenter at {self.host}")
        assert self.content is not None
        return self.content

    def wait_for_task(self, task: Any, description: str = "Task", timeout_sec: int = 600) -> Tuple[bool, str]:
        """Wait for a vSphere Task to finish with progress reporting."""
        t0 = time.time()
        last_pct = -1
        while task.info.state in [vim.TaskInfo.State.running, vim.TaskInfo.State.queued]:
            pct = task.info.progress or 0
            if pct != last_pct and pct > 0:
                logger.info(" -> %s progress: %d%%", description, pct)
                last_pct = pct
            time.sleep(2)
            if time.time() - t0 > timeout_sec:
                return False, f"Timeout after {timeout_sec}s waiting for {description}"

        if task.info.state == vim.TaskInfo.State.success:
            return True, "SUCCESS"
        else:
            err = task.info.error.msg if task.info.error else "Unknown error"
            return False, err

    def get_datacenter(self) -> vim.Datacenter:
        content = self._ensure_connected()
        return cast(vim.Datacenter, content.rootFolder.childEntity[0])

    def get_vm_folder(self) -> vim.Folder:
        return self.get_datacenter().vmFolder

    def get_datastore(self, ds_name="Base_DS") -> Optional[vim.Datastore]:
        dc = self.get_datacenter()
        for ds in dc.datastore:
            if ds.name.lower() == ds_name.lower():
                return ds
        return None

    def get_resource_pool(self) -> Any:
        dc = self.get_datacenter()
        host_folder: Any = dc.hostFolder
        for child in host_folder.childEntity:
            rp = getattr(child, "resourcePool", None)
            if rp is not None and not callable(rp):
                return rp
            hosts = getattr(child, "host", None)
            if hosts and hasattr(hosts, "__getitem__") and len(hosts) > 0:
                return getattr(hosts[0].parent, "resourcePool", None)
        return None

    def list_all_entities(self) -> List[vim.VirtualMachine]:
        """Retrieve all virtual machine and template objects."""
        content = self._ensure_connected()
        assert content.viewManager is not None
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        vms = list(container.view)
        container.Destroy()
        return cast(List[vim.VirtualMachine], vms)

    def list_templates(self) -> List[Dict]:
        """List all master VM templates registered in vCenter."""
        all_vms = self.list_all_entities()
        templates = []
        for v in all_vms:
            if v.config and v.config.template:
                templates.append({
                    "name": v.name,
                    "id": v._moId,
                    "guest_os": v.config.guestId if v.config else "unknown",
                    "num_cpus": v.config.hardware.numCPU if v.config else 0,
                    "ram_mb": v.config.hardware.memoryMB if v.config else 0
                })
        return templates

    def list_vms(self) -> List[Dict]:
        """List all active virtual machines (excluding templates)."""
        all_vms = self.list_all_entities()
        result = []
        for v in all_vms:
            if v.config and not v.config.template:
                ip = v.guest.ipAddress if v.guest else None
                power = str(v.runtime.powerState) if v.runtime else "unknown"
                result.append({
                    "name": v.name,
                    "id": v._moId,
                    "power_state": power.replace("poweredOn", "POWERED_ON").replace("poweredOff", "POWERED_OFF"),
                    "num_cpus": v.config.hardware.numCPU if v.config else 0,
                    "ram_mb": v.config.hardware.memoryMB if v.config else 0,
                    "ip_address": ip
                })
        return result

    def find_vm_by_name(self, name: str) -> Optional[vim.VirtualMachine]:
        """Locate VM or template object by name."""
        all_vms = self.list_all_entities()
        for v in all_vms:
            if v.name.lower() == name.lower():
                return v
        return None

    def power_on_vm(self, vm_name: str) -> bool:
        """Power on virtual machine."""
        vm = self.find_vm_by_name(vm_name)
        if not vm or not vm.runtime:
            logger.error("VM %s not found", vm_name)
            return False
        if str(vm.runtime.powerState) == "poweredOn":
            logger.info("VM %s is already powered on.", vm_name)
            return True
        logger.info("Powering on VM %s...", vm_name)
        power_on_func = getattr(vm, "PowerOnVM_Task")
        task = power_on_func()
        ok, msg = self.wait_for_task(task, f"Power on {vm_name}")
        return ok

    def power_off_vm(self, vm_name: str) -> bool:
        """Power off virtual machine."""
        vm = self.find_vm_by_name(vm_name)
        if not vm or not vm.runtime:
            return True
        if str(vm.runtime.powerState) == "poweredOff":
            return True
        logger.info("Powering off VM %s...", vm_name)
        try:
            power_off_func = getattr(vm, "PowerOffVM_Task")
            task = power_off_func()
            ok, msg = self.wait_for_task(task, f"Power off {vm_name}", timeout_sec=60)
            return ok
        except Exception as e:
            logger.warning("Power off warning on %s: %s", vm_name, e)
            return True

    def submit_clone_task(
        self,
        template_key: str,
        target_name: str,
        ram_mib: int = 16384,
        cpus: int = 4,
        target_ds: str = "Base_DS",
        power_on: bool = True
    ) -> Optional[Tuple[Any, str, str, float]]:
        """
        Native vCenter Asynchronous Fast Clone Submission:
        Submits CloneVM_Task to vCenter immediately without blocking.
        Returns: (task, template_name, target_name, start_time)
        """
        self._ensure_connected()
        tpl_key = template_key.lower().replace("-", "").replace("_", "")

        # Resolve template object
        target_tpl_name = None
        if tpl_key in TEMPLATES:
            target_tpl_name = TEMPLATES[tpl_key]["name"]
        else:
            for k, tpl_info in TEMPLATES.items():
                if tpl_info["name"].lower() == template_key.lower():
                    target_tpl_name = tpl_info["name"]
                    break

        if not target_tpl_name:
            target_tpl_name = template_key

        tpl_vm = self.find_vm_by_name(target_tpl_name)
        if not tpl_vm:
            logger.error("Master template '%s' not found in vCenter inventory!", target_tpl_name)
            return None

        # Datastore & Pool resolution
        ds = self.get_datastore(target_ds)
        if not ds:
            logger.error("Target datastore '%s' not found in datacenter!", target_ds)
            return None

        pool = self.get_resource_pool()
        if not pool:
            logger.error("Resource pool not found!")
            return None

        # Build RelocateSpec (preserves native thin-provisioned format)
        relospec = vim.vm.RelocateSpec()
        relospec.datastore = ds
        relospec.pool = pool

        # Build ConfigSpec (vCPUs and RAM)
        configspec = vim.vm.ConfigSpec()
        configspec.numCPUs = cpus
        configspec.memoryMB = ram_mib

        # Build CloneSpec
        clonespec = vim.vm.CloneSpec()
        clonespec.location = relospec
        clonespec.config = configspec
        clonespec.powerOn = power_on
        clonespec.template = False

        # Execute async CloneVM_Task
        vm_folder = self.get_vm_folder()
        t0 = time.time()
        logger.info(" [->] Submitting parallel CloneVM_Task: %-18s -> %-10s (%d vCPUs, %d GB RAM on %s)...", 
                    tpl_vm.name, target_name, cpus, ram_mib // 1024, target_ds)
        task = tpl_vm.Clone(folder=vm_folder, name=target_name, spec=clonespec)
        return (task, tpl_vm.name, target_name, t0)

    def wait_for_tasks_parallel(self, task_map: Dict[str, Tuple[Any, str, str, float]], timeout_sec: int = 900) -> bool:
        """
        Polls multiple concurrent vCenter tasks, displaying synchronized live progress.
        """
        if not task_map:
            return True

        pending = dict(task_map)
        last_progress = {name: -1 for name in pending}
        t_start = time.time()

        while pending:
            if time.time() - t_start > timeout_sec:
                logger.error(" [!] Timeout waiting for parallel vCenter tasks: %s", list(pending.keys()))
                return False

            time.sleep(2)
            for name, (task, src_name, target_name, t0) in list(pending.items()):
                try:
                    state = task.info.state
                    prog = task.info.progress if task.info.progress is not None else 0

                    if prog != last_progress[name]:
                        last_progress[name] = prog
                        logger.info("  [%s] Clone Progress: %d%%", name, prog)

                    if state == vim.TaskInfo.State.success:
                        elapsed = time.time() - t0
                        logger.info("  [+] VM '%s' cloned & provisioned successfully in %.1f seconds!", name, elapsed)
                        del pending[name]
                    elif state == vim.TaskInfo.State.error:
                        err_msg = task.info.error.msg if task.info and task.info.error else "Unknown vCenter error"
                        logger.error("  [!] Failed to clone VM '%s': %s", name, err_msg)
                        return False
                except Exception:
                    pass

        return True

    def clone_from_template(
        self,
        template_key: str,
        target_name: str,
        ram_mib: int = 16384,
        cpus: int = 4,
        target_ds: str = "Base_DS",
        power_on: bool = True
    ) -> bool:
        """
        Native vCenter Fast Cloning Engine:
        1. Clones directly from template using vCenter CloneVM_Task.
        2. Configures thin-provisioned virtual disks on Base_DS.
        3. Configures 4 vCPUs and 16 GB RAM (16384 MiB).
        4. Generates unique BIOS UUID, instance UUID, and MAC address.
        5. Master template is 100% UNTOUCHED and preserved as a template.
        """
        task_info = self.submit_clone_task(template_key, target_name, ram_mib=ram_mib, cpus=cpus, target_ds=target_ds, power_on=power_on)
        if not task_info:
            return False
        return self.wait_for_tasks_parallel({target_name: task_info})

    def destroy_vm(self, vm_name: str) -> bool:
        """
        Safely power off and destroy a virtual machine from vCenter and datastore.
        SAFETY GUARD: Refuses to delete protected master templates or infrastructure VMs.
        """
        if is_protected(vm_name):
            logger.error("SAFETY GUARD: Refusing to destroy protected asset '%s'! Master templates are immutable.", vm_name)
            return False

        vm = self.find_vm_by_name(vm_name)
        if not vm:
            logger.info("VM %s is not present in vCenter.", vm_name)
            return True

        if vm.config and vm.config.template:
            logger.error("SAFETY GUARD: VM '%s' is marked as a template! Refusing to destroy.", vm_name)
            return False

        logger.info("=== Safely Destroying VM: %s (%s) ===", vm_name, vm._moId)
        # Power off if running
        self.power_off_vm(vm_name)
        time.sleep(1)

        # Destroy task deletes VM registration and all disk files on datastore cleanly
        logger.info("Deleting VM %s from vCenter and datastore...", vm_name)
        destroy_func = getattr(vm, "Destroy_Task")
        task = destroy_func()
        ok, msg = self.wait_for_task(task, f"Destroy {vm_name}", timeout_sec=120)
        if ok:
            logger.info(" [+] VM %s successfully destroyed and storage reclaimed.", vm_name)
            return True
        else:
            logger.error(" [!] Failed to destroy VM %s: %s", vm_name, msg)
            return False

    def clean_fleet(self) -> bool:
        """
        Safe infrastructure teardown:
        Stops and purges ONLY the 4 managed fleet VMs:
        - RHEL10, RHEL9, Win2025, Win2019 (and any scaled workers)
        NEVER touches master templates, datastores, or core infrastructure.
        """
        logger.info("=================================================================")
        logger.info("   AIST: Safe Fleet Teardown (Preserving All Master Templates)")
        logger.info("=================================================================")
        fleet_vms = ["RHEL10", "RHEL9", "Win2025", "Win2019"]

        # Also find any scaled worker VMs (e.g. RHEL10-Worker-01)
        all_vms = self.list_vms()
        for v in all_vms:
            vname = v["name"]
            if "-worker" in vname.lower() and not is_protected(vname):
                if vname not in fleet_vms:
                    fleet_vms.append(vname)

        for vm in fleet_vms:
            self.destroy_vm(vm)
        return True

    def scale_fleet(self, template_key: str, count: int = 1, ram_gb: int = 16, cpus: int = 4) -> List[str]:
        """
        Horizontally scale additional worker nodes directly from master templates in parallel.
        Example: RHEL10-Worker-01, RHEL10-Worker-02
        """
        tpl_key = template_key.lower().replace("-", "").replace("_", "")
        prefix = f"{tpl_key.upper()}-Worker"

        existing = [v["name"].lower() for v in self.list_vms()]

        created = 0
        idx = 1
        targets = []
        while created < count and idx < 100:
            target_name = f"{prefix}-{idx:02d}"
            if target_name.lower() not in existing:
                targets.append(target_name)
                created += 1
            idx += 1

        if not targets:
            return []

        logger.info("Scaling out %d worker nodes in parallel from template %s: %s...", len(targets), tpl_key, targets)
        tasks = {}
        for target_name in targets:
            task_info = self.submit_clone_task(tpl_key, target_name, ram_mib=ram_gb * 1024, cpus=cpus, target_ds=DATASTORE_TARGET, power_on=True)
            if task_info:
                tasks[target_name] = task_info

        if tasks and self.wait_for_tasks_parallel(tasks):
            return list(tasks.keys())
        return []

    def setup_fleet(self, force_recreate: bool = False, cpus: int = 4, ram_gb: int = 16) -> bool:
        """
        Full Infrastructure Automation via Native vCenter Cloning:
        1. Identifies master templates on vCenter / Base_DS.
        2. Clones/provisions the 4 multi-OS fleet VMs (RHEL10, RHEL9, Win2025, Win2019) IN PARALLEL:
           - 4 vCPUs and 16 GB RAM (16384 MiB) thin-provisioned on Base_DS.
           - Cloned concurrently without touching or altering master templates.
        3. Powers on all VMs.
        4. Injects/binds static IPs concurrently across all 4 nodes.
        5. Configures mutual multi-OS firewall rules concurrently.
        6. Verifies complete network reachability.
        """
        logger.info("=================================================================")
        logger.info("   AIST: Automated Infrastructure & VM Fleet Setup (vCenter Native)")
        logger.info("   Target Datastore: %s | vCPUs: %d | RAM: %d GB (PARALLEL MODE)", DATASTORE_TARGET, cpus, ram_gb)
        logger.info("=================================================================")

        # Step 1: Discover & Validate Master Templates
        logger.info("\n--- [Stage 1/5] Identifying Master VM Templates in vCenter ---")
        templates = self.list_templates()
        tpl_names = {t["name"].lower(): t for t in templates}

        required = [
            ("rhel10", "RHEL10_Template"),
            ("rhel9", "RHEL9_Template"),
            ("win2025", "Win2025_Template"),
            ("win2019", "Win2019_Template")
        ]
        missing = [tpl_name for _, tpl_name in required if tpl_name.lower() not in tpl_names]
        if missing:
            logger.error("Missing required master templates in vCenter: %s", missing)
            return False

        for k, tpl_name in required:
            info = tpl_names[tpl_name.lower()]
            logger.info(" [+] Master Template Verified: %-20s (ID: %s, OS: %s)", info["name"], info["id"], info["guest_os"])

        # Step 2: Provision Fleet VMs in Parallel
        logger.info("\n--- [Stage 2/5] Concurrent Provisioning of Fleet VMs (%d vCPUs, %d GB RAM each) ---", cpus, ram_gb)
        fleet = [
            ("rhel10", "RHEL10", ram_gb * 1024, cpus, RHEL10_IP),
            ("rhel9", "RHEL9", ram_gb * 1024, cpus, RHEL9_IP),
            ("win2025", "Win2025", ram_gb * 1024, cpus, WIN2025_IP),
            ("win2019", "Win2019", ram_gb * 1024, cpus, WIN2019_IP),
        ]

        tasks_to_wait = {}
        for tpl_key, name, ram_mib, num_cpus, ip in fleet:
            existing = self.find_vm_by_name(name)
            if existing and not force_recreate:
                power = str(existing.runtime.powerState) if existing.runtime else "unknown"
                logger.info(" -> VM '%s' already exists (ID: %s, Power: %s).", name, existing._moId, power)
                if existing.runtime and str(existing.runtime.powerState) != "poweredOn":
                    self.power_on_vm(name)
            else:
                if existing and force_recreate:
                    logger.info("Recreating existing VM '%s'...", name)
                    self.destroy_vm(name)

                task_info = self.submit_clone_task(
                    tpl_key, name,
                    ram_mib=ram_mib, cpus=num_cpus,
                    target_ds=DATASTORE_TARGET, power_on=True
                )
                if not task_info:
                    logger.error("Failed to submit clone task for VM %s", name)
                    return False
                tasks_to_wait[name] = task_info

        if tasks_to_wait:
            logger.info("All %d clone tasks submitted to vCenter! Waiting for parallel completion...", len(tasks_to_wait))
            ok = self.wait_for_tasks_parallel(tasks_to_wait)
            if not ok:
                logger.error("One or more parallel VM clone tasks failed!")
                return False

        # Step 3: Wait for Guest OS Initialization
        logger.info("\n--- [Stage 3/5] Waiting for Guest OS Initialization ---")
        time.sleep(15)

        # Step 4: Configure Direct Static IPs Concurrently
        logger.info("\n--- [Stage 4/5] Binding Direct Static IPs (Concurrent Execution) ---")
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from infrastructure.assign_static_ips import configure_linux_static, configure_windows_static

            ip_tasks = [
                ("RHEL10", configure_linux_static, ("RHEL10", RHEL10_IP)),
                ("RHEL9", configure_linux_static, ("RHEL9", RHEL9_IP)),
                ("Win2025", configure_windows_static, ("Win2025", WIN2025_IP)),
                ("Win2019", configure_windows_static, ("Win2019", WIN2019_IP)),
            ]

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(fn, *args): name for name, fn, args in ip_tasks}
                for fut in as_completed(futures):
                    vm_name = futures[fut]
                    try:
                        res = fut.result()
                        logger.info("  [%s] Static IP configuration: %s", vm_name, "SUCCESS" if res else "FAILED")
                    except Exception as e:
                        logger.warning("  [%s] Static IP configuration exception: %s", vm_name, e)
        except Exception as e:
            logger.warning("Static IP binding notice: %s", e)

        # Step 5: Configure Bidirectional Firewalls Concurrently
        logger.info("\n--- [Stage 5/5] Configuring Multi-OS Firewalls for Inter-Node Communication (Concurrent) ---")
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


if __name__ == "__main__":
    prov = VCenterProvisioner()
    if prov.connect():
        print("\nTemplates:")
        for t in prov.list_templates():
            print(f" - {t['name']:<22} ID: {t['id']:<10} OS: {t['guest_os']}")
        print("\nVMs:")
        for v in prov.list_vms():
            print(f" - {v['name']:<22} ID: {v['id']:<10} Power: {v['power_state']:<12} IP: {v['ip_address']}")
        prov.close()
