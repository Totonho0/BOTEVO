"""Persistencia e checagem de cargos por categoria do leitor de manga.

Estrutura do arquivo `data/manga_config.json`:

    {
        "<guild_id>": {
            "categories": {
                "<categoria Niadd serv.2>": [<role_id>, ...],
            },
            "mlto_categories": {
                "<etiqueta Manga Livre .to serv.3>": [<role_id>, ...],
            }
        }
    }

Regra de acesso (`member_can_access*`):

    - Se a categoria nao tem cargos configurados -> liberada para todos.
    - Se tem cargos -> o membro precisa ter pelo menos 1.
    - Administradores e dono do servidor sempre tem acesso.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Iterable

import discord


CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "manga_config.json"

_lock = threading.Lock()
_cache: dict | None = None


def _load_all() -> dict:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        if not CONFIG_PATH.exists():
            _cache = {}
            return _cache
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            data = {}
        _cache = data
        return _cache


def _save_all() -> None:
    with _lock:
        if _cache is None:
            return
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(_cache, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


def _guild_block(guild_id: int) -> dict:
    data = _load_all()
    block = data.setdefault(str(int(guild_id)), {})
    block.setdefault("categories", {})
    block.setdefault("mlto_categories", {})
    return block


def _access_core(
    member: discord.abc.User | None,
    guild_id: int,
    required: list[int],
) -> bool:
    if not required:
        return True
    if member is None:
        return False
    perms = getattr(member, "guild_permissions", None)
    if perms is not None and getattr(perms, "administrator", False):
        return True
    roles = getattr(member, "roles", None)
    if not roles:
        return False
    member_role_ids = {getattr(r, "id", None) for r in roles}
    return any(rid in member_role_ids for rid in required)


# --------- Niadd (servidor 2) ---------

def get_required_roles(guild_id: int, category: str) -> list[int]:
    if not guild_id:
        return []
    block = _guild_block(guild_id)
    return list(block["categories"].get(category, []))


def add_required_role(guild_id: int, category: str, role_id: int) -> bool:
    block = _guild_block(guild_id)
    roles: list[int] = block["categories"].setdefault(category, [])
    if role_id in roles:
        return False
    roles.append(int(role_id))
    _save_all()
    return True


def remove_required_role(guild_id: int, category: str, role_id: int) -> bool:
    block = _guild_block(guild_id)
    roles: list[int] = block["categories"].get(category, [])
    if role_id not in roles:
        return False
    roles.remove(int(role_id))
    if not roles:
        block["categories"].pop(category, None)
    _save_all()
    return True


def clear_category(guild_id: int, category: str) -> bool:
    block = _guild_block(guild_id)
    if category not in block["categories"]:
        return False
    block["categories"].pop(category)
    _save_all()
    return True


def reset_guild(guild_id: int) -> None:
    block = _guild_block(guild_id)
    block["categories"] = {}
    _save_all()


def list_all_configs(guild_id: int) -> dict[str, list[int]]:
    if not guild_id:
        return {}
    block = _guild_block(guild_id)
    return {cat: list(roles) for cat, roles in block["categories"].items()}


def member_can_access(
    member: discord.abc.User | None,
    guild_id: int,
    category: str,
) -> bool:
    return _access_core(member, guild_id, get_required_roles(guild_id, category))


# --------- Manga Livre .to (servidor 3) ---------

def get_required_roles_mlto(guild_id: int, category_label: str) -> list[int]:
    if not guild_id:
        return []
    block = _guild_block(guild_id)
    return list(block["mlto_categories"].get(category_label, []))


def add_required_role_mlto(guild_id: int, category_label: str, role_id: int) -> bool:
    block = _guild_block(guild_id)
    roles: list[int] = block["mlto_categories"].setdefault(category_label, [])
    if role_id in roles:
        return False
    roles.append(int(role_id))
    _save_all()
    return True


def remove_required_role_mlto(guild_id: int, category_label: str, role_id: int) -> bool:
    block = _guild_block(guild_id)
    roles: list[int] = block["mlto_categories"].get(category_label, [])
    if role_id not in roles:
        return False
    roles.remove(int(role_id))
    if not roles:
        block["mlto_categories"].pop(category_label, None)
    _save_all()
    return True


def clear_category_mlto(guild_id: int, category_label: str) -> bool:
    block = _guild_block(guild_id)
    if category_label not in block["mlto_categories"]:
        return False
    block["mlto_categories"].pop(category_label)
    _save_all()
    return True


def reset_guild_mlto(guild_id: int) -> None:
    block = _guild_block(guild_id)
    block["mlto_categories"] = {}
    _save_all()


def list_all_configs_mlto(guild_id: int) -> dict[str, list[int]]:
    if not guild_id:
        return {}
    block = _guild_block(guild_id)
    return {cat: list(roles) for cat, roles in block["mlto_categories"].items()}


def member_can_access_mlto(
    member: discord.abc.User | None,
    guild_id: int,
    category_label: str,
) -> bool:
    return _access_core(
        member, guild_id, get_required_roles_mlto(guild_id, category_label)
    )


def categories_blocked_for(
    member: discord.abc.User | None,
    guild_id: int,
    categories: Iterable[str],
) -> list[str]:
    return [c for c in categories if not member_can_access(member, guild_id, c)]


__all__ = [
    "CONFIG_PATH",
    "get_required_roles",
    "add_required_role",
    "remove_required_role",
    "clear_category",
    "reset_guild",
    "list_all_configs",
    "member_can_access",
    "get_required_roles_mlto",
    "add_required_role_mlto",
    "remove_required_role_mlto",
    "clear_category_mlto",
    "reset_guild_mlto",
    "list_all_configs_mlto",
    "member_can_access_mlto",
    "categories_blocked_for",
]
