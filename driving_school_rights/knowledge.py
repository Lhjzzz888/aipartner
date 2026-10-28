"""Verified legal source and official contact lookup."""

from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import re

DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class LawRecord:
    id: str
    title: str
    article: str
    summary: str
    keywords: tuple[str, ...]
    issue_types: tuple[str, ...]
    effective_from: date
    effective_to: date | None
    source_url: str
    source_name: str
    verified_at: date


@dataclass(frozen=True)
class ContactRecord:
    name: str
    phone: str
    website: str
    scope: str
    verified_at: date
    source_url: str
    is_official: bool
    city: str | None = None
    unverified_local: bool = False


def _date(value):
    return date.fromisoformat(value) if value else None


def load_laws(path: Path | None = None) -> list[LawRecord]:
    rows = json.loads((path or DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    return [LawRecord(**{**row, "keywords": tuple(row["keywords"]), "issue_types": tuple(row["issue_types"]), "effective_from": _date(row["effective_from"]), "effective_to": _date(row["effective_to"]), "verified_at": _date(row["verified_at"])}) for row in rows]


def load_contacts(path: Path | None = None) -> list[ContactRecord]:
    rows = json.loads((path or DATA_DIR / "contacts.json").read_text(encoding="utf-8"))
    return [ContactRecord(**{**row, "verified_at": _date(row["verified_at"])}) for row in rows]


def search_laws(query: str, issue_type: str, laws: list[LawRecord] | None = None, today: date | None = None) -> list[LawRecord]:
    today = today or date.today()
    ranked = []
    for law in laws if laws is not None else load_laws():
        if law.effective_from > today or (law.effective_to and law.effective_to < today) or law.verified_at > today:
            continue
        score = sum(1 for keyword in law.keywords if keyword.lower() in (query or "").lower())
        normalized_issue = (issue_type or "").lower()
        score += 2 if any(tag.lower() in normalized_issue or normalized_issue in tag.lower() for tag in law.issue_types if normalized_issue) else 0
        if score:
            ranked.append((score, law))
    return [law for _, law in sorted(ranked, key=lambda item: item[0], reverse=True)[:8]]


def get_contacts(city: str | None, issue_type: str, contacts: list[ContactRecord] | None = None, today: date | None = None) -> list[ContactRecord]:
    today = today or date.today()
    rows = contacts if contacts is not None else load_contacts()
    current = [row for row in rows if row.is_official and row.verified_at <= today and today - row.verified_at <= timedelta(days=730)]
    if not city:
        return current
    local = [row for row in current if row.city == city]
    globals_ = [row for row in current if row.city is None]
    if not local:
        globals_ = [ContactRecord(**{**row.__dict__, "unverified_local": True}) for row in globals_]
    return local + globals_
