import os
import sys
import time
import json
import psutil
import select
import termios
import tty
import requests
from paramiko import SSHClient, AutoAddPolicy
from typing import Tuple, List, Dict
from firecracker.config import MicroVMConfig
from firecracker.api import Api
from firecracker.logger import Logger
from firecracker.network import NetworkManager
from firecracker.process import ProcessManager
from firecracker.vmm import VMMManager
from firecracker.utils import run, get_public_ip, validate_ip_address, generate_id, generate_name
from firecracker.exceptions import APIError, VMMError, ConfigurationError, ProcessError
import paramiko.ssh_exception


class MicroVM:
    """A class to manage Firecracker microVMs.

    Args:
        id (str, optional): ID for the MicroVM
    """
    def __init__(self, name: str = None, kernel_file: str = None, base_rootfs: str = None, rootfs_url: str = None, vcpu: int = None, mem_size_mib: int = None, ip_addr: str = None, bridge: bool = None, bridge_name: str = None, mmds_enabled: bool = None, mmds_ip: str = None, labels: dict = None, working_dir: str = '/root', expose_ports: bool = None, host_port: int = None, dest_port: int = None, verbose: bool = False) -> None:
        """Initialize a new MicroVM instance with configuration.

        Args:
            id (str, optional): ID for the MicroVM
            hostname (str, optional): Hostname for the MicroVM
            kernel_file (str, optional): Path to the kernel file
            base_rootfs (str, optional): Path to the base rootfs file
            vcpu (int, optional): Number of vCPUs
            mem_size_mib (int, optional): Memory size in MiB
            ip_addr (str, optional): IP address for the MicroVM
            bridge (bool, optional): Whether to use a bridge for networking
            bridge_name (str, optional): Name of the bridge interface
            mmds_enabled (bool, optional): Whether to enable MMDS
            mmds_ip (str, optional): IP address for MMDS
            labels (dict, optional): Labels for the MicroVM
            working_dir (str, optional): Working directory for the MicroVM
            expose_ports (bool, optional): Whether to expose ports
            host_port (int, optional): Host port for port forwarding
            dest_port (int, optional): Destination port for port forwarding
            verbose (bool, optional): Whether to enable verbose logging
        """
        # Generate IDs and Names
        self._microvm_id = generate_id()
        self._microvm_name = generate_name() if name is None else name

        # Configuration
        self._config = MicroVMConfig()
        self._vcpu = self._config.vcpu_count if vcpu is None else vcpu
        self._mem_size_mib = self._config.mem_size_mib if mem_size_mib is None else mem_size_mib
        self._mmds_enabled = self._config.mmds_enabled if mmds_enabled is None else mmds_enabled
        self._mmds_ip = self._config.mmds_ip if mmds_ip is None else mmds_ip
        self._user_data = {"meta-data": {"instance-id": self._microvm_id}}
        self._labels = labels if labels is not None else {}
        self._working_dir = working_dir

        self._logger = Logger(level="INFO", verbose=verbose)
        self._network = NetworkManager(verbose=verbose)
        self._process = ProcessManager(verbose=verbose)
        self._vmm = VMMManager(verbose=verbose)

        self._socket_file = f"{self._config.data_path}/{self._microvm_id}/firecracker.socket"
        self._api = self._vmm.get_api(self._microvm_id)

        self._kernel_file = kernel_file if kernel_file else self._config.kernel_file
        if rootfs_url:
            self._base_rootfs = self._download_rootfs(rootfs_url)
        else:
            self._base_rootfs = base_rootfs if base_rootfs else self._config.base_rootfs
        base_rootfs_name = os.path.basename(self._base_rootfs.replace('./', ''))
        self._vmm_dir = f"{self._config.data_path}/{self._microvm_id}"
        self._log_dir = f"{self._vmm_dir}/logs"
        self._rootfs_dir = f"{self._vmm_dir}/rootfs"
        self._rootfs_file = os.path.join(self._rootfs_dir, base_rootfs_name)

        self._iface_name = self._network.get_interface_name()
        self._host_dev_name = f"tap_{self._microvm_id}"
        self._ip_addr = ip_addr if ip_addr is not None else self._config.ip_addr
        self._gateway_ip = self._network.get_gateway_ip(self._ip_addr)
        self._bridge = self._config.bridge if bridge is None else bridge
        self._bridge_name = self._config.bridge_name if bridge_name is None else bridge_name

        self._ssh_client = SSHClient()
        self._expose_ports = self._config.expose_ports if expose_ports is None else expose_ports
        
        self._host_port = self._parse_ports(host_port)
        self._dest_port = self._parse_ports(dest_port)

        if not isinstance(self._vcpu, int) or self._vcpu <= 0:
            raise ValueError("vcpu must be a positive integer")
        if not isinstance(self._mem_size_mib, int) or self._mem_size_mib < 128:
            raise ValueError("mem_size_mib must be valid")

        if hasattr(self, '_ip_addr') and self._ip_addr:
            validate_ip_address(self._ip_addr)

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

        with open(config_file, "r") as f:
            config = json.load(f)
            return config

    def status(self, id=None):
        """Get the status of the current VMM or a specific VMM.

        Args:
            id (str, optional): ID of the VMM to check. If not provided,
                uses the current VMM's ID.
        """
        id = id if id else self._microvm_id
        if not id:
            return "No VMM ID specified for checking status"
        
        with open(f"{self._config.data_path}/{id}/config.json", "r") as f:
            config = json.load(f)
            if config['State']['Running']:
                return f"VMM {id} is running"
            elif config['State']['Paused']:
                return f"VMM {id} is paused"

    def create(self) -> dict:
        """Create a new VMM and configure it."""
        vmm_list = self._vmm.list_vmm()

        if self._microvm_name in [vmm['name'] for vmm in vmm_list]:
            return f"VMM with name {self._microvm_name} already exists"

        try:
            self._run_firecracker()
            if not self._basic_config():
                return "Failed to configure VMM"

            if self._vmm.check_network_overlap(self._ip_addr):
                return f"IP address {self._ip_addr} is already in use"

            if self._config.verbose:
                self._logger.info(f"Creating VMM {self._microvm_name}")

            if self._config.verbose:
                self._logger.info("VMM configuration completed")

            self._api.actions.put(action_type="InstanceStart")

            if self._config.verbose:
                self._logger.info("VMM started successfully")

            if self._expose_ports:
                if self._config.verbose:
                    self._logger.info("Port forwarding is enabled")
                    self._logger.info(f"Host ports: {self._host_port}")
                    self._logger.info(f"Destination ports: {self._dest_port}")

                if not self._host_port or not self._dest_port:
                    if self._config.verbose:
                        self._logger.warn("Port forwarding requested but no ports specified")
                else:
                    try:
                        if self._config.verbose:
                            self._logger.info("Attempting to configure port forwarding...")
                        self.port_forward(host_port=self._host_port, dest_port=self._dest_port)
                        if self._config.verbose:
                            self._logger.info("Port forwarding configured successfully")
                    except Exception as e:
                        if self._config.verbose:
                            self._logger.error(f"Failed to configure port forwarding: {str(e)}")

                ports = {}
                port_pairs = zip(self._host_port, self._dest_port)
                if self._config.verbose:
                    self._logger.info(f"Port pairs: {list(port_pairs)}")
                
                for host_port, dest_port in zip(self._host_port, self._dest_port):
                    port_key = f"{dest_port}/tcp"
                    if port_key not in ports:
                        ports[port_key] = []
                        
                    ports[port_key].append({
                        "HostPort": host_port,
                        "DestPort": dest_port
                    })
            else:
                if self._config.verbose:
                    self._logger.info("Port forwarding is disabled")
                ports = {}

            pid, create_time = self._process.get_pids(self._microvm_id)

            if self._process.is_process_running(self._microvm_id):
                self._vmm.create_vmm_json_file(
                    id=self._microvm_id,
                    Name=self._microvm_name,
                    CreatedAt=create_time,
                    Rootfs=self._rootfs_file,
                    Kernel=self._kernel_file,
                    Pid=pid,
                    Ports=ports,
                    IPAddress=self._ip_addr,
                    Labels=self._labels,
                    WorkingDir=self._working_dir
                )
                return f"VMM {self._microvm_id} is created successfully"
            else:
                if self._config.verbose:
                    self._logger.info(f"VMM {self._microvm_id} is failed to create, deleting the VMM")
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
            with open(config_path, "r+") as file:
                config = json.load(file)
                config['State']['Paused'] = "true"
                file.seek(0)
                json.dump(config, file)
                file.truncate()

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
            with open(config_path, "r+") as file:
                config = json.load(file)
                config['State']['Paused'] = "false"
                file.seek(0)
                json.dump(config, file)
                file.truncate()

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
            FirecrackerError: If an error occurs during the deletion process.
        """
        try:
            id = id if id else self._microvm_id

            if not id and not all:
                return "No VMM ID specified for deletion"

            vmm_list = self._vmm.list_vmm()
            if not vmm_list:
                return "No VMMs available to delete"

            if all:
                for vmm in vmm_list:
                    self._vmm.delete_vmm(vmm['id'])
                return "All VMMs deleted successfully"

            if id not in [vmm['id'] for vmm in vmm_list]:
                return f"VMM with ID {id} not found"

            if self._config.verbose:
                self._logger.info(f"Deleting VMM with ID {id}")
            self._vmm.delete_vmm(id)
            return f"VMM {id} deleted successfully"

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
            if not self._vmm.list_vmm():
                return "No VMMs available to connect"

            id = id if id else self._microvm_id
            available_vmm_ids = [vmm['id'] for vmm in self._vmm.list_vmm()]

            if id not in available_vmm_ids:
                return f"VMM with ID {id} does not exist"

            with open(f"{self._config.data_path}/{id}/config.json", "r") as f:
                ip_addr = json.load(f)['Network'][f"tap_{id}"]['IPAddress']

            max_retries = 3
            retries = 0
            while retries < max_retries:
                try:
                    self._ssh_client.set_missing_host_key_policy(AutoAddPolicy())
                    self._ssh_client.connect(
                        hostname=ip_addr,
                        username=username if username else self._config.ssh_user,
                        key_filename=key_path
                    )
                    break
                except paramiko.ssh_exception.NoValidConnectionsError as e:
                    retries += 1
                    if retries >= max_retries:
                        raise VMMError(
                            f"Unable to connect to the VMM {id} via SSH after {max_retries} attempts: {str(e)}"
                        )
                    time.sleep(2)

            if self._config.verbose:
                self._logger.info(f"Attempting SSH connection to {ip_addr} with user {self._config.ssh_user}")

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
            except Exception as e:
                if self._config.verbose:
                    self._logger.info(f"SSH session exited: {str(e)}")
            finally:
                if old_settings:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                channel.close()
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
            if not self._vmm.list_vmm():
                return "No VMMs available to forward ports"

            id = id if id else self._microvm_id
            available_vmm_ids = [vmm['id'] for vmm in self._vmm.list_vmm()]
            if id not in available_vmm_ids:
                return f"VMM with ID {id} does not exist"

            # Get the host IP address
            host_ip = get_public_ip()
            if not host_ip:
                raise VMMError("Could not determine host IP address")

            # Get the VM's IP address from the config file
            config_path = f"{self._config.data_path}/{id}/config.json"
            if not os.path.exists(config_path):
                raise VMMError(f"Config file not found for VMM {id}")

            with open(config_path, "r") as f:
                config = json.load(f)
                if 'Network' not in config or f"tap_{id}" not in config['Network']:
                    raise VMMError(f"Network configuration not found for VMM {id}")
                dest_ip = config['Network'][f"tap_{id}"]['IPAddress']

            if not dest_ip:
                raise VMMError(f"Could not determine destination IP address for VMM {id}")

            # Validate ports
            if not host_port or not dest_port:
                raise ValueError("Both host_port and dest_port must be provided")

            if not isinstance(host_port, (int, list)) or not isinstance(dest_port, (int, list)):
                raise ValueError("Ports must be integers or lists of integers")

            # Convert single ports to lists for consistent handling
            host_ports = [host_port] if isinstance(host_port, int) else host_port
            dest_ports = [dest_port] if isinstance(dest_port, int) else dest_port

            if len(host_ports) != len(dest_ports):
                raise ValueError("Number of host ports must match number of destination ports")

            # Process each port pair
            for h_port, d_port in zip(host_ports, dest_ports):
                if remove:
                    self._network.delete_port_forward(host_ip, h_port, dest_ip, d_port)
                    if self._config.verbose:
                        self._logger.info(f"Removed port forwarding: {host_ip}:{h_port} -> {dest_ip}:{d_port}")
                else:
                    self._network.add_port_forward(host_ip, h_port, dest_ip, d_port)
                    if self._config.verbose:
                        self._logger.info(f"Added port forwarding: {host_ip}:{h_port} -> {dest_ip}:{d_port}")

            return f"Port forwarding {'removed' if remove else 'added'} successfully"

        except Exception as e:
            raise VMMError(f"Failed to configure port forwarding: {str(e)}")

    def execute_in_vm(self, id=None, commands=None):
        """Execute commands in the VM console through the screen session.
        
        This method allows sending commands directly to the VM's console, which is useful
        for configuring networking when SSH is not available.
        
        Args:
            id (str, optional): VM ID. If not provided, uses the current VM ID.
            commands (list): List of commands to execute in the VM console
            
        Returns:
            bool: Success status
            
        Raises:
            VMMError: If the command execution fails
        """
        if not commands:
            return False
        
        id = id if id else self._microvm_id
        session_name = f"fc_{id}"
        
        if self._config.verbose:
            self._logger.info(f"Executing commands in VM {id} console")
        
        try:
            # Prepare the commands with newlines
            cmd_string = "\n".join(commands) + "\n"
            
            # Write commands to a temp file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp:
                temp_path = temp.name
                temp.write(cmd_string)
            
            # Use screen's stuff command to send commands to the VM
            stuff_cmd = f"screen -S {session_name} -X stuff $'$(cat {temp_path})'"
            result = run(stuff_cmd)
            
            # Clean up temp file
            import os
            os.unlink(temp_path)
            
            if result.returncode == 0:
                if self._config.verbose:
                    self._logger.info(f"Successfully executed commands in VM {id}")
                return True
            else:
                raise VMMError(f"Failed to execute commands in VM {id}: {result.stderr}")
        
        except Exception as e:
            raise VMMError(f"Failed to execute commands in VM {id}: {str(e)}")

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

    def _basic_config(self) -> bool:
        """Configure the microVM with basic settings.

        This method orchestrates the configuration of various components:
        - Boot source
        - Root drive
        - Machine resources (vCPUs and memory)
        - Network interface
        - MMDS (if enabled)

        Returns:
            bool: True if configuration is successful, False otherwise.
        """
        try:
            self._configure_vmm_boot_source()
            self._configure_vmm_root_drive()
            self._configure_vmm_resources()
            self._configure_vmm_network()
            if self._mmds_enabled:
                self._configure_vmm_mmds()
            return True
        except Exception as exc:
            raise ConfigurationError(str(exc))

    @property
    def _boot_args(self):
        """Generate boot arguments using current configuration."""
        if self._mmds_enabled:
            return (
                "console=ttyS0 reboot=k panic=1 "
                f"ds=nocloud-net;s=http://{self._mmds_ip}/latest/ "
                f"ip={self._ip_addr}::{self._gateway_ip}:255.255.255.0:"
                f"{self._microvm_name}:{self._iface_name}:on "
            )
        else:
            return (
                "console=ttyS0 reboot=k panic=1 "
                f"ip={self._ip_addr}::{self._gateway_ip}:255.255.255.0:"
                f"{self._microvm_name}:{self._iface_name}:on "
            )

    def _configure_vmm_boot_source(self):
        """Configure the boot source for the microVM."""
        try:
            if self._config.verbose:
                self._logger.info("Configuring boot source...")

            if not os.path.exists(self._kernel_file):
                raise ConfigurationError(f"Kernel file not found: {self._kernel_file}")

            boot_response = self._api.boot.put(
                kernel_image_path=self._kernel_file,
                boot_args=self._boot_args
            )

            if self._config.verbose:
                self._logger.debug(f"Boot configuration response: {boot_response}")
                self._logger.info("Boot source configured")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure boot source: {str(e)}")

    def _configure_vmm_root_drive(self):
        """Configure the root drive for the microVM."""
        try:
            if self._config.verbose:
                self._logger.info("Configuring root drive...")

            drive_response = self._api.drive.put(
                drive_id="rootfs",
                path_on_host=self._rootfs_file,
                is_root_device=True,
                is_read_only=False
            )

            if self._config.verbose:
                self._logger.info(f"Root drive configured with {self._rootfs_file}")
                self._logger.debug(f"Drive configuration response: {drive_response}")

        except Exception:
            raise ConfigurationError("Failed to configure root drive")

    def _configure_vmm_resources(self):
        """Configure machine resources (vCPUs and memory)."""
        try:
            if self._config.verbose:
                self._logger.info("Configuring VMM resources...")

            self._api.machine_config.put(
                vcpu_count=self._vcpu,
                mem_size_mib=self._mem_size_mib
            )

            if self._config.verbose:
                self._logger.info(f"VMM is configured with {self._vcpu} vCPUs and {self._mem_size_mib} MiB of memory")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure VMM resources: {str(e)}")

    def _configure_vmm_network(self):
        """Configure network interface.

        Raises:
            NetworkError: If network configuration fails
        """
        try:
            if self._config.verbose:
                self._logger.info("Configuring VMM network interface...")

            self._network.create_tap(
                name=self._host_dev_name,
                iface_name=self._iface_name,
                gateway_ip=self._gateway_ip,
                bridge=self._bridge
            )

            self._api.network.put(
                iface_id=self._iface_name,
                host_dev_name=self._host_dev_name
            )

            # Enable NAT internet access if configured
            if self._config.nat_enabled:
                self._network.enable_nat_internet_access(
                    tap_name=self._host_dev_name,
                    iface_name=self._iface_name,
                    vm_ip=self._ip_addr
                )

            if self._config.verbose:
                self._logger.info("Network configuration complete")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure network: {str(e)}")

    def _configure_vmm_mmds(self):
        """Configure MMDS (Microvm Metadata Service) if enabled.

        MMDS is a service that provides metadata to the microVM.
        """
        try:
            if self._config.verbose:
                self._logger.info("MMDS is " + ("disabled" if not self._mmds_enabled else "enabled, configuring MMDS network..."))

            if not self._mmds_enabled:
                return

            mmds_response = self._api.mmds_config.put(
                version="V2",
                ipv4_address=self._mmds_ip,
                network_interfaces=[self._iface_name]
            )

            if self._config.verbose:
                self._logger.debug(f"MMDS network configuration response: {mmds_response}")
                self._logger.info("Setting MMDS data...")

            # Prepare user data
            user_data = {
                "latest": {
                    "meta-data": {
                        "instance-id": self._microvm_id,
                        "local-hostname": self._microvm_name
                    }
                }
            }

            # Add user data if provided
            if self._config.user_data:
                user_data["latest"]["user-data"] = self._config.user_data

            mmds_data_response = self._api.mmds.put(**user_data)

            if self._config.verbose:
                self._logger.debug(f"MMDS data response: {mmds_data_response}")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure MMDS: {str(e)}")

    def _run_firecracker(self) -> Tuple[Api, int]:
        """Start a new Firecracker process using screen."""
        try:
            self._vmm._ensure_socket_file(self._microvm_id)

            for path in [self._vmm_dir, f"{self._vmm_dir}/rootfs", f"{self._vmm_dir}/logs"]:
                self._vmm.create_vmm_dir(path)

            run(f"cp {self._base_rootfs} {self._rootfs_file}")
            if self._config.verbose:
                self._logger.info(f"Copied base rootfs from {self._base_rootfs} to {self._rootfs_file}")

            for log_file in [f"{self._microvm_id}.log", f"{self._microvm_id}_screen.log"]:
                self._vmm.create_log_file(self._microvm_id, log_file)

            binary_params = [
                f"--api-sock {self._socket_file}",
                f"--id {self._microvm_id}",
                f"--log-path {self._log_dir}/{self._microvm_id}.log"
            ]

            session_name = f"fc_{self._microvm_id}"
            screen_pid = self._process.start_screen_process(
                screen_log=f"{self._log_dir}/{self._microvm_id}_screen.log",
                session_name=session_name,
                binary_path=self._config.binary_path,
                binary_params=binary_params
            )

            max_retries = 3
            for retry in range(max_retries):
                if not psutil.pid_exists(int(screen_pid)):
                    raise ProcessError("Firecracker process is not running")

                if os.path.exists(self._socket_file):
                    return Api(self._socket_file)

                if retry < max_retries - 1:
                    time.sleep(0.5)

            raise APIError(f"Failed to connect to the API socket after {max_retries} attempts")

        except Exception as exc:
            self._vmm.cleanup_resources(self._microvm_id)
            raise VMMError(str(exc))

    def _download_rootfs(self, url: str):
        """Download the rootfs from the given URL."""

        if not url.startswith(("http://", "https://")):
            raise VMMError(f"Invalid URL: {url}")

        try:
            response = requests.get(url, stream=True, timeout=10)
            response.raise_for_status()

            if self._config.verbose:
                self._logger.info(f"Downloading rootfs from {url}")

            filename = url.split("/")[-1]
            path = os.path.join(self._config.data_path, filename)

            with open(path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return path

        except Exception as e:
            raise VMMError(f"Failed to download rootfs from {url}: {str(e)}")