import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict
from json_utils import atomic_write_json


class ConfigStore:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self._lock = threading.RLock()
        self._server_cfg = os.path.join(base_dir, "data", "server_config.json")
        self._econ_cfg = os.path.join(base_dir, "data", "econ_config.json")
        self._antilink_cfg = os.path.join(base_dir, "dados", "antilink.json")
        self._antinuke_cfg = os.path.join(base_dir, "dados", "antinuke.json")
        self._antp_cfg = os.path.join(base_dir, "antp", "settings.json")
        self._audit_log = os.path.join(base_dir, "data", "web_audit.json")
        self._automation_cfg = os.path.join(base_dir, "data", "automation_config.json")
        self._moderation_cfg = os.path.join(base_dir, "data", "moderation_config.json")

    def _ensure_parent(self, file_path: str) -> None:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

    def _read_json(self, file_path: str, default: Any) -> Any:
        self._ensure_parent(file_path)
        if not os.path.exists(file_path):
            return default
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return default

    def _write_json(self, file_path: str, payload: Any) -> None:
        self._ensure_parent(file_path)
        atomic_write_json(file_path, payload)

    def _append_audit(self, actor_id: int, guild_id: int, section: str, changes: Dict[str, Any]) -> None:
        entries = self._read_json(self._audit_log, [])
        if not isinstance(entries, list):
            entries = []
        entries.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "actor_id": int(actor_id),
                "guild_id": str(guild_id),
                "section": section,
                "changes": changes,
            }
        )
        self._write_json(self._audit_log, entries[-500:])

    def get_server_slash(self, guild_id: int) -> Dict[str, Any]:
        with self._lock:
            cfg = self._read_json(self._server_cfg, {})
            return cfg.get(str(guild_id), {"slash_cmds": {}, "prefix": "!", "modules": {}})

    def update_server_slash(self, actor_id: int, guild_id: int, slash_cmds: Dict[str, bool]) -> None:
        with self._lock:
            cfg = self._read_json(self._server_cfg, {})
            gid = str(guild_id)
            guild_cfg = cfg.get(gid, {})
            guild_cfg.setdefault("slash_cmds", {})
            for cmd, enabled in slash_cmds.items():
                guild_cfg["slash_cmds"][cmd] = bool(enabled)
            cfg[gid] = guild_cfg
            self._write_json(self._server_cfg, cfg)
            self._append_audit(actor_id, guild_id, "slash", {"updated": list(slash_cmds.keys())})

    def update_server_general(self, actor_id: int, guild_id: int, payload: Dict[str, Any]) -> None:
        with self._lock:
            cfg = self._read_json(self._server_cfg, {})
            gid = str(guild_id)
            guild_cfg = cfg.get(gid, {})
            if "prefix" in payload:
                prefix = str(payload["prefix"]).strip()
                if not prefix:
                    prefix = "!"
                guild_cfg["prefix"] = prefix[:5]
            if "modules" in payload and isinstance(payload["modules"], dict):
                guild_cfg.setdefault("modules", {})
                for module_name, enabled in payload["modules"].items():
                    guild_cfg["modules"][str(module_name)] = bool(enabled)
            cfg[gid] = guild_cfg
            self._write_json(self._server_cfg, cfg)
            self._append_audit(actor_id, guild_id, "general", payload)

    def get_econ(self) -> Dict[str, Any]:
        with self._lock:
            cfg = self._read_json(self._econ_cfg, {})
            if not isinstance(cfg, dict):
                cfg = {}
            cfg.setdefault("tot_per_min", 2)
            cfg.setdefault("payout_interval_sec", 120)
            cfg.setdefault("speed_multipliers", {})
            cfg.setdefault("time_multipliers", {})
            cfg.setdefault("rank_role_ids", {})
            return cfg

    def update_econ(self, actor_id: int, guild_id: int, payload: Dict[str, Any]) -> None:
        with self._lock:
            cfg = self.get_econ()
            if "tot_per_min" in payload:
                cfg["tot_per_min"] = max(1, int(payload["tot_per_min"]))
            if "payout_interval_sec" in payload:
                cfg["payout_interval_sec"] = max(30, min(1800, int(payload["payout_interval_sec"])))
            if "speed_multipliers" in payload and isinstance(payload["speed_multipliers"], dict):
                cfg["speed_multipliers"] = payload["speed_multipliers"]
            if "rank_role_ids" in payload and isinstance(payload["rank_role_ids"], dict):
                cfg["rank_role_ids"] = payload["rank_role_ids"]
            self._write_json(self._econ_cfg, cfg)
            self._append_audit(actor_id, guild_id, "economy", payload)

    def get_antilink(self, guild_id: int) -> Dict[str, Any]:
        with self._lock:
            cfg = self._read_json(self._antilink_cfg, {})
            return cfg.get(
                str(guild_id),
                {
                    "enabled": False,
                    "action": "delete",
                    "warning_message": "Links nao sao permitidos!",
                    "timeout_minutes": 5,
                    "whitelist": [],
                    "ignored_channels": [],
                    "log_channel": None,
                },
            )

    def update_antilink(self, actor_id: int, guild_id: int, payload: Dict[str, Any]) -> None:
        with self._lock:
            cfg = self._read_json(self._antilink_cfg, {})
            gid = str(guild_id)
            cur = cfg.get(gid, self.get_antilink(guild_id))
            cur.update(payload)
            cfg[gid] = cur
            self._write_json(self._antilink_cfg, cfg)
            self._append_audit(actor_id, guild_id, "antilink", payload)

    def get_antinuke(self, guild_id: int) -> Dict[str, Any]:
        with self._lock:
            cfg = self._read_json(self._antinuke_cfg, {})
            return cfg.get(
                str(guild_id),
                {
                    "enabled": False,
                    "limits": {},
                    "punishments": {},
                    "trusted_users": [],
                    "trusted_role_ids": [],
                    "log_channel": None,
                    "notify_admins": True,
                    "action_history": [],
                },
            )

    def update_antinuke(self, actor_id: int, guild_id: int, payload: Dict[str, Any]) -> None:
        with self._lock:
            cfg = self._read_json(self._antinuke_cfg, {})
            gid = str(guild_id)
            cur = cfg.get(gid, self.get_antinuke(guild_id))
            cur.update(payload)
            cfg[gid] = cur
            self._write_json(self._antinuke_cfg, cfg)
            self._append_audit(actor_id, guild_id, "antinuke", payload)

    def get_antp(self, guild_id: int) -> Dict[str, Any]:
        with self._lock:
            cfg = self._read_json(self._antp_cfg, {})
            gid = str(guild_id)
            cur = cfg.get(
                gid,
                {
                    "log_channel_id": 0,
                    "shame_channel_id": 0,
                    "spam_allowed_channel_id": 0,
                    "exempt_role_ids": [],
                    "flood_limit": 5,
                    "flood_window_sec": 8,
                    "timeout_minutes": 4320,
                    "score_threshold": 60,
                    "enabled": True,
                },
            )
            if not isinstance(cur, dict):
                cur = {}
            normalized = {
                "log_channel_id": int(cur.get("log_channel_id", 0) or 0),
                "shame_channel_id": int(cur.get("shame_channel_id", 0) or 0),
                "spam_allowed_channel_id": int(cur.get("spam_allowed_channel_id", 0) or 0),
                "exempt_role_ids": [int(v) for v in cur.get("exempt_role_ids", []) if str(v).isdigit()],
                "flood_limit": max(2, min(int(cur.get("flood_limit", 5)), 20)),
                "flood_window_sec": max(2, min(int(cur.get("flood_window_sec", 8)), 60)),
                "timeout_minutes": max(1, min(int(cur.get("timeout_minutes", 4320)), 43200)),
                "score_threshold": max(1, min(int(cur.get("score_threshold", 60)), 100)),
                "enabled": bool(cur.get("enabled", True)),
            }
            return normalized

    def update_antp(self, actor_id: int, guild_id: int, payload: Dict[str, Any]) -> None:
        with self._lock:
            cfg = self._read_json(self._antp_cfg, {})
            gid = str(guild_id)
            cur = cfg.get(gid, self.get_antp(guild_id))
            if "enabled" in payload:
                cur["enabled"] = bool(payload["enabled"])
            if "score_threshold" in payload:
                cur["score_threshold"] = max(1, min(int(payload["score_threshold"]), 100))
            if "timeout_minutes" in payload:
                cur["timeout_minutes"] = max(1, min(int(payload["timeout_minutes"]), 43200))
            if "flood_limit" in payload:
                cur["flood_limit"] = max(2, min(int(payload["flood_limit"]), 20))
            if "flood_window_sec" in payload:
                cur["flood_window_sec"] = max(2, min(int(payload["flood_window_sec"]), 60))
            if "log_channel_id" in payload:
                cur["log_channel_id"] = max(0, int(payload["log_channel_id"]))
            if "shame_channel_id" in payload:
                cur["shame_channel_id"] = max(0, int(payload["shame_channel_id"]))
            if "spam_allowed_channel_id" in payload:
                cur["spam_allowed_channel_id"] = max(0, int(payload["spam_allowed_channel_id"]))
            if "exempt_role_ids" in payload and isinstance(payload["exempt_role_ids"], list):
                cur["exempt_role_ids"] = sorted(set(int(v) for v in payload["exempt_role_ids"] if str(v).isdigit()))
            cfg[gid] = cur
            self._write_json(self._antp_cfg, cfg)
            self._append_audit(actor_id, guild_id, "antp", payload)

    def get_audit_entries(self, guild_id: int, limit: int = 40):
        with self._lock:
            entries = self._read_json(self._audit_log, [])
            if not isinstance(entries, list):
                return []
            gid = str(guild_id)
            filtered = [e for e in entries if isinstance(e, dict) and e.get("guild_id") == gid]
            return filtered[-max(1, min(int(limit), 200)):]

    # -----------------------------
    # Leveling / Moderation / Automation
    # -----------------------------
    def get_leveling(self, guild_id: int) -> Dict[str, Any]:
        with self._lock:
            # source of truth in DB; web panel writes db via API route.
            return {}

    def update_leveling(self, actor_id: int, guild_id: int, payload: Dict[str, Any]) -> None:
        self._append_audit(actor_id, guild_id, "leveling", payload)

    def get_moderation(self, guild_id: int) -> Dict[str, Any]:
        with self._lock:
            cfg = self._read_json(self._moderation_cfg, {})
            return cfg.get(str(guild_id), {"modlog_channel_id": 0, "warn_escalation": {"3": "timeout:30", "5": "kick", "7": "ban"}})

    def update_moderation(self, actor_id: int, guild_id: int, payload: Dict[str, Any]) -> None:
        with self._lock:
            cfg = self._read_json(self._moderation_cfg, {})
            gid = str(guild_id)
            cur = cfg.get(gid, self.get_moderation(guild_id))
            cur.update(payload)
            cfg[gid] = cur
            self._write_json(self._moderation_cfg, cfg)
            self._append_audit(actor_id, guild_id, "moderation", payload)

    def get_automation(self, guild_id: int) -> Dict[str, Any]:
        with self._lock:
            cfg = self._read_json(self._automation_cfg, {})
            return cfg.get(
                str(guild_id),
                {
                    "welcome_channel_id": 0,
                    "welcome_message": "Bem-vindo(a), {user}, ao servidor {guild}!",
                    "leave_channel_id": 0,
                    "leave_message": "{user_name} saiu do servidor.",
                    "autorole_id": 0,
                    "reaction_roles": [],
                    "content_alerts": [],
                },
            )

    def update_automation(self, actor_id: int, guild_id: int, payload: Dict[str, Any]) -> None:
        with self._lock:
            cfg = self._read_json(self._automation_cfg, {})
            gid = str(guild_id)
            cur = cfg.get(gid, self.get_automation(guild_id))
            cur.update(payload)
            cfg[gid] = cur
            self._write_json(self._automation_cfg, cfg)
            self._append_audit(actor_id, guild_id, "automation", payload)

    def apply_preset(self, actor_id: int, guild_id: int, preset_name: str) -> None:
        preset = (preset_name or "").strip().lower()
        if preset == "comunidade":
            self.update_server_general(actor_id, guild_id, {"prefix": "!", "modules": {"voz": True, "economy": True, "admin": True}})
            self.update_antilink(actor_id, guild_id, {"enabled": True, "action": "delete"})
            self.update_antinuke(actor_id, guild_id, {"enabled": True, "notify_admins": True})
            self.update_antp(actor_id, guild_id, {"enabled": True, "score_threshold": 60})
        elif preset == "creator":
            self.update_server_general(actor_id, guild_id, {"prefix": "!", "modules": {"voz": True, "economy": True, "admin": True}})
            self.update_automation(actor_id, guild_id, {"welcome_channel_id": 0, "autorole_id": 0})
            self.update_antilink(actor_id, guild_id, {"enabled": True, "action": "warn"})
            self.update_antinuke(actor_id, guild_id, {"enabled": True, "notify_admins": True})
