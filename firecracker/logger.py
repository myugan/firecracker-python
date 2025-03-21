import logging


class Logger:
    """Custom logger class for MicroVM operations."""
    COLORS = {
        "INFO": "\033[0m",
        "ERROR": "\033[91m",
        "WARN": "\033[93m",
        "DEBUG": "\033[94m",
    }
    RESET = "\033[0m"

    LEVEL_MAP = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
    }

    def __init__(self, level: str = "INFO", verbose: bool = False):
        """Initialize the logger with custom configuration.

        Args:
            level (str): Initial log level (INFO, ERROR, SUCCESS, WARN, DEBUG)
            verbose (bool): Enable verbose (DEBUG) logging
        """
        self.logger = logging.getLogger('microvm')
        self.verbose = verbose

        console_handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "\r[%(asctime)s.%(msecs)03d] [%(colored_levelname)s] %(message)s",
            "%Y-%m-%dT%H:%M:%S"
        )
        console_handler.addFilter(self._add_colored_levelname)
        console_handler.setFormatter(formatter)

        if not self.logger.handlers:
            self.logger.addHandler(console_handler)

        self.set_level(level)

    def _add_colored_levelname(self, record):
        """Add colored levelname to the log record."""
        level = record.levelname
        if level == "INFO" and getattr(record, "success", False):
            level = "SUCCESS"
        color = self.COLORS.get(level, self.COLORS["INFO"])
        record.colored_levelname = f"{color}{level}{self.RESET}"
        return True

    def set_level(self, level: str):
        """Set the logging level.

        Args:
            level (str): Log level to set (INFO, ERROR, WARN, DEBUG)
        """
        logging_level = self.LEVEL_MAP.get(level, logging.INFO)
        self.logger.setLevel(logging_level)
        self.current_level = level

    def __call__(self, level: str, message: str):
        """Log a message at the specified level.

        Args:
            level (str): Level to log at (INFO, ERROR, WARN, DEBUG)
            message (str): Message to log
        """
        if level not in self.LEVEL_MAP:
            level = "INFO"  # Default to INFO for unknown levels

        log_method = getattr(self.logger, level.lower())
        log_method(message)

    def info(self, message: str):
        """Log an info message."""
        self("INFO", message)

    def error(self, message: str):
        """Log an error message."""
        self("ERROR", message)

    def warn(self, message: str):
        """Log a warning message."""
        self("WARN", message)

    def debug(self, message: str):
        """Log a debug message."""
        self("DEBUG", message)
