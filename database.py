"""Database layer — voice stats, chat stats, economy.
All SQL uses parameterized queries (no f-string injection).
Connections reused where possible."""
import sqlite3
import threading
from datetime import datetime, timedelta
import pytz
import json
import os
import shutil

from utils import get_tz, now_brazil, ensure_aware

VOICE_DB = 'voice_stats.db'
BOT_DB = 'bot_systems.db'
LEGACY_BOT_PATH = r"C:\Users\anton\Desktop\BOTS\bot-primal"


def _current_db_has_data(path: str, table_name: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        if not row:
            return False
        count = cur.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return bool(count and int(count[0]) > 0)
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _copy_if_missing_or_empty(src: str, dst: str, probe_table: str):
    if not os.path.exists(src):
        return False
    if _current_db_has_data(dst, probe_table):
        return False
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_json_if_missing(src: str, dst: str):
    if not os.path.exists(src) or os.path.exists(dst):
        return False
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_file_if_missing(src: str, dst: str):
    if not os.path.exists(src) or os.path.exists(dst):
        return False
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_tree_missing(src_dir: str, dst_dir: str):
    if not os.path.isdir(src_dir):
        return 0
    copied = 0
    for root, _, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        target_root = dst_dir if rel == "." else os.path.join(dst_dir, rel)
        for name in files:
            src = os.path.join(root, name)
            dst = os.path.join(target_root, name)
            if _copy_file_if_missing(src, dst):
                copied += 1
    return copied


def _merge_sqlite_table_by_pk(src_db: str, dst_db: str, table_name: str, pk_name: str = "id"):
    """
    Merge simples: copia linhas de `src` para `dst` quando a PK nao existe em `dst`.
    Nao sobrescreve dados ja existentes.
    """
    if not os.path.exists(src_db) or not os.path.exists(dst_db):
        return 0
    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(src_db)
        dst_conn = sqlite3.connect(dst_db)
        src_cur = src_conn.cursor()
        dst_cur = dst_conn.cursor()

        src_cols = [r[1] for r in src_cur.execute(f"PRAGMA table_info({table_name})").fetchall()]
        dst_cols = [r[1] for r in dst_cur.execute(f"PRAGMA table_info({table_name})").fetchall()]
        if not src_cols or not dst_cols or pk_name not in src_cols or pk_name not in dst_cols:
            return 0

        common = [c for c in src_cols if c in dst_cols]
        if not common or pk_name not in common:
            return 0

        col_sql = ", ".join(common)
        placeholders = ", ".join(["?"] * len(common))
        select_sql = f"SELECT {col_sql} FROM {table_name}"
        insert_sql = f"INSERT INTO {table_name} ({col_sql}) VALUES ({placeholders})"

        inserted = 0
        for row in src_cur.execute(select_sql).fetchall():
            row_map = dict(zip(common, row))
            pk_value = row_map.get(pk_name)
            exists = dst_cur.execute(
                f"SELECT 1 FROM {table_name} WHERE {pk_name}=? LIMIT 1",
                (pk_value,),
            ).fetchone()
            if exists:
                continue
            dst_cur.execute(insert_sql, row)
            inserted += 1

        if inserted:
            dst_conn.commit()
        return inserted
    except Exception:
        return 0
    finally:
        if src_conn:
            try:
                src_conn.close()
            except Exception:
                pass
        if dst_conn:
            try:
                dst_conn.close()
            except Exception:
                pass


def _export_legacy_marriages_json(src_db: str, output_json: str):
    """Exporta casamentos do banco legado para JSON (debug/backup legivel)."""
    if not os.path.exists(src_db):
        return 0
    conn = None
    try:
        conn = sqlite3.connect(src_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM marriages ORDER BY id ASC").fetchall()
        data = [dict(r) for r in rows]
        os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return len(data)
    except Exception:
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _merge_legacy_marriages_by_fingerprint(src_db: str, dst_db: str):
    """
    Merge de casamentos ignorando `id` legado.
    Evita conflito de PK quando dois bancos tem IDs iguais para registros diferentes.
    """
    if not os.path.exists(src_db) or not os.path.exists(dst_db):
        return 0
    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(src_db)
        dst_conn = sqlite3.connect(dst_db)
        src_conn.row_factory = sqlite3.Row
        dst_conn.row_factory = sqlite3.Row
        src_cur = src_conn.cursor()
        dst_cur = dst_conn.cursor()

        src_cols = [r[1] for r in src_cur.execute("PRAGMA table_info(marriages)").fetchall()]
        dst_cols = [r[1] for r in dst_cur.execute("PRAGMA table_info(marriages)").fetchall()]
        if not src_cols or not dst_cols:
            return 0

        # Monta assinatura por campos estaveis para detectar duplicado sem depender do ID.
        stable_keys = [k for k in ("guild_id", "spouse_a", "spouse_b", "created_at", "status") if k in dst_cols]
        if len(stable_keys) < 3:
            return 0

        existing = set()
        for r in dst_cur.execute(
            "SELECT guild_id, spouse_a, spouse_b, created_at, status FROM marriages"
        ).fetchall():
            existing.add((r["guild_id"], r["spouse_a"], r["spouse_b"], r["created_at"], r["status"]))

        # Insere sem `id` para deixar o SQLite gerar PK nova.
        insert_cols = [c for c in src_cols if c in dst_cols and c != "id"]
        if not insert_cols:
            return 0
        col_sql = ", ".join(insert_cols)
        placeholders = ", ".join(["?"] * len(insert_cols))
        insert_sql = f"INSERT INTO marriages ({col_sql}) VALUES ({placeholders})"

        inserted = 0
        for r in src_cur.execute("SELECT * FROM marriages ORDER BY id ASC").fetchall():
            fp = (
                r["guild_id"],
                r["spouse_a"],
                r["spouse_b"],
                r["created_at"],
                r["status"],
            )
            if fp in existing:
                continue
            values = [r[c] for c in insert_cols]
            dst_cur.execute(insert_sql, values)
            existing.add(fp)
            inserted += 1

        if inserted:
            dst_conn.commit()
        return inserted
    except Exception:
        return 0
    finally:
        if src_conn:
            try:
                src_conn.close()
            except Exception:
                pass
        if dst_conn:
            try:
                dst_conn.close()
            except Exception:
                pass


def _bootstrap_legacy_saves():
    """
    Importa saves do bot antigo se este projeto ainda nao tiver dados.
    Permite subir o codigo no GitHub sem perder os dados locais de producao.
    """
    base = os.environ.get("BOT_LEGACY_SAVE_PATH", LEGACY_BOT_PATH).strip()
    if not base or not os.path.isdir(base):
        return
    try:
        # 1) Bancos principais: copia se nao existir ou estiver vazio.
        _copy_if_missing_or_empty(
            os.path.join(base, VOICE_DB),
            VOICE_DB,
            "voice_stats",
        )
        _copy_if_missing_or_empty(
            os.path.join(base, BOT_DB),
            BOT_DB,
            "marriages",
        )

        # 2) Sidecars do SQLite (WAL/SHM) e outros bancos locais, se faltarem.
        for name in os.listdir(base):
            if not (name.endswith(".db") or name.endswith(".db-wal") or name.endswith(".db-shm")):
                continue
            _copy_file_if_missing(
                os.path.join(base, name),
                name,
            )

        # 3) Todos os saves em JSON/assets de dados (sem sobrescrever existentes).
        _copy_tree_missing(os.path.join(base, "dados"), "dados")
        _copy_tree_missing(os.path.join(base, "data"), "data")

        # 4) Merge de casamentos por ID (caso o db atual ja exista com outros dados).
        _merge_sqlite_table_by_pk(
            os.path.join(base, BOT_DB),
            BOT_DB,
            "marriages",
            "id",
        )
        # 5) Export legivel em JSON + merge robusto sem depender do ID legado.
        _export_legacy_marriages_json(
            os.path.join(base, BOT_DB),
            os.path.join("data", "marriage", "legacy_marriages.json"),
        )
        _merge_legacy_marriages_by_fingerprint(
            os.path.join(base, BOT_DB),
            BOT_DB,
        )
    except Exception:
        # Nunca derruba o bot por falha na copia.
        pass


_bootstrap_legacy_saves()

# ============================================================
# CONNECTION MANAGEMENT
# ============================================================
class _DB:
    """Thread-local connection wrapper per database."""
    def __init__(self, path):
        self.path = path
        self._local = threading.local()

    def _get(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def execute(self, sql, params=None):
        c = self._get().cursor()
        c.execute(sql, params or ())
        self._get().commit()
        return c

_vdb = _DB(VOICE_DB)
_bdb = _DB(BOT_DB)

def _close_all():
    _vdb.close()
    _bdb.close()

# ============================================================
# TABLE CREATION
# ============================================================
def init():
    _vdb.execute('''CREATE TABLE IF NOT EXISTS voice_stats (
        guild_id INTEGER, user_id INTEGER,
        total_seconds INTEGER DEFAULT 0, session_count INTEGER DEFAULT 0,
        longest_session INTEGER DEFAULT 0, last_join TIMESTAMP,
        PRIMARY KEY (guild_id, user_id))''')
    _vdb.execute('''CREATE TABLE IF NOT EXISTS voice_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER, user_id INTEGER,
        join_time TIMESTAMP, leave_time TIMESTAMP, duration INTEGER)''')

    _bdb.execute('''CREATE TABLE IF NOT EXISTS chat_stats (
        guild_id INTEGER, user_id INTEGER,
        total_messages INTEGER DEFAULT 0, today_messages INTEGER DEFAULT 0,
        week_messages INTEGER DEFAULT 0, month_messages INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id))''')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS economy (
        guild_id INTEGER, user_id INTEGER,
        coins INTEGER DEFAULT 0, daily_voice_coins INTEGER DEFAULT 0,
        daily_coins_claimed TIMESTAMP, last_tot_earned TIMESTAMP,
        PRIMARY KEY (guild_id, user_id))''')
    econ_cols = [r[1] for r in _bdb.execute("PRAGMA table_info(economy)").fetchall()]
    if 'daily_streak' not in econ_cols:
        _bdb.execute('ALTER TABLE economy ADD COLUMN daily_streak INTEGER DEFAULT 0')

    # New: shop_items table for /loja
    _bdb.execute('''CREATE TABLE IF NOT EXISTS shop_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER, name TEXT, description TEXT,
        price INTEGER DEFAULT 0, role_id INTEGER, emoji TEXT)''')

    # New: user_inventory
    _bdb.execute('''CREATE TABLE IF NOT EXISTS user_inventory (
        guild_id INTEGER, user_id INTEGER, item_id INTEGER,
        quantity INTEGER DEFAULT 1, acquired_at TIMESTAMP,
        PRIMARY KEY (guild_id, user_id, item_id))''')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS level_stats (
        guild_id INTEGER, user_id INTEGER,
        xp INTEGER DEFAULT 0, level INTEGER DEFAULT 0,
        last_xp_at TIMESTAMP,
        PRIMARY KEY (guild_id, user_id))''')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS level_rewards (
        guild_id INTEGER, level INTEGER, role_id INTEGER,
        coins_reward INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, level))''')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS level_config (
        guild_id INTEGER PRIMARY KEY,
        enabled INTEGER DEFAULT 1,
        message_xp_min INTEGER DEFAULT 8,
        message_xp_max INTEGER DEFAULT 16,
        message_cooldown_sec INTEGER DEFAULT 45,
        voice_xp_per_min REAL DEFAULT 1.0,
        announce_levelup INTEGER DEFAULT 1
    )''')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS mod_cases (
        case_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        moderator_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        reason TEXT,
        created_at TIMESTAMP NOT NULL,
        expires_at TIMESTAMP
    )''')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS market_listings (
        listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        seller_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        price INTEGER NOT NULL,
        created_at TIMESTAMP NOT NULL
    )''')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS marriages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        proposer_id INTEGER NOT NULL,
        spouse_a INTEGER NOT NULL,
        spouse_b INTEGER NOT NULL,
        witnesses_json TEXT DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP NOT NULL,
        accepted_at TIMESTAMP,
        ended_at TIMESTAMP,
        ended_by INTEGER,
        end_reason TEXT,
        proposal_dm_channel_id INTEGER,
        proposal_dm_message_id INTEGER
    )''')
    _bdb.execute('CREATE INDEX IF NOT EXISTS idx_marriages_guild_status ON marriages(guild_id, status)')
    _bdb.execute('CREATE INDEX IF NOT EXISTS idx_marriages_spouse_a ON marriages(spouse_a)')
    _bdb.execute('CREATE INDEX IF NOT EXISTS idx_marriages_spouse_b ON marriages(spouse_b)')
    cols = [r[1] for r in _bdb.execute("PRAGMA table_info(marriages)").fetchall()]
    if 'celebrant_id' not in cols:
        _bdb.execute('ALTER TABLE marriages ADD COLUMN celebrant_id INTEGER')
    if 'kiss_count' not in cols:
        _bdb.execute('ALTER TABLE marriages ADD COLUMN kiss_count INTEGER DEFAULT 0')
    if 'hug_count' not in cols:
        _bdb.execute('ALTER TABLE marriages ADD COLUMN hug_count INTEGER DEFAULT 0')
    if 'affection_click_count' not in cols:
        _bdb.execute('ALTER TABLE marriages ADD COLUMN affection_click_count INTEGER DEFAULT 0')
    if 'retribute_click_count' not in cols:
        _bdb.execute('ALTER TABLE marriages ADD COLUMN retribute_click_count INTEGER DEFAULT 0')
    if 'reject_click_count' not in cols:
        _bdb.execute('ALTER TABLE marriages ADD COLUMN reject_click_count INTEGER DEFAULT 0')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS coleira_authorized (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        granted_by INTEGER NOT NULL,
        granted_at TIMESTAMP NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    )''')
    _bdb.execute('''CREATE TABLE IF NOT EXISTS coleiras (
        guild_id INTEGER NOT NULL,
        owner_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        created_at TIMESTAMP NOT NULL,
        PRIMARY KEY (guild_id, target_id)
    )''')
    _bdb.execute('CREATE INDEX IF NOT EXISTS idx_coleiras_owner ON coleiras(guild_id, owner_id)')

