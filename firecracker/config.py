import os
from dataclasses import dataclass


@dataclass
class MicroVMConfig:
    """Configuration defaults for Firecracker microVMs."""
    data_path: str = "/var/lib/firecracker"
    binary_path: str = "/usr/local/bin/firecracker"
    kernel_file: str = os.path.join(data_path, "vmlinux")
    initrd_file: str = None
    init_file: str = "/sbin/init"
    base_rootfs: str = None
    overlayfs: bool = False
    overlayfs_file: str = None
    ip_addr: str = "172.16.0.2"
    bridge: bool = False
    bridge_name: str = "docker0"
    mmds_enabled: bool = False
    mmds_ip: str = "169.254.169.254"
    user_data: str = None
    vcpu: int = 1
    memory: int = 512
    hostname: str = "fc-vm"
    verbose: bool = False
    level: str = "INFO"
    ssh_user: str = "root"
    expose_ports: bool = False
    host_port: int = None
    dest_port: int = None