"""Centralized authorization helpers for privileged bot actions."""

from __future__ import annotations

import os

DEFAULT_OWNER_ID = 377188128735232010
DEFAULT_ADMIN_IDS = {377188128735232010, 882266401262420008}


def _parse_ids(raw: str):
    ids = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids


OWNER_ID = int(os.environ.get("BOT_OWNER_ID", DEFAULT_OWNER_ID))
ADMIN_IDS = _parse_ids(os.environ.get("BOT_ADMIN_IDS", "")) or set(DEFAULT_ADMIN_IDS)
ADMIN_IDS.add(OWNER_ID)


def is_owner(user_id: int) -> bool:
    return int(user_id) == OWNER_ID


def is_admin(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS
