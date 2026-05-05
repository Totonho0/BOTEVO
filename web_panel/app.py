import html
import json
import os
import sqlite3
import time
import secrets
from typing import Dict, List
from urllib.parse import quote, urlencode

import bcrypt
import requests
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from cogs.config import ALWAYS_SLASH, COMMAND_CATEGORIES
from .config_store import ConfigStore
from database import get_level_config, update_level_config, get_level_rewards, set_level_reward

DISCORD_API = "https://discord.com/api/v10"
DISCORD_CDN = "https://cdn.discordapp.com"
ADMIN_PERMS = 0x8 | 0x20
BOT_BRAND_IMAGE_DEFAULT = (
    "https://images-ext-1.discordapp.net/external/L-xPZGh-QVcihHA7E64GHTXy-mNPNgdIYpvBnvaYArc/"
    "%3Fsize%3D1024/https/cdn.discordapp.com/icons/1466616485777768539/"
    "a66071a8ba585a3dc80610a851e18428.webp?format=webp&width=144&height=144"
)
ADMIN_DEFAULT_ROLE = "superadmin"


class SlashUpdate(BaseModel):
    slash_cmds: Dict[str, bool] = Field(default_factory=dict)


class EconUpdate(BaseModel):
    tot_per_min: int | None = None
    payout_interval_sec: int | None = None
    speed_multipliers: Dict[str, float] | None = None
    rank_role_ids: Dict[str, int] | None = None


class AntiLinkUpdate(BaseModel):
    enabled: bool | None = None
    action: str | None = None
    warning_message: str | None = None
    timeout_minutes: int | None = None
    ignored_channels: List[int] | None = None
    log_channel: int | None = None


class AntiNukeUpdate(BaseModel):
    enabled: bool | None = None
    notify_admins: bool | None = None
    log_channel: int | None = None


class AntpUpdate(BaseModel):
    enabled: bool | None = None
    score_threshold: int | None = None
    timeout_minutes: int | None = None
    flood_limit: int | None = None
    flood_window_sec: int | None = None
    log_channel_id: int | None = None
    shame_channel_id: int | None = None
    spam_allowed_channel_id: int | None = None
    exempt_role_ids: List[int] | None = None


class GeneralUpdate(BaseModel):
    prefix: str | None = None
    modules: Dict[str, bool] | None = None


class LevelingUpdate(BaseModel):
    enabled: bool | None = None
    message_xp_min: int | None = None
    message_xp_max: int | None = None
    message_cooldown_sec: int | None = None
    voice_xp_per_min: float | None = None
    announce_levelup: bool | None = None


class ModerationUpdate(BaseModel):
    modlog_channel_id: int | None = None
    warn_escalation: Dict[str, str] | None = None


class AutomationUpdate(BaseModel):
    welcome_channel_id: int | None = None
    welcome_message: str | None = None
    leave_channel_id: int | None = None
    leave_message: str | None = None
    autorole_id: int | None = None
    reaction_roles: List[Dict] | None = None
    content_alerts: List[Dict] | None = None


