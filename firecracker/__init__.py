from .microvm import MicroVM
from .api import Api
from .logger import Logger
from . import scripts

try:
    scripts.check_firecracker_binary()
    scripts.create_firecracker_directory()
except scripts.ConfigurationError as e:
    print(f"Warning: {e}")

try:
    from ._version import version as __version__
except ImportError:
    __version__ = "0.0.0"

__all__ = [
    "MicroVM",
    "Api",
    "Logger",
    "scripts",
    "__version__",
]
