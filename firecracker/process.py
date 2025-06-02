import re
import time
import psutil
import signal
import subprocess
from datetime import datetime
from firecracker.utils import run, safe_kill
from firecracker.logger import Logger
from firecracker.config import MicroVMConfig
from firecracker.exceptions import ProcessError


class ProcessManager:
    """Manages process-related operations for Firecracker microVMs."""

    FLUSH_CMD = "screen -S {session} -X colon 'logfile flush 0^M'"

    def __init__(self, verbose: bool = False, level: str = "INFO"):
        self._logger = Logger(level=level, verbose=verbose)
        self._config = MicroVMConfig()
        self._config.verbose = verbose

    def start_screen_process(self, screen_log: str, session_name: str,
                           binary_path: str, binary_params: list) -> str:
        """Start a binary process within a screen session.

        Args:
            screen_log (str): Path to screen log file
            session_name (str): Name for the screen session
            binary_path (str): Path to the binary to execute
            binary_params (list): Parameters for the binary

        Returns:
            str: Process ID of the screen session

        Raises:
            ProcessError: If the process fails to start or verify
        """
        try:
            start_cmd = "screen -L -Logfile {logfile} -dmS {session} {binary} {params}".format(
                logfile=screen_log,
                session=session_name,
                binary=binary_path,
                params=" ".join(binary_params)
            )

            run(start_cmd)

            get_screen_pid = run(
                f"screen -ls | grep {session_name} | head -1 | awk '{{print $1}}' | cut -d. -f1"
            )
            screen_pid = get_screen_pid.stdout.strip()
            if not screen_pid:
                raise ProcessError("Firecracker is not running")

            self._logger.info(f"Firecracker is running with PID: {screen_pid}")

            screen_ps = psutil.Process(int(screen_pid))
            self.wait_process_running(screen_ps)

            try:
                run(self.FLUSH_CMD.format(session=session_name))
            except subprocess.SubprocessError as e:
                raise ProcessError(f"Failed to configure screen flush: {str(e)}")

            return screen_pid

        except Exception:
            try:
                if screen_pid:
                    if self._logger.verbose:
                        self._logger.info(f"Killing screen session {screen_pid}")
                    safe_kill(int(screen_pid))
            except Exception as cleanup_error:
                raise ProcessError(f"Cleanup after failure error: {str(cleanup_error)}") from cleanup_error

    def cleanup_screen_session(self, session_name: str):
        """Clean up a screen session.

        Args:
            session_name (str): Name of the screen session to cleanup
        """
        try:
            run(f"screen -S {session_name} -X quit")
            time.sleep(0.5)

            screen_check = run(f"screen -ls | grep {session_name}")
            if screen_check.returncode == 0:
                # Get a list of PIDs - using more specific pattern matching
                cmd = f"screen -ls | grep '[0-9]\\.{session_name}' | awk '{{print $1}}' | cut -d. -f1"
                screen_pid_output = run(cmd).stdout.strip()

                if screen_pid_output:
                    for pid in screen_pid_output.splitlines():
                        try:
                            pid_int = int(pid.strip())
                            if self._logger.verbose:
                                self._logger.info(f"Killing screen session {pid_int}")
                            safe_kill(pid_int, signal.SIGKILL)
                            time.sleep(0.5)  # Ensure the process is terminated
                        except (ProcessLookupError, ValueError) as e:
                            self._logger.warn(f"Failed to kill process {pid}: {str(e)}")

                    return screen_pid_output.splitlines()[0] if screen_pid_output.splitlines() else None

            return None

        except Exception as e:
            self._logger.error(f"Failed to cleanup screen session: {str(e)}")
            raise ProcessError(f"Failed to cleanup screen session: {str(e)}")

    @staticmethod
    def wait_process_running(process: psutil.Process):
        """Wait for a process to run."""
        assert process.is_running()

    def is_process_running(self, id: str) -> bool:
        """Check if a process is running.

        Args:
            id (str): ID of the process to check

        Returns:
            bool: True if the process is running, False otherwise
        """
        try:
            screen_process = run(f"screen -ls | grep {id} | head -1")
            if screen_process.returncode == 0:
                screen_output = screen_process.stdout.strip()
                if "Dead" in screen_output:
                    return False

                match = re.search(r'\d+', screen_output)
                if match:
                    screen_pid = match.group(0)
                    if screen_pid:
                        process = psutil.Process(int(screen_pid))
                        return process.is_running()
            return False

        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            return False

    def get_pids(self, id: str):
        """Get the PIDs of all running Firecracker processes."""
        try:
            screen_process = run(f"screen -ls | grep {id} | head -1 | awk '{{print $1}}' | cut -d. -f1")
            if screen_process.returncode == 0:
                screen_pid = screen_process.stdout.strip()
                if screen_pid:
                    process = psutil.Process(int(screen_pid))
                    pid = process.pid
                    create_time = datetime.fromtimestamp(
                        process.create_time()
                    ).strftime('%Y-%m-%d %H:%M:%S')
                    return pid, create_time

        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            return False

    def get_all_pids(self):
        """Get the PIDs of all running processes."""
        try:
            pids = run("screen -ls | grep 'fc_' | awk '{print $1}' | cut -d. -f1")
            pid_list = []
            for pid in pids.stdout.strip().splitlines():
                pid_list.append(int(pid))
            return pid_list

        except Exception as e:
            raise ProcessError(f"Failed to get all PIDs: {str(e)}")