BASE_CSS = """
:root {
  --bg-0: #05070f;
  --bg-1: #0b1124;
  --bg-2: #111a35;
  --card: rgba(18, 23, 48, 0.78);
  --card-strong: rgba(22, 28, 58, 0.9);
  --line: rgba(140, 160, 220, 0.18);
  --line-strong: rgba(140, 160, 220, 0.35);
  --text: #e7ecff;
  --muted: #9aa7d0;
  --brand-a: #7c8bff;
  --brand-b: #b467ff;
  --brand-c: #38e8ff;
  --ok: #30d48a;
  --danger: #ff6b6b;
  --warning: #ffb547;
  --shadow: 0 20px 50px rgba(5, 8, 20, 0.55);
}

* { box-sizing: border-box; }

html, body { margin: 0; padding: 0; min-height: 100%; }

body {
  color: var(--text);
  font-family: "Inter", "Segoe UI", system-ui, -apple-system, Arial, sans-serif;
  background:
    radial-gradient(900px 500px at 85% -10%, rgba(180, 103, 255, 0.18), transparent 70%),
    radial-gradient(700px 500px at -10% 10%, rgba(56, 232, 255, 0.15), transparent 70%),
    linear-gradient(180deg, #05070f 0%, #070b1d 100%);
  min-height: 100vh;
  overflow-x: hidden;
}

body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image:
    radial-gradient(1px 1px at 20% 30%, rgba(255,255,255,0.25), transparent 60%),
    radial-gradient(1px 1px at 70% 80%, rgba(255,255,255,0.2), transparent 60%),
    radial-gradient(1.5px 1.5px at 40% 70%, rgba(255,255,255,0.18), transparent 60%),
    radial-gradient(1px 1px at 85% 20%, rgba(255,255,255,0.25), transparent 60%);
  opacity: 0.45;
  z-index: 0;
}

.wrap { position: relative; z-index: 1; max-width: 1180px; margin: 0 auto; padding: 24px 20px 60px; }

.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: linear-gradient(120deg, rgba(124,139,255,0.18), rgba(180,103,255,0.12));
  border: 1px solid var(--line);
  border-radius: 18px;
  backdrop-filter: blur(14px);
  margin-bottom: 24px;
}

.brand {
  display: flex; align-items: center; gap: 12px;
  text-decoration: none; color: var(--text); font-weight: 700;
}

.brand-badge {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, var(--brand-a), var(--brand-b));
  box-shadow: 0 10px 25px rgba(124, 139, 255, 0.35);
  font-weight: 800;
  overflow: hidden;
}
.brand-badge img {
  width: 100%; height: 100%; object-fit: cover;
}

.nav-right { display: flex; align-items: center; gap: 10px; }

.btn {
  border: 1px solid var(--line-strong);
  color: var(--text);
  text-decoration: none;
  padding: 10px 16px;
  border-radius: 12px;
  display: inline-flex; align-items: center; gap: 8px;
  background: rgba(255,255,255,0.04);
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
  cursor: pointer;
  font-size: 0.95rem;
}
.btn:hover { transform: translateY(-1px); border-color: var(--brand-a); box-shadow: 0 10px 20px rgba(124,139,255,0.18); }
.btn-ghost { background: transparent; }
.btn-brand {
  border: 0;
  color: #fff;
  background: linear-gradient(120deg, var(--brand-a), var(--brand-b));
  box-shadow: 0 12px 30px rgba(124, 139, 255, 0.35);
}
.btn-brand:hover { box-shadow: 0 16px 40px rgba(124, 139, 255, 0.45); }
.btn-admin-hidden {
  padding: 7px 9px;
  min-width: 34px;
  justify-content: center;
  opacity: 0.45;
  font-size: 0.9rem;
}
.btn-admin-hidden:hover {
  opacity: 1;
}

.hero {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 28px;
  margin-bottom: 28px;
}

.hero-left {
  background: linear-gradient(160deg, rgba(124,139,255,0.25), rgba(180,103,255,0.18));
  border: 1px solid var(--line);
  border-radius: 22px;
  padding: 36px;
  position: relative;
  overflow: hidden;
}

.hero-left::after {
  content: "";
  position: absolute;
  right: -80px; top: -80px;
  width: 240px; height: 240px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(56,232,255,0.35), transparent 70%);
  filter: blur(10px);
}

.hero h1 {
  margin: 0 0 10px;
  font-size: 2.1rem;
  letter-spacing: -0.02em;
  line-height: 1.1;
}

.hero h1 .grad {
  background: linear-gradient(120deg, var(--brand-c), var(--brand-a), var(--brand-b));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.hero p { color: var(--muted); margin: 0 0 22px; max-width: 520px; line-height: 1.5; }

.hero-right {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 22px;
  padding: 22px;
  box-shadow: var(--shadow);
  display: flex; flex-direction: column; justify-content: center;
}
.bot-photo {
  width: 88px; height: 88px; border-radius: 22px; object-fit: cover;
  border: 1px solid var(--line-strong);
  box-shadow: 0 12px 30px rgba(0,0,0,0.35);
  margin-bottom: 14px;
}

.feature-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; }
.feature-list li { display: flex; gap: 10px; align-items: flex-start; color: var(--muted); }
.feature-list b { color: var(--text); font-weight: 700; }
.feature-dot {
  width: 10px; height: 10px; border-radius: 50%; margin-top: 6px;
  background: linear-gradient(135deg, var(--brand-a), var(--brand-b));
  box-shadow: 0 0 10px rgba(124, 139, 255, 0.55);
  flex-shrink: 0;
}

.section-title {
  display: flex; align-items: center; justify-content: space-between;
  margin: 28px 0 16px;
}
.section-title h2 { margin: 0; font-size: 1.25rem; }
.section-title .muted { color: var(--muted); }

.grid { display: grid; gap: 18px; grid-template-columns: repeat(12, 1fr); }

.card {
  grid-column: span 12;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 20px;
  backdrop-filter: blur(14px);
  box-shadow: var(--shadow);
}

.card h3 { margin: 0 0 4px; font-size: 1.1rem; }
.card .hint { color: var(--muted); font-size: 0.9rem; margin-top: 0; margin-bottom: 14px; }

.half { grid-column: span 6; }
.third { grid-column: span 4; }
.two-third { grid-column: span 8; }
.full { grid-column: span 12; }

.server-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}

.server {
  position: relative;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: linear-gradient(160deg, rgba(124,139,255,0.08), rgba(180,103,255,0.06));
  text-decoration: none;
  color: var(--text);
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
  display: flex; align-items: center; gap: 12px;
}
.server:hover { transform: translateY(-2px); border-color: var(--brand-a); box-shadow: 0 10px 24px rgba(124,139,255,0.18); }

.server-avatar {
  width: 48px; height: 48px; border-radius: 14px; object-fit: cover; flex-shrink: 0;
  background: linear-gradient(135deg, var(--brand-a), var(--brand-b));
  display: flex; align-items: center; justify-content: center;
  color: white; font-weight: 700; font-size: 1.1rem;
}

.server-name { font-weight: 700; }
.server-id { font-size: 0.78rem; color: var(--muted); margin-top: 2px; }

.pill {
  display: inline-flex; align-items: center;
  font-size: 0.78rem;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--muted);
}
.pill-ok { color: #1f3a24; background: #b7f2ce; border: 0; }
.pill-err { color: #4c1a1a; background: #ffb0b0; border: 0; }

.tabs {
  display: inline-flex;
  gap: 4px;
  padding: 5px;
  border: 1px solid var(--line);
  background: rgba(10, 14, 30, 0.55);
  border-radius: 14px;
  margin-bottom: 18px;
  overflow-x: auto;
  max-width: 100%;
}

.tab {
  padding: 9px 16px;
  border-radius: 10px;
  color: var(--muted);
  cursor: pointer;
  border: 0;
  background: transparent;
  font-size: 0.95rem;
  white-space: nowrap;
}
.tab.active {
  color: #fff;
  background: linear-gradient(120deg, var(--brand-a), var(--brand-b));
  box-shadow: 0 6px 14px rgba(124, 139, 255, 0.35);
}

.panel { display: none; }
.panel.active { display: block; }

.cmd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.cmd-category { font-weight: 700; margin: 14px 0 8px; color: var(--text); }
.cmd-category:first-child { margin-top: 0; }

.cmd-item {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px;
  background: rgba(6, 10, 24, 0.65);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  transition: border-color 0.2s, transform 0.2s;
}
.cmd-item:hover { border-color: var(--brand-a); transform: translateY(-1px); }
.cmd-item code {
  color: #c8d3ff;
  background: rgba(124, 139, 255, 0.08);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.92rem;
}

.switch {
  position: relative;
  width: 44px; height: 24px;
  display: inline-block;
  flex-shrink: 0;
}
.switch input { display: none; }
.slider {
  position: absolute; cursor: pointer;
  top: 0; left: 0; right: 0; bottom: 0;
  background: #2a355c;
  border-radius: 999px;
  transition: 0.2s;
}
.slider:before {
  position: absolute; content: "";
  height: 18px; width: 18px;
  left: 3px; top: 3px;
  background: white; border-radius: 50%;
  transition: 0.2s;
  box-shadow: 0 3px 8px rgba(0,0,0,0.35);
}
.switch input:checked + .slider {
  background: linear-gradient(120deg, var(--brand-a), var(--brand-b));
}
.switch input:checked + .slider:before { transform: translateX(20px); }

label { display: block; font-size: 0.85rem; color: var(--muted); margin-top: 8px; }

input[type="text"], input[type="number"], input[type="password"], select, textarea {
  width: 100%;
  background: rgba(5, 8, 22, 0.85);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 11px 12px;
  margin: 6px 0 4px;
  font-size: 0.95rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}
input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--brand-a);
  box-shadow: 0 0 0 3px rgba(124, 139, 255, 0.18);
}

.row { display: grid; gap: 10px; grid-template-columns: 1fr 1fr; }

.flash {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 0.9rem;
  display: none;
}
.flash.ok { display: block; background: rgba(48, 212, 138, 0.15); border: 1px solid rgba(48, 212, 138, 0.45); color: #9cf3c6; }
.flash.err { display: block; background: rgba(255, 107, 107, 0.15); border: 1px solid rgba(255, 107, 107, 0.45); color: #ffc0c0; }

.err-banner {
  margin-bottom: 18px;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.35);
  color: #ffd2d2;
}

.top-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.top-list li {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(6, 10, 24, 0.5);
}
.top-list .pos {
  width: 26px; height: 26px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, var(--brand-a), var(--brand-b));
  font-weight: 700; font-size: 0.8rem; color: white;
  flex-shrink: 0;
}
.audit-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.audit-item {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(6, 10, 24, 0.55);
  padding: 10px 12px;
}
.audit-item .meta { color: var(--muted); font-size: 0.78rem; margin-bottom: 4px; }
.audit-item .chg { color: var(--text); font-size: 0.88rem; white-space: pre-wrap; word-break: break-word; }

.stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; margin-bottom: 14px; }
.stat {
  border: 1px solid var(--line);
  background: rgba(6, 10, 24, 0.55);
  border-radius: 12px;
  padding: 12px 14px;
}
.stat .v { font-size: 1.3rem; font-weight: 700; }
.stat .l { font-size: 0.78rem; color: var(--muted); margin-top: 2px; }

footer {
  margin-top: 40px;
  text-align: center;
  color: var(--muted);
  font-size: 0.85rem;
}

@media (max-width: 960px) {
  .hero { grid-template-columns: 1fr; }
  .half, .third, .two-third { grid-column: span 12; }
  .row { grid-template-columns: 1fr; }
  .hero h1 { font-size: 1.65rem; }
}
"""


def _nav(user: Dict | None = None, show_servers: bool = False) -> str:
    right = ""
    if user:
        uname = html.escape(user.get("username", "?"))
        role = html.escape(str(user.get("role", "")))
        role_badge = f'<span class="pill">{role}</span>' if role else ""
        right = (
            f'<span class="pill">Logado: {uname}</span>'
            f"{role_badge}"
            f'<a class="btn btn-ghost" href="/dashboard">Servidores</a>'
            f'<a class="btn" href="/admin/logout">Sair</a>'
        )
    else:
        right = (
            '<a class="btn btn-brand" href="/login">Entrar com Discord</a>'
            '<a class="btn btn-ghost btn-admin-hidden" href="/admin" title="Admin">'
            "&#128737;"
            "</a>"
        )

    brand_image = html.escape(_bot_brand_image())
    return f"""
    <nav class="nav">
      <a class="brand" href="/">
        <div class="brand-badge"><img src="{brand_image}" alt="bot avatar"/></div>
        <div>
          <div>MIOSE Panel</div>
          <div style="font-size:.72rem;color:var(--muted);font-weight:400">Dashboard do bot</div>
        </div>
      </a>
      <div class="nav-right">{right}</div>
    </nav>
    """


