import os
from .config import MicroVMConfig
from .exceptions import ConfigurationError


def check_firecracker_binary():
    """Check if Firecracker binary exists and is executable.

    Raises:
        ConfigurationError: If binary is not found or not executable
    """
    try:
        config = MicroVMConfig()
        binary_path = config.binary_path

        if not os.path.exists(binary_path):
            raise ConfigurationError(f"Firecracker binary not found at: {binary_path}")

        if not os.access(binary_path, os.X_OK):
            raise ConfigurationError(f"Firecracker binary is not executable at: {binary_path}")

    except Exception as e:
        raise ConfigurationError(f"Failed to check Firecracker binary: {str(e)}") from e

def create_firecracker_directory():
    """Create the Firecracker data directory if it doesn't exist.

    Raises:
        ConfigurationError: If directory creation fails
    """
    try:
        config = MicroVMConfig()
        data_path = config.data_path

        if not os.path.exists(data_path):
            os.makedirs(data_path, mode=0o755)
            print(f"Created Firecracker data directory at: {data_path}")

    except Exception as e:
        raise ConfigurationError(f"Failed to create Firecracker data directory: {str(e)}") from e


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("This script must be run as root.")

    check_firecracker_binary()
    create_firecracker_directory()