def cleanup_old():
    cutoff = (now_brazil() - timedelta(days=30)).isoformat()
    _vdb.execute('DELETE FROM voice_sessions WHERE leave_time < ?', (cutoff,))
    _close_all()

def vacuum():
    try:
        _vdb.execute("VACUUM")
    except Exception:
        pass
    try:
        _bdb.execute("VACUUM")
    except Exception:
        pass

# ============================================================
# VOICE
# ============================================================
def add_voice(guild_id, user_id, dur, jt):
    longest = dur
    row = _vdb.execute('SELECT longest_session FROM voice_stats WHERE guild_id=? AND user_id=?',
                       (guild_id, user_id)).fetchone()
    if row:
        longest = max(row[0], dur)
    _vdb.execute('''INSERT INTO voice_stats (guild_id,user_id,total_seconds,session_count,longest_session,last_join)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(guild_id,user_id) DO UPDATE SET
            total_seconds=total_seconds+excluded.total_seconds,
            session_count=session_count+1,
            longest_session=excluded.longest_session,
            last_join=excluded.last_join''',
        (guild_id, user_id, dur, 1, longest, jt))
    _vdb.execute('INSERT INTO voice_sessions (guild_id,user_id,join_time,leave_time,duration) VALUES (?,?,?,?,?)',
                 (guild_id, user_id, jt, now_brazil(), dur))