def _render_page(title: str, body: str) -> HTMLResponse:
    page = f"""<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} — MIOSE Panel</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{BASE_CSS}</style>
</head>
<body>
  <div class="wrap">{body}
    <footer>MIOSE Panel - gerenciamento por servidor com login Discord</footer>
  </div>
</body>
</html>"""
    return HTMLResponse(page)


def _env_or_file(key: str, default: str = "") -> str:
    val = os.environ.get(key, "").strip().strip('"').strip("'")
    if val:
        return val
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        parsed = v.strip().strip('"').strip("'")
                        if parsed:
                            return parsed
        except Exception:
            pass
    return default


def _cfg() -> Dict[str, str]:

    return {
        "client_id": _env_or_file("DISCORD_CLIENT_ID", ""),
        "client_secret": _env_or_file("DISCORD_CLIENT_SECRET", ""),
        "redirect_uri": _env_or_file("DISCORD_REDIRECT_URI", ""),
    }


def _bot_brand_image() -> str:
    return (os.environ.get("WEB_BRAND_IMAGE_URL", "").strip() or BOT_BRAND_IMAGE_DEFAULT).strip()


def _admin_cfg() -> Dict[str, str | int]:
    ttl_raw = _env_or_file("ADMIN_SESSION_TTL_SEC", "7200")
    try:
        ttl = max(300, int(ttl_raw))
    except ValueError:
        ttl = 7200
    return {
        "username": _env_or_file("ADMIN_USERNAME", ""),
        "password_hash": _env_or_file("ADMIN_PASSWORD_HASH", ""),
        "password_plain": _env_or_file("ADMIN_PASSWORD", ""),
        "allow_plain_fallback": _env_or_file("ADMIN_ALLOW_PLAIN_FALLBACK", "false").lower() in {"1", "true", "yes"},
        "role": _env_or_file("ADMIN_ROLE", ADMIN_DEFAULT_ROLE).lower() or ADMIN_DEFAULT_ROLE,
        "ttl_sec": ttl,
    }


def _session_secret() -> str:
    secret = os.environ.get("WEB_SESSION_SECRET", "").strip()
    if not secret:
        secret = "change-me-now"
    strict = _env_or_file("WEB_STRICT_SECURITY", "false").lower() in {"1", "true", "yes"}
    if strict and secret == "change-me-now":
        # In strict mode we still keep app online, but warn loudly and rotate an in-memory secret.
        # This avoids taking down the whole panel due missing env in hosting platforms.
        secret = secrets.token_urlsafe(48)
        print("[WEB] WARNING: WEB_STRICT_SECURITY=true sem WEB_SESSION_SECRET valido; usando segredo temporario.")
    if secret == "change-me-now":
        # Fallback to keep web panel online in unmanaged environments.
        secret = secrets.token_urlsafe(48)
        print("[WEB] WARNING: WEB_SESSION_SECRET nao definido; usando segredo temporario gerado em runtime.")
    return secret


def _authorized(request: Request) -> bool:
    return bool(request.session.get("user"))


def _panel_authorized(request: Request) -> bool:
    return _admin_session_valid(request) or _authorized(request)


def _require_auth(request: Request) -> None:
    if not _panel_authorized(request):
        raise HTTPException(status_code=401, detail="Nao autenticado")


def _ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def _validate_csrf(request: Request) -> None:
    expected = str(request.session.get("csrf_token") or "")
    provided = str(request.headers.get("x-csrf-token") or "")
    if not expected or not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=403, detail="CSRF invalido")


def _admin_session_valid(request: Request) -> bool:
    session = request.session
    if not session.get("admin_authenticated"):
        return False
    if session.get("admin_role") != str(_admin_cfg()["role"]):
        return False
    try:
        auth_at = int(session.get("admin_auth_at") or 0)
    except (TypeError, ValueError):
        return False
    ttl = int(_admin_cfg()["ttl_sec"])
    if (int(time.time()) - auth_at) > ttl:
        session.clear()
        return False
    return True


def _require_admin(request: Request) -> None:
    if not _admin_session_valid(request):
        raise HTTPException(status_code=401, detail="Sessao admin expirada ou inexistente")


def _actor_id_from_session(request: Request) -> int:
    user = request.session.get("user", {})
    if isinstance(user, dict):
        uid = user.get("id")
        if uid is not None:
            try:
                return int(uid)
            except (TypeError, ValueError):
                pass
    admin_user = str(request.session.get("admin_user", "")).strip()
    if admin_user:
        if admin_user.isdigit():
            return int(admin_user)
        # Fallback estavel para auditoria quando username admin nao e numerico.
        return abs(hash(admin_user)) % 2_000_000_000
    return 0


