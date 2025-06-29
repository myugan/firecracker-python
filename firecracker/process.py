import os
import time
import psutil
import subprocess
from datetime import datetime
from firecracker.logger import Logger
from firecracker.config import MicroVMConfig
from firecracker.exceptions import ProcessError
from tenacity import retry, stop_after_delay, wait_fixed, retry_if_exception_type


class ProcessManager:
    """Manages process-related operations for Firecracker microVMs."""

    def __init__(self, verbose: bool = False, level: str = "INFO"):
        self._logger = Logger(level=level, verbose=verbose)
        self._config = MicroVMConfig()
        self._config.verbose = verbose

    def start(self, id: str, args: list) -> str:
        """Start a Firecracker process.
        
        Args:
            id (str): The ID of the Firecracker VM
            args (list): List of command arguments
            
        Returns:
            str: Process ID if successful
            
        Raises:
            ProcessError: If process fails to start or becomes defunct
        """
        try:
            cmd = [self._config.binary_path] + args

            process = subprocess.Popen(
                cmd,
                stdout=open(f"{self._config.data_path}/{id}/firecracker.log", "w"),
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
            
            if process.poll() is None:
                proc = psutil.Process(process.pid)
                if proc.status() == psutil.STATUS_ZOMBIE:
                    raise ProcessError("Firecracker process became defunct")

                with open(f"{self._config.data_path}/{id}/firecracker.pid", "w") as f:
                    f.write(str(process.pid))
                    
                if self._logger.verbose:
                    self._logger.debug(f"Firecracker process started with PID: {process.pid}")

                return process.pid

        except Exception as e:
            raise ProcessError(f"Failed to start Firecracker: {str(e)}")

    @retry(
        stop=stop_after_delay(3),
        wait=wait_fixed(0.5),
        retry=retry_if_exception_type(ProcessError)
    )
    def is_running(self, id: str) -> bool:
        """Check if Firecracker is running."""
        try:
            if os.path.exists(f"{self._config.data_path}/{id}/firecracker.pid"):
                with open(f"{self._config.data_path}/{id}/firecracker.pid", "r") as f:
                    pid = int(f.read().strip())

                try:
                    os.kill(pid, 0)
                    if self._logger.verbose:
                        self._logger.debug(f"Firecracker is running with PID: {pid}")
                    return True
                except OSError:
                    if self._logger.verbose:
                        self._logger.info("Firecracker is not running (stale PID file)")
                    os.remove(f"{self._config.data_path}/{id}/firecracker.pid")
                    return False
            else:
                if self._logger.verbose:
                    self._logger.info("Firecracker is not running")
                return False

        except Exception as e:
            if self._logger.verbose:
                self._logger.error(f"Error checking status: {e}")
            return False

    def stop(self, id: str) -> bool:
        """Stop Firecracker."""
        try:
            if os.path.exists(f"{self._config.data_path}/{id}/firecracker.pid"):
                with open(f"{self._config.data_path}/{id}/firecracker.pid", "r") as f:
                    pid = int(f.read().strip())

                os.kill(pid, 15)
                time.sleep(0.5)

                try:
                    os.kill(pid, 0)
                    os.kill(pid, 9)
                    if self._logger.verbose:
                        self._logger.info(f"Firecracker process {pid} force killed")
                except OSError:
                    if self._logger.verbose:
                        self._logger.info(f"Firecracker process {pid} terminated")
                
                os.remove(f"{self._config.data_path}/{id}/firecracker.pid")
                if self._logger.verbose:
                    self._logger.debug(f"Removed PID file: {pid}")

                if os.path.exists(f"{self._config.data_path}/{id}/firecracker.socket"):
                    os.remove(f"{self._config.data_path}/{id}/firecracker.socket")

                return True
            else:
                if self._logger.verbose:
                    self._logger.info("Firecracker is not running")
                return False

        except Exception as e:
            if self._logger.verbose:
                self._logger.error(f"Error stopping Firecracker: {e}")
            return False

    def get_pid(self, id: str) -> tuple:
        """Get the PID of the Firecracker process.
        
        Args:
            id (str): The ID of the Firecracker VM
            
        Returns:
            tuple: (pid, create_time) if process is found and running
            
        Raises:
            ProcessError: If the process is not found or not running
        """
        try:
            pid_file = f"{self._config.data_path}/{id}/firecracker.pid"
            if not os.path.exists(pid_file):
                raise ProcessError(f"No PID file found for VM {id}")
                
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())

            try:
                process = psutil.Process(pid)
                if not process.is_running():
                    os.remove(pid_file)
                    raise ProcessError(f"Firecracker process {pid} is not running")

                if process.name() != 'firecracker':
                    os.remove(pid_file)
                    raise ProcessError(f"Process {pid} is not a Firecracker process")

                create_time = datetime.fromtimestamp(
                    process.create_time()
                ).strftime('%Y-%m-%d %H:%M:%S')
                
                if self._logger.verbose:
                    self._logger.debug(f"Found Firecracker process {pid} created at {create_time}")

                return pid, create_time

            except psutil.NoSuchProcess:
                os.remove(pid_file)
                raise ProcessError(f"Firecracker process {pid} is not running")

            except psutil.AccessDenied:
                raise ProcessError(f"Access denied to process {pid}")

            except psutil.TimeoutExpired:
                raise ProcessError(f"Timeout while checking process {pid}")
                
        except Exception as e:
            raise ProcessError(f"Failed to get Firecracker PID: {str(e)}")

    def get_pids(self) -> list:
        """
        Get all PIDs of the Firecracker processes that have --api-sock parameter.
        
        Returns:
            list: List of process IDs (integers)
        """
        pid_list = []
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] == 'firecracker':
                        cmdline = proc.info['cmdline']
                        if cmdline and len(cmdline) > 1 and '--api-sock' in cmdline:
                            pid_list.append(proc.info['pid'])
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

        except Exception as e:
            raise ProcessError(f"Failed to get Firecracker processes: {str(e)}")
            
        return pid_list

    @staticmethod
    def wait_process_running(process: psutil.Process):
        """Wait for a process to run."""
        assert process.is_running()
