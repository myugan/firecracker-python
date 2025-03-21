import os
from firecracker.config import MicroVMConfig
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


if __name__ == "__main__":
    check_firecracker_binary()
