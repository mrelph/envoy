"""Structured logging module for the Envoy agent framework."""

import functools
import glob
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from typing import Callable


@dataclass
class LogEntry:
    """A single structured log record for the Envoy agent."""

    timestamp: str
    level: str
    event_type: str
    message: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str | None = None
    request_id: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize this LogEntry to a single-line JSON string."""

        def _default(obj):
            """Fallback serializer for non-serializable values."""
            return repr(obj)

        data = asdict(self)
        return json.dumps(data, default=_default, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "LogEntry":
        """Deserialize a JSON string back to a LogEntry."""
        data = json.loads(json_str)
        return cls(**data)

# Valid log levels in severity order
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}


class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs LogEntry JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        if hasattr(record, "log_entry") and isinstance(record.log_entry, LogEntry):
            return record.log_entry.to_json()
        # Fallback for non-LogEntry records
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=record.levelname,
            event_type="status",
            message=record.getMessage(),
        )
        return entry.to_json()


class _ConsoleFilter(logging.Filter):
    """Filter that only allows records at or above a given level."""

    def __init__(self, min_level: int):
        super().__init__()
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.min_level


class EnvoyLogger:
    """Singleton structured logger for the Envoy agent."""

    _instance: "EnvoyLogger | None" = None

    def __init__(
        self,
        log_dir: str = "~/.envoy/logs/",
        file_level: str = "INFO",
        console_level: str = "WARNING",
        retention_days: int = 14,
        max_output_length: int = 500,
    ):
        self.log_dir = os.path.expanduser(log_dir)
        self.max_output_length = max_output_length
        self.retention_days = retention_days
        self._session_id: str | None = None
        self._request_id: str | None = None
        self._callbacks: list[Callable[[LogEntry], None]] = []

        # Read environment overrides
        self._file_level = self._resolve_level(
            os.environ.get("ENVOY_LOG_LEVEL", file_level)
        )
        self._console_level = console_level
        self._retention_days = self._resolve_retention(
            os.environ.get("ENVOY_LOG_RETENTION_DAYS"), retention_days
        )

        # Set up Python logging
        self._logger = logging.getLogger("envoy")
        self._logger.setLevel(logging.DEBUG)  # Let handlers decide filtering
        self._logger.propagate = False

        # Remove any existing handlers to avoid duplicates on re-init
        self._logger.handlers.clear()

        # JSON formatter shared by all handlers
        formatter = JSONFormatter()

        # File handler
        self._file_handler = None
        self._setup_file_handler(formatter)

        # Console handler
        self._setup_console_handler(formatter)

        # Run cleanup on init
        try:
            self.cleanup_old_logs()
        except Exception:
            pass

    def _resolve_level(self, level_str: str) -> str:
        """Resolve a log level string, falling back to INFO on invalid input."""
        if level_str and level_str.upper() in _VALID_LEVELS:
            return level_str.upper()
        # Invalid level — will emit warning after logger is set up
        self._pending_level_warning = level_str
        return "INFO"

    def _resolve_retention(self, env_val: str | None, default: int) -> int:
        """Resolve retention days from env, falling back to default on invalid input."""
        if env_val is None:
            return default
        try:
            days = int(env_val)
            if days < 0:
                raise ValueError("negative")
            return days
        except (ValueError, TypeError):
            return default

    def _setup_file_handler(self, formatter: JSONFormatter):
        """Set up TimedRotatingFileHandler, falling back to console-only on failure."""
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            log_path = os.path.join(self.log_dir, f"envoy-{today}.log")
            handler = TimedRotatingFileHandler(
                log_path,
                when="midnight",
                interval=1,
                backupCount=0,  # We handle cleanup ourselves
                encoding="utf-8",
            )
            handler.setLevel(getattr(logging, self._file_level))
            handler.setFormatter(formatter)
            # Override namer to produce envoy-YYYY-MM-DD.log format for rotated files
            handler.namer = lambda name: os.path.join(
                self.log_dir,
                f"envoy-{datetime.now().strftime('%Y-%m-%d')}.log",
            )
            self._logger.addHandler(handler)
            self._file_handler = handler
        except (OSError, PermissionError):
            # Fall back to console-only logging
            print(
                "WARNING: Could not create log directory, falling back to console-only logging",
                file=sys.stderr,
            )
            self._file_handler = None

    def _setup_console_handler(self, formatter: JSONFormatter):
        """Set up console handler filtered at WARNING level by default."""
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)  # Let filter handle it
        handler.addFilter(_ConsoleFilter(getattr(logging, self._console_level)))
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

    def _emit_pending_warnings(self):
        """Emit any warnings that were deferred during init."""
        if hasattr(self, "_pending_level_warning"):
            bad_level = self._pending_level_warning
            del self._pending_level_warning
            self.log(
                "WARNING",
                "config_warning",
                f"Invalid ENVOY_LOG_LEVEL '{bad_level}', falling back to INFO",
            )

    def log(
        self,
        level: str,
        event_type: str,
        message: str,
        request_id: str = None,
        **metadata,
    ) -> LogEntry:
        """Create and emit a structured log entry."""
        try:
            entry = LogEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                level=level.upper(),
                event_type=event_type,
                message=message,
                session_id=self._session_id,
                request_id=request_id or self._request_id,
                metadata=metadata,
            )

            # Emit via Python logging
            record = logging.LogRecord(
                name="envoy",
                level=getattr(logging, level.upper(), logging.INFO),
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None,
            )
            record.log_entry = entry
            self._logger.handle(record)

            # Notify callbacks
            for cb in self._callbacks:
                try:
                    cb(entry)
                except Exception:
                    pass

            return entry
        except Exception as e:
            # Logging must never interfere with operations
            print(f"Logging error: {e}", file=sys.stderr)
            return LogEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                level=level.upper(),
                event_type=event_type,
                message=message,
            )

    def log_info(self, message: str, **metadata) -> LogEntry:
        """Convenience: create an INFO-level status log entry."""
        return self.log("INFO", "status", message, **metadata)

    def log_error(self, message: str, **metadata) -> LogEntry:
        """Convenience: create an ERROR-level status log entry."""
        return self.log("ERROR", "status", message, **metadata)

    def log_debug(self, message: str, **metadata) -> LogEntry:
        """Convenience: create a DEBUG-level status log entry."""
        return self.log("DEBUG", "status", message, **metadata)

    def log_warning(self, message: str, **metadata) -> LogEntry:
        """Convenience: create a WARNING-level status log entry."""
        return self.log("WARNING", "status", message, **metadata)

    def set_session_id(self, session_id: str):
        """Set the active session ID for all subsequent log entries."""
        self._session_id = session_id

    def new_request_id(self) -> str:
        """Generate and set a new request ID, returning it."""
        self._request_id = f"req-{uuid.uuid4().hex[:12]}"
        return self._request_id

    def on_entry(self, callback: Callable[[LogEntry], None]):
        """Register a callback to be invoked on every log entry."""
        self._callbacks.append(callback)

    def cleanup_old_logs(self):
        """Delete log files older than the retention period."""
        try:
            pattern = os.path.join(self.log_dir, "envoy-*.log")
            cutoff = datetime.now() - timedelta(days=self._retention_days)
            for filepath in glob.glob(pattern):
                basename = os.path.basename(filepath)
                # Extract date from envoy-YYYY-MM-DD.log
                try:
                    date_str = basename.replace("envoy-", "").replace(".log", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if file_date < cutoff:
                        os.remove(filepath)
                except (ValueError, OSError):
                    # Skip files that don't match the expected format or can't be deleted
                    pass
        except Exception:
            # Cleanup failures must not block the session
            pass


# Module-level singleton
_logger_instance: EnvoyLogger | None = None


def get_logger() -> EnvoyLogger:
    """Module-level singleton accessor for EnvoyLogger."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = EnvoyLogger()
        _logger_instance._emit_pending_warnings()
    return _logger_instance


