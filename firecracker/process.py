import os
import time
import psutil
import subprocess
from datetime import datetime
from firecracker.logger import Logger
from firecracker.config import MicroVMConfig
from firecracker.exceptions import ProcessError
from tenacity import (
    retry,
    stop_after_delay,
    wait_fixed,
    retry_if_exception_type,
    stop_after_attempt,
)


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

            log_path = f"{self._config.data_path}/{id}/firecracker.log"
            pid_path = f"{self._config.data_path}/{id}/firecracker.pid"

            # Get parent's process group
            parent_pgid = os.getpgid(0)

            process = subprocess.Popen(
                cmd,
                stdout=open(log_path, "w"),
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                # Explicitly set to parent's group
                preexec_fn=lambda: os.setpgid(0, parent_pgid),
            )

            time.sleep(0.2)

            if process.poll() is not None:
                raise ProcessError("Firecracker process exited during startup")

            proc = psutil.Process(process.pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                raise ProcessError("Firecracker process became defunct")

            try:
                proc.wait(timeout=1)
            except psutil.TimeoutExpired:
                pass
            except psutil.NoSuchProcess:
                raise ProcessError("Firecracker process disappeared during startup")

            with open(pid_path, "w") as f:
                f.write(str(process.pid))

            if self._logger.verbose:
                self._logger.debug(
                    f"Firecracker process started with PID: {process.pid}"
                )

            return process.pid

        except Exception as e:
            raise ProcessError(f"Failed to start Firecracker: {str(e)}")

    @retry(
        stop=stop_after_delay(3),
        wait=wait_fixed(0.5),
        retry=retry_if_exception_type(ProcessError),
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

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_fixed(0.5),
        retry=retry_if_exception_type((ProcessError, OSError)),
    )
    def stop(self, id: str) -> bool:
        """Stop Firecracker with retry mechanism.

        Args:
            id (str): The ID of the Firecracker VM

        Returns:
            bool: True if successfully stopped, False otherwise

        Raises:
            ProcessError: If process fails to stop after retries
        """
        try:
            if os.path.exists(f"{self._config.data_path}/{id}/firecracker.pid"):
                with open(f"{self._config.data_path}/{id}/firecracker.pid", "r") as f:
                    original_pid = int(f.read().strip())

                # Try to stop using the PID from file
                if self._try_stop_process(original_pid, id):
                    self._cleanup_files(id)
                    return True

                # If PID-based stop failed, search for actual running process
                if self._logger.verbose:
                    self._logger.info(
                        f"PID {original_pid} not found, searching for running Firecracker process for VM {id}"
                    )

                actual_pid = self._find_running_process(id)
                if actual_pid:
                    if self._logger.verbose:
                        self._logger.info(
                            f"Found running Firecracker process {actual_pid} for VM {id}"
                        )
                    if self._try_stop_process(actual_pid, id):
                        self._cleanup_files(id)
                        return True
                else:
                    if self._logger.verbose:
                        self._logger.info(
                            f"No running Firecracker process found for VM {id}"
                        )

                # Clean up files even if no process found
                self._cleanup_files(id)
                return True
            else:
                if self._logger.verbose:
                    self._logger.info("Firecracker is not running (no PID file)")
                return False

        except Exception as e:
            if self._logger.verbose:
                self._logger.error(f"Error stopping Firecracker: {e}")
            raise ProcessError(f"Failed to stop Firecracker {id}: {str(e)}")

    def _try_stop_process(self, pid: int, id: str) -> bool:
        """Try to stop a specific process by PID.

        Args:
            pid (int): Process ID to stop
            id (str): VM ID for logging

        Returns:
            bool: True if process was successfully stopped

        Raises:
            ProcessError: If process fails to stop
        """
        try:
            os.kill(pid, 15)  # SIGTERM
            time.sleep(0.5)
        except OSError as e:
            if e.errno == 3:  # ESRCH - No such process
                if self._logger.verbose:
                    self._logger.info(f"Firecracker process {pid} already terminated")
                return True
            else:
                raise ProcessError(f"Failed to send SIGTERM to process {pid}: {e}")

        # Check if process is still running
        try:
            os.kill(pid, 0)  # Check if process exists
            # Process still running, try force kill
            os.kill(pid, 9)  # SIGKILL
            time.sleep(0.2)

            # Verify process is actually killed
            try:
                os.kill(pid, 0)
                raise ProcessError(
                    f"Firecracker process {pid} still running after SIGKILL"
                )
            except OSError:
                if self._logger.verbose:
                    self._logger.info(f"Firecracker process {pid} force killed")
                return True

        except OSError as e:
            if e.errno == 3:  # ESRCH - No such process
                if self._logger.verbose:
                    self._logger.info(f"Firecracker process {pid} terminated")
                return True
            else:
                raise ProcessError(f"Failed to kill process {pid}: {e}")

    def _find_running_process(self, id: str) -> int:
        """Find the actual running Firecracker process for a given VM ID.

        Args:
            id (str): The VM ID to search for

        Returns:
            int: Process ID if found, None otherwise
        """
        try:
            socket_path = f"{self._config.data_path}/{id}/firecracker.socket"

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    if proc.info["name"] == "firecracker":
                        cmdline = proc.info["cmdline"]
                        if cmdline and len(cmdline) > 1:
                            # Check if this process uses the same socket path
                            for i, arg in enumerate(cmdline):
                                if arg == "--api-sock" and i + 1 < len(cmdline):
                                    if cmdline[i + 1] == socket_path:
                                        return proc.info["pid"]
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    continue

        except Exception as e:
            if self._logger.verbose:
                self._logger.warning(f"Error searching for running process: {e}")

        return None

    def _cleanup_files(self, id: str):
        """Clean up PID and socket files for a VM.

        Args:
            id (str): The VM ID
        """
        # Clean up PID file
        pid_file = f"{self._config.data_path}/{id}/firecracker.pid"
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
                if self._logger.verbose:
                    self._logger.debug(f"Removed PID file for VM {id}")
            except OSError as e:
                if self._logger.verbose:
                    self._logger.warning(f"Failed to remove PID file: {e}")

        # Clean up socket file
        socket_path = f"{self._config.data_path}/{id}/firecracker.socket"
        if os.path.exists(socket_path):
            try:
                os.remove(socket_path)
                if self._logger.verbose:
                    self._logger.debug(f"Removed socket file: {socket_path}")
            except OSError as e:
                if self._logger.verbose:
                    self._logger.warning(f"Failed to remove socket file: {e}")

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

                if process.name() != "firecracker":
                    os.remove(pid_file)
                    raise ProcessError(f"Process {pid} is not a Firecracker process")

                create_time = datetime.fromtimestamp(process.create_time()).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                if self._logger.verbose:
                    self._logger.debug(
                        f"Found Firecracker process {pid} created at {create_time}"
                    )

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
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    if proc.info["name"] == "firecracker":
                        cmdline = proc.info["cmdline"]
                        if cmdline and len(cmdline) > 1 and "--api-sock" in cmdline:
                            pid_list.append(proc.info["pid"])
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    continue

        except Exception as e:
            raise ProcessError(f"Failed to get Firecracker processes: {str(e)}")

        return pid_list

    @staticmethod
    def wait_process_running(process: psutil.Process):
        """Wait for a process to run."""
        assert process.is_running()