def get_voice(guild_id, user_id):
    return _vdb.execute('SELECT * FROM voice_stats WHERE guild_id=? AND user_id=?',
                        (guild_id, user_id)).fetchone()

def get_all_voice(guild_id, limit=10000):
    return _vdb.execute(
        'SELECT user_id,total_seconds FROM voice_stats WHERE guild_id=? ORDER BY total_seconds DESC LIMIT ?',
        (guild_id, limit)).fetchall()


def get_voice_totals(guild_id):
    """Voice leaderboard base from aggregate table."""
    return _vdb.execute(
        'SELECT user_id,total_seconds FROM voice_stats WHERE guild_id=? ORDER BY total_seconds DESC',
        (guild_id,)
    ).fetchall()


def get_voice_since(guild_id, since_iso):
    """Voice leaderboard by summed sessions since a given ISO timestamp."""
    return _vdb.execute(
        'SELECT user_id,SUM(duration) FROM voice_sessions WHERE guild_id=? AND leave_time>=? GROUP BY user_id ORDER BY SUM(duration) DESC',
        (guild_id, since_iso)
    ).fetchall()


def get_chat_total_messages(guild_id):
    return _bdb.execute(
        'SELECT user_id,total_messages FROM chat_stats WHERE guild_id=? AND total_messages>0 ORDER BY total_messages DESC',
        (guild_id,)
    ).fetchall()

def voice_period(guild_id, user_id, since):
    r = _vdb.execute(
        'SELECT SUM(duration) FROM voice_sessions WHERE guild_id=? AND user_id=? AND leave_time>=?',
        (guild_id, user_id, since.isoformat())).fetchone()
    return r[0] if r and r[0] else 0

def all_voice_period(guild_id, since):
    return _vdb.execute(
        'SELECT user_id,SUM(duration) as t FROM voice_sessions WHERE guild_id=? AND leave_time>=? GROUP BY user_id ORDER BY t DESC',
        (guild_id, since.isoformat())).fetchall()

def add_voice_seconds(guild_id, user_id, secs):
    _vdb.execute('INSERT OR IGNORE INTO voice_stats (guild_id,user_id) VALUES (?,?)', (guild_id, user_id))
    _vdb.execute('UPDATE voice_stats SET total_seconds=total_seconds+? WHERE guild_id=? AND user_id=?',
                 (secs, guild_id, user_id))

def remove_voice_seconds(guild_id, user_id, secs):
    _vdb.execute('UPDATE voice_stats SET total_seconds=MAX(0,total_seconds-?) WHERE guild_id=? AND user_id=?',
                 (secs, guild_id, user_id))