def _truncate(text: str, max_length: int = 500) -> str:
    """Truncate a string to max_length, appending '...' if truncated."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def _sanitize_args(args: dict) -> dict:
    """Safely serialize tool arguments to JSON-compatible types."""
    sanitized = {}
    for key, value in args.items():
        try:
            json.dumps(value)
            sanitized[key] = value
        except (TypeError, ValueError):
            sanitized[key] = repr(value)
    return sanitized


def logged_tool(tool_func):
    """Wrap a Strands @tool with start/end/error logging, preserving the tool object."""
    original_inner = tool_func._tool_func if hasattr(tool_func, '_tool_func') else None
    if original_inner is None:
        # Not a Strands tool object — fall back to plain wrapper
        @functools.wraps(tool_func)
        def wrapper(*args, **kwargs):
            logger = get_logger()
            tool_name = tool_func.__name__
            logger.log("INFO", "tool_call_start", f"Calling {tool_name}",
                        tool_name=tool_name, arguments=_sanitize_args(kwargs))
            start = time.monotonic()
            try:
                result = tool_func(*args, **kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.log("INFO", "tool_call_end", f"{tool_name} completed",
                            tool_name=tool_name, duration_ms=round(elapsed_ms, 1),
                            output_summary=_truncate(str(result), logger.max_output_length))
                return result
            except Exception as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.log("ERROR", "tool_call_error", f"{tool_name} failed: {e}",
                            tool_name=tool_name, duration_ms=round(elapsed_ms, 1),
                            exception_type=type(e).__name__, exception_message=str(e))
                raise
        return wrapper

    # Strands tool — monkey-patch _tool_func to add logging while keeping the tool object intact
    tool_name = getattr(original_inner, '__name__', str(tool_func))

    @functools.wraps(original_inner)
    def logged_inner(*args, **kwargs):
        logger = get_logger()
        logger.log("INFO", "tool_call_start", f"Calling {tool_name}",
                    tool_name=tool_name, arguments=_sanitize_args(kwargs))
        start = time.monotonic()
        try:
            result = original_inner(*args, **kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.log("INFO", "tool_call_end", f"{tool_name} completed",
                        tool_name=tool_name, duration_ms=round(elapsed_ms, 1),
                        output_summary=_truncate(str(result), logger.max_output_length))
            return result
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.log("ERROR", "tool_call_error", f"{tool_name} failed: {e}",
                        tool_name=tool_name, duration_ms=round(elapsed_ms, 1),
                        exception_type=type(e).__name__, exception_message=str(e))
            raise

    tool_func._tool_func = logged_inner
    return tool_func
