import os
import random
import string
import signal
import requests
import subprocess
import socket
from faker import Faker


def run(cmd, **kwargs):
    """Execute a shell command with configurable options.

    Provides a convenient wrapper around subprocess.run with sensible defaults
    for shell command execution.

    Args:
        cmd (str): Shell command to execute
        **kwargs: Additional arguments to pass to subprocess.run
            Defaults if not specified:
            - shell=True: Enable shell command interpretation
            - capture_output=True: Capture stdout/stderr
            - text=True: Return string output instead of bytes

    Returns:
        subprocess.CompletedProcess: Process completion information including:
            - returncode: Exit code of the command
            - stdout: Standard output (if captured)
            - stderr: Standard error (if captured)

    Note:
        Default behavior can be overridden by passing explicit kwargs
    """
    default_kwargs = {
        'shell': True,
        'capture_output': True,
        'text': True
    }
    default_kwargs.update(kwargs)

    return subprocess.run(cmd, **default_kwargs)


def safe_kill(pid: int, sig: signal.Signals = signal.SIGTERM) -> bool:
    """Safely kill a process."""
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def generate_id() -> str:
    """Generate a random ID for the MicroVM instance.

    Returns:
        str: A random identifier (exactly 8 lowercase alphanumeric characters)
    """
    chars = string.ascii_lowercase + string.digits
    generated_id = ''.join(random.choice(chars) for _ in range(8))
    return generated_id


def generate_name() -> str:
    """Generate a random name for the MicroVM instance using Faker.

    Returns:
        str: A random name
    """
    fake = Faker()
    generated_name = fake.name().replace(' ', '_').lower()
    return generated_name


def generate_mac_address() -> str:
    """Generate a random MAC address for the MicroVM instance.

    Returns:
        str: A random MAC address in the format XX:XX:XX:XX:XX:XX
    """
    # Generate 6 random bytes
    mac_bytes = [random.randint(0, 255) for _ in range(6)]
    # Convert to hex and format with colons
    mac_address = ':'.join([f'{b:02x}' for b in mac_bytes])
    return mac_address


def requires_id(func):
    """Decorator to check if VMM ID is provided."""
    def wrapper(*args, **kwargs):
        id = kwargs.get('id') or (len(args) > 1 and args[1])
        if not id:
            raise RuntimeError("VMM ID required")
        return func(*args, **kwargs)
    return wrapper


def validate_hostname(hostname):
    """Validate hostname according to RFC 1123."""
    import re
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', hostname):
        raise ValueError(f"Invalid hostname: {hostname}")


def validate_ip_address(ip_addr: str) -> bool:
    """Validate an IP address according to standard format rules.

    Args:
        ip_addr (str): The IP address to validate

    Returns:
        bool: True if the IP address is valid

    Raises:
        Exception: If the IP address is invalid, with a descriptive message
    """
    if not ip_addr:
        raise Exception("IP address cannot be empty")

    try:
        # Test IP address format
        socket.inet_aton(ip_addr)

        # Check if the IP has exactly 4 parts
        ip_parts = ip_addr.split('.')
        if len(ip_parts) != 4:
            raise Exception(f"Invalid IP address format: {ip_addr}")

        # Check if any part is outside the valid range
        for part in ip_parts:
            if not (0 <= int(part) <= 255):
                raise Exception(f"IP address contains invalid octet: {part}")

        # Check if it's a reserved address (like .0 ending)
        if ip_parts[-1] == '0':
            raise Exception(
                f"IP address with .0 suffix is reserved: {ip_addr}"
            )

        return True

    except (socket.error, ValueError):
        raise Exception(f"Invalid IP address: {ip_addr}")


def get_public_ip(timeout: int = 5):
    """Get the public IP address."""
    URLS = [
        "https://ifconfig.me",
        "https://ipinfo.io/ip",
        "https://api.ipify.org"
    ]

    for url in URLS:
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text.strip()
        except requests.RequestException:
            continue

    raise RuntimeError("Failed to get public IP")
