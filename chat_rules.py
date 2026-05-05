"""Pure helpers for chat-count exclusion rules."""

from __future__ import annotations

from copy import deepcopy

DEFAULT_CHAT_COUNT_CONFIG = {
    "exclude_name_keywords": ["call", "calls", "voice", "voz"],
    "exclude_channel_ids_by_guild": {},
    # Lista branca de voz por servidor.
    "include_voice_channel_ids_by_guild": {},
    # Liga/desliga a lista branca de voz por servidor.
    # True + lista vazia => nenhum canal de voz conta.
    "voice_allowlist_enabled_by_guild": {},
}


def sanitize_chat_count_config(data):
    cfg = deepcopy(DEFAULT_CHAT_COUNT_CONFIG)
    if isinstance(data, dict):
        cfg.update(data)

    keywords = []
    seen_keywords = set()
    for raw_kw in cfg.get("exclude_name_keywords", DEFAULT_CHAT_COUNT_CONFIG["exclude_name_keywords"]):
        kw = str(raw_kw).strip().lower()
        if not kw or kw in seen_keywords:
            continue
        seen_keywords.add(kw)
        keywords.append(kw)
    cfg["exclude_name_keywords"] = keywords

    cleaned = {}
    raw_guild_map = cfg.get("exclude_channel_ids_by_guild", {})
    if isinstance(raw_guild_map, dict):
        for gid_raw, ids in raw_guild_map.items():
            gid = str(gid_raw).strip()
            if not gid or not isinstance(ids, list):
                continue
            uniq_ids = []
            seen = set()
            for raw_id in ids:
                try:
                    cid = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if cid not in seen:
                    seen.add(cid)
                    uniq_ids.append(cid)
            cleaned[gid] = uniq_ids
    cfg["exclude_channel_ids_by_guild"] = cleaned

    voice_in = {}
    raw_voice = cfg.get("include_voice_channel_ids_by_guild", {})
    if isinstance(raw_voice, dict):
        for gid_raw, ids in raw_voice.items():
            gid = str(gid_raw).strip()
            if not gid or not isinstance(ids, list):
                continue
            uniq_ids = []
            seen = set()
            for raw_id in ids:
                try:
                    cid = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if cid not in seen:
                    seen.add(cid)
                    uniq_ids.append(cid)
            voice_in[gid] = uniq_ids
    cfg["include_voice_channel_ids_by_guild"] = voice_in

    allowlist_enabled = {}
    raw_enabled = cfg.get("voice_allowlist_enabled_by_guild", {})
    if isinstance(raw_enabled, dict):
        for gid_raw, val in raw_enabled.items():
            gid = str(gid_raw).strip()
            if not gid:
                continue
            allowlist_enabled[gid] = bool(val)
    cfg["voice_allowlist_enabled_by_guild"] = allowlist_enabled
    return cfg


def should_count_channel_message(channel_id, channel_name, category_name, guild_id, cfg):
    gid = str(guild_id)
    excluded_ids = set(cfg.get("exclude_channel_ids_by_guild", {}).get(gid, []))
    if channel_id in excluded_ids:
        return False
    keywords = [str(k).strip().lower() for k in cfg.get("exclude_name_keywords", []) if str(k).strip()]
    if not keywords:
        return True
    target = f"{channel_name or ''} {category_name or ''}".lower()
    return not any(k in target for k in keywords)


def should_count_voice_time(channel_id, channel_name, guild_id, cfg):
    """
    Regras de rconfig para TEMPO de voz (diferente de chat):
    - Todos os canais de voz contam por padrao.
    - Somente canais com ID em exclude_channel_ids_by_guild nao contam.
    """
    gid = str(guild_id)
    excluded_ids = set(cfg.get("exclude_channel_ids_by_guild", {}).get(gid, []))
    if channel_id in excluded_ids:
        return False
    return True