def _exchange_code_for_token(code: str) -> Dict[str, str]:
    conf = _cfg()
    data = {
        "client_id": conf["client_id"],
        "client_secret": conf["client_secret"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": conf["redirect_uri"],
    }
    r = requests.post(f"{DISCORD_API}/oauth2/token", data=data, timeout=20)
    r.raise_for_status()
    return r.json()


def _discord_get(url: str, token: str):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    r.raise_for_status()
    return r.json()


def _manageable_guilds(token: str) -> List[Dict]:
    guilds = _discord_get(f"{DISCORD_API}/users/@me/guilds", token)
    allowed = []
    for guild in guilds:
        # Discord pode enviar permissoes em chaves diferentes conforme contexto/versionamento.
        # Aceitamos owner ou bit de admin/manage_guild em qualquer campo conhecido.
        raw_perms = guild.get("permissions_new", guild.get("permissions", "0"))
        try:
            perms = int(raw_perms or 0)
        except (TypeError, ValueError):
            perms = 0
        is_owner = bool(guild.get("owner"))
        if is_owner or (perms & ADMIN_PERMS):
            allowed.append(guild)
    return allowed


def _ensure_guild_access(request: Request, guild_id: int) -> None:
    if request.session.get("admin_role") == ADMIN_DEFAULT_ROLE:
        return
    allowed = request.session.get("allowed_guild_ids", [])
    gid = str(guild_id)
    if gid in allowed:
        return

    raise HTTPException(status_code=403, detail="Sem permissao para este servidor")


def _guild_avatar_html(g: Dict) -> str:
    gid = g.get("id", "")
    icon = g.get("icon")
    name = g.get("name", "?")
    if icon and gid:
        ext = "gif" if str(icon).startswith("a_") else "png"
        src = f"{DISCORD_CDN}/icons/{gid}/{icon}.{ext}?size=128"
        return f'<img class="server-avatar" src="{html.escape(src)}" alt=""/>'
    initial = html.escape(name.strip()[:1].upper() or "?")
    return f'<div class="server-avatar">{initial}</div>'


def _bot_guilds(bot) -> List[Dict]:
    guilds = []
    for guild in getattr(bot, "guilds", []) or []:
        guilds.append(
            {
                "id": str(guild.id),
                "name": str(guild.name),
                "icon": str(guild.icon.key) if getattr(guild, "icon", None) else None,
                "owner": True,
            }
        )
    return guilds


def create_app(bot) -> FastAPI:
    def _redirect_if_not_auth(request: Request):
        if not _panel_authorized(request):
            return RedirectResponse("/login")
        return None

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    store = ConfigStore(base_dir)
    access_audit_path = os.path.join(base_dir, "data", "admin_access_audit.json")

    def _audit_admin_event(request: Request, action: str, ok: bool, details: Dict | None = None) -> None:
        payload = {
            "at": int(time.time()),
            "action": action,
            "ok": bool(ok),
            "actor": request.session.get("admin_user") or "anonymous",
            "role": request.session.get("admin_role") or "",
            "ip": request.client.host if request.client else "",
            "details": details or {},
        }
        try:
            os.makedirs(os.path.dirname(access_audit_path), exist_ok=True)
            entries = []
            if os.path.exists(access_audit_path):
                with open(access_audit_path, "r", encoding="utf-8") as fp:
                    loaded = json.load(fp)
                    if isinstance(loaded, list):
                        entries = loaded
            entries.append(payload)
            with open(access_audit_path, "w", encoding="utf-8") as fp:
                json.dump(entries[-1000:], fp, indent=2, ensure_ascii=False)
        except Exception:
            pass

    app = FastAPI(title="MIOSE Panel")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(),
        max_age=int(_admin_cfg()["ttl_sec"]),
        same_site="lax",
        https_only=_env_or_file("WEB_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
    )

    @app.get("/health")
    async def health():
        return {"ok": True, "bot_user": str(bot.user) if bot.user else None}

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if _panel_authorized(request):
            return RedirectResponse("/dashboard")
        err = request.query_params.get("error_msg", "")
        err_block = ""
        if err:
            err_block = (
                f'<div class="err-banner"><b>Erro OAuth:</b> {html.escape(err)}</div>'
            )
        brand_image = html.escape(_bot_brand_image())

        body = (
            _nav(None)
            + err_block
            + """
            <section class="hero">
              <div class="hero-left">
                <h1>Controle total do bot <span class="grad">do seu jeito</span></h1>
                <p>
                  Entre com a sua conta do Discord e configure cada servidor de um jeito visual:
                  slash/prefix, economia, anti-link e anti-nuke, tudo em tempo real.
                </p>
                <div style="display:flex;gap:10px;flex-wrap:wrap;">
                  <a class="btn btn-brand" href="/login">Entrar com Discord</a>
                  <a class="btn" href="https://discord.com/oauth2/authorize?client_id=1295993386364567552" target="_blank" rel="noopener noreferrer">
                    Adicionar bot ao servidor
                  </a>
                </div>
              </div>
              <div class="hero-right">
                """
            + f'<img class="bot-photo" src="{brand_image}" alt="Bot avatar" />'
            + """
                <ul class="feature-list">
                  <li><span class="feature-dot"></span><div><b>Por servidor</b><div class="muted">Selecione e configure cada guild independentemente.</div></div></li>
                  <li><span class="feature-dot"></span><div><b>Toggles e formularios</b><div class="muted">Interface clara para ativar, desativar e ajustar valores.</div></div></li>
                  <li><span class="feature-dot"></span><div><b>Seguranca</b><div class="muted">Apenas quem tem permissao administrativa no Discord entra.</div></div></li>
                  <li><span class="feature-dot"></span><div><b>Integrado ao bot</b><div class="muted">Mudancas aparecem ao vivo sem reiniciar nada.</div></div></li>
                </ul>
              </div>
            </section>

            <div class="section-title">
              <h2>O que voce pode fazer</h2>
              <span class="muted">visao geral</span>
            </div>
            <div class="grid">
              <div class="card third"><h3>Slash / Prefix</h3><p class="hint">Ative ou desative comandos slash por categoria e servidor, com fallback em prefix.</p></div>
              <div class="card third"><h3>Economia</h3><p class="hint">Ajuste ToT por minuto, multiplicadores e cargos do ranking top 1/2/3.</p></div>
              <div class="card third"><h3>Seguranca</h3><p class="hint">Anti-link com acoes (warn/delete/kick/timeout) e anti-nuke com notificacoes.</p></div>
            </div>
            """
        )
        return _render_page("Login", body)

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_login_page(request: Request):
        if _admin_session_valid(request):
            return RedirectResponse("/dashboard")
        err = request.query_params.get("error", "")
        err_block = ""
        if err == "invalid_credentials":
            err_block = '<div class="err-banner"><b>Falha no login:</b> credenciais invalidas.</div>'
        elif err == "invalid_hash":
            err_block = (
                '<div class="err-banner"><b>Config invalida:</b> '
                "ADMIN_PASSWORD_HASH nao esta em formato bcrypt valido.</div>"
            )
        body = (
            _nav(None)
            + err_block
            + """
            <div class="grid">
              <div class="card half" style="margin:0 auto;grid-column:span 12;max-width:500px;">
                <h3>Login administrativo</h3>
                <p class="hint">Acesso protegido por credenciais de superadmin configuradas no .env.</p>
                <form method="post" action="/admin/login">
                  <label>Usuario</label>
                  <input type="text" name="username" autocomplete="username" required />
                  <label>Senha</label>
                  <input type="password" name="password" autocomplete="current-password" required />
                  <div style="margin-top:12px;">
                    <button class="btn btn-brand" type="submit">Entrar</button>
                  </div>
                </form>
              </div>
            </div>
            """
        )
        return _render_page("Admin Login", body)

    @app.post("/admin/login")
    async def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
        conf = _admin_cfg()
        expected_username = str(conf["username"]).strip()
        expected_hash = str(conf["password_hash"]).strip()
        expected_plain = str(conf["password_plain"]).strip()
        allow_plain = bool(conf.get("allow_plain_fallback"))
        if not expected_username or (not expected_hash and not (allow_plain and expected_plain)):
            _audit_admin_event(request, "login", False, {"reason": "missing_env"})
            raise HTTPException(
                status_code=500,
                detail="Configure ADMIN_USERNAME e ADMIN_PASSWORD_HASH no .env",
            )
        valid_user = username.strip() == expected_username
        valid_password = False
        if valid_user:
            if expected_hash:
                try:
                    valid_password = bcrypt.checkpw(password.encode("utf-8"), expected_hash.encode("utf-8"))
                except ValueError:
                    valid_password = False
                    _audit_admin_event(request, "login", False, {"reason": "invalid_hash_format"})
            if (not valid_password) and allow_plain and expected_plain:
                valid_password = password == expected_plain
                if valid_password:
                    _audit_admin_event(request, "login", True, {"auth": "plain_fallback"})
        if not (valid_user and valid_password):
            _audit_admin_event(request, "login", False, {"user": username.strip()})
            return RedirectResponse("/admin?error=invalid_credentials", status_code=303)
        request.session.clear()
        request.session["admin_authenticated"] = True
        request.session["admin_role"] = str(conf["role"])
        request.session["admin_user"] = username.strip()
        request.session["admin_auth_at"] = int(time.time())
        panel_guilds = _bot_guilds(bot)
        request.session["guilds"] = panel_guilds
        request.session["allowed_guild_ids"] = [g["id"] for g in panel_guilds]
        _audit_admin_event(request, "login", True, {"user": username.strip()})
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/login")
    async def login(request: Request):
        conf = _cfg()
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        params = urlencode(
            {
                "client_id": conf["client_id"],
                "response_type": "code",
                "redirect_uri": conf["redirect_uri"],
                "scope": "identify guilds",
                "state": state,
            }
        )
        return RedirectResponse(f"https://discord.com/oauth2/authorize?{params}")

    @app.get("/callback")
    async def callback(request: Request, code: str | None = None, error: str | None = None, state: str | None = None):
        if error:
            return RedirectResponse(f"/?error_msg={quote(error)}")
        if not code:
            return RedirectResponse("/?error_msg=missing_code")
        expected_state = str(request.session.get("oauth_state") or "")
        if not state or not expected_state or not secrets.compare_digest(expected_state, state):
            return RedirectResponse("/?error_msg=invalid_state")
        try:
            token_data = _exchange_code_for_token(code)
            access_token = token_data["access_token"]
            user = _discord_get(f"{DISCORD_API}/users/@me", access_token)
            guilds = _manageable_guilds(access_token)
            request.session.pop("oauth_state", None)
            request.session["user"] = {
                "id": user["id"],
                "username": user.get("global_name") or user.get("username") or "?",
                "avatar": user.get("avatar"),
            }
            request.session["guilds"] = guilds
            request.session["allowed_guild_ids"] = [g["id"] for g in guilds]
            return RedirectResponse("/dashboard")
        except requests.HTTPError as e:
            msg = "oauth_http_error"
            try:
                payload = e.response.json()
                if isinstance(payload, dict):
                    msg = payload.get("error_description") or payload.get("error") or msg
            except Exception:
                pass
            return RedirectResponse(f"/?error_msg={quote(str(msg))}")
        except Exception:
            return RedirectResponse("/?error_msg=oauth_failed")

    @app.get("/logout")
    async def logout(request: Request):
        _audit_admin_event(request, "logout", True)
        request.session.clear()
        return RedirectResponse("/")

    @app.get("/admin/logout")
    async def admin_logout(request: Request):
        _audit_admin_event(request, "logout", True)
        request.session.clear()
        return RedirectResponse("/admin")

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        maybe_redirect = _redirect_if_not_auth(request)
        if maybe_redirect:
            return maybe_redirect
        if _admin_session_valid(request):
            _audit_admin_event(request, "dashboard_view", True)
            user = {
                "username": request.session.get("admin_user", "admin"),
                "role": request.session.get("admin_role", ADMIN_DEFAULT_ROLE),
            }
            guilds = request.session.get("guilds", _bot_guilds(bot))
        else:
            user = request.session.get("user", {})
            guilds = request.session.get("guilds", [])

        server_cards = []
        for g in guilds:
            gname = html.escape(g.get("name", "Servidor"))
            gid = html.escape(str(g.get("id", "")))
            server_cards.append(
                f"""
                <a class="server" href="/guild/{gid}">
                  {_guild_avatar_html(g)}
                  <div>
                    <div class="server-name">{gname}</div>
                    <div class="server-id">ID {gid}</div>
                  </div>
                </a>
                """
            )

        stats = f"""
        <div class="stat-grid">
          <div class="stat"><div class="v">{len(guilds)}</div><div class="l">Servidores disponiveis</div></div>
          <div class="stat"><div class="v">OAuth2</div><div class="l">Metodo de login</div></div>
          <div class="stat"><div class="v">Discord</div><div class="l">Conta autenticada</div></div>
        </div>
        """

        body = (
            _nav(user)
            + f"""
            <div class="section-title">
              <h2>Ola, {html.escape(user.get('username','?'))}</h2>
              <span class="muted">escolha um servidor para configurar</span>
            </div>
            <div class="card full">
              {stats}
              <div class="server-grid">
                {''.join(server_cards) or '<p class="muted">Nenhum servidor com permissao administrativa encontrado.</p>'}
              </div>
            </div>
            """
        )
        return _render_page("Dashboard", body)

    @app.get("/guild/{guild_id}", response_class=HTMLResponse)
    async def guild_page(guild_id: int, request: Request):
        maybe_redirect = _redirect_if_not_auth(request)
        if maybe_redirect:
            return maybe_redirect
        _ensure_guild_access(request, guild_id)
        if _admin_session_valid(request):
            user = {
                "username": request.session.get("admin_user", "admin"),
                "role": request.session.get("admin_role", ADMIN_DEFAULT_ROLE),
            }
            guilds = request.session.get("guilds", _bot_guilds(bot))
        else:
            user = request.session.get("user", {})
            guilds = request.session.get("guilds", [])
        guild_obj = {"id": str(guild_id), "name": str(guild_id)}
        for g in guilds:
            if g.get("id") == str(guild_id):
                guild_obj = g
                break
        if guild_obj.get("name") == str(guild_id):
            bot_guild = bot.get_guild(int(guild_id))
            if bot_guild:
                guild_obj = {
                    "id": str(bot_guild.id),
                    "name": str(bot_guild.name),
                    "icon": str(bot_guild.icon.key) if getattr(bot_guild, "icon", None) else None,
                }
        guild_name = html.escape(guild_obj.get("name", str(guild_id)))

        general_cfg = store.get_server_slash(guild_id)
        slash_cfg = general_cfg.get("slash_cmds", {})
        current_prefix = str(general_cfg.get("prefix", "!") or "!")[:5]
        modules_cfg = general_cfg.get("modules", {}) if isinstance(general_cfg.get("modules", {}), dict) else {}
        econ_cfg = store.get_econ()
        rank_roles = econ_cfg.get("rank_role_ids", {}) or {}
        anti_link = store.get_antilink(guild_id)
        anti_nuke = store.get_antinuke(guild_id)
        antp_cfg = store.get_antp(guild_id)
        commands_payload = []
        try:
            guild_obj_ref = discord.Object(id=int(guild_id))
            slash_commands = bot.tree.get_commands(guild=guild_obj_ref) or bot.tree.get_commands() or []
            commands_payload = sorted({c.name for c in slash_commands if getattr(c, "name", None)})
        except Exception:
            # fallback to known categories if tree isn't ready
            flat = []
            for _cat, cmds in COMMAND_CATEGORIES.items():
                flat.extend(cmds)
            commands_payload = sorted(set(flat))

        # New unified panel (replaces legacy tabbed page) with command categories.
        categories_map = {}
        for cat_name, cmds in COMMAND_CATEGORIES.items():
            categories_map[str(cat_name)] = {str(c).strip().lstrip("/") for c in cmds if str(c).strip()}
        all_known = set().union(*categories_map.values()) if categories_map else set()
        uncategorized = sorted([c for c in commands_payload if c not in all_known])
        if uncategorized:
            categories_map["Outros"] = set(uncategorized)

        section_rows = []
        normalized_payload = set(commands_payload)
        for cat_name, cat_cmds in categories_map.items():
            present_cmds = sorted([c for c in cat_cmds if c in normalized_payload])
            if not present_cmds:
                continue
            rows_html = []
            for cmd_name in present_cmds:
                on = slash_cfg.get(cmd_name, True)
                checked = "checked" if on else ""
                rows_html.append(
                    f"""
                    <div class="cmd-row" data-cat="{html.escape(cat_name.lower())}">
                      <div>
                        <div class="cmd-name">/{html.escape(cmd_name)}</div>
                        <div class="cmd-sub">Categoria: {html.escape(cat_name)} • Slash {'ativo' if on else 'desativado'}</div>
                      </div>
                      <label class="switch">
                        <input type="checkbox" name="slash_cmd" value="{html.escape(cmd_name)}" {checked}/>
                        <span class="slider"></span>
                      </label>
                    </div>
                    """
                )
            section_rows.append(
                f"""
                <details class="cmd-cat" open>
                  <summary>{html.escape(cat_name)} <span class="muted">({len(present_cmds)})</span></summary>
                  <div class="cmd-list">{''.join(rows_html)}</div>
                </details>
                """
            )
        command_rows_html = "".join(section_rows) or "<p class='muted'>Sem comandos detectados.</p>"

        body = (
            _nav(user)
            + f"""
            <style>
              .layoutX {{ display:grid; grid-template-columns: 260px minmax(0,1fr); gap:16px; align-items:start; }}
              .sidebarX {{ position:sticky; top:14px; background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px; }}
              .sb-title {{ font-weight:800; margin:0 0 4px 0; }}
              .sb-sub {{ color:var(--muted); font-size:.9rem; margin:0 0 12px 0; }}
              .sb-nav {{ display:grid; gap:8px; }}
              .sb-btn {{ width:100%; text-align:left; border:1px solid var(--line); background:rgba(255,255,255,.02); color:var(--text); border-radius:10px; padding:10px; cursor:pointer; }}
              .sb-btn.active {{ border-color:var(--brand); box-shadow:0 0 0 1px rgba(126,92,255,.35) inset; background:rgba(126,92,255,.12); }}
              .contentX {{ display:grid; gap:14px; }}
              .cardX {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px; }}
              .headX {{ display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }}
              .sectionX {{ display:none; }}
              .sectionX.active {{ display:block; }}
              .gridX {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; }}
              .cmd-groups {{ max-height:62vh; overflow:auto; display:grid; gap:10px; margin-top:10px; padding-right:4px; }}
              .cmd-list {{ display:grid; gap:8px; margin-top:8px; }}
              .cmd-row {{ display:flex; justify-content:space-between; align-items:center; gap:10px; padding:10px; border:1px solid var(--line); border-radius:10px; background:rgba(255,255,255,.02); }}
              .cmd-name {{ font-weight:700; }}
              .cmd-sub {{ color:var(--muted); font-size:.85rem; }}
              .cmd-cat {{ border:1px solid var(--line); border-radius:12px; padding:10px; background:rgba(255,255,255,.01); }}
              .cmd-cat summary {{ cursor:pointer; font-weight:700; }}
              .toolbar {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }}
              .field {{ display:grid; gap:6px; margin-bottom:10px; }}
              .field input,.field select,.field textarea {{ background:rgba(0,0,0,.25); color:var(--text); border:1px solid var(--line); border-radius:8px; padding:10px; }}
              .row2 {{ display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); }}
              .flashBox {{ margin-top:8px; min-height:20px; color:var(--muted); }}
              .ok {{ color:#30d48a; }} .err {{ color:#ff6b6b; }}
              @media (max-width: 940px) {{
                .layoutX {{ grid-template-columns:1fr; }}
                .sidebarX {{ position:static; }}
              }}
            </style>

            <section class="hero" style="grid-template-columns: 1fr;">
              <div class="hero-left">
                <h1>Painel • <span class="grad">{guild_name}</span></h1>
                <p>Interface clean com barra lateral para gerenciar tudo em um lugar.</p>
                <div style="display:flex;gap:8px;flex-wrap:wrap;">
                  <a class="btn" href="/dashboard">Voltar</a>
                  <span class="pill">Guild: {guild_id}</span>
                  <span class="pill">Slash detectados: {len(commands_payload)}</span>
                </div>
              </div>
            </section>

            <div class="layoutX">
              <aside class="sidebarX">
                <p class="sb-title">Navegacao</p>
                <p class="sb-sub">Escolha a categoria para configurar.</p>
                <div class="sb-nav">
                  <button class="sb-btn active" data-target="sec-comandos">Comandos</button>
                  <button class="sb-btn" data-target="sec-geral">Geral</button>
                  <button class="sb-btn" data-target="sec-economia">Economia</button>
                  <button class="sb-btn" data-target="sec-leveling">Leveling</button>
                  <button class="sb-btn" data-target="sec-moderacao">Moderacao</button>
                  <button class="sb-btn" data-target="sec-automacao">Automacao</button>
                </div>
              </aside>

              <main class="contentX">
                <section class="sectionX active" id="sec-comandos">
                  <div class="cardX">
                    <div class="headX">
                      <h3 style="margin:0;">Comandos Slash por categoria</h3>
                      <input id="cmdSearch" type="text" placeholder="Filtrar /comando..." style="max-width:280px;" />
                    </div>
                    <div class="cmd-groups" id="cmdList">{command_rows_html}</div>
                    <div class="toolbar">
                      <button class="btn" onclick="toggleAllSlash(true)">Tudo slash</button>
                      <button class="btn" onclick="toggleAllSlash(false)">Tudo prefix</button>
                      <button class="btn btn-brand" onclick="saveSlash()">Salvar comandos</button>
                      <span class="pill" id="slashCount"></span>
                    </div>
                    <div id="flash-slash" class="flashBox"></div>
                  </div>
                </section>

                <section class="sectionX" id="sec-geral">
                  <div class="cardX">
                    <h3 style="margin-top:0;">Configuracoes gerais</h3>
                    <div class="field"><label>Prefixo</label><input id="guild_prefix" maxlength="5" value="{html.escape(current_prefix)}"/></div>
                    <button class="btn btn-brand" onclick="saveGeneral()">Salvar geral</button>
                    <div id="flash-geral" class="flashBox"></div>
                  </div>
                </section>

                <section class="sectionX" id="sec-economia">
                  <div class="cardX">
                    <h3 style="margin-top:0;">Economia</h3>
                    <div class="row2">
                      <div class="field"><label>ToT/min</label><input id="tot_per_min" type="number" min="1" value="{int(econ_cfg.get('tot_per_min', 2))}"/></div>
                      <div class="field"><label>Intervalo (s)</label><input id="payout_interval_sec" type="number" min="30" max="1800" value="{int(econ_cfg.get('payout_interval_sec', 120))}"/></div>
                    </div>
                    <div class="row2">
                      <div class="field"><label>Top1 role ID</label><input id="top1" type="number" value="{rank_roles.get('top1') or ''}"/></div>
                      <div class="field"><label>Top2 role ID</label><input id="top2" type="number" value="{rank_roles.get('top2') or ''}"/></div>
                      <div class="field"><label>Top3 role ID</label><input id="top3" type="number" value="{rank_roles.get('top3') or ''}"/></div>
                    </div>
                    <button class="btn btn-brand" onclick="saveEconomy()">Salvar economia</button>
                    <div id="flash-econ" class="flashBox"></div>
                  </div>
                </section>

                <section class="sectionX" id="sec-leveling">
                  <div class="cardX">
                    <h3 style="margin-top:0;">Leveling</h3>
                    <div class="row2">
                      <div class="field"><label>Ativo</label><select id="lv_enabled"><option value="true">Sim</option><option value="false">Nao</option></select></div>
                      <div class="field"><label>Cooldown msg (s)</label><input id="lv_cd" type="number" min="5" value="45"/></div>
                    </div>
                    <div class="row2">
                      <div class="field"><label>XP msg min</label><input id="lv_min" type="number" min="1" value="8"/></div>
                      <div class="field"><label>XP msg max</label><input id="lv_max" type="number" min="1" value="16"/></div>
                      <div class="field"><label>XP voz/min</label><input id="lv_vpm" type="number" min="0.1" step="0.1" value="1.0"/></div>
                    </div>
                    <button class="btn btn-brand" onclick="saveLeveling()">Salvar leveling</button>
                    <div id="flash-leveling" class="flashBox"></div>
                  </div>
                </section>

                <section class="sectionX" id="sec-moderacao">
                  <div class="cardX">
                    <h3 style="margin-top:0;">Moderacao</h3>
                    <div class="field"><label>Canal modlog ID</label><input id="modlog_channel_id" type="number" min="0" value="0"/></div>
                    <div class="field"><label>Escalonamento (JSON)</label><textarea id="warn_escalation" rows="6">{{"3":"timeout:30","5":"kick","7":"ban"}}</textarea></div>
                    <button class="btn btn-brand" onclick="saveModeration()">Salvar moderacao</button>
                    <div id="flash-moderation" class="flashBox"></div>
                  </div>
                </section>

                <section class="sectionX" id="sec-automacao">
                  <div class="cardX">
                    <h3 style="margin-top:0;">Automacao</h3>
                    <div class="row2">
                      <div class="field"><label>Canal welcome ID</label><input id="welcome_channel_id" type="number" min="0" value="0"/></div>
                      <div class="field"><label>Canal leave ID</label><input id="leave_channel_id" type="number" min="0" value="0"/></div>
                      <div class="field"><label>Autorole ID</label><input id="autorole_id" type="number" min="0" value="0"/></div>
                    </div>
                    <div class="field"><label>Mensagem welcome</label><input id="welcome_message" value="Bem-vindo(a), {{user}}, ao servidor {{guild}}!"/></div>
                    <div class="field"><label>Mensagem leave</label><input id="leave_message" value="{{user_name}} saiu do servidor."/></div>
                    <button class="btn btn-brand" onclick="saveAutomation()">Salvar automacao</button>
                    <div id="flash-automation" class="flashBox"></div>
                  </div>
                </section>
              </main>
            </div>

            <script>
              const gid = "{guild_id}";
              const csrfToken = "{_ensure_csrf_token(request)}";
              const sidebarButtons = [...document.querySelectorAll(".sb-btn")];
              const sections = [...document.querySelectorAll(".sectionX")];
              function openSection(id) {{
                sidebarButtons.forEach(b => b.classList.toggle("active", b.dataset.target === id));
                sections.forEach(s => s.classList.toggle("active", s.id === id));
              }}
              sidebarButtons.forEach(btn => btn.addEventListener("click", () => openSection(btn.dataset.target)));
              function flash(id, ok, text) {{
                const el = document.getElementById(id);
                el.className = "flashBox " + (ok ? "ok" : "err");
                el.textContent = text;
              }}
              async function postJSON(url, data) {{
                const r = await fetch(url, {{
                  method: "POST",
                  headers: {{ "Content-Type": "application/json", "X-CSRF-Token": csrfToken }},
                  body: JSON.stringify(data)
                }});
                if (!r.ok) {{
                  let msg = "Erro ao salvar";
                  try {{ const b = await r.json(); if (b.detail) msg = b.detail; }} catch (_e) {{}}
                  throw new Error(msg);
                }}
              }}
              function updateSlashCount() {{
                const all = [...document.querySelectorAll("input[name='slash_cmd']")];
                const on = all.filter(x=>x.checked).length;
                document.getElementById("slashCount").textContent = `Slash: ${{on}} / Prefix: ${{all.length-on}}`;
              }}
              function toggleAllSlash(v) {{
                document.querySelectorAll("input[name='slash_cmd']").forEach(el=>el.checked=!!v);
                updateSlashCount();
              }}
              async function saveSlash() {{
                const data={{}};
                document.querySelectorAll("input[name='slash_cmd']").forEach(el=>data[el.value]=!!el.checked);
                try {{ await postJSON(`/api/guild/${{gid}}/slash`, {{slash_cmds:data}}); flash("flash-slash", true, "Comandos salvos."); }}
                catch(e) {{ flash("flash-slash", false, e.message); }}
              }}
              async function saveGeneral() {{
                try {{
                  await postJSON(`/api/guild/${{gid}}/general`, {{prefix:(document.getElementById("guild_prefix").value||"!").trim().slice(0,5)||"!"}});
                  flash("flash-geral", true, "Geral salvo.");
                }} catch(e) {{ flash("flash-geral", false, e.message); }}
              }}
              async function saveEconomy() {{
                const payload={{
                  tot_per_min:Number(document.getElementById("tot_per_min").value||2),
                  payout_interval_sec:Number(document.getElementById("payout_interval_sec").value||120),
                  rank_role_ids:{{
                    top1:Number(document.getElementById("top1").value||0),
                    top2:Number(document.getElementById("top2").value||0),
                    top3:Number(document.getElementById("top3").value||0),
                  }}
                }};
                try {{ await postJSON(`/api/guild/${{gid}}/economy`, payload); flash("flash-econ", true, "Economia salva."); }}
                catch(e) {{ flash("flash-econ", false, e.message); }}
              }}
              async function saveLeveling() {{
                const payload={{
                  enabled:String(document.getElementById("lv_enabled").value)==="true",
                  message_xp_min:Number(document.getElementById("lv_min").value||8),
                  message_xp_max:Number(document.getElementById("lv_max").value||16),
                  message_cooldown_sec:Number(document.getElementById("lv_cd").value||45),
                  voice_xp_per_min:Number(document.getElementById("lv_vpm").value||1),
                }};
                try {{ await postJSON(`/api/guild/${{gid}}/leveling`, payload); flash("flash-leveling", true, "Leveling salvo."); }}
                catch(e) {{ flash("flash-leveling", false, e.message); }}
              }}
              async function saveModeration() {{
                let esc={{}};
                try {{ esc = JSON.parse(document.getElementById("warn_escalation").value||"{{}}"); }} catch(_e) {{}}
                const payload={{
                  modlog_channel_id:Number(document.getElementById("modlog_channel_id").value||0),
                  warn_escalation:esc
                }};
                try {{ await postJSON(`/api/guild/${{gid}}/moderation`, payload); flash("flash-moderation", true, "Moderacao salva."); }}
                catch(e) {{ flash("flash-moderation", false, e.message); }}
              }}
              async function saveAutomation() {{
                const payload={{
                  welcome_channel_id:Number(document.getElementById("welcome_channel_id").value||0),
                  welcome_message:document.getElementById("welcome_message").value||"",
                  leave_channel_id:Number(document.getElementById("leave_channel_id").value||0),
                  leave_message:document.getElementById("leave_message").value||"",
                  autorole_id:Number(document.getElementById("autorole_id").value||0),
                }};
                try {{ await postJSON(`/api/guild/${{gid}}/automation`, payload); flash("flash-automation", true, "Automacao salva."); }}
                catch(e) {{ flash("flash-automation", false, e.message); }}
              }}
              async function loadSnapshot() {{
                try {{
                  const r = await fetch(`/api/guild/${{gid}}/snapshot`);
                  if (!r.ok) throw new Error("Falha ao carregar snapshot");
                  const s = await r.json();

                  const slash = s.slash_cmds || {{}};
                  document.querySelectorAll("input[name='slash_cmd']").forEach(el => {{
                    if (Object.prototype.hasOwnProperty.call(slash, el.value)) {{
                      el.checked = !!slash[el.value];
                    }}
                  }});

                  const prefix = (s.general && s.general.prefix) || "!";
                  document.getElementById("guild_prefix").value = String(prefix).slice(0, 5);

                  const economy = s.economy || {{}};
                  document.getElementById("tot_per_min").value = Number(economy.tot_per_min ?? 2);
                  document.getElementById("payout_interval_sec").value = Number(economy.payout_interval_sec ?? 120);
                  const rr = economy.rank_role_ids || {{}};
                  document.getElementById("top1").value = rr.top1 || "";
                  document.getElementById("top2").value = rr.top2 || "";
                  document.getElementById("top3").value = rr.top3 || "";

                  const leveling = s.leveling || {{}};
                  document.getElementById("lv_enabled").value = String(!!leveling.enabled);
                  document.getElementById("lv_min").value = Number(leveling.message_xp_min ?? 8);
                  document.getElementById("lv_max").value = Number(leveling.message_xp_max ?? 16);
                  document.getElementById("lv_cd").value = Number(leveling.message_cooldown_sec ?? 45);
                  document.getElementById("lv_vpm").value = Number(leveling.voice_xp_per_min ?? 1);

                  const moderation = s.moderation || {{}};
                  document.getElementById("modlog_channel_id").value = Number(moderation.modlog_channel_id ?? 0);
                  document.getElementById("warn_escalation").value = JSON.stringify(moderation.warn_escalation || {{}}, null, 2);

                  const automation = s.automation || {{}};
                  document.getElementById("welcome_channel_id").value = Number(automation.welcome_channel_id ?? 0);
                  document.getElementById("welcome_message").value = automation.welcome_message || "";
                  document.getElementById("leave_channel_id").value = Number(automation.leave_channel_id ?? 0);
                  document.getElementById("leave_message").value = automation.leave_message || "";
                  document.getElementById("autorole_id").value = Number(automation.autorole_id ?? 0);
                }} catch (_e) {{}}
              }}
              document.getElementById("cmdSearch").addEventListener("input", (ev) => {{
                const q=(ev.target.value||"").toLowerCase().trim();
                document.querySelectorAll(".cmd-row").forEach(row=> {{
                  const t=row.querySelector(".cmd-name").textContent.toLowerCase();
                  row.style.display = (!q || t.includes(q)) ? "" : "none";
                }});
                document.querySelectorAll(".cmd-cat").forEach(cat => {{
                  const visibleRows = [...cat.querySelectorAll(".cmd-row")].filter(r => r.style.display !== "none").length;
                  cat.style.display = visibleRows ? "" : "none";
                }});
              }});
              loadSnapshot();
              updateSlashCount();
            </script>
            """
        )
        return _render_page(f"Servidor {guild_name}", body)

    @app.post("/api/guild/{guild_id}/slash")
    async def update_slash(guild_id: int, payload: SlashUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        store.update_server_slash(actor, guild_id, payload.slash_cmds)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/general")
    async def update_general(guild_id: int, payload: GeneralUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        data = payload.model_dump(exclude_none=True)
        if "prefix" in data:
            p = str(data["prefix"]).strip()
            if not p:
                p = "!"
            data["prefix"] = p[:5]
        if "modules" in data and isinstance(data["modules"], dict):
            data["modules"] = {str(k).lower(): bool(v) for k, v in data["modules"].items()}
        store.update_server_general(actor, guild_id, data)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/economy")
    async def update_economy(guild_id: int, payload: EconUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        data = payload.model_dump(exclude_none=True)
        if "rank_role_ids" in data:
            cleaned_roles = {}
            for k, v in data["rank_role_ids"].items():
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                if iv > 0:
                    cleaned_roles[k] = iv
            data["rank_role_ids"] = cleaned_roles
        store.update_econ(actor, guild_id, data)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/antilink")
    async def update_antilink(guild_id: int, payload: AntiLinkUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        data = payload.model_dump(exclude_none=True)
        if "action" in data and data["action"] not in {"warn", "delete", "kick", "timeout"}:
            raise HTTPException(status_code=400, detail="action invalida")
        if "timeout_minutes" in data:
            data["timeout_minutes"] = max(1, min(int(data["timeout_minutes"]), 1440))
        store.update_antilink(actor, guild_id, data)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/antinuke")
    async def update_antinuke(guild_id: int, payload: AntiNukeUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        data = payload.model_dump(exclude_none=True)
        if "log_channel" in data:
            data["log_channel"] = int(data["log_channel"]) or None
        store.update_antinuke(actor, guild_id, data)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/antp")
    async def update_antp(guild_id: int, payload: AntpUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        data = payload.model_dump(exclude_none=True)
        if "exempt_role_ids" in data and isinstance(data["exempt_role_ids"], list):
            cleaned = []
            for v in data["exempt_role_ids"]:
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                if iv > 0:
                    cleaned.append(iv)
            data["exempt_role_ids"] = cleaned
        store.update_antp(actor, guild_id, data)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/leveling")
    async def update_leveling_api(guild_id: int, payload: LevelingUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        data = payload.model_dump(exclude_none=True)
        if data:
            clean = {}
            if "enabled" in data:
                clean["enabled"] = bool(data["enabled"])
            if "message_xp_min" in data:
                clean["message_xp_min"] = max(1, min(int(data["message_xp_min"]), 1000))
            if "message_xp_max" in data:
                clean["message_xp_max"] = max(1, min(int(data["message_xp_max"]), 1000))
            if "message_cooldown_sec" in data:
                clean["message_cooldown_sec"] = max(5, min(int(data["message_cooldown_sec"]), 600))
            if "voice_xp_per_min" in data:
                clean["voice_xp_per_min"] = max(0.1, min(float(data["voice_xp_per_min"]), 100.0))
            if "announce_levelup" in data:
                clean["announce_levelup"] = bool(data["announce_levelup"])
            update_level_config(guild_id, **clean)
            store.update_leveling(actor, guild_id, clean)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/leveling/reward")
    async def update_leveling_reward_api(guild_id: int, level: int, request: Request, role_id: int = 0, coins_reward: int = 0):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        set_level_reward(guild_id, int(level), role_id=int(role_id) if int(role_id) > 0 else None, coins_reward=max(0, int(coins_reward)))
        store.update_leveling(actor, guild_id, {"reward_level": int(level), "role_id": int(role_id), "coins_reward": int(coins_reward)})
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/moderation")
    async def update_moderation_api(guild_id: int, payload: ModerationUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        data = payload.model_dump(exclude_none=True)
        if "modlog_channel_id" in data:
            data["modlog_channel_id"] = max(0, int(data["modlog_channel_id"]))
        if "warn_escalation" in data and isinstance(data["warn_escalation"], dict):
            safe = {}
            for k, v in data["warn_escalation"].items():
                try:
                    wk = str(max(1, int(k)))
                except (TypeError, ValueError):
                    continue
                vv = str(v).strip().lower()
                if vv.startswith("timeout:") or vv in {"kick", "ban"}:
                    safe[wk] = vv
            data["warn_escalation"] = safe
        store.update_moderation(actor, guild_id, data)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/automation")
    async def update_automation_api(guild_id: int, payload: AutomationUpdate, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        data = payload.model_dump(exclude_none=True)
        for k in ("welcome_channel_id", "leave_channel_id", "autorole_id"):
            if k in data:
                data[k] = max(0, int(data[k]))
        store.update_automation(actor, guild_id, data)
        return JSONResponse({"ok": True})

    @app.post("/api/guild/{guild_id}/preset")
    async def apply_preset_api(guild_id: int, preset_name: str, request: Request):
        _require_auth(request)
        _validate_csrf(request)
        _ensure_guild_access(request, guild_id)
        actor = _actor_id_from_session(request)
        store.apply_preset(actor, guild_id, preset_name)
        return JSONResponse({"ok": True})

    @app.get("/api/guild/{guild_id}/snapshot")
    async def guild_snapshot(guild_id: int, request: Request):
        _require_auth(request)
        _ensure_guild_access(request, guild_id)
        lv = get_level_config(guild_id)
        level_cfg = {
            "enabled": bool(lv[1]),
            "message_xp_min": int(lv[2]),
            "message_xp_max": int(lv[3]),
            "message_cooldown_sec": int(lv[4]),
            "voice_xp_per_min": float(lv[5]),
            "announce_levelup": bool(lv[6]),
            "rewards": [{"level": int(l), "role_id": int(r) if r else 0, "coins_reward": int(c)} for l, r, c in get_level_rewards(guild_id)],
        }
        return JSONResponse(
            {
                "slash": store.get_server_slash(guild_id).get("slash_cmds", {}),
                "general": store.get_server_slash(guild_id),
                "economy": store.get_econ(),
                "antilink": store.get_antilink(guild_id),
                "antinuke": store.get_antinuke(guild_id),
                "antp": store.get_antp(guild_id),
                "leveling": level_cfg,
                "moderation": store.get_moderation(guild_id),
                "automation": store.get_automation(guild_id),
            }
        )

    @app.get("/api/guild/{guild_id}/audit")
    async def guild_audit(guild_id: int, request: Request):
        _require_auth(request)
        _ensure_guild_access(request, guild_id)
        return JSONResponse({"entries": store.get_audit_entries(guild_id, limit=60)})

    @app.get("/api/guild/{guild_id}/commands")
    async def guild_commands(guild_id: int, request: Request):
        _require_auth(request)
        _ensure_guild_access(request, guild_id)
        names = []
        try:
            guild_ref = discord.Object(id=int(guild_id))
            slash_commands = bot.tree.get_commands(guild=guild_ref) or bot.tree.get_commands() or []
            names = sorted({c.name for c in slash_commands if getattr(c, "name", None)})
        except Exception:
            flat = []
            for _cat, cmds in COMMAND_CATEGORIES.items():
                flat.extend(cmds)
            names = sorted(set(flat))
        return JSONResponse(
            {
                "always_slash": sorted(ALWAYS_SLASH),
                "categories": COMMAND_CATEGORIES,
                "all_slash_commands": names,
            }
        )

    @app.get("/api/me")
    async def me(request: Request):
        _require_auth(request)
        if _admin_session_valid(request):
            user_payload = {
                "username": request.session.get("admin_user", ""),
                "role": request.session.get("admin_role", ""),
            }
        else:
            user_payload = request.session.get("user", {})
        return JSONResponse(
            {
                "user": user_payload,
                "guilds": request.session.get("guilds", []),
            }
        )

    return app
