import os
import sys
import tty
import time
import json
import select
import termios
import docker
import tarfile
import tempfile
from http import HTTPStatus
from typing import List, Dict
from firecracker.config import MicroVMConfig
from firecracker.api import Api
from firecracker.logger import Logger
from firecracker.network import NetworkManager
from firecracker.process import ProcessManager
from firecracker.vmm import VMMManager
from firecracker.utils import run, get_public_ip, validate_ip_address, generate_id, generate_name, generate_mac_address
from firecracker.exceptions import VMMError, ConfigurationError
from paramiko import SSHClient, AutoAddPolicy, SSHException
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type


class MicroVM:
    """A class to manage Firecracker microVMs.

    Args:
        id (str, optional): ID for the MicroVM
        name (str, optional): Name for the MicroVM
        kernel_file (str, optional): Path to the kernel file
        kernel_url (str, optional): URL to the kernel file
        initrd_file (str, optional): Path to the initrd file
        init_file (str, optional): Path to the init file
        image (str, optional): Docker image to use for the MicroVM
        base_rootfs (str, optional): Path to the base rootfs file
        rootfs_size (str, optional): Size of the rootfs file
        overlayfs (bool, optional): Whether to use overlayfs
        overlayfs_file (str, optional): Path to the overlayfs file
        vcpu (int, optional): Number of vCPUs
        memory (int, optional): Amount of memory
        ip_addr (str, optional): IP address for the MicroVM
        mmds_enabled (bool, optional): Whether to enable mmds
        mmds_ip (str, optional): IP address for the mmds
        user_data (str, optional): User data for the MicroVM
        user_data_file (str, optional): Path to the user data file
        labels (dict, optional): Labels for the MicroVM
        expose_ports (bool, optional): Whether to expose ports
        host_port (int, optional): Host port to expose
        dest_port (int, optional): Destination port to expose
        verbose (bool, optional): Whether to enable verbose logging
        level (str, optional): Logging level

    Raises:
        ValueError: If the configuration is invalid
        VMMError: If the VMM creation fails
        SSHException: If the SSH connection fails
        ConfigurationError: If the configuration is invalid
        ProcessError: If the process fails
    """
    def __init__(self, name: str = None, kernel_file: str = None, kernel_url: str = None, initrd_file: str = None, init_file: str = None,
                 image: str = None, base_rootfs: str = None, rootfs_size: str = None, overlayfs: bool = False, overlayfs_file: str = None,
                 vcpu: int = None, memory: int = None, ip_addr: str = None,
                 mmds_enabled: bool = None, mmds_ip: str = None, user_data: str = None, user_data_file: str = None,
                 labels: dict = None, expose_ports: bool = False, host_port: int = None, dest_port: int = None,
                 vsock_enabled: bool = False, vsock_guest_cid: int = None, verbose: bool = False, level: str = "INFO") -> None:
        self._microvm_id = generate_id()
        self._microvm_name = generate_name() if name is None else name

        self._config = MicroVMConfig()
        self._config.verbose = verbose
        self._logger = Logger(level=level, verbose=verbose)
        self._logger.set_level(level)

        self._network = NetworkManager(verbose=verbose, level=level)
        self._process = ProcessManager(verbose=verbose, level=level)
        self._vmm = VMMManager(verbose=verbose, level=level)

        self._vcpu = vcpu or self._config.vcpu
        if not isinstance(self._vcpu, int) or self._vcpu <= 0:
            raise ValueError("vcpu must be a positive integer (greater than zero)")
        
        self._memory = int(self._convert_memory_size(memory or self._config.memory))
        self._mmds_enabled = mmds_enabled if mmds_enabled is not None else self._config.mmds_enabled
        self._mmds_ip = mmds_ip or self._config.mmds_ip

        if user_data_file and user_data:
            raise ValueError("Cannot specify both user_data and user_data_file. Use only one of them.")
        if user_data_file:
            if not os.path.exists(user_data_file):
                raise ValueError(f"User data file not found: {user_data_file}")
            with open(user_data_file, 'r') as f:
                self._user_data = f.read()
        else:
            self._user_data = user_data

        self._labels = labels or {}

        self._iface_name = self._network.get_interface_name()
        self._host_dev_name = f"tap_{self._microvm_id}"
        self._mac_addr = generate_mac_address()
        if ip_addr:
            validate_ip_address(ip_addr)
            self._network.detect_cidr_conflict(ip_addr, 24)
            self._ip_addr = ip_addr
        else:
            self._ip_addr = self._config.ip_addr
        self._gateway_ip = self._network.get_gateway_ip(self._ip_addr)

        self._socket_file = f"{self._config.data_path}/{self._microvm_id}/firecracker.socket"
        self._vmm_dir = f"{self._config.data_path}/{self._microvm_id}"
        self._log_dir = f"{self._vmm_dir}/logs"
        self._rootfs_dir = f"{self._vmm_dir}/rootfs"

        self._docker = docker.from_env()
        self._docker_image = image

        if image:
            if not base_rootfs:
                raise ValueError("base_rootfs is required when image is provided")
            if not self._is_valid_docker_image(image):
                raise ValueError(f"Invalid Docker image: {image}")
            self._download_docker(image)

        if kernel_url and kernel_file:
            self._kernel_file = kernel_file
            self._download_kernel(kernel_url, self._kernel_file)
        elif kernel_file:
            self._kernel_file = kernel_file
        elif kernel_url:
            self._kernel_file = None
        elif image:
            self._kernel_file = None
        else:
            self._kernel_file = None

        if initrd_file:
            if not os.path.exists(initrd_file):
                raise FileNotFoundError(f"Initrd file not found: {initrd_file}")
            self._initrd_file = initrd_file
        else:
            self._initrd_file = None

        self._init_file = init_file or self._config.init_file

        if base_rootfs:
            self._base_rootfs = base_rootfs
            base_rootfs_name = os.path.basename(self._base_rootfs.replace('./', ''))
            self._rootfs_file = os.path.join(self._rootfs_dir, base_rootfs_name)

        self._rootfs_size = rootfs_size or self._config.rootfs_size
        self._overlayfs = overlayfs or self._config.overlayfs
        if self._overlayfs:
            self._overlayfs_file = overlayfs_file or os.path.join(self._rootfs_dir, "overlayfs.ext4")
            self._overlayfs_name = os.path.basename(self._overlayfs_file.replace('./', ''))
            self._overlayfs_dir = os.path.join(self._rootfs_dir, self._overlayfs_name)

        self._mem_file_path = f"{self._config.snapshot_path}/{self._microvm_id}/memory"
        self._snapshot_path = f"{self._config.snapshot_path}/{self._microvm_id}/snapshot"

        self._ssh_client = SSHClient()
        self._expose_ports = expose_ports
        self._host_ip = get_public_ip()
        self._host_port = self._parse_ports(host_port)
        self._dest_port = self._parse_ports(dest_port)

        self._vsock_enabled = vsock_enabled or self._config.vsock_enabled
        self._vsock_guest_cid = vsock_guest_cid or self._config.vsock_guest_cid
        self._vsock_uds_path = f"{self._config.data_path}/{self._microvm_id}/v.sock"

        self._api = self._vmm.get_api(self._microvm_id)

    @staticmethod
    def list() -> List[Dict]:
        """List all running Firecracker VMs.

        Returns:
            List[Dict]: List of dictionaries containing VMM details
        """
        vmm_manager = VMMManager()
        return vmm_manager.list_vmm()

    def find(self, state=None, labels=None):
        """Find a VMM by ID or labels.

        Args:
            state (str, optional): State of the VMM to find.
            labels (dict, optional): Labels to filter VMMs by.
        
        Returns:
            str: ID of the found VMM or error message.
        """
        if state:
            return self._vmm.find_vmm_by_labels(state, labels)
        else:
            return "No state provided"

    def config(self, id=None):
        """Get the configuration for the current VMM or a specific VMM.

        Args:
            id (str, optional): ID of the VMM to query. If not provided,
                uses the current VMM's ID.

        Returns:
            dict: Response from the VMM configuration endpoint or error message.
        """
        id = id if id else self._microvm_id
        if not id:
            return "No VMM ID specified for checking configuration"
        return self._vmm.get_vmm_config(id)

    def inspect(self, id=None):
        """Inspect a VMM by ID.

        Args:
            id (str, optional): ID of the VMM to inspect. If not provided,
                uses the current VMM's ID.
        """
        id = id if id else self._microvm_id

        if not id:
            return f"VMM with ID {id} does not exist"

        config_file = f"{self._config.data_path}/{id}/config.json"
        if not os.path.exists(config_file):
            return "VMM ID not exist"

        try:
            with open(config_file, "r") as f:
                config = json.load(f)
                return config
        except Exception as e:
            raise VMMError(f"Failed to inspect VMM {id}: {str(e)}")

    def status(self, id=None):
        """Get the status of the current VMM or a specific VMM.

        Args:
            id (str, optional): ID of the VMM to check. If not provided,
                uses the current VMM's ID.
        """
        id = id if id else self._microvm_id
        if not id:
            return "No VMM ID specified for checking status"
        
        try:
            with open(f"{self._config.data_path}/{id}/config.json", "r") as f:
                config = json.load(f)
                if config['State']['Running']:
                    return f"VMM {id} is running"
                elif config['State']['Paused']:
                    return f"VMM {id} is paused"

        except Exception as e:
            raise VMMError(f"Failed to get status for VMM {id}: {str(e)}")

    def build(self):
        """Build the rootfs from the Docker image.

        Returns:
            str: Status message indicating the result of the build operation.
        """
        try:
            if not self._docker_image:
                return "No Docker image specified for building rootfs"

            self._build_rootfs(self._docker_image, self._base_rootfs, self._rootfs_size)

            return f"Rootfs built at {self._base_rootfs}"

        except Exception as e:
            raise VMMError(f"Failed to build rootfs from Docker image: {str(e)}")

    def create(self, snapshot: bool = False, memory_path: str = None, snapshot_path: str = None) -> dict:
        """Create a new microVM.

        Args:
            snapshot (bool, optional): Whether to create a snapshot of the microVM.
            memory_path (str, optional): Path to the memory file.
            snapshot_path (str, optional): Path to the snapshot file.

        Returns:
            dict: Status message indicating the result of the create operation.
        """
        vmm_dir = f"{self._config.data_path}/{self._microvm_id}"
        if os.path.exists(vmm_dir):
            return f"VMM with ID {self._microvm_id} already exists"

        try:
            if self._kernel_file is None:
                raise ValueError("kernel_file is required when no kernel_url or image is provided")
            if self._base_rootfs is None:
                raise ValueError("base_rootfs is required when no kernel_url or image is provided")

            for file_path, name in [(self._kernel_file, "kernel file"), (self._base_rootfs, "base rootfs")]:
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"{name.capitalize()} not found: {file_path}")

            if self._vmm.check_network_overlap(self._ip_addr):
                return f"IP address {self._ip_addr} is already in use"

            if self._docker_image:
                if not os.path.exists(self._base_rootfs):
                    if self._config.verbose:
                        self._logger.info(f"Building rootfs from Docker image: {self._docker_image}")
                    self._build_rootfs(self._docker_image, self._base_rootfs, self._rootfs_size)

            self._network.setup(
                tap_name=self._host_dev_name,
                iface_name=self._iface_name,
                gateway_ip=self._gateway_ip,
            )

            self._run_firecracker()
            if snapshot:
                if not memory_path or not snapshot_path:
                    raise ValueError("memory_path and snapshot_path are required when snapshot is True")
                self.snapshot(id=self._microvm_id, action="load", memory_path=memory_path, snapshot_path=snapshot_path)
            else:
                self._configure_vmm_boot_source()
                self._configure_vmm_root_drive()
                self._configure_vmm_resources()
                self._configure_vmm_network()
                if self._mmds_enabled:
                    self._configure_vmm_mmds()
                if self._vsock_enabled:
                    self._configure_vmm_vsock()

            self._api.actions.put(action_type="InstanceStart")
            if self._config.verbose:
                self._logger.info(f"VMM {self._microvm_id} started")

            if self._expose_ports:
                if not self._host_port or not self._dest_port:
                    raise ValueError("Port forwarding requested but no ports specified. Both host_port and dest_port must be set.")
                
                ports = self._setup_port_forwarding(self._host_port, self._dest_port, update_config=False)
            else:
                ports = {}

            pid, create_time = self._process.get_pid(self._microvm_id)

            if self._process.is_running(self._microvm_id):
                self._vmm.create_vmm_json_file(
                    id=self._microvm_id,
                    Name=self._microvm_name,
                    CreatedAt=create_time,
                    Rootfs=self._rootfs_file,
                    Kernel=self._kernel_file,
                    Pid=pid,
                    Ports=ports,
                    IPAddress=self._ip_addr,
                    Labels=self._labels
                )
                return f"VMM {self._microvm_id} created"
            else:
                self._vmm.delete_vmm(self._microvm_id)
                return f"VMM {self._microvm_id} failed to create"

        except Exception as e:
            raise VMMError(f"Failed to create VMM {self._microvm_id}: {str(e)}")

        finally:
            self._api.close()

    def pause(self, id=None):
        """Pause the configured microVM.

        Args:
            id (str, optional): ID of the VMM to pause. If not provided,
                uses the current VMM's ID.

        Returns:
            str: Status message indicating the result of the pause operation.

        Raises:
            FirecrackerError: If the pause operation fails.
        """
        try:
            id = id if id else self._microvm_id
            self._vmm.update_vmm_state(id, "Paused")

            config_path = f"{self._config.data_path}/{id}/config.json"
            try:
                with open(config_path, "r+") as file:
                    config = json.load(file)
                    config['State']['Paused'] = "true"
                    file.seek(0)
                    json.dump(config, file)
                    file.truncate()
            except Exception as e:
                raise VMMError(f"Failed to update VMM state: {str(e)}")

            return f"VMM {id} paused successfully"

        except Exception as e:
            raise VMMError(str(e))

    def resume(self, id=None):
        """Resume the configured microVM.

        Args:
            id (str, optional): ID of the VMM to resume. If not provided,
                uses the current VMM's ID.

        Returns:
            str: Status message indicating the result of the resume operation.

        Raises:
            FirecrackerError: If the resume operation fails.
        """
        try:
            id = id if id else self._microvm_id
            self._vmm.update_vmm_state(id, "Resumed")

            config_path = f"{self._config.data_path}/{id}/config.json"
            try:
                with open(config_path, "r+") as file:
                    config = json.load(file)
                    config['State']['Paused'] = "false"
                    file.seek(0)
                    json.dump(config, file)
                    file.truncate()
            except Exception as e:
                raise VMMError(f"Failed to update VMM state: {str(e)}")

            return f"VMM {id} resumed successfully"

        except Exception as e:
            raise VMMError(str(e))

    def delete(self, id=None, all=False) -> str:
        """Delete a specific VMM or all VMMs and clean up associated resources.

        Args:
            id (str, optional): The ID of the VMM to delete. If not provided, the current VMM's ID is used.
            all (bool, optional): If True, delete all running VMMs. Defaults to False.

        Returns:
            str: A status message indicating the result of the deletion operation.

        Raises:
            VMMError: If an error occurs during the deletion process.
        """
        try:
            vmm_list = self._vmm.list_vmm()
            if not vmm_list:
                return "No VMMs available to delete"

            if all:
                for vmm in vmm_list:
                    self._vmm.delete_vmm(vmm['id'])
                return "All VMMs are deleted"

            target_id = id if id else self._microvm_id
            if not target_id:
                return "No VMM ID specified for deletion"

            if target_id not in [vmm['id'] for vmm in vmm_list]:
                return f"VMM with ID {target_id} not found"

            self._vmm.delete_vmm(target_id)
            return f"VMM {target_id} is deleted"

        except Exception as e:
            self._logger.error(f"Error deleting VMM: {str(e)}")
            raise VMMError(str(e))

    def connect(self, id=None, username: str = None, key_path: str = None):
        """Connect to the microVM via SSH.

        Args:
            id (str, optional): ID of the microVM to connect to. If not provided,
                uses the current VMM's ID.
            username (str, optional): SSH username. Defaults to 'root'.
            key_path (str, optional): Path to SSH private key.

        Returns:
            str: Status message indicating the SSH session was closed.

        Raises:
            VMMError: If the SSH connection fails for any reason.
        """
        if not key_path:
            return "SSH key path is required"

        if not os.path.exists(key_path):
            return f"SSH key file not found: {key_path}"

        try:
            vmm_list = self._vmm.list_vmm()
            if not vmm_list:
                return "No VMMs available to connect"

            id = id if id else self._microvm_id
            available_vmm_ids = [vmm['id'] for vmm in vmm_list]

            if id not in available_vmm_ids:
                return f"VMM with ID {id} does not exist"

            with open(f"{self._config.data_path}/{id}/config.json", "r") as f:
                ip_addr = json.load(f)['Network'][f"tap_{id}"]['IPAddress']

            self._establish_ssh_connection(ip_addr, username, key_path, id)

            if self._config.verbose:
                self._logger.info(f"Attempting SSH connection to {ip_addr} with user {self._config.ssh_user}")

            try:
                channel = self._ssh_client.invoke_shell()
                try:
                    old_settings = termios.tcgetattr(sys.stdin)
                    tty.setraw(sys.stdin)
                except (termios.error, AttributeError):
                    old_settings = None

                try:
                    while True:
                        if channel.exit_status_ready():
                            break

                        if channel.recv_ready():
                            data = channel.recv(1024)
                            if len(data) == 0:
                                break
                            sys.stdout.buffer.write(data)
                            sys.stdout.flush()

                        if old_settings and sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                            char = sys.stdin.read(1)
                            if not char:
                                break
                            channel.send(char)
                        elif not old_settings:
                            time.sleep(5)
                            break
                finally:
                    if old_settings:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    channel.close()
            finally:
                self._ssh_client.close()

            message = f"SSH session to VMM {id or self._microvm_id} closed"
            print(f"\n{message}\n")

        except Exception as e:
            raise VMMError(str(e))

    def port_forward(self, id=None, host_port: int = None, dest_port: int = None, remove: bool = False):
        """Forward a port from the host to the microVM and maintain the connection until interrupted.

        Args:
            host_port (int): Port on the host to forward
            dest_port (int): Port on the destination
            id (str, optional): ID of the VMM to forward ports to. If not provided, uses the last created VMM.
            remove (bool, optional): If True, remove the port forwarding rule instead of adding it.

        Raises:
            VMMError: If VMM IP address cannot be found or port forwarding fails
            ValueError: If the provided ports are not valid port numbers
        """
        try:
            vmm_list = self._vmm.list_vmm()
            if not vmm_list:
                return "No VMMs available"

            id = id if id else self._microvm_id 
            available_vmm_ids = [vmm['id'] for vmm in vmm_list]
            if id not in available_vmm_ids:
                return f"VMM with ID {id} does not exist" 

            config_path = f"{self._config.data_path}/{id}/config.json"
            with open(config_path, "r") as f:
                config = json.load(f)
                if 'Network' not in config or f"tap_{id}" not in config['Network']:
                    raise VMMError(f"Network configuration not found for VMM {id}")
                dest_ip = config['Network'][f"tap_{id}"]['IPAddress']

            if not dest_ip:
                raise VMMError(f"Could not determine destination IP address for VMM {id}")

            if not host_port or not dest_port:
                raise ValueError("Both host_port and dest_port must be provided")

            if not isinstance(host_port, (int, list)) or not isinstance(dest_port, (int, list)):
                raise ValueError("Ports must be integers or lists of integers")

            if remove:
                self._remove_port_forwarding(host_port, dest_port, id)
                return f"Port forwarding removed successfully for VMM {id}"
            else:
                self._setup_port_forwarding(host_port, dest_port, id, dest_ip)
                return f"Port forwarding added successfully for VMM {id}"

        except Exception as e:
            raise VMMError(f"Failed to configure port forwarding: {str(e)}")

    def snapshot(self, id=None, action: str = None, memory_path: str = None, snapshot_path: str = None):
        """Create a snapshot of the microVM.
        
        Args:
            id (str, optional): ID of the VMM to create a snapshot of. If not provided, uses the last created VMM.
            action (str, optional): Action to perform on the snapshot.
            memory_path (str, optional): Path to the memory file. If not provided, uses the default memory path.
            snapshot_path (str, optional): Path to the snapshot file. If not provided, uses the default snapshot path.
        """
        try:
            id = id if id else self._microvm_id

            if action == "create":
                if self._vmm.get_vmm_state(id) == "Paused":
                    if self._config.verbose:
                        self._logger.info(f"VMM {id} is already paused")
                else:
                    if self._config.verbose:
                        self._logger.info(f"Pausing VMM {id} to create snapshot")
                    self._vmm.update_vmm_state(id, "Paused")

                if not os.path.exists(f"{self._config.snapshot_path}/{id}"):
                    os.makedirs(f"{self._config.snapshot_path}/{id}", mode=0o755)
                    self._logger.info(f"Created VMM {id} snapshot directory")

                self._api.create_snapshot.put(
                    mem_file_path=self._mem_file_path if memory_path is None else memory_path,
                    snapshot_path=self._snapshot_path if snapshot_path is None else snapshot_path,
                )
                if self._config.verbose:
                    self._logger.debug(f"Snapshot created at {self._snapshot_path}")
                    self._logger.info(f"Snapshot created for VMM {id}")
                self._vmm.update_vmm_state(id, "Resumed")
            elif action == "load":
                self._api.load_snapshot.put(
                    enable_diff_snapshots=True,
                    mem_backend={
                        "backend_type": "File",
                        "backend_path": memory_path if memory_path is not None else self._mem_file_path
                    },
                    snapshot_path=snapshot_path if snapshot_path is not None else self._snapshot_path,
                    resume_vm=True,
                    network_overrides=[
                        {
                            "iface_id": self._iface_name,
                            "host_dev_name": self._host_dev_name
                        }
                    ]
                )
                if self._config.verbose:
                    self._logger.debug(f"Snapshot loaded from {snapshot_path if snapshot_path is not None else self._snapshot_path}")
                    self._logger.info(f"Snapshot loaded for VMM {id}")
            else:
                raise ValueError("Invalid action. Must be 'create' or 'load'")

        except Exception as e:
            raise VMMError(f"Failed to create snapshot: {str(e)}")

    def _parse_ports(self, port_value, default_value=None):
        """Parse port values from various input formats.

        Args:
            port_value: Port specification that could be None, an integer, a string with comma-separated values,
                    or a list of integers
            default_value: Default value to use if port_value is None

        Returns:
            list: A list of integer port values
        """
        if port_value is None:
            return [default_value] if default_value is not None else []

        if isinstance(port_value, int):
            return [port_value]

        if isinstance(port_value, str):
            if ',' in port_value:
                return [int(p.strip()) for p in port_value.split(',') if p.strip().isdigit()]
            elif port_value.isdigit():
                return [int(port_value)]

        if isinstance(port_value, list):
            ports = []
            for p in port_value:
                if isinstance(p, int):
                    ports.append(p)
                elif isinstance(p, str) and p.isdigit():
                    ports.append(int(p))
            return ports

        return []

    @property
    def _boot_args(self):
        """Generate boot arguments using current configuration.
        
        Returns:
            str: Boot arguments
        """
        common_args = (
            "console=ttyS0 reboot=k pci=off panic=1 "
            f"ip={self._ip_addr}::{self._gateway_ip}:255.255.255.0:"
            f"{self._microvm_name}:{self._iface_name}:on"
        )

        if self._mmds_enabled:
            return f"{common_args} init={self._init_file}"
        elif self._overlayfs:
            return f"{common_args} init={self._init_file} overlay_root=/vdb"
        else:
            return f"{common_args}"

    def _configure_vmm_boot_source(self):
        """Configure the boot source for the microVM.
        
        Raises:
            ConfigurationError: If boot source configuration fails
        """
        try:
            boot_params = {
                'kernel_image_path': self._kernel_file,
                'boot_args': self._boot_args
            }

            if self._initrd_file:
                boot_params['initrd_path'] = self._initrd_file
                self._logger.info(f"Using initrd file: {self._initrd_file}")

            boot_response = self._api.boot.put(**boot_params)

            if self._config.verbose:
                self._logger.debug(f"Boot configuration response: {boot_response.status_code}")
                self._logger.info("Boot source configured")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure boot source: {str(e)}")

    def _configure_vmm_root_drive(self):
        """Configure the root drive for the microVM.
        
        Raises:
            ConfigurationError: If root drive configuration fails
        """
        try:
            rootfs_path = self._rootfs_file
            if self._overlayfs and self._base_rootfs:
                rootfs_path = self._base_rootfs
            
            self._api.drive.put(
                drive_id="rootfs",
                path_on_host=rootfs_path,
                is_root_device=True if self._initrd_file is None else False,
                is_read_only=self._overlayfs is True
            )
            if self._config.verbose:
                self._logger.info("Root drive configured")

            if self._overlayfs:
                self._api.drive.put(
                    drive_id="overlayfs",
                    path_on_host=self._overlayfs_file,
                    is_root_device=False,
                    is_read_only=False
                )

                if self._config.verbose:
                    self._logger.info("Overlayfs drive configured")

        except Exception:
            raise ConfigurationError("Failed to configure root drive")

    def _configure_vmm_resources(self):
        """Configure machine resources (vCPUs and memory).
        
        Raises:
            ConfigurationError: If machine configuration fails
        """
        try:
            self._api.machine_config.put(
                vcpu_count=self._vcpu,
                mem_size_mib=self._memory
            )

            if self._config.verbose:
                self._logger.info(f"Configured VMM with {self._vcpu} vCPUs and {self._memory} MiB RAM")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure VMM resources: {str(e)}")

    def _configure_vmm_network(self):
        """Configure network interface.

        Raises:
            NetworkError: If network configuration fails
        """
        try:
            response = self._api.network.put(
                iface_id=self._iface_name,
                host_dev_name=self._host_dev_name
            )

            if self._config.verbose:
                self._logger.debug(f"Network configuration response: {response.status_code}")
                self._logger.info("Configured network interface")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure network: {str(e)}")

    def _configure_vmm_mmds(self):
        """Configure MMDS (Microvm Metadata Service) if enabled.

        MMDS is a service that provides metadata to the microVM.
        """
        try:
            if self._config.verbose:
                self._logger.debug("MMDS is " + ("disabled" if not self._mmds_enabled else "enabled, configuring MMDS network..."))

            if not self._mmds_enabled:
                return

            self._api.mmds_config.put(
                version="V2",
                ipv4_address=self._mmds_ip,
                network_interfaces=[self._iface_name]
            )

            user_data = {
                "latest": {
                    "meta-data": {
                        "instance-id": self._microvm_id,
                        "local-hostname": self._microvm_name
                    }
                }
            }

            if self._user_data:
                user_data["latest"]["user-data"] = self._user_data
                if hasattr(self, '_user_data_file') and self._user_data_file:
                    user_data["latest"]["meta-data"]["user-data-file"] = self._user_data_file

            mmds_data_response = self._api.mmds.put(**user_data)

            if self._config.verbose:
                self._logger.debug(f"MMDS data response: {mmds_data_response.status_code}")
                self._logger.info("MMDS data configured")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure MMDS: {str(e)}")

    def _configure_vmm_vsock(self):
        """Configure Vsock if enabled.

        Vsock is a communication channel between the microVM and the host.
        """
        try:
            if self._config.verbose:
                self._logger.debug("Vsock is " + ("disabled" if not self._vsock_enabled else "enabled, configuring Vsock..."))

            self._api.vsock.put(
                guest_cid=self._vsock_guest_cid,
                uds_path=self._vsock_uds_path
            )

            if self._config.verbose:
                self._logger.debug(f"Vsock configured with guest CID {self._vsock_guest_cid} and UDS path {self._vsock_uds_path}")
                self._logger.info("Vsock configured")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure Vsock: {str(e)}")

    def _run_firecracker(self):
        """Run the Firecracker process.

        Raises:
            VMMError: If Firecracker process fails to start
            ConfigurationError: If Firecracker configuration fails
            NetworkError: If network configuration fails
            SSHException: If SSH connection fails
        """
        try:
            self._vmm.socket_file(self._microvm_id)

            paths = [self._vmm_dir, f"{self._vmm_dir}/rootfs", f"{self._vmm_dir}/logs"]
            for path in paths:
                self._vmm.create_vmm_dir(path)

            if not self._overlayfs and self._base_rootfs and os.path.exists(self._base_rootfs):
                run(f"cp {self._base_rootfs} {self._rootfs_file}", capture_output=True)
                if self._config.verbose:
                    self._logger.debug(f"Copied base rootfs from {self._base_rootfs} to {self._rootfs_file}")

            self._vmm.create_log_file(self._microvm_id, f"{self._microvm_id}.log")

            args = [
                "--api-sock", self._socket_file,
                "--id", self._microvm_id,
                "--log-path", f"{self._log_dir}/{self._microvm_id}.log"
            ]

            self._process.start(self._microvm_id, args)
            self._process.is_running(self._microvm_id)

            for _ in range(3):
                try:
                    response = self._api.describe.get()
                    if response.status_code == HTTPStatus.OK:
                        return Api(self._socket_file)
                except Exception:
                    pass
                time.sleep(0.5)

        except Exception as exc:
            self._vmm.cleanup(self._microvm_id)
            raise VMMError(str(exc))

    def _download_kernel(self, url: str, path: str):
        """Download the kernel file from the provided URL.
        
        Args:
            url (str): URL to download the kernel from
            path (str): Local path where to save the kernel file
            
        Raises:
            ValueError: If URL is invalid or doesn't contain http/https
            VMMError: If download fails
        """
        import urllib.request
        import urllib.parse
        
        if not url or not isinstance(url, str):
            return "URL must be a non-empty string"
  
        if not (url.startswith('http://') or url.startswith('https://')):
            return "URL must start with http:// or https://"

        try:
            parsed_url = urllib.parse.urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                raise ValueError("Invalid URL format")

        except Exception as e:
            raise ValueError(f"Invalid URL format: {str(e)}")

        if os.path.exists(path):
            if self._config.verbose:
                self._logger.info(f"Kernel file already exists: {path}")
            return

        try:
            if self._config.verbose:
                self._logger.info(f"Downloading kernel file from {url}...")

            urllib.request.urlretrieve(url, path)

            if not os.path.exists(path) or os.path.getsize(path) == 0:
                raise VMMError("Download failed: file is empty or was not created")
                
            if self._config.verbose:
                self._logger.info(f"Kernel file downloaded successfully: {path}")
                
        except Exception as e:
            if os.path.exists(path):
                os.remove(path)
            raise VMMError(f"Failed to download kernel from {url}: {str(e)}")

    def _convert_memory_size(self, size):
        """Convert memory size to MiB.
        
        Args:
            size: Memory size in format like '1G', '2G', or plain number (assumed to be MiB)
            
        Returns:
            int: Memory size in MiB
        """
        MIN_MEMORY = 128  # Minimum memory size in MiB
        
        if isinstance(size, int):
            return max(size, MIN_MEMORY)
            
        if isinstance(size, str):
            size = size.upper().strip()
            try:
                if size.endswith('G'):
                    # Convert GB to MiB and ensure minimum
                    mem_size = int(float(size[:-1]) * 1024)
                elif size.endswith('M'):
                    # Already in MiB, just convert
                    mem_size = int(float(size[:-1]))
                else:
                    # If no unit specified, assume MiB
                    mem_size = int(float(size))
                
                return max(mem_size, MIN_MEMORY)
            except ValueError:
                raise ValueError(f"Invalid memory size format: {size}")
        raise ValueError(f"Invalid memory size type: {type(size)}")

    def _is_valid_docker_image(self, name: str) -> bool:
        """
        Check if a Docker image is valid by checking both local images and registry
        
        Args:
            name (str): Docker image name (e.g., 'alpine', 'nginx:latest')
        
        Returns:
            bool: True if image exists locally or in registry, False otherwise
        """
        try:
            try:
                local_image = self._docker.images.get(name)
                if local_image:
                    return True
            except docker.errors.ImageNotFound:
                pass
            
            try:
                inspect = self._docker.api.inspect_distribution(name)
                if inspect:
                    return True
                else:
                    return False
            except Exception:
                return False

        except Exception as e:
            raise VMMError(f"Failed to check if Docker image {name} is valid: {str(e)}")

    def _download_docker(self, image: str) -> str:
        """Download a Docker image and extract its root filesystem.
        
        Args:
            image (str): Docker image name (e.g., 'ubuntu:24.04', 'alpine:latest')
            
        Returns:
            str: Docker image tag or ID
            
        Raises:
            VMMError: If Docker operations fail
        """
        try:
            local = self._docker.images.get(image)
            if self._config.verbose:
                self._logger.info(f"Docker image {image} already exists")
            if local.tags:
                return local.tags[0]
            else:
                return local.id

        except docker.errors.ImageNotFound:
            if self._config.verbose:
                self._logger.info(f"Pulling Docker image: {image}")

            pulled = self._docker.images.pull(image)

            if pulled.tags:
                return pulled.tags[0]
            else:
                raise VMMError(f"Failed to pull Docker image {image}")

        except Exception as e:
            raise VMMError(f"Unexpected error: {e}")

    def _export_docker_image(self, image: str) -> str:
        """
        Export Docker image to a tar file
        
        Args:
            image (str): Docker image name (e.g., 'alpine', 'ubuntu:20.04')
            
        Returns:
            str: Path to the exported tar file
        """
        container_name = image.split('/')[-1].replace(':', '-')
        tar_file = f"{self._config.data_path}/rootfs_{container_name}.tar"

        try:
            if not image:
                raise VMMError(f"Failed to download Docker image {image}")

            if self._config.verbose:
                self._logger.debug(f"Creating container: {container_name}")
            
            container = self._docker.containers.create(image, name=container_name)
            export_data = container.export()

            if self._config.verbose:
                self._logger.debug(f"Exporting container to {tar_file}")

            with open(tar_file, 'wb') as f:
                for chunk in export_data:
                    f.write(chunk)

            container.remove(force=True)
            
            if self._config.verbose:
                self._logger.debug(f"Successfully exported container to {tar_file}")

            return tar_file
                
        except (docker.errors.ImageNotFound, docker.errors.APIError) as e:
            raise VMMError(f"Docker error: {e}")
        except Exception as e:
            raise VMMError(f"Unexpected error: {e}")

    def _build_rootfs(self, image: str, file: str, size: str):
        """Create a filesystem image from a tar file.
        
        Args:
            image (str): Docker image name
            file (str): Path to the output image file
            size (str): Size of the image file

        Returns:
            str: Path to the created image file
        """
        tmp_dir = None
        try:
            self._download_docker(image)
            tar_file = self._export_docker_image(image)

            if not tar_file or not os.path.exists(tar_file):
                return f"Failed to export Docker image {image}"

            run(f"fallocate -l {size} {file}")
            if self._config.verbose:
                self._logger.debug(f"Image file created: {file}")

            run(f"mkfs.ext4 {file}")
            if self._config.verbose:
                self._logger.debug(f"Formatting filesystem: {file} with size {size}")

            tmp_dir = tempfile.mkdtemp()
            run(f"mount -o loop {file} {tmp_dir}")

            with tarfile.open(tar_file, 'r') as tar:
                tar.extractall(path=tmp_dir)

            os.remove(tar_file)
            if self._config.verbose:
                self._logger.debug(f"Removed tar file: {tar_file}")

            if self._config.verbose:
                self._logger.info("Build rootfs completed")

        except Exception as e:
            if tmp_dir:
                run(f"umount {tmp_dir}", "unmounting")
                os.rmdir(tmp_dir)
            raise VMMError(f"Failed to create image file: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(SSHException)
    )
    def _establish_ssh_connection(self, ip_addr: str, username: str, key_path: str, id: str):
        """Establish SSH connection to the VMM with retry logic.
        
        Args:
            ip_addr (str): IP address of the VMM
            username (str): SSH username
            key_path (str): Path to SSH private key
            id (str): VMM ID for error messages
            
        Raises:
            VMMError: If connection fails after all retry attempts
        """
        self._ssh_client.set_missing_host_key_policy(AutoAddPolicy())
        self._ssh_client.connect(
            hostname=ip_addr,
            username=username if username else self._config.ssh_user,
            key_filename=key_path
        )

    def _setup_port_forwarding(self, host_ports, dest_ports, vmm_id=None, dest_ip=None, update_config=True):
        """Helper method to set up port forwarding rules.
        
        Args:
            host_ports: List of host ports or single port
            dest_ports: List of destination ports or single port  
            vmm_id: VMM ID (uses self._microvm_id if None)
            dest_ip: Destination IP (uses self._ip_addr if None)
            update_config: Whether to update the config file
            
        Returns:
            dict: Port configuration dictionary
            
        Raises:
            ValueError: If port validation fails
            VMMError: If port forwarding setup fails
        """
        vmm_id = vmm_id or self._microvm_id
        dest_ip = dest_ip or self._ip_addr

        host_ports_list = [host_ports] if isinstance(host_ports, int) else host_ports
        dest_ports_list = [dest_ports] if isinstance(dest_ports, int) else dest_ports
        
        if len(host_ports_list) != len(dest_ports_list):
            raise ValueError("Number of host ports must match number of destination ports")

        ports_config = {}
        for host_port, dest_port in zip(host_ports_list, dest_ports_list):
            self._network.add_port_forward(vmm_id, self._host_ip, host_port, dest_ip, dest_port)
            
            port_key = f"{dest_port}/tcp"
            if port_key not in ports_config:
                ports_config[port_key] = []
            
            ports_config[port_key].append({
                "HostPort": host_port,
                "DestPort": dest_port
            })

        if update_config:
            config_path = f"{self._config.data_path}/{vmm_id}/config.json"
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                
                if 'Ports' not in config:
                    config['Ports'] = {}
                
                config['Ports'].update(ports_config)
                
                with open(config_path, "w") as f:
                    json.dump(config, f)
                
                if self._config.verbose:
                    self._logger.debug(f"Added {host_port} -> {dest_port} to VMM {vmm_id}")
                    self._logger.info(f"Port forwarding added successfully for VMM {vmm_id}")
        
        return ports_config

    def _remove_port_forwarding(self, host_ports, dest_ports, vmm_id=None, update_config=True):
        """Helper method to remove port forwarding rules.
        
        Args:
            host_ports: List of host ports or single port
            dest_ports: List of destination ports or single port
            vmm_id: VMM ID (uses self._microvm_id if None)
            update_config: Whether to update the config file
            
        Returns:
            str: Status message
        """
        vmm_id = vmm_id or self._microvm_id
        
        host_ports_list = [host_ports] if isinstance(host_ports, int) else host_ports
        dest_ports_list = [dest_ports] if isinstance(dest_ports, int) else dest_ports

        for host_port, dest_port in zip(host_ports_list, dest_ports_list):
            self._network.delete_port_forward(vmm_id, host_port)
            if self._config.verbose:
                self._logger.debug(f"Removed {host_port} -> {dest_port} from VMM {vmm_id}")
        
        if update_config:
            config_path = f"{self._config.data_path}/{vmm_id}/config.json"
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                
                for dest_port in dest_ports_list:
                    config['Ports'].pop(f"{dest_port}/tcp", None)
                
                with open(config_path, "w") as f:
                    json.dump(config, f)

        if self._config.verbose:
            self._logger.info(f"Port forwarding removed successfully for VMM {vmm_id}")
