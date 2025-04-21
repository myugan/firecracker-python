import os
import urllib.request
from dataclasses import dataclass


@dataclass
class MicroVMConfig:
    """Configuration defaults for Firecracker microVMs."""
    data_path: str = "/var/lib/firecracker"
    binary_path: str = "/usr/local/bin/firecracker"
    kernel_file: str = os.path.join(data_path, "vmlinux-5.10.225")
    base_rootfs: str = f"{data_path}/rootfs.img"
    ip_addr: str = "172.16.0.2"
    bridge: bool = False
    bridge_name: str = "docker0"
    mmds_enabled: bool = False
    mmds_ip: str = "169.254.169.254"
    vcpu_count: int = 1
    mem_size_mib: int = 512
    hostname: str = "fc-vm"
    verbose: bool = False
    level: str = "INFO"
    ssh_user: str = "root"
    port_forwarding: bool = False
    host_port: int = None
    dest_port: int = None
    enable_nat: bool = False
    user_data: str = None  # Cloud-init user data

    def __post_init__(self):
        """Initialize paths and download kernel if needed."""
        os.makedirs(self.data_path, exist_ok=True)

        if not os.path.exists(self.kernel_file):
            kernel_url = "https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.11/x86_64/vmlinux-5.10.225"
            try:
                print(f"Downloading kernel from {kernel_url}...")
                urllib.request.urlretrieve(kernel_url, self.kernel_file)
                print(f"Kernel downloaded to {self.kernel_file}")
            except Exception:
                raise RuntimeError(f"Error: Failed to download kernel from {kernel_url}")