# ============================================================
# CHAT
# ============================================================
def bump_msg(guild_id, user_id):
    _bdb.execute('''INSERT INTO chat_stats (guild_id,user_id,total_messages,today_messages,week_messages,month_messages)
        VALUES (?,?,1,1,1,1) ON CONFLICT(guild_id,user_id) DO UPDATE SET
            total_messages=total_messages+1, today_messages=today_messages+1,
            week_messages=week_messages+1, month_messages=month_messages+1''',
        (guild_id, user_id))

def get_chat(guild_id, user_id):
    return _bdb.execute('SELECT * FROM chat_stats WHERE guild_id=? AND user_id=?',
                        (guild_id, user_id)).fetchone()

def all_chat(guild_id, field='total_messages'):
    # Whitelist allowed fields — no injection
    allowed = {'total_messages', 'today_messages', 'week_messages', 'month_messages'}
    if field not in allowed:
        field = 'total_messages'
    return _bdb.execute(
        f'SELECT user_id,{field} FROM chat_stats WHERE guild_id=? AND {field}>0 ORDER BY {field} DESC',
        (guild_id,)).fetchall()

def reset_chat(field):
    allowed = {'today_messages', 'week_messages', 'month_messages'}
    if field in allowed:
        _bdb.execute(f'UPDATE chat_stats SET {field}=0')

# ============================================================
# ECONOMY
# ============================================================
def ensure_econ(guild_id, user_id):
    _bdb.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, user_id))

def get_econ(guild_id, user_id):
    return _bdb.execute('SELECT * FROM economy WHERE guild_id=? AND user_id=?',
                        (guild_id, user_id)).fetchone()

def add_coins(guild_id, user_id, amt):
    _bdb.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, user_id))
    _bdb.execute('UPDATE economy SET coins=coins+? WHERE guild_id=? AND user_id=?',
                 (amt, guild_id, user_id))

def remove_coins(guild_id, user_id, amt):
    _bdb.execute('UPDATE economy SET coins=MAX(0,coins-?) WHERE guild_id=? AND user_id=?',
                 (amt, guild_id, user_id))

def set_coins(guild_id, user_id, amt):
    """Set exact coin amount."""
    _bdb.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, user_id))
    _bdb.execute('UPDATE economy SET coins=? WHERE guild_id=? AND user_id=?',
                 (amt, guild_id, user_id))

def set_daily_coins(guild_id, user_id, amt, ts):
    _bdb.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, user_id))
    _bdb.execute('UPDATE economy SET daily_voice_coins=?,last_tot_earned=? WHERE guild_id=? AND user_id=?',
                 (amt, ts, guild_id, user_id))


def claim_daily(guild_id, user_id, amount):
    today = now_brazil().strftime('%Y-%m-%d')
    yesterday = (now_brazil() - timedelta(days=1)).strftime('%Y-%m-%d')
    conn = _bdb._get()
    c = conn.cursor()
    try:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, user_id))
        row = c.execute('SELECT daily_coins_claimed,daily_streak FROM economy WHERE guild_id=? AND user_id=?',
                        (guild_id, user_id)).fetchone()
        if row and row[0] == today:
            conn.rollback()
            return False, row[1] if len(row) > 1 and row[1] is not None else 0
        prev_claim = row[0] if row else None
        prev_streak = int(row[1]) if row and len(row) > 1 and row[1] is not None else 0
        streak = (prev_streak + 1) if prev_claim == yesterday else 1
        c.execute('UPDATE economy SET coins=coins+?, daily_coins_claimed=?, daily_streak=? WHERE guild_id=? AND user_id=?',
                  (amount, today, streak, guild_id, user_id))
        conn.commit()
        return True, streak
    except Exception:
        conn.rollback()
        raise


def transfer_coins(guild_id, from_user_id, to_user_id, amt):
    """Atomic transfer between two users. Returns True on success."""
    if amt <= 0 or from_user_id == to_user_id:
        return False
    conn = _bdb._get()
    c = conn.cursor()
    try:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, from_user_id))
        c.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, to_user_id))
        row = c.execute('SELECT coins FROM economy WHERE guild_id=? AND user_id=?',
                        (guild_id, from_user_id)).fetchone()
        balance = row[0] if row else 0
        if balance < amt:
            conn.rollback()
            return False
        c.execute('UPDATE economy SET coins=coins-? WHERE guild_id=? AND user_id=?',
                  (amt, guild_id, from_user_id))
        c.execute('UPDATE economy SET coins=coins+? WHERE guild_id=? AND user_id=?',
                  (amt, guild_id, to_user_id))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise

def all_econ(guild_id):
    return _bdb.execute('SELECT user_id,coins FROM economy WHERE guild_id=? ORDER BY coins DESC',
                        (guild_id,)).fetchall()

# ============================================================
# SHOP
# ============================================================
def add_shop_item(guild_id, name, description, price, role_id=None, emoji=None):
    c = _bdb.execute(
        'INSERT INTO shop_items (guild_id,name,description,price,role_id,emoji) VALUES (?,?,?,?,?,?)',
        (guild_id, name, description, price, role_id, emoji))
    return c.lastrowid

def get_shop_items(guild_id):
    return _bdb.execute('SELECT * FROM shop_items WHERE guild_id=? ORDER BY price ASC', (guild_id,)).fetchall()

def delete_shop_item(guild_id, item_id):
    _bdb.execute('DELETE FROM shop_items WHERE guild_id=? AND id=?', (guild_id, item_id))

def buy_item(guild_id, user_id, item_id):
    item = _bdb.execute('SELECT * FROM shop_items WHERE guild_id=? AND id=?', (guild_id, item_id)).fetchone()
    if not item:
        return None, "Item nao encontrado."
    price = item[4]  # price column
    econ = _bdb.execute('SELECT coins FROM economy WHERE guild_id=? AND user_id=?', (guild_id, user_id)).fetchone()
    coins = econ[0] if econ else 0
    if coins < price:
        return None, f"Saldo insuficiente. Voce tem {coins} ToT, precisa de {price}."
    _bdb.execute('UPDATE economy SET coins=coins-? WHERE guild_id=? AND user_id=?', (price, guild_id, user_id))
    _bdb.execute(
        'INSERT INTO user_inventory (guild_id,user_id,item_id,quantity,acquired_at) VALUES (?,?,?,?,?) '
        'ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+1',
        (guild_id, user_id, item_id, 1, now_brazil().isoformat()))
    return item, None

