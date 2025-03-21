"""Custom exceptions for the Firecracker library."""


class FirecrackerError(Exception):
    """Base exception for all Firecracker errors."""
    def __init__(self, message: str, *args, **kwargs):
        self.message = message
        super().__init__(message, *args)


class NetworkError(FirecrackerError):
    """Network-related errors."""
    pass


class ConfigurationError(FirecrackerError):
    """Configuration-related errors."""
    pass


class VMMError(FirecrackerError):
    """VMM operation errors."""
    pass


class APIError(FirecrackerError):
    """API-related errors."""
    pass


class ProcessError(FirecrackerError):
    """Process management errors."""
    pass
