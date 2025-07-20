import os
import re
import json
from typing import List, Dict
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
        self._network = NetworkManager(verbose=verbose, level=level)
        self._process = ProcessManager(verbose=verbose, level=level)
        self._api = None

    def get_api(self, id: str) -> Api:
        """Get an API instance for a given VMM ID."""
        socket_file = f"{self._config.data_path}/{id}/firecracker.socket"
        return Api(socket_file)

    def create_vmm_json_file(self, id: str, **kwargs):
        """Create a JSON file for a VMM.

        Args:
            id (str): VMM ID
            **kwargs: Keyword arguments for the VMM

        Returns:
            str: Path to the created config file

        Raises:
            VMMError: If file creation fails
        """
        vm_data = {
            "ID": kwargs.get("ID", id),
            "Name": kwargs.get("Name", ""),
            "CreatedAt": kwargs.get("CreatedAt", ""),
            "Rootfs": kwargs.get("Rootfs", self._config.base_rootfs),
            "Kernel": kwargs.get("Kernel", self._config.kernel_file),
            "State": {
                "Pid": kwargs.get("Pid", ""),
                "Running": kwargs.get("Running", True),
                "Paused": kwargs.get("Paused", False),
            },
            "Network": {
                f"tap_{id}": {
                    "IPAddress": kwargs.get("IPAddress", "")
                }
            },
            "Ports": kwargs.get("Ports", {}),
            "Labels": kwargs.get("Labels", {}),
            "LogPath": kwargs.get("LogPath", f"{self._config.data_path}/{id}/logs")
        }

        try:
            vmm_dir = f"{self._config.data_path}/{id}"
            os.makedirs(vmm_dir, exist_ok=True)
            
            file_path = f"{vmm_dir}/config.json"
            with open(file_path, 'w') as json_file:
                json.dump(vm_data, json_file, indent=4)

            if self._config.verbose:
                self._logger.debug(f"Created VMM config file: {file_path}")

            return file_path

        except Exception as e:
            raise VMMError(f"Failed to create VMM config file: {str(e)}") from e

    def list_vmm(self) -> List[Dict]:
        """List all VMMs using their config.json files.

        Returns:
            List[Dict]: List of dictionaries containing VMM details
        """
        vmm_list = []

        running_pids = set(self._process.get_pids())
        has_running_vmms = bool(running_pids)

        vmm_id_pattern = re.compile(r'^[a-zA-Z0-9]{8}$')
        
        data_path = self._config.data_path
        
        try:
            # Use listdir with error handling
            vmm_dirs = os.listdir(data_path)
        except OSError as e:
            self._logger.error(f"Failed to read data directory {data_path}: {e}")
            return vmm_list
        
        for vmm_id in vmm_dirs:
            # Early validation - skip non-matching IDs
            if not vmm_id_pattern.match(vmm_id):
                continue
                
            vmm_path = os.path.join(data_path, vmm_id)

            config_path = os.path.join(vmm_path, 'config.json')
            if not (os.path.isdir(vmm_path) and os.path.exists(config_path)):
                if has_running_vmms and self._config.verbose:
                    self._logger.info(f"Config file not found for VMM ID: {vmm_id}")
                continue

            try:
                with open(config_path, 'r') as config_file:
                    config_data = json.load(config_file)
                    
                pid = config_data.get('State', {}).get('Pid', '')
                
                if pid and pid in running_pids:
                    network_key = f"tap_{vmm_id}"
                    network_info = config_data.get('Network', {}).get(network_key, {})
                    ports_info = config_data.get('Ports', {})
                    
                    vmm_info = {
                        "id": config_data.get('ID', vmm_id),
                        "name": config_data.get('Name', ''),
                        "pid": pid,
                        "ip_addr": network_info.get("IPAddress", ''),
                        "state": 'Running' if config_data.get('State', {}).get('Running', False) else 'Paused',
                        "created_at": config_data.get('CreatedAt', ''),
                        "ports": ports_info,
                        "labels": config_data.get('Labels', {})
                    }
                    vmm_list.append(vmm_info)
                    
            except (json.JSONDecodeError, IOError) as e:
                if self._config.verbose:
                    self._logger.warning(f"Failed to read config for VMM {vmm_id}: {e}")
                continue

        return vmm_list

    def find_vmm_by_id(self, id: str) -> str:
        """Find a VMM by ID and return its ID.

        Args:
            id (str): ID of the VMM to find

        Returns:
            str: ID of the found VMM or error message
        """
        try:
            vmm_list = self.list_vmm()
            for vmm_info in vmm_list:
                if vmm_info['id'] == id:
                    return vmm_info['id']

            return f"VMM with ID {id} not found"

        except Exception as e:
            raise VMMError(f"Error finding VMM by ID: {str(e)}")

    def find_vmm_by_labels(self, state: str, labels: Dict[str, str]) -> List[str]:
        """Find VMMs by state (Running or Paused) and multiple labels, and return their IDs.

        Args:
            state (str): State to filter by ('Running' or 'Paused')
            labels (Dict[str, str]): Dictionary of labels to search for

        Returns:
            List[str]: List of VMM IDs that match the state and all the labels
        """
        try:
            matching_vmm_ids = []

            vmm_list = self.list_vmm()
            
            if not vmm_list:
                return matching_vmm_ids

            state_matching_vmms = [
                vmm_info for vmm_info in vmm_list 
                if vmm_info['state'] == state
            ]
            
            if not state_matching_vmms:
                return matching_vmm_ids
            
            for vmm_info in state_matching_vmms:
                vmm_id = vmm_info['id']
                config_path = os.path.join(self._config.data_path, vmm_id, 'config.json')
                
                if not os.path.exists(config_path):
                    continue
                    
                try:
                    with open(config_path, 'r') as config_file:
                        config_data = json.load(config_file)
                    
                    vmm_labels = config_data.get('Labels', {})
                    if all(vmm_labels.get(key) == value for key, value in labels.items()):
                        vmm_info = {
                            'id': config_data.get('ID', vmm_id),
                            'name': config_data.get('Name', ''),
                            'state': "Running" if config_data.get('State', {}).get('Running', False) else "Paused",
                            'created_at': config_data.get('CreatedAt', ''),
                        }
                        matching_vmm_ids.append(vmm_info)
                        
                except (json.JSONDecodeError, IOError) as e:
                    if self._config.verbose:
                        self._logger.warning(f"Failed to read config for VMM {vmm_id}: {e}")
                    continue

            return matching_vmm_ids

        except Exception as e:
            raise VMMError(f"Error finding VMM by labels: {str(e)}")

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
                self._logger.debug(
                    f"Changed VMM {id} state response: {response}"
                )

            return f"{state} VMM {id} successfully"

        except Exception as e:
            raise VMMError(f"Failed to {state.lower()} VMM {id}: {str(e)}")

        finally:
            if api:
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
                self._logger.debug(
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
            if api:
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
            api = self.get_api(id)
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

    def check_network_overlap(self, ip_addr: str) -> bool:
        """Check if the network configuration overlaps with another VMM.

        Args:
            ip_addr (str): IP address to check for overlap

        Returns:
            bool: True if the IP address overlaps, False otherwise.
        """
        try:
            vmm_list = self.list_vmm()
            
            existing_ips = {
                vmm_info['ip_addr'] 
                for vmm_info in vmm_list 
                if vmm_info.get('ip_addr') and vmm_info['ip_addr'] != 'Unknown'
            }

            return ip_addr in existing_ips

        except Exception as e:
            raise VMMError(f"Error checking network overlap: {str(e)}")

    def create_vmm_dir(self, path: str):
        """Create directories for the microVM.

        Args:
            path (str): Path to the VMM directory to create
        """
        try:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
                if self._config.verbose:
                    self._logger.info(f"Directory {path} is created")

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
                    self._logger.info(f"Log file {log_dir}/{log_file} is created")

        except Exception as e:
            raise VMMError(
                f"Unable to create log file at {log_dir}: {str(e)}"
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
                    self._logger.info(f"Directory {vmm_dir} is removed")

        except Exception as e:
            self._logger.error(f"Failed to remove {vmm_dir} directory: {str(e)}")
            raise VMMError(f"Failed to remove {vmm_dir} directory: {str(e)}")

    def delete_vmm(self, id: str = None) -> str:
        """Delete VMM instances from the config.json file.

        Args:
            id (str, optional): ID of specific VMM to delete. If None, deletes all VMMs.

        Returns:
            str: Status message indicating deletion results
        """
        try:
            vmm_list = self.list_vmm()
            
            if not vmm_list:
                return "No VMMs found to delete"

            if id:
                if not any(vmm['id'] == id for vmm in vmm_list):
                    return f"VMM with ID {id} not found"
                ids_to_delete = [id]
            else:
                ids_to_delete = [vmm['id'] for vmm in vmm_list]

            deleted_count = 0
            for vmm_id in ids_to_delete:
                try:
                    self.cleanup(vmm_id)
                    deleted_count += 1
                    if self._config.verbose:
                        self._logger.info(f"Removed VMM {vmm_id}")
                except Exception as e:
                    self._logger.error(f"Failed to delete VMM {vmm_id}: {e}")
                    continue

            if id:
                return f"VMM {id} {'removed' if deleted_count > 0 else 'not found'}"
            else:
                return f"Deleted {deleted_count} VMM(s)"

        except Exception as e:
            raise VMMError(f"Error during VMM deletion: {str(e)}")

    def cleanup(self, id=None):
        """Clean up network and process resources for a VMM."""
        try:
            self._process.stop(id)
            self._network.cleanup(f"tap_{id}")
            self.delete_vmm_dir(id)

        except Exception as e:
            raise VMMError(f"Failed to cleanup VMM {id}: {str(e)}") from e

    def socket_file(self, id: str) -> str:
        """Ensure the socket file is ready for use, unlinking if necessary.

        Returns:
            str: Path to the socket file

        Raises:
            VMMError: If unable to create or verify the socket file
        """
        try:
            socket_file = f"{self._config.data_path}/{id}/firecracker.socket"

            if os.path.exists(socket_file):
                os.unlink(socket_file)
                if self._config.verbose:
                    self._logger.info(
                        f"Unlinked existing socket file {socket_file}"
                    )

            self.create_vmm_dir(f"{self._config.data_path}/{id}")
            return socket_file

        except OSError as e:
            raise VMMError(f"Failed to ensure socket file {socket_file}: {e}")