def get_inventory(guild_id, user_id):
    return _bdb.execute(
        'SELECT ui.*, si.name, si.description, si.price, si.emoji, si.role_id FROM user_inventory ui '
        'JOIN shop_items si ON ui.item_id=si.id WHERE ui.guild_id=? AND ui.user_id=?',
        (guild_id, user_id)).fetchall()


def adjust_inventory(guild_id, user_id, item_id, delta_qty):
    """Adjust inventory quantity atomically. Returns False when insufficient."""
    if delta_qty == 0:
        return True
    conn = _bdb._get()
    c = conn.cursor()
    try:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT quantity FROM user_inventory WHERE guild_id=? AND user_id=? AND item_id=?',
                        (guild_id, user_id, item_id)).fetchone()
        cur = row[0] if row else 0
        new_qty = cur + int(delta_qty)
        if new_qty < 0:
            conn.rollback()
            return False
        if new_qty == 0:
            c.execute('DELETE FROM user_inventory WHERE guild_id=? AND user_id=? AND item_id=?',
                      (guild_id, user_id, item_id))
        elif row:
            c.execute('UPDATE user_inventory SET quantity=? WHERE guild_id=? AND user_id=? AND item_id=?',
                      (new_qty, guild_id, user_id, item_id))
        else:
            c.execute('INSERT INTO user_inventory (guild_id,user_id,item_id,quantity,acquired_at) VALUES (?,?,?,?,?)',
                      (guild_id, user_id, item_id, new_qty, now_brazil().isoformat()))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def create_market_listing(guild_id, seller_id, item_id, qty, price):
    c = _bdb.execute(
        'INSERT INTO market_listings (guild_id,seller_id,item_id,quantity,price,created_at) VALUES (?,?,?,?,?,?)',
        (guild_id, seller_id, item_id, qty, price, now_brazil().isoformat()))
    return c.lastrowid


def get_market_listings(guild_id, limit=25):
    return _bdb.execute(
        '''SELECT ml.listing_id, ml.seller_id, ml.item_id, ml.quantity, ml.price, ml.created_at,
                  si.name, si.emoji
           FROM market_listings ml
           LEFT JOIN shop_items si ON si.id=ml.item_id AND si.guild_id=ml.guild_id
           WHERE ml.guild_id=?
           ORDER BY ml.created_at DESC LIMIT ?''',
        (guild_id, limit)).fetchall()


def buy_market_listing(guild_id, buyer_id, listing_id):
    """Atomic listing purchase. Returns tuple (ok, msg)."""
    conn = _bdb._get()
    c = conn.cursor()
    try:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute(
            'SELECT seller_id,item_id,quantity,price FROM market_listings WHERE guild_id=? AND listing_id=?',
            (guild_id, listing_id)
        ).fetchone()
        if not row:
            conn.rollback()
            return False, "Anuncio nao encontrado."
        seller_id, item_id, qty, price = row
        if int(buyer_id) == int(seller_id):
            conn.rollback()
            return False, "Voce nao pode comprar seu proprio anuncio."
        c.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, buyer_id))
        c.execute('INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)', (guild_id, seller_id))
        buyer_row = c.execute('SELECT coins FROM economy WHERE guild_id=? AND user_id=?',
                              (guild_id, buyer_id)).fetchone()
        buyer_balance = buyer_row[0] if buyer_row else 0
        if buyer_balance < price:
            conn.rollback()
            return False, "Saldo insuficiente."
        c.execute('UPDATE economy SET coins=coins-? WHERE guild_id=? AND user_id=?',
                  (price, guild_id, buyer_id))
        c.execute('UPDATE economy SET coins=coins+? WHERE guild_id=? AND user_id=?',
                  (price, guild_id, seller_id))
        inv_row = c.execute('SELECT quantity FROM user_inventory WHERE guild_id=? AND user_id=? AND item_id=?',
                            (guild_id, buyer_id, item_id)).fetchone()
        if inv_row:
            c.execute('UPDATE user_inventory SET quantity=quantity+? WHERE guild_id=? AND user_id=? AND item_id=?',
                      (qty, guild_id, buyer_id, item_id))
        else:
            c.execute('INSERT INTO user_inventory (guild_id,user_id,item_id,quantity,acquired_at) VALUES (?,?,?,?,?)',
                      (guild_id, buyer_id, item_id, qty, now_brazil().isoformat()))
        c.execute('DELETE FROM market_listings WHERE guild_id=? AND listing_id=?', (guild_id, listing_id))
        conn.commit()
        return True, "Compra concluida."
    except Exception:
        conn.rollback()
        raise


# ============================================================
# LEVELING
# ============================================================
def get_level_config(guild_id):
    row = _bdb.execute('SELECT * FROM level_config WHERE guild_id=?', (guild_id,)).fetchone()
    if not row:
        _bdb.execute('INSERT OR IGNORE INTO level_config (guild_id) VALUES (?)', (guild_id,))
        row = _bdb.execute('SELECT * FROM level_config WHERE guild_id=?', (guild_id,)).fetchone()
    return row


def update_level_config(guild_id, **kwargs):
    current = get_level_config(guild_id)
    fields = ["enabled", "message_xp_min", "message_xp_max", "message_cooldown_sec", "voice_xp_per_min", "announce_levelup"]
    data = dict(zip(fields, current[1:]))
    data.update({k: v for k, v in kwargs.items() if k in data and v is not None})
    _bdb.execute(
        '''UPDATE level_config
           SET enabled=?, message_xp_min=?, message_xp_max=?, message_cooldown_sec=?, voice_xp_per_min=?, announce_levelup=?
           WHERE guild_id=?''',
        (int(bool(data["enabled"])), int(data["message_xp_min"]), int(data["message_xp_max"]),
         int(data["message_cooldown_sec"]), float(data["voice_xp_per_min"]),
         int(bool(data["announce_levelup"])), guild_id)
    )


