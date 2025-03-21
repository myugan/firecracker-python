import os
import re
import psutil
from datetime import datetime
from typing import List, Dict
from firecracker.utils import run
from firecracker.logger import Logger
from firecracker.api import Api
from firecracker.config import MicroVMConfig
from firecracker.network import NetworkManager
from firecracker.process import ProcessManager
from firecracker.utils import requires_id
from firecracker.exceptions import VMMError


class VMMManager:
    """Manages Virtual Machine Monitor (VMM) instances.

    Handles the lifecycle and configuration of Firecracker VMM instances,
    including creation, monitoring, and cleanup of VMM processes.

    Attributes:
        logger (Logger): Logger instance for VMM operations
    """
    def __init__(self, verbose: bool = False, level: str = "INFO"):
        self._logger = Logger(level=level, verbose=verbose)
        self._config = MicroVMConfig()
        self._config.verbose = verbose
        self._network = NetworkManager(verbose=verbose)
        self._process = ProcessManager(verbose=verbose)
        self._api = None

    def get_api(self, id: str) -> Api:
        """Get an API instance for a given VMM ID."""
        socket_file = f"{self._config.data_path}/{id}/firecracker.socket"
        return Api(socket_file)

    def list_vmms(self) -> List[Dict]:
        """List all running Firecracker VMMs with their details."""
        try:
            vmm_list = []
            screen_process = run("screen -ls || true")
            pattern = r'(\d+)\.fc_([^\s]+)'
            matches = re.findall(pattern, screen_process.stdout)

            if not matches:
                return []

            for pid, session_name in matches:
                fc_pid = int(pid)
                vmm_id = session_name

                process = psutil.Process(fc_pid)
                ip_addr = self.get_vmm_ip_addr(vmm_id)
                state = self.get_vmm_state(vmm_id)
                create_time = datetime.fromtimestamp(
                    process.create_time()
                ).strftime('%Y-%m-%d %H:%M:%S')

                vmm_list.append({
                    'id': vmm_id,
                    'pid': fc_pid,
                    'ip_addr': ip_addr,
                    'state': state,
                    'created_at': create_time
                })

            return vmm_list

        except Exception as e:
            raise VMMError(f"Error listing VMMs: {str(e)}")

    def update_vmm_state(self, id: str, state: str) -> str:
        """Update VM state (pause/resume).

        Args:
            state (str): Target state ("Paused" or "Resumed")

        Returns:
            str: Status message
        """
        try:
            api = self.get_api(id)
            response = api.vm.patch(state=state)

            if self._config.verbose:
                self._logger.info(
                    f"Changed VMM {id} state response: {response}"
                )

            return f"{state} VMM {id} successfully"

        except Exception as e:
            raise VMMError(f"Failed to {state.lower()} VMM {id}: {str(e)}")

        finally:
            api.close()

    @requires_id
    def get_vmm_config(self, id: str) -> Dict:
        """Get the configuration for a specific VMM.

        Args:
            id (str): ID of the VMM to query

        Returns:
            dict: VMM configuration

        Raises:
            RuntimeError: If VMM ID is invalid or VMM is not running
        """
        try:
            api = self.get_api(id)
            response = api.vm_config.get().json()

            if self._config.verbose:
                self._logger.info(
                    f"VMM {id} configuration response: {response}"
                )

            return response

        except Exception as e:
            raise VMMError(f"Failed to get VMM configuration: {str(e)}")

        finally:
            api.close()

    def get_vmm_state(self, id: str) -> str:
        """Get the state of a specific VMM.

        Args:
            id (str): ID of the VMM to query

        Returns:
            str: VMM state ('Running', 'Paused', 'Unknown', etc.)

        Raises:
            VMMError: If VMM state cannot be retrieved
        """
        try:
            api = self.get_api(id)
            response = api.describe.get().json()
            state = response.get('state')

            if isinstance(state, str) and state.strip():
                return state

            return 'Unknown'

        except Exception as e:
            raise VMMError(f"Failed to get state for VMM {id}: {str(e)}")

        finally:
            api.close()

    def get_vmm_ip_addr(self, id: str) -> str:
        """Get the IP address of a specific VMM.

        Args:
            id (str): ID of the VMM to query

        Returns:
            str: IP address of the VMM

        Raises:
            VMMError: If no IP address is found or an error occurs after
                      retries
        """
        try:
            api = self.get_api(id,)
            vmm_config = api.vm_config.get().json()
            boot_args = vmm_config.get('boot-source', {}).get('boot_args', '')

            ip_match = re.search(r'ip=([0-9.]+)', boot_args)
            if ip_match:
                ip_addr = ip_match.group(1)
                return ip_addr

            else:
                if self._config.verbose:
                    self._logger.info(
                        f"No ip= found in boot-args for VMM {id}"
                    )
                return 'Unknown'

        except Exception as e:
            raise VMMError(
                f"Error while retrieving IP address for VMM {id}: {str(e)}"
            )

        finally:
            api.close()

    def create_vmm_dir(self, path: str):
        """Create directories for the microVM.

        Args:
            path (str): Path to the VMM directory to create
        """
        try:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
                if self._config.verbose:
                    self._logger.info(f"Created directory at {path}")

        except Exception as e:
            raise VMMError(f"Failed to create directory at {path}: {str(e)}")

    def create_log_file(self, id: str, log_file: str):
        """Create a log file for the microVM.

        Args:
            log_file (str): Name of the log file to create
        """
        try:
            log_dir = f"{self._config.data_path}/{id}/logs"

            if not os.path.exists(f"{log_dir}/{log_file}"):
                with open(f"{log_dir}/{log_file}", 'w'):
                    pass
                if self._config.verbose:
                    self._logger.info(f"Created log file {log_dir}/{log_file}")

        except Exception as e:
            raise VMMError(
                f"Unable to create log directory at {log_dir}: {str(e)}"
            )

    def delete_vmm_dir(self, id: str = None):
        """
        Clean up all resources associated with the microVM by removing the
        VMM directory.

        Args:
            id (str): ID of the VMM to delete
        """
        import shutil

        try:
            vmm_dir = f"{self._config.data_path}/{id}"

            if os.path.exists(vmm_dir):
                shutil.rmtree(vmm_dir)

            if self._config.verbose:
                self._logger.info(f"Directory {vmm_dir} removed")

        except Exception as e:
            raise VMMError(f"Failed to remove {vmm_dir} directory: {str(e)}")

    def delete_vmms(self, vmm_id: str = None) -> str:
        """Delete VMM instances.

        Args:
            vmm_id (str, optional): ID of the VMM to delete. If None, delete all VMMs.

        Returns:
            str: Status message indicating success or failure
        """
        try:
            if self._config.verbose:
                if vmm_id:
                    self._logger.info(f"Deleting VMM {vmm_id}")
                else:
                    self._logger.info("Deleting all VMMs")

            vmm_list = self.list_vmms()

            if vmm_id:
                if not any(vmm['id'] == vmm_id for vmm in vmm_list):
                    return f"VMM with ID {vmm_id} not found"
                vmm_ids = [vmm_id]
            else:
                vmm_ids = [vmm['id'] for vmm in vmm_list]

            for vmm_id in vmm_ids:
                self.cleanup_resources(vmm_id)

        except Exception as e:
            raise VMMError(f"Error deleting VMM(s): {str(e)}")

    def cleanup_resources(self, vmm_id=None):
        """Clean up network and process resources for a VMM."""
        try:
            if self._config.verbose:
                self._logger.info(f"Cleaning up VMM {vmm_id}")

            self._process.cleanup_screen_session(f"fc_{vmm_id}")
            self._network.cleanup(f"tap_{vmm_id}")
            self.delete_vmm_dir(vmm_id)

        except Exception as e:
            raise VMMError(f"Failed to cleanup VMM {vmm_id}: {str(e)}") from e

    def _ensure_socket_file(self, vmm_id: str) -> str:
        """Ensure the socket file is ready for use, unlinking if necessary.

        Returns:
            str: Path to the socket file

        Raises:
            VMMError: If unable to create or verify the socket file
        """
        try:
            socket_file = f"{self._config.data_path}/{vmm_id}/firecracker.socket"

            if os.path.exists(socket_file):
                os.unlink(socket_file)
                if self._config.verbose:
                    self._logger.info(
                        f"Unlinked existing socket file {socket_file}"
                    )

            self.create_vmm_dir(f"{self._config.data_path}/{vmm_id}")
            return socket_file

        except OSError as e:
            raise VMMError(f"Failed to ensure socket file {socket_file}: {e}")
