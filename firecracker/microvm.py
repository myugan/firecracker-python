import os
import sys
import time
import psutil
import select
import termios
import tty
from paramiko import SSHClient, AutoAddPolicy
from typing import Optional, Tuple, List, Dict
from firecracker.config import MicroVMConfig
from firecracker.api import Api
from firecracker.logger import Logger
from firecracker.network import NetworkManager
from firecracker.process import ProcessManager
from firecracker.vmm import VMMManager
from firecracker.utils import run, get_public_ip, validate_ip_address, validate_hostname, generate_id
from firecracker.exceptions import APIError, VMMError, ConfigurationError, ProcessError
import paramiko.ssh_exception


class MicroVM:
    """A class to manage Firecracker microVMs.

    Args:
        id (str, optional): ID for the MicroVM
        **kwargs: Configuration parameters that override defaults
    """
    def __init__(self, id: Optional[str] = None, **kwargs) -> None:
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
        """
        self._microvm_id = id if id else generate_id()
        self._config = MicroVMConfig()

        # Apply configuration from kwargs
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)

        # Initialize logging and managers
        verbose = self._config.verbose
        self._logger = Logger(level="INFO", verbose=verbose)
        self._network = NetworkManager(verbose=verbose)
        self._process = ProcessManager(verbose=verbose)
        self._vmm = VMMManager(verbose=verbose)

        # API and socket file setup
        self._socket_file = f"{self._config.data_path}/{self._microvm_id}/firecracker.socket"
        self._api = self._vmm.get_api(self._microvm_id)

        # System configuration
        self._hostname = self._config.hostname if self._config.hostname else self._microvm_id
        self._kernel_file = self._config.kernel_file
        self._base_rootfs = self._config.base_rootfs
        base_rootfs_name = os.path.basename(self._base_rootfs.replace('./', ''))
        self._vmm_dir = f"{self._config.data_path}/{self._microvm_id}"
        self._log_dir = f"{self._vmm_dir}/logs"
        self._rootfs_dir = f"{self._vmm_dir}/rootfs"
        self._rootfs_file = os.path.join(self._rootfs_dir, base_rootfs_name)
        self._vcpu = self._config.vcpu_count
        self._mem_size_mib = self._config.mem_size_mib
        self._mmds_enabled = self._config.mmds_enabled
        self._mmds_ip = self._config.mmds_ip
        self._user_data = {"meta-data": {"instance-id": self._microvm_id}}

        # Network configuration
        self._iface_name = self._network.get_interface_name()
        self._host_dev_name = f"tap_{self._microvm_id}"
        self._ip_addr = self._config.ip_addr
        self._gateway_ip = self._network.get_gateway_ip(self._ip_addr)
        self._bridge = self._config.bridge
        self._bridge_name = self._config.bridge_name

        # SSH and port forwarding
        self._ssh_client = SSHClient()
        self._port_forwarding = self._config.port_forwarding
        self._host_port = self._config.host_port
        self._dest_port = self._config.dest_port

        # Validation
        if not isinstance(self._vcpu, int) or self._vcpu <= 0:
            raise ValueError("vcpu must be a positive integer")
        if not isinstance(self._mem_size_mib, int) or self._mem_size_mib < 128:
            raise ValueError("mem_size_mib must be valid")

        if hasattr(self, '_hostname') and self._hostname:
            validate_hostname(self._hostname)
        if hasattr(self, '_ip_addr') and self._ip_addr:
            validate_ip_address(self._ip_addr)

        if not os.path.exists(self._kernel_file):
            raise ConfigurationError(f"Kernel file not found at: {self._kernel_file}")

        if not os.path.exists(self._base_rootfs):
            raise ConfigurationError(f"Base root filesystem not found at: {self._base_rootfs}")

    @staticmethod
    def list() -> List[Dict]:
        """List all running Firecracker VMs.

        Returns:
            List[Dict]: List of dictionaries containing VMM details
        """
        try:
            vmm_manager = VMMManager()
            return vmm_manager.list_vmms()

        except Exception as e:
            raise VMMError(str(e))

    def config(self, id=None, **kwargs):
        """Get the configuration for the current VMM or a specific VMM.

        Args:
            id (str, optional): ID of the VMM to query. If not provided,
                uses the current VMM's ID.

        Returns:
            dict: Response from the VMM configuration endpoint or error message.
        """
        if kwargs:
            unexpected_arg = next(iter(kwargs))
            return f"Got an unexpected keyword argument '{unexpected_arg}'"

        try:
            id = id if id else self._microvm_id
            if not id:
                return "No VMM ID specified for checking configuration"
            return self._vmm.get_vmm_config(id)

        except Exception as e:
            raise VMMError(str(e))

    def status(self, id=None, **kwargs):
        """Get the status of the current VMM or a specific VMM.

        Args:
            id (str, optional): ID of the VMM to check. If not provided,
                uses the current VMM's ID.
        """
        if kwargs:
            unexpected_arg = next(iter(kwargs))
            return f"Got an unexpected keyword argument '{unexpected_arg}'"

        try:
            id = id if id else self._microvm_id
            if not id:
                return "No VMM ID specified for checking status"
            return self._vmm.get_vmm_state(id)

        except Exception as e:
            raise VMMError(str(e))

    def create(self, **kwargs) -> dict:
        """Create a new VMM and configure it."""
        if kwargs:
            unexpected_arg = next(iter(kwargs))
            return f"Got an unexpected keyword argument '{unexpected_arg}'"

        if os.path.exists(self._socket_file) or self._microvm_id in [vmm['id'] for vmm in self._vmm.list_vmms()]:
            message = f"VMM with ID {self._microvm_id} already exists"
            if self._config.verbose:
                self._logger.error(message)
            return message

        if self._config.verbose:
            self._logger.info(f"Creating VMM {self._microvm_id}")

        try:
            self._spawn()
            self._basic_config()

            if self._config.verbose:
                self._logger.info(f"VMM configuration completed")

            self._api.actions.put(action_type="InstanceStart")

            if self._config.verbose:
                self._logger.info("VMM started successfully")

            if self._port_forwarding:
                self._port_forward()
                if self._config.verbose:
                    self._logger.info(f"Port forwarding set up for VMM {self._microvm_id}")

            if self._config.verbose:
                self._logger.info(f"VMM {self._microvm_id} is created successfully")
            return f"VMM {self._microvm_id} is created successfully"

        except Exception as e:
            raise VMMError(f"Failed to create VMM {self._microvm_id}: {str(e)}")

        finally:
            self._api.close()

    def pause(self, id=None, **kwargs):
        """Pause the configured microVM.

        Args:
            id (str, optional): ID of the VMM to pause. If not provided,
                uses the current VMM's ID.

        Returns:
            str: Status message indicating the result of the pause operation.

        Raises:
            FirecrackerError: If the pause operation fails.
        """
        if kwargs:
            unexpected_arg = next(iter(kwargs))
            return f"Got an unexpected keyword argument '{unexpected_arg}'"

        try:
            id = id if id else self._microvm_id
            return self._vmm.update_vmm_state(id, "Paused")

        except Exception as e:
            raise VMMError(str(e))

    def resume(self, id=None, **kwargs):
        """Resume the configured microVM.

        Args:
            id (str, optional): ID of the VMM to resume. If not provided,
                uses the current VMM's ID.

        Returns:
            str: Status message indicating the result of the resume operation.

        Raises:
            FirecrackerError: If the resume operation fails.
        """
        if kwargs:
            unexpected_arg = next(iter(kwargs))
            return f"Got an unexpected keyword argument '{unexpected_arg}'"

        try:
            id = id if id else self._microvm_id
            return self._vmm.update_vmm_state(id, "Resumed")

        except Exception as e:
            raise VMMError(str(e))

    def delete(self, id=None, all=False, **kwargs) -> str:
        """Delete a specific VMM or all VMMs and clean up associated resources.

        Args:
            id (str, optional): The ID of the VMM to delete. If not provided, the current VMM's ID is used.
            all (bool, optional): If True, delete all running VMMs. Defaults to False.

        Returns:
            str: A status message indicating the result of the deletion operation.

        Raises:
            FirecrackerError: If an error occurs during the deletion process.
        """
        if kwargs:
            unexpected_arg = next(iter(kwargs))
            return f"Got an unexpected keyword argument '{unexpected_arg}'"

        try:
            id = id if id else self._microvm_id

            if not id and not all:
                return "No VMM ID specified for deletion"

            if not self._vmm.list_vmms():
                return "No VMMs available to delete"

            if all:
                self._vmm.delete_vmms()
                return "All VMMs deleted successfully"

            self._vmm.delete_vmms(id)
            return f"VMM {id} deleted successfully"

        except Exception as e:
            raise VMMError(str(e))

    def connect(self, id=None, username: str = None, key_path: str = None, **kwargs):
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
        if kwargs:
            unexpected_arg = next(iter(kwargs))
            return f"Got an unexpected keyword argument '{unexpected_arg}'"

        if not key_path:
            return "SSH key path is required"

        if not os.path.exists(key_path):
            return f"SSH key file not found: {key_path}"

        try:
            if not self._vmm.list_vmms():
                return "No VMMs available to connect"

            microvm_id = id if id else self._microvm_id
            available_vmm_ids = [vmm['id'] for vmm in self._vmm.list_vmms()]

            if microvm_id not in available_vmm_ids:
                return f"VMM with ID {microvm_id} does not exist"

            ip_addr = self._vmm.get_vmm_ip_addr(microvm_id)

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
                            f"Unable to connect to the VMM {microvm_id or self._microvm_id} via SSH after {max_retries} attempts: {str(e)}"
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

            message = f"SSH session to VMM {microvm_id or self._microvm_id} closed"
            print(f"\n{message}\n")

        except Exception as e:
            raise VMMError(str(e))

    def port_forward(self, id=None, host_port: int = None, dest_port: int = None, remove: bool = False, **kwargs):
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
        if kwargs:
            unexpected_arg = next(iter(kwargs))
            return f"Got an unexpected keyword argument '{unexpected_arg}'"

        try:
            if not self._vmm.list_vmms():
                return "No VMMs available to forward ports"

            id = id if id else self._microvm_id
            available_vmm_ids = [vmm['id'] for vmm in self._vmm.list_vmms()]
            if id not in available_vmm_ids:
                return f"VMM with ID {id} does not exist"

            host_ip = get_public_ip()
            dest_ip = self._vmm.get_vmm_ip_addr(id)

            if remove:
                self._network.delete_port_forward(host_ip, host_port, dest_ip, dest_port)
                return f"Port forwarding rule removed: {host_ip}:{host_port} -> {dest_ip}:{dest_port}"

            self._network.add_port_forward(id, host_ip, host_port, dest_ip, dest_port)
            return f"Port forwarding active: {host_ip}:{host_port} -> {dest_ip}:{dest_port}"

        except Exception as e:
            raise VMMError(str(e))

    def _basic_config(self):
        """Configure the microVM with basic settings.

        This method orchestrates the configuration of various components:
        - Boot source
        - Root drive
        - Machine resources (vCPUs and memory)
        - Network interface
        - MMDS (if enabled)
        """
        try:
            self._configure_vmm_boot_source()
            self._configure_vmm_root_drive()
            self._configure_vmm_resources()
            self._configure_vmm_network()
            if self._mmds_enabled:
                self._configure_vmm_mmds()

        except Exception as exc:
            raise ConfigurationError(str(exc))

    @property
    def _boot_args(self):
        """Generate boot arguments using current configuration."""
        if self._mmds_enabled:
            return (
                "console=ttyS0 reboot=k panic=1 pci=off "
                f"ds=nocloud-net;s=http://{self._mmds_ip}/latest/ "
                f"ip={self._ip_addr}::{self._gateway_ip}:255.255.255.0:{self._hostname}:{self._iface_name}:off "
            )
        else:
            return (
                "console=ttyS0 reboot=k panic=1 pci=off "
                f"ip={self._ip_addr}::{self._gateway_ip}:255.255.255.0:{self._hostname}:{self._iface_name}:off "
            )

    def _configure_vmm_boot_source(self):
        """Configure the boot source for the microVM."""
        try:
            if self._config.verbose:
                self._logger.info("Configuring boot source...")

            boot_response = self._api.boot.put(
                kernel_image_path=self._kernel_file,
                boot_args=self._boot_args
            )

            if self._config.verbose:
                self._logger.info("Boot source configured")
                self._logger.debug(f"Boot configuration response: {boot_response}")

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

        except Exception as e:
            raise ConfigurationError(f"Failed to configure root drive: {str(e)}")

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

            mmds_response = self._api.mmds_config.put(
                version="V2",
                ipv4_address=self._mmds_ip,
                network_interfaces=[self._iface_name]
            )

            if self._config.verbose:
                self._logger.debug(f"MMDS network configuration response: {mmds_response}")
                self._logger.info("Setting MMDS data...")

            mmds_data_response = self._api.mmds.put(latest=self._user_data)

            if self._config.verbose:
                self._logger.debug(f"MMDS data response: {mmds_data_response}")

        except Exception as e:
            raise ConfigurationError(f"Failed to configure MMDS: {str(e)}")

    def _spawn(self) -> Tuple[Api, int]:
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
            retries = 0
            while retries < max_retries:
                if not psutil.pid_exists(int(screen_pid)):
                    raise ProcessError("Firecracker process is not running")

                if os.path.exists(self._socket_file):
                    return Api(self._socket_file)

                retries += 1
                time.sleep(0.5)

            raise APIError(
                f"Failed to connect to the API socket after {max_retries} attempts"
            )

        except Exception as exc:
            self._vmm.cleanup_resources(self._microvm_id)
            raise VMMError(str(exc))