def get_level_stats(guild_id, user_id):
    row = _bdb.execute('SELECT guild_id,user_id,xp,level,last_xp_at FROM level_stats WHERE guild_id=? AND user_id=?',
                       (guild_id, user_id)).fetchone()
    if not row:
        _bdb.execute('INSERT OR IGNORE INTO level_stats (guild_id,user_id,xp,level) VALUES (?,?,0,0)',
                     (guild_id, user_id))
        row = _bdb.execute('SELECT guild_id,user_id,xp,level,last_xp_at FROM level_stats WHERE guild_id=? AND user_id=?',
                           (guild_id, user_id)).fetchone()
    return row


def set_level_stats(guild_id, user_id, xp, level, last_xp_at=None):
    _bdb.execute('INSERT OR IGNORE INTO level_stats (guild_id,user_id) VALUES (?,?)', (guild_id, user_id))
    _bdb.execute('UPDATE level_stats SET xp=?, level=?, last_xp_at=? WHERE guild_id=? AND user_id=?',
                 (int(xp), int(level), last_xp_at, guild_id, user_id))


def add_xp(guild_id, user_id, amount, new_level):
    _bdb.execute('INSERT OR IGNORE INTO level_stats (guild_id,user_id) VALUES (?,?)', (guild_id, user_id))
    _bdb.execute(
        'UPDATE level_stats SET xp=xp+?, level=?, last_xp_at=? WHERE guild_id=? AND user_id=?',
        (int(amount), int(new_level), now_brazil().isoformat(), guild_id, user_id)
    )


def top_levels(guild_id, limit=20):
    return _bdb.execute(
        'SELECT user_id,xp,level FROM level_stats WHERE guild_id=? ORDER BY level DESC, xp DESC LIMIT ?',
        (guild_id, limit)
    ).fetchall()


def set_level_reward(guild_id, level, role_id=None, coins_reward=0):
    _bdb.execute(
        '''INSERT INTO level_rewards (guild_id,level,role_id,coins_reward)
           VALUES (?,?,?,?)
           ON CONFLICT(guild_id,level) DO UPDATE SET role_id=excluded.role_id, coins_reward=excluded.coins_reward''',
        (guild_id, int(level), role_id, int(coins_reward))
    )


def get_level_rewards(guild_id):
    return _bdb.execute(
        'SELECT level,role_id,coins_reward FROM level_rewards WHERE guild_id=? ORDER BY level ASC',
        (guild_id,)
    ).fetchall()


def get_level_reward(guild_id, level):
    return _bdb.execute(
        'SELECT level,role_id,coins_reward FROM level_rewards WHERE guild_id=? AND level=?',
        (guild_id, int(level))
    ).fetchone()


# ============================================================
# MOD CASES
# ============================================================
def add_mod_case(guild_id, target_id, moderator_id, action, reason=None, expires_at=None):
    c = _bdb.execute(
        '''INSERT INTO mod_cases (guild_id,target_id,moderator_id,action,reason,created_at,expires_at)
           VALUES (?,?,?,?,?,?,?)''',
        (guild_id, target_id, moderator_id, str(action), reason, now_brazil().isoformat(), expires_at)
    )
    return c.lastrowid


def get_mod_cases(guild_id, target_id=None, action=None, limit=50):
    sql = 'SELECT case_id,target_id,moderator_id,action,reason,created_at,expires_at FROM mod_cases WHERE guild_id=?'
    params = [guild_id]
    if target_id is not None:
        sql += ' AND target_id=?'
        params.append(target_id)
    if action:
        sql += ' AND action=?'
        params.append(str(action))
    sql += ' ORDER BY case_id DESC LIMIT ?'
    params.append(limit)
    return _bdb.execute(sql, tuple(params)).fetchall()


def get_warn_count(guild_id, target_id):
    row = _bdb.execute(
        "SELECT COUNT(*) FROM mod_cases WHERE guild_id=? AND target_id=? AND action='warn'",
        (guild_id, target_id)
    ).fetchone()
    return row[0] if row else 0


def remove_warn_case(guild_id, case_id):
    row = _bdb.execute(
        "SELECT case_id FROM mod_cases WHERE guild_id=? AND case_id=? AND action='warn'",
        (guild_id, case_id)
    ).fetchone()
    if not row:
        return False
    _bdb.execute("DELETE FROM mod_cases WHERE guild_id=? AND case_id=?", (guild_id, case_id))
    return True

# ============================================================
# MARRIAGE
# ============================================================
def _to_list_json(values):
    return json.dumps([int(v) for v in values], ensure_ascii=False)

def _parse_list_json(value):
    if not value:
        return []
    try:
        data = json.loads(value)
        if isinstance(data, list):
            return [int(x) for x in data]
    except Exception:
        pass
    return []

def get_active_marriage_by_user(guild_id, user_id):
    # Casamento global: ignora guild_id por regra de negocio.
    return get_active_marriage_by_user_global(user_id)

def get_active_marriage_by_user_global(user_id):
    local = _bdb.execute(
        '''SELECT * FROM marriages
           WHERE status='active' AND (spouse_a=? OR spouse_b=?)
           ORDER BY id DESC LIMIT 1''',
        (user_id, user_id)
    ).fetchone()
    if local:
        return local
    legacy_db = os.path.join(os.environ.get("BOT_LEGACY_SAVE_PATH", LEGACY_BOT_PATH).strip(), BOT_DB)
    if not os.path.exists(legacy_db):
        return None
    conn = None
    try:
        conn = sqlite3.connect(legacy_db)
        row = conn.execute(
            '''SELECT * FROM marriages
               WHERE status='active' AND (spouse_a=? OR spouse_b=?)
               ORDER BY id DESC LIMIT 1''',
            (user_id, user_id)
        ).fetchone()
        return row
    except Exception:
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_pending_marriage_by_partner(guild_id, proposer_id, partner_id):
    # Pedido global: nao depende de guild.
    return get_pending_marriage_by_partner_global(proposer_id, partner_id)

def get_pending_marriage_by_partner_global(proposer_id, partner_id):
    return _bdb.execute(
        '''SELECT * FROM marriages
           WHERE status='pending' AND proposer_id=? AND spouse_a=? AND spouse_b=?
           ORDER BY id DESC LIMIT 1''',
        (proposer_id, proposer_id, partner_id)
    ).fetchone()

