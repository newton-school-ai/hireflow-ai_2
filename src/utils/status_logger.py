"""
Status logging system for HireFlow AI.
Records application state transitions to Python logging and a persistent log file.
"""

import datetime
import logging
import os
from src.config.settings import settings

logger = logging.getLogger("status_logger")


def log_status_change(
    application_id: str,
    old_status: str,
    new_status: str,
    reason: str | None = None,
) -> None:
    """Record a state change for an application with a timestamp and optional reason.

    Logs to standard Python logger and appends to a local log file for auditability.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    log_msg = f"[{timestamp}] App: {application_id} | Transition: {old_status} -> {new_status}"
    if reason:
        log_msg += f" | Reason: {reason}"

    logger.info(log_msg)

    # Resolve log file directory path
    storage_path = getattr(settings, "local_storage_path", "data")
    log_dir = os.path.join(storage_path, "logs")
    log_file = os.path.join(log_dir, "status_changes.log")

    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except Exception as exc:
        logger.error(f"Failed to write to status log file {log_file}: {exc}")
