"""Shared utilities — timezone, formatting, helpers used across all modules."""
import json
import os
import pytz
from datetime import datetime

# ============================================================
# TIMEZONE
# ============================================================
_TZ = None

def get_tz():
    global _TZ
    if _TZ is None:
        tz_file = 'data/timezone_config.json'
        tz_name = 'America/Sao_Paulo'
        if os.path.exists(tz_file):
            try:
                with open(tz_file, 'r') as f:
                    tz_name = json.load(f).get('timezone', 'America/Sao_Paulo')
            except Exception:
                pass
        _TZ = pytz.timezone(tz_name)
    return _TZ

def now_brazil():
    return datetime.now(get_tz())

def ensure_aware(dt):
    """Convert naive datetime to Brazil-aware."""
    if dt.tzinfo is None:
        return get_tz().localize(dt)
    return dt

# ============================================================
# FORMATTING
# ============================================================
def fmt_time(seconds):
    """Format seconds into human-readable time string."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def fmt_time_short(seconds):
    """Compact format: 1h23m, 45m30s, or 12s."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h{m:02d}m"
    if m > 0:
        return f"{m}m{s:02d}s"
    return f"{s}s"

def fmt_time_hms(seconds):
    """Format as HH:MM:SS."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def fmt_number(n):
    """Format large numbers: 1.2k, 1.5M, etc."""
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)

# ============================================================
# RANK HELPERS
# ============================================================
def get_member_name(bot, uid, guild):
    """Get display name for a user ID, max 22 chars."""
    m = guild.get_member(uid) if guild else None
    if m:
        return m.display_name[:22]
    u = bot.get_user(uid) if bot else None
    if u:
        return u.display_name[:22]
    return f"User {uid}"

def rank_badge(pos):
    """Return emoji/medal for rank position."""
    if pos == 1:
        return "\U0001F947"  # 🥇
    if pos == 2:
        return "\U0001F948"  # 🥈
    if pos == 3:
        return "\U0001F949"  # 🥉
    return f"#{pos}"

def get_rank_color(pos):
    """Return color tuple for rank position."""
    if pos == 1:
        return (255, 215, 0)  # Gold
    if pos == 2:
        return (192, 192, 192)  # Silver
    if pos == 3:
        return (205, 127, 50)  # Bronze
    return (148, 163, 184)  # Default slate