def create_marriage_proposal(guild_id, proposer_id, partner_id, witnesses, celebrant_id=None, dm_channel_id=None, dm_message_id=None):
    now = now_brazil().isoformat()
    c = _bdb.execute(
        '''INSERT INTO marriages (
            guild_id, proposer_id, spouse_a, spouse_b, witnesses_json, status, created_at,
            proposal_dm_channel_id, proposal_dm_message_id, celebrant_id
        ) VALUES (?,?,?,?,?,'pending',?,?,?,?)''',
        (guild_id, proposer_id, proposer_id, partner_id, _to_list_json(witnesses), now, dm_channel_id, dm_message_id, celebrant_id)
    )
    return c.lastrowid

def set_marriage_proposal_message(marriage_id, dm_channel_id, dm_message_id):
    _bdb.execute(
        'UPDATE marriages SET proposal_dm_channel_id=?, proposal_dm_message_id=? WHERE id=?',
        (dm_channel_id, dm_message_id, marriage_id)
    )

def accept_marriage(marriage_id):
    _bdb.execute(
        "UPDATE marriages SET status='active', accepted_at=? WHERE id=? AND status='pending'",
        (now_brazil().isoformat(), marriage_id)
    )

def set_marriage_accepted_at(marriage_id, accepted_at_iso):
    _bdb.execute(
        "UPDATE marriages SET accepted_at=? WHERE id=?",
        (accepted_at_iso, marriage_id)
    )


def set_marriage_witness(marriage_id, slot_index, user_id):
    if slot_index < 0:
        return False
    row = get_marriage_by_id(marriage_id)
    info = marriage_row_to_dict(row)
    if not info:
        return False
    witnesses = list(info.get('witnesses', []))
    while len(witnesses) <= slot_index:
        witnesses.append(user_id)
    witnesses[slot_index] = int(user_id)
    _bdb.execute(
        "UPDATE marriages SET witnesses_json=? WHERE id=?",
        (_to_list_json(witnesses), marriage_id)
    )
    return True

def reject_marriage(marriage_id, rejected_by, reason='recusado'):
    _bdb.execute(
        "UPDATE marriages SET status='rejected', ended_at=?, ended_by=?, end_reason=? WHERE id=? AND status='pending'",
        (now_brazil().isoformat(), rejected_by, reason, marriage_id)
    )

def divorce_marriage(guild_id, user_id, reason=None):
    # Divorcio global: ignora guild_id.
    return divorce_marriage_global(user_id, reason)

def divorce_marriage_global(user_id, reason=None):
    marriage = get_active_marriage_by_user_global(user_id)
    if not marriage:
        return None
    _bdb.execute(
        "UPDATE marriages SET status='divorced', ended_at=?, ended_by=?, end_reason=? WHERE id=?",
        (now_brazil().isoformat(), user_id, reason, marriage[0])
    )
    return marriage

def get_marriage_by_id(marriage_id):
    return _bdb.execute('SELECT * FROM marriages WHERE id=?', (marriage_id,)).fetchone()

def add_marriage_affection(marriage_id, kind, amount=1):
    if kind not in ('kiss', 'hug'):
        return
    col = 'kiss_count' if kind == 'kiss' else 'hug_count'
    _bdb.execute(f'UPDATE marriages SET {col}=COALESCE({col},0)+? WHERE id=?', (amount, marriage_id))

def add_marriage_click_stat(marriage_id, stat, amount=1):
    col_map = {
        'affection': 'affection_click_count',
        'retribute': 'retribute_click_count',
        'reject': 'reject_click_count',
    }
    col = col_map.get(stat)
    if not col:
        return
    _bdb.execute(f'UPDATE marriages SET {col}=COALESCE({col},0)+? WHERE id=?', (amount, marriage_id))

def get_latest_marriage_history(guild_id, user_id, limit=5):
    return _bdb.execute(
        '''SELECT * FROM marriages
           WHERE guild_id=? AND (spouse_a=? OR spouse_b=?)
           ORDER BY id DESC LIMIT ?''',
        (guild_id, user_id, user_id, limit)
    ).fetchall()

def marriage_row_to_dict(row):
    if not row:
        return None
    return {
        'id': row[0],
        'guild_id': row[1],
        'proposer_id': row[2],
        'spouse_a': row[3],
        'spouse_b': row[4],
        'witnesses': _parse_list_json(row[5]),
        'status': row[6],
        'created_at': row[7],
        'accepted_at': row[8],
        'ended_at': row[9],
        'ended_by': row[10],
        'end_reason': row[11],
        'proposal_dm_channel_id': row[12],
        'proposal_dm_message_id': row[13],
        'celebrant_id': row[14] if len(row) > 14 else None,
        'kiss_count': row[15] if len(row) > 15 and row[15] is not None else 0,
        'hug_count': row[16] if len(row) > 16 and row[16] is not None else 0,
        'affection_click_count': row[17] if len(row) > 17 and row[17] is not None else 0,
        'retribute_click_count': row[18] if len(row) > 18 and row[18] is not None else 0,
        'reject_click_count': row[19] if len(row) > 19 and row[19] is not None else 0,
    }

