"""Audit logging for vacation app — track all mutations and state changes."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Setup audit logger
AUDIT_LOG_DIR = Path(__file__).parent.parent / "audit_logs"
AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.jsonl"

# Configure logger for JSON output
audit_logger = logging.getLogger("vacation_audit")
audit_logger.setLevel(logging.INFO)

# Handler: write to JSONL file
handler = logging.FileHandler(AUDIT_LOG_FILE, encoding="utf-8")
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
audit_logger.addHandler(handler)


def log_mutation(
    action: str,
    entity: str,
    entity_id: Optional[str] = None,
    username: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    status: str = "success",
) -> None:
    """
    Log a mutation (create, update, delete) to the audit trail.
    
    Args:
        action: "create", "update", "delete", "approve", "reject", etc.
        entity: "vacation", "staff", "user", "login", etc.
        entity_id: ID of affected entity (optional)
        username: Username of actor (optional)
        details: Additional context (e.g., old_value, new_value)
        status: "success" or "failure"
    """
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "username": username or "system",
        "status": status,
        "details": details or {},
    }
    audit_logger.info(json.dumps(record, ensure_ascii=False))


def get_audit_history(
    entity: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """
    Retrieve audit history, optionally filtered by entity and/or entity_id.
    
    Args:
        entity: Filter by entity type (e.g., "vacation")
        entity_id: Filter by entity ID
        limit: Max records to return
    
    Returns:
        List of audit records (most recent first)
    """
    records = []
    if not AUDIT_LOG_FILE.exists():
        return records
    
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line.strip())
                if entity and record.get("entity") != entity:
                    continue
                if entity_id and record.get("entity_id") != entity_id:
                    continue
                records.append(record)
            except json.JSONDecodeError:
                continue
    
    # Return most recent first, limited
    return sorted(records, key=lambda r: r.get("timestamp", ""), reverse=True)[:limit]
