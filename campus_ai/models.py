"""Normalized, provider-independent academic data."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from hashlib import sha256
import json


@dataclass
class AcademicItem:
    uid: str
    source: str  # moodle, gmail, demo
    category: str  # material, assignment, message, announcement
    title: str
    course: str = "Geral"
    description: str = ""
    url: str = ""
    due_iso: str = ""
    status: str = "unknown"  # unknown, pending, submitted
    meta: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = asdict(self)
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode('utf8')).hexdigest()