# ============================================================
# WIPES
# ============================================================
def wipe_user(guild_id, user_id):
    _vdb.execute('DELETE FROM voice_stats WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    _vdb.execute('DELETE FROM voice_sessions WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    _bdb.execute('DELETE FROM chat_stats WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    _bdb.execute('DELETE FROM economy WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    _bdb.execute('DELETE FROM user_inventory WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    _bdb.execute('DELETE FROM level_stats WHERE guild_id=? AND user_id=?', (guild_id, user_id))
    _bdb.execute('DELETE FROM mod_cases WHERE guild_id=? AND target_id=?', (guild_id, user_id))

def reset_all_voice(guild_id):
    """Reset all voice hours for a guild (leaderboard only, keeps sessions)."""
    _vdb.execute('UPDATE voice_stats SET total_seconds=0, session_count=0, longest_session=0 WHERE guild_id=?',
                 (guild_id,))

def reset_all_chat(guild_id):
    """Reset all chat stats for a guild (leaderboard only)."""
    _bdb.execute('UPDATE chat_stats SET total_messages=0, today_messages=0, week_messages=0, month_messages=0 WHERE guild_id=?',
                 (guild_id,))

def wipe_guild(guild_id):
    _vdb.execute('DELETE FROM voice_stats WHERE guild_id=?', (guild_id,))
    _vdb.execute('DELETE FROM voice_sessions WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM chat_stats WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM economy WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM shop_items WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM user_inventory WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM level_stats WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM level_rewards WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM level_config WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM mod_cases WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM market_listings WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM coleira_authorized WHERE guild_id=?', (guild_id,))
    _bdb.execute('DELETE FROM coleiras WHERE guild_id=?', (guild_id,))

# ============================================================
# COLEIRA
# ============================================================
def is_coleira_authorized(guild_id, user_id):
    row = _bdb.execute(
        'SELECT 1 FROM coleira_authorized WHERE guild_id=? AND user_id=?',
        (guild_id, user_id)
    ).fetchone()
    return bool(row)


def set_coleira_authorized(guild_id, user_id, granted_by):
    _bdb.execute(
        '''INSERT INTO coleira_authorized (guild_id,user_id,granted_by,granted_at)
           VALUES (?,?,?,?)
           ON CONFLICT(guild_id,user_id) DO UPDATE SET
             granted_by=excluded.granted_by,
             granted_at=excluded.granted_at''',
        (guild_id, user_id, granted_by, now_brazil().isoformat())
    )


def remove_coleira_authorized(guild_id, user_id):
    _bdb.execute(
        'DELETE FROM coleira_authorized WHERE guild_id=? AND user_id=?',
        (guild_id, user_id)
    )


def get_coleira_authorized_users(guild_id):
    return _bdb.execute(
        'SELECT user_id FROM coleira_authorized WHERE guild_id=? ORDER BY granted_at DESC',
        (guild_id,)
    ).fetchall()


def add_coleira(guild_id, owner_id, target_id):
    _bdb.execute(
        '''INSERT INTO coleiras (guild_id,owner_id,target_id,created_at)
           VALUES (?,?,?,?)
           ON CONFLICT(guild_id,target_id) DO UPDATE SET
             owner_id=excluded.owner_id,
             created_at=excluded.created_at''',
        (guild_id, owner_id, target_id, now_brazil().isoformat())
    )


def remove_coleira(guild_id, owner_id, target_id):
    c = _bdb.execute(
        'DELETE FROM coleiras WHERE guild_id=? AND owner_id=? AND target_id=?',
        (guild_id, owner_id, target_id)
    )
    return c.rowcount > 0


def get_coleiras_by_owner(guild_id, owner_id):
    return _bdb.execute(
        'SELECT target_id, created_at FROM coleiras WHERE guild_id=? AND owner_id=? ORDER BY created_at DESC',
        (guild_id, owner_id)
    ).fetchall()


def get_coleira_by_target(guild_id, target_id):
    return _bdb.execute(
        'SELECT owner_id, target_id, created_at FROM coleiras WHERE guild_id=? AND target_id=?',
        (guild_id, target_id)
    ).fetchone()


def get_coleiras_where_owner(guild_id, owner_id):
    return _bdb.execute(
        'SELECT owner_id, target_id FROM coleiras WHERE guild_id=? AND owner_id=?',
        (guild_id, owner_id)
    ).fetchall()

# ============================================================
# SHARED VOICE TIME (for DM after season reset)
# ============================================================
def get_user_sessions(guild_id, user_id):
    """Get all voice sessions for a user as list of (join_time, leave_time)."""
    return _vdb.execute(
        'SELECT join_time, leave_time FROM voice_sessions WHERE guild_id=? AND user_id=? AND leave_time IS NOT NULL ORDER BY join_time',
        (guild_id, user_id)).fetchall()

def get_all_user_ids_voice(guild_id):
    """Get all user IDs that have voice stats."""
    return _vdb.execute('SELECT user_id FROM voice_stats WHERE guild_id=?', (guild_id,)).fetchall()

def get_all_user_ids_chat(guild_id):
    """Get all user IDs that have chat stats."""
    return _bdb.execute('SELECT user_id FROM chat_stats WHERE guild_id=? AND total_messages>0', (guild_id,)).fetchall()

def shared_voice_time(guild_id, user_a_id, user_b_id):
    """Calculate overlapping voice time between two users in seconds.
    Uses session-based calculation from the last 30 days."""
    cutoff = (now_brazil() - timedelta(days=30)).isoformat()
    sessions_a = _vdb.execute(
        '''SELECT join_time, leave_time
           FROM voice_sessions
           WHERE guild_id=? AND user_id=? AND leave_time IS NOT NULL AND leave_time>=?
           ORDER BY join_time''',
        (guild_id, user_a_id, cutoff)).fetchall()
    sessions_b = _vdb.execute(
        '''SELECT join_time, leave_time
           FROM voice_sessions
           WHERE guild_id=? AND user_id=? AND leave_time IS NOT NULL AND leave_time>=?
           ORDER BY join_time''',
        (guild_id, user_b_id, cutoff)).fetchall()

    def _coerce_aware(value):
        from datetime import datetime as dt
        if isinstance(value, str):
            try:
                value = dt.fromisoformat(value)
            except Exception:
                return None
        if value is None:
            return None
        try:
            return ensure_aware(value)
        except Exception:
            return None

    parsed_a = []
    for ja, la in sessions_a:
        ja_dt = _coerce_aware(ja)
        la_dt = _coerce_aware(la)
        if ja_dt and la_dt and la_dt > ja_dt:
            parsed_a.append((ja_dt, la_dt))

    parsed_b = []
    for jb, lb in sessions_b:
        jb_dt = _coerce_aware(jb)
        lb_dt = _coerce_aware(lb)
        if jb_dt and lb_dt and lb_dt > jb_dt:
            parsed_b.append((jb_dt, lb_dt))

    # Two-pointer sweep: O(n + m) instead of O(n * m).
    overlap = 0
    i = 0
    j = 0
    while i < len(parsed_a) and j < len(parsed_b):
        a_start, a_end = parsed_a[i]
        b_start, b_end = parsed_b[j]

        start = max(a_start, b_start)
        end = min(a_end, b_end)
        if end > start:
            overlap += int((end - start).total_seconds())

        # Advance the interval that ends first.
        if a_end <= b_end:
            i += 1
        else:
            j += 1
    return overlap
