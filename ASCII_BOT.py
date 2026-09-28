from __future__ import annotations

import asyncio
import subprocess
import sys
import importlib
import importlib.util
import html
import io
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)

from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    import pyfiglet
    from pyfiglet import Figlet, FigletFont
    HAS_FIGLET = True
except ImportError:
    HAS_FIGLET = False


# ===========================================================================
#  CONFIGURATION & DATABASE SETUP
# ===========================================================================

# Render / Environment Variable se token lega
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Admin Credentials
ADMIN_ID = 7552507251
ADMIN_USERNAME = "TENZOOGAMER"

# Catbox image links
CATBOX_IMAGE_URL = "https://files.catbox.moe/ch8rst.png"
ADMIN_PANEL_PHOTO = "https://files.catbox.moe/nv7v1v.png"

CATBOX_CAPTION = (
    "✨ ASCII / ANSI STUDIO ✨\n\n"
    "🚀 Welcome to the ASCII Maker! Transform your text and imagery.\n\n"
    "🧭 Navigate your experience below:\n\n"
    "👑 7X SNIPER • @TENZOOGAMER"
)

# Database Initialization
DB_FILE = "bot_users.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            joined_date TEXT,
            last_active TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def track_user(user):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    username_str = f"@{user.username}" if user.username else "No Username"
    
    cursor.execute("SELECT joined_date FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, username, joined_date, last_active) VALUES (?, ?, ?, ?)",
            (user.id, username_str, now_str, now_str)
        )
    else:
        cursor.execute(
            "UPDATE users SET username = ?, last_active = ? WHERE user_id = ?",
            (username_str, now_str, user.id)
        )
    conn.commit()
    conn.close()


# ===========================================================================
#  COLOR PALETTE
# ===========================================================================

COLORS = {
    "primary":  (0, 122, 255),
    "success":  (40, 167, 69),
    "danger":   (220, 53, 69),
    "white":    (255, 255, 255),
    "black":    (0, 0, 0),
    "gray":     (128, 128, 128),
    "silver":   (192, 192, 192),
    "darkgray": (64, 64, 64),
    "red":      (255, 0, 0),
    "crimson":  (220, 20, 60),
    "maroon":   (128, 0, 0),
    "salmon":   (250, 128, 114),
    "pink":     (255, 105, 180),
    "orange":   (255, 165, 0),
    "gold":     (255, 215, 0),
    "yellow":   (255, 255, 0),
    "amber":    (255, 191, 0),
    "green":    (0, 255, 0),
    "lime":     (50, 205, 50),
    "matrix":   (0, 255, 120),
    "emerald":  (80, 200, 120),
    "olive":    (128, 128, 0),
    "teal":     (0, 128, 128),
    "cyan":     (0, 255, 255),
    "skyblue":  (135, 206, 235),
    "blue":     (0, 100, 255),
    "navy":     (0, 0, 128),
    "royal":    (65, 105, 225),
    "indigo":   (75, 0, 130),
    "violet":   (138, 43, 226),
    "purple":   (160, 32, 240),
    "magenta":  (255, 0, 255),
    "fuchsia":  (255, 119, 255),
    "brown":    (139, 69, 19),
    "tan":      (210, 180, 140),
    "beige":    (245, 245, 220),
}


# ===========================================================================
#  GLOBAL DEFAULTS
# ===========================================================================

DEFAULT_BANNER_FONT = "slant"
DEFAULT_IMAGE_STYLE = "density"
DEFAULT_COLOR_MODE = "primary"
DEFAULT_FORMAT = "ansi"

MAX_PREVIEW = 3800

STYLES = ("density", "binary", "block", "braille")
COLOR_MODES = ("gray", "mono", "rgb", "gradient")
FORMATS = ("txt", "html", "ansi", "png")

RAMP_DENSITY = " .:•●⬤"
RAMP_BINARY = ". "
RAMP_BLOCK = " ░▒▓█"
RAMP_BRAILLE = " ⠁⠉⠋⠛⡟⠿⡿⣿"

MIN_WIDTH, MAX_WIDTH = 40, 400
MIN_BANNER_WIDTH, MAX_BANNER_WIDTH = 40, 300
MIN_SCALE, MAX_SCALE = 1, 4
MIN_ASPECT, MAX_ASPECT = 0.3, 1.2
MIN_CONTRAST, MAX_CONTRAST = 0.5, 3.0


# ===========================================================================
#  PER-USER STATE
# ===========================================================================

@dataclass
class UserState:
    banner_font: str = DEFAULT_BANNER_FONT
    banner_width: int = 200
    banner_scale: int = 1
    banner_color: str = "primary"

    image_style: str = DEFAULT_IMAGE_STYLE
    color_mode: str = DEFAULT_COLOR_MODE
    image_color: str = "primary"
    image_color2: str = "cyan"
    gradient_dir: str = "vertical"
    width: int = 140
    scale: int = 1
    aspect: float = 0.5
    contrast: float = 1.0
    invert: bool = False

    fmt: str = DEFAULT_FORMAT
    mode: str = "idle"
    broadcast_pending_msg: str | None = None


USERS: dict[int, UserState] = {}


def get_user(uid: int) -> UserState:
    if uid not in USERS:
        USERS[uid] = UserState()
    return USERS[uid]


# ===========================================================================
#  LOGGING
# ===========================================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("studio")


# ===========================================================================
#  FIGLET
# ===========================================================================

def all_figlet_fonts() -> list[str]:
    if not HAS_FIGLET:
        return []
    try:
        return sorted(FigletFont.getFonts())
    except Exception:
        return []


ALL_FONTS = all_figlet_fonts()
FONT_COUNT = len(ALL_FONTS)


def find_fonts(query: str) -> list[str]:
    q = query.lower().strip()
    if not q:
        return ALL_FONTS
    return [f for f in ALL_FONTS if q in f.lower()]


def render_banner(text: str, font: str, width: int, scale: int) -> str:
    if not HAS_FIGLET:
        raise RuntimeError("pyfiglet is not installed")
    try:
        fig = Figlet(font=font, width=max(40, width))
        raw = fig.renderText(text)
    except Exception as exc:
        raise ValueError(f"Font '{font}' failed to render: {exc}") from exc
    if scale > 1:
        raw = _scale_text(raw, scale)
    return raw


def _scale_text(text: str, scale: int) -> str:
    if scale <= 1:
        return text
    lines = text.split("\n")
    out = []
    for line in lines:
        stretched = "".join(ch * scale for ch in line)
        for _ in range(scale):
            out.append(stretched)
    return "\n".join(out)


# ===========================================================================
#  COLOR HELPERS
# ===========================================================================

HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def parse_hex(s: str):
    s = s.strip().lstrip("#")
    if not HEX_RE.match(s):
        return None
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def resolve_color(name: str, fallback=(0, 122, 255)):
    if not name:
        return fallback
    key = name.lower().strip().lstrip("#")
    if key in COLORS:
        return COLORS[key]
    hx = parse_hex(key)
    if hx:
        return hx
    return fallback


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_color(c1, c2, x, y, w, h, direction: str):
    if direction == "horizontal":
        t = x / max(1, w - 1)
    elif direction == "diagonal":
        t = (x + y) / max(1, (w - 1) + (h - 1))
    else:
        t = y / max(1, h - 1)
    return lerp(c1, c2, t)


# ===========================================================================
#  IMAGE → GRID
# ===========================================================================

def image_to_grid(image_bytes: bytes, width: int, style: str,
                  invert: bool = False, contrast: float = 1.0,
                  aspect: float = 0.5, scale: int = 1):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception as e:
        raise ValueError(f"Could not open image: {e}")

    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    rgb_img = img
    gray_img = img.convert("L")
    if invert:
        gray_img = ImageOps.invert(gray_img)

    orig_w, orig_h = gray_img.size
    if orig_w <= 0 or orig_h <= 0:
        raise ValueError("Image has zero dimensions")

    ar = orig_h / orig_w
    new_w = max(1, int(width))
    new_h = max(1, int(new_w * ar * aspect))

    gray_img = gray_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    rgb_img = rgb_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    gp = list(gray_img.getdata())
    rp = list(rgb_img.getdata())

    ramps = {
        "density": RAMP_DENSITY,
        "binary":  RAMP_BINARY,
        "block":   RAMP_BLOCK,
        "braille": RAMP_BRAILLE,
    }
    ramp = ramps.get(style, RAMP_DENSITY)
    rl = len(ramp)

    grid = []
    for y in range(new_h):
        row = []
        base = y * new_w
        for x in range(new_w):
            v = gp[base + x]
            rgb = rp[base + x]
            idx = ((255 - v) * (rl - 1)) // 255
            row.append((ramp[idx], v, rgb))

        if scale > 1:
            expanded = []
            for cell in row:
                expanded.extend([cell] * scale)
            row = expanded

        for _ in range(scale):
            grid.append(list(row))
    return grid


# ===========================================================================
#  EXPORTERS
# ===========================================================================

def _rgb_to_ansi(rgb) -> int:
    r, g, b = rgb
    ri = round(r / 255 * 5)
    gi = round(g / 255 * 5)
    bi = round(b / 255 * 5)
    return 16 + 36 * ri + 6 * gi + bi


def _apply_color_mode(grid, color_mode: str, c1, c2, direction: str):
    if not grid:
        return grid
    h = len(grid)
    w = max(len(r) for r in grid)

    out = []
    for y, row in enumerate(grid):
        new_row = []
        for x, (ch, v, rgb) in enumerate(row):
            if color_mode == "rgb":
                final = rgb
            elif color_mode == "mono":
                brightness = (255 - v) / 255.0
                final = tuple(int(c * brightness) for c in c1)
            elif color_mode == "gradient":
                base = gradient_color(c1, c2, x, y, w, h, direction)
                brightness = (255 - v) / 255.0
                final = tuple(int(c * brightness) for c in base)
            else:
                g = 255 - v
                final = (g, g, g)
            new_row.append((ch, v, final))
        out.append(new_row)
    return out


def export_txt(grid) -> bytes:
    lines = ["".join(c[0] for c in row) for row in grid]
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_html(grid, title: str = "ASCII Art") -> bytes:
    rows_html = []
    for row in grid:
        spans = []
        for ch, _v, rgb in row:
            safe = "&nbsp;" if ch == " " else html.escape(ch)
            r, g, b = rgb
            spans.append(f'<span style="color:rgb({r},{g},{b})">{safe}</span>')
        rows_html.append("".join(spans))
    body = "\n".join(rows_html)
    doc = (
        "<!DOCTYPE html>\n<html lang='en'><head>\n"
        "<meta charset='utf-8'>\n"
        f"<title>{html.escape(title)}</title>\n"
        "<style>\n"
        "html,body{margin:0;padding:0;background:#000;color:#eee;"
        "font-family:'Consolas','Menlo','DejaVu Sans Mono',monospace;"
        "font-size:10px;line-height:1.0;}\n"
        "pre{margin:0;padding:12px;white-space:pre;display:inline-block;}\n"
        ".meta{color:#666;font-size:11px;padding:8px 12px;"
        "font-family:sans-serif;}\n"
        "</style></head><body>\n"
        '<div class="meta">ASCII Studio · @TENZOOGAMER · 7X SNIPER</div>\n'
        f"<pre>{body}</pre></body></html>\n"
    )
    return doc.encode("utf-8")


def export_ansi(grid) -> bytes:
    out_lines = []
    for row in grid:
        chunks = []
        cur = None
        for ch, _v, rgb in row:
            if ch == " ":
                chunks.append(" ")
                continue
            idx = _rgb_to_ansi(rgb)
            if idx != cur:
                chunks.append(f"\x1b[38;5;{idx}m")
                cur = idx
            chunks.append(ch)
        chunks.append("\x1b[0m")
        out_lines.append("".join(chunks))
    return ("\n".join(out_lines) + "\n").encode("utf-8")


def _load_font(size):
    for path in (
        "DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "consola.ttf", "cour.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def export_png(grid, font_size: int = 14, bg=(0, 0, 0)) -> bytes:
    font = _load_font(font_size)
    if not grid:
        raise ValueError("Empty grid")

    try:
        bbox = font.getbbox("M")
        cw = bbox[2] - bbox[0] or font_size // 2
        ch = bbox[3] - bbox[1] or font_size
    except Exception:
        cw, ch = font_size // 2, font_size

    line_h = int(ch * 1.15)
    cols = max(len(r) for r in grid)
    rows = len(grid)

    img = Image.new("RGB", (cols * cw + 20, rows * line_h + 20), bg)
    draw = ImageDraw.Draw(img)

    for y, row in enumerate(grid):
        for x, (c, _v, rgb) in enumerate(row):
            if c == " ":
                continue
            draw.text((10 + x * cw, 10 + y * line_h), c, font=font, fill=rgb)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


def banner_to_grid(banner_text: str):
    grid = []
    for line in banner_text.split("\n"):
        row = []
        for ch in line:
            if ch == " ":
                row.append((ch, 255, (0, 0, 0)))
            else:
                row.append((ch, 0, (255, 255, 255)))
        grid.append(row)
    return grid


def _export_grid(grid, fmt: str):
    fmt = fmt.lower()
    if fmt == "txt":
        return export_txt(grid), "art.txt", "text/plain"
    if fmt == "html":
        return export_html(grid), "art.html", "text/html"
    if fmt == "ansi":
        return export_ansi(grid), "art.ansi", "text/plain"
    if fmt == "png":
        return export_png(grid), "art.png", "image/png"
    raise ValueError(f"Unknown format: {fmt}")


# ===========================================================================
#  UI HELPERS & KEYBOARDS
# ===========================================================================

def _btn(text: str, icon: str = "") -> KeyboardButton:
    label = f"{icon} {text}".strip() if icon else text
    return KeyboardButton(text=label)


def _mark(active: bool, label: str) -> str:
    return f"✅ {label}" if active else label


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(" ✍️ Text → Banner", callback_data="menu:banner")],
        [InlineKeyboardButton(" 🖼️ Image → Art",   callback_data="menu:image")],
        [InlineKeyboardButton(" 📐 Size Presets",  callback_data="menu:presets")],
        [InlineKeyboardButton(" 📥 Export Format", callback_data="menu:format")],
    ])


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [
                _btn("FF Free Likes", "⚡"),
                _btn("FF Hologram", "🎨")
            ],
            [
                _btn("ADMIN PANEL", "👑")
            ]
        ],
        resize_keyboard=True
    )


def admin_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌍 User List", callback_data="admin:userlist"),
            InlineKeyboardButton("🦸‍♂️ Broadcast", callback_data="admin:broadcast")
        ],
        [
            InlineKeyboardButton(" 🔙 Return", callback_data="menu:main")
        ]
    ])


def banner_menu_kb(u: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(" 🔤 Typography Font", callback_data="ban:fonts:0")],
        [InlineKeyboardButton(" 🔍 Search Font",     callback_data="ban:search")],
        [InlineKeyboardButton(f" ↔️ Width: {u.banner_width}", callback_data="ban:w:show")],
        [InlineKeyboardButton(f" 🔍 Scale: {u.banner_scale}x", callback_data="ban:s:show")],
        [InlineKeyboardButton(" 📥 Export Format",   callback_data="menu:format")],
        [InlineKeyboardButton(" ⚡ Generate Now",    callback_data="action:send_text")],
        [InlineKeyboardButton(" 🔙 Return",          callback_data="menu:main")],
    ])


def format_kb(u: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_mark(u.fmt == "txt", "📄 .txt"), callback_data="fmt:txt"),
         InlineKeyboardButton(_mark(u.fmt == "html", "🌐 .html"), callback_data="fmt:html")],
        [InlineKeyboardButton(_mark(u.fmt == "ansi", "💻 .ansi"), callback_data="fmt:ansi"),
         InlineKeyboardButton(_mark(u.fmt == "png", "🖼️ PNG"), callback_data="fmt:png")],
        [InlineKeyboardButton(" 🔙 Return", callback_data="menu:main")],
    ])


def presets_kb(u: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(" 📐 Compact (80w, 1x)", callback_data="pre:small"),
         InlineKeyboardButton(" 🎨 Elegant (140w, 1x)", callback_data="pre:medium")],
        [InlineKeyboardButton(" 🏛️ Grand (220w, 1x)", callback_data="pre:large"),
         InlineKeyboardButton(" 🖼️ Imperial (200w, 2x)", callback_data="pre:poster")],
        [InlineKeyboardButton(" 👑 Majestic (250w, 3x)", callback_data="pre:huge")],
        [InlineKeyboardButton(" 🔙 Return", callback_data="menu:main")],
    ])


def width_control_kb(u: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(" ➖ 20", callback_data="ban:w:-20"),
         InlineKeyboardButton(f" {u.banner_width}", callback_data="ban:w:show"),
         InlineKeyboardButton(" ➕ 20", callback_data="ban:w:+20")],
        [InlineKeyboardButton(" ➖ 50", callback_data="ban:w:-50"),
         InlineKeyboardButton(" ➕ 50", callback_data="ban:w:+50")],
        [InlineKeyboardButton(" ✍️ Enter custom value", callback_data="ban:w:type")],
        [InlineKeyboardButton(" 🔙 Return", callback_data="menu:banner")],
    ])


# ===========================================================================
#  UI SCREENS
# ===========================================================================

def _header() -> str:
    return (
        "╔════════════════════════════════════╗\n"
        "║     🎨 ASCII & ANSI STUDIO 🎨      ║\n"
        "╚════════════════════════════════════╝"
    )


def _footer() -> str:
    return "🔥 7X SNIPER  •  @TENZOOGAMER 🔥"


def welcome_text(u: UserState) -> str:
    fc = FONT_COUNT if HAS_FIGLET else 0
    return (
        f"{_header()}\n\n"
        "✨ Welcome to the ASCII Studio. Convert your text and images into ASCII and ANSI artwork!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✍️ Text → Banner Studio\n"
        f"   • 🔤 {fc}+ FIGlet typography options\n"
        "   • 📏 Custom width and precision scaling\n"
        "   • 🎨 Primary & Success button themes\n\n"
        "🖼️ Image → Art Engine\n"
        "   • 🎭 4 artistic rendering styles\n"
        "   • 🌈 Color modes\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚙️ Format: `{u.fmt.upper()}`   "
        f"🎨 Color: `{u.image_color}`   "
        f"📐 Width: `{u.width}`\n\n"
        "👇 Select your option below:\n\n"
        f"{_footer()}"
    )


def banner_screen(u: UserState) -> str:
    return (
        "✍️ Text → Banner Studio\n\n"
        "💬 Send your text to craft a typography banner.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔤 Font   : `{u.banner_font}`\n"
        f"↔️ Width  : `{u.banner_width}`\n"
        f"🔍 Scale  : `{u.banner_scale}x`\n"
        f"🎨 Color  : `{u.banner_color}`\n"
        f"📥 Format : `{u.fmt.upper()}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚙️ Configure via buttons, then send your text:"
    )


# ===========================================================================
#  COMMANDS
# ===========================================================================

async def post_init(application: Application) -> None:
    try:
        await application.bot.set_my_commands([])
        log.info("Cleared cached commands.")
    except Exception as e:
        log.warning(f"Could not clear commands: {e}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    u = get_user(update.effective_user.id)
    u.mode = "idle"

    if CATBOX_IMAGE_URL and CATBOX_IMAGE_URL.startswith("http"):
        try:
            await update.message.reply_photo(
                photo=CATBOX_IMAGE_URL,
                caption=CATBOX_CAPTION,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(),
            )
        except TelegramError as exc:
            log.warning("Catbox image send failed: %s", exc)
            await update.message.reply_text(
                welcome_text(u),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_kb(),
            )
    else:
        await update.message.reply_text(
            welcome_text(u),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_kb(),
        )

    await update.message.reply_text(
        "⚡ Access your exclusive Free Fire portals below:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_keyboard()
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    await cmd_start(update, context)


async def cmd_banner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    u = get_user(update.effective_user.id)
    u.mode = "awaiting_banner_text"
    try:
        await update.message.reply_photo(
            photo="https://files.catbox.moe/95j7vf.png",
            caption=banner_screen(u),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=banner_menu_kb(u)
        )
    except Exception:
        await update.message.reply_text(
            banner_screen(u),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=banner_menu_kb(u),
        )


async def cmd_fonts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    u = get_user(update.effective_user.id)
    await update.message.reply_text(
        f"🔤 Typography Fonts ({FONT_COUNT} available)\n\n📌 Current Active: `{u.banner_font}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=font_list_kb(0),
    )


async def cmd_font(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    u = get_user(update.effective_user.id)
    args = context.args or []
    if not args:
        await cmd_fonts(update, context)
        return
    q = " ".join(args).strip()
    matches = find_fonts(q)
    if not matches:
        await update.message.reply_text(f"❌ No typography style matched `{q}`.", parse_mode=ParseMode.MARKDOWN)
        return
    exact = [f for f in matches if f.lower() == q.lower()]
    if exact:
        u.banner_font = exact[0]
        await update.message.reply_text(f"✅ Font successfully updated: `{u.banner_font}`", parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        f"🔍 `{q}` → {len(matches)} styles found:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=font_list_kb(0, query=q),
    )


async def cmd_color(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    u = get_user(update.effective_user.id)
    args = context.args or []
    if not args:
        await update.message.reply_text(
            f"🎨 Active Color Palettes:\n  ✍️ Banner : `{u.banner_color}`\n  🖼️ Image1 : `{u.image_color}`\n  🖼️ Image2 : `{u.image_color2}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    val = args[0].lower().lstrip("#") if args[0].startswith("#") else args[0].lower()
    if val not in COLORS and not parse_hex(val):
        await update.message.reply_text(
            f"❌ `{val}` is not recognized.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    u.banner_color = val
    u.image_color = val
    await update.message.reply_text(f"✅ Palette applied successfully: `{val}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_width(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    u = get_user(update.effective_user.id)
    args = context.args or []
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            f"↔️ Current width dimension: `{u.width}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    u.width = max(MIN_WIDTH, min(MAX_WIDTH, int(args[0])))
    await update.message.reply_text(f"✅ Width dimension adjusted: `{u.width}`", parse_mode=ParseMode.MARKDOWN)


async def cmd_scale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    u = get_user(update.effective_user.id)
    args = context.args or []
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            f"🔍 Current scale factor: `{u.scale}x`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    u.scale = max(MIN_SCALE, min(MAX_SCALE, int(args[0])))
    await update.message.reply_text(f"✅ Scale factor configured: `{u.scale}x`", parse_mode=ParseMode.MARKDOWN)


async def cmd_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update.effective_user)
    u = get_user(update.effective_user.id)
    await update.message.reply_text(
        f"📥 Export Format\n\n📌 Current Format: `{u.fmt.upper()}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=format_kb(u),
    )


async def cmd_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Aapke paas iss command ko chalane ki permission nahi hai.", parse_mode=ParseMode.MARKDOWN)
        return

    track_user(user)
    u = get_user(user.id)
    if u.mode != "awaiting_broadcast_confirm" or not u.broadcast_pending_msg:
        await update.message.reply_text("❌ Koi broadcast command ya message pending nahi hai.", parse_mode=ParseMode.MARKDOWN)
        return

    msg_to_send = u.broadcast_pending_msg
    u.broadcast_pending_msg = None
    u.mode = "idle"

    status_msg = await update.message.reply_text("⚡ Broadcast starting... Sabhi users ko message bheja ja raha hai.", parse_mode=ParseMode.MARKDOWN)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()

    success_count = 0
    fail_count = 0

    for row in rows:
        target_id = row[0]
        try:
            await context.bot.send_message(chat_id=target_id, text=msg_to_send, parse_mode=ParseMode.MARKDOWN)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1

    await status_msg.edit_text(
        f"🎉 *Broadcast Finished!*\n\n"
        f"✅ Successfully Delivered: `{success_count}`\n"
        f"❌ Failed / Blocked: `{fail_count}`",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Aapke paas iss command ko chalane ki permission nahi hai.", parse_mode=ParseMode.MARKDOWN)
        return

    track_user(user)
    u = get_user(user.id)
    if u.mode == "awaiting_broadcast_msg" or u.mode == "awaiting_broadcast_confirm":
        u.mode = "idle"
        u.broadcast_pending_msg = None
        await update.message.reply_text("🚫 *Broadcast request cancel ho gayi hai.* Message bhej na stop kar diya gaya hai.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("ℹ️ Active broadcast process nahi mila cancel karne ke liye.", parse_mode=ParseMode.MARKDOWN)


# ===========================================================================
#  FONT LIST
# ===========================================================================

def font_list_kb(page: int, query: str = "") -> InlineKeyboardMarkup:
    fonts = find_fonts(query)
    per_page = 12
    start = page * per_page
    chunk = fonts[start:start + per_page]

    rows = []
    for i in range(0, len(chunk), 2):
        pair = chunk[i:i + 2]
        rows.append([
            InlineKeyboardButton(f"🔤 {f}", callback_data=f"ban:setfont:{f}")
            for f in pair
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"ban:fonts:{page-1}"))
    if start + per_page < len(fonts):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"ban:fonts:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(" 🔙 Return", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


# ===========================================================================
#  CALLBACK HANDLER
# ===========================================================================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or not q.data:
        return
    track_user(q.from_user)
    u = get_user(q.from_user.id)
    data = q.data

    if data == "noop":
        await q.answer()
        return

    await q.answer()

    if data == "admin:userlist":
        if q.from_user.id != ADMIN_ID and (q.from_user.username or "").lower() != ADMIN_USERNAME.lower():
            await q.message.reply_text("⚠️ Access Denied! Sirf admin hi yeh information dekh sakta hai.", parse_mode=ParseMode.MARKDOWN)
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, joined_date, last_active FROM users")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            text = "🌍 *USER DATABASE*\n\nAbhi koi user registered nahi hai!"
        else:
            text = f"🌍 *USER LIST ({len(rows)} Total Users)*\n\n"
            for row in rows:
                uid, uname, joined, last_act = row
                text += f"👤 *Username:* {uname} (`{uid}`)\n"
                text += f"📅 *Joined Date:* {joined}\n"
                text += f"⚡ *Last Active:* {last_act}\n"
                text += "━━━━━━━━━━━━━━━━━━━━\n"

        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                await q.message.reply_text(text[i:i+4000], parse_mode=ParseMode.MARKDOWN)
        else:
            await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "admin:broadcast":
        if q.from_user.id != ADMIN_ID and (q.from_user.username or "").lower() != ADMIN_USERNAME.lower():
            await q.message.reply_text("⚠️ Access Denied! Sirf admin hi broadcast feature use kar sakta hai.", parse_mode=ParseMode.MARKDOWN)
            return

        u.mode = "awaiting_broadcast_msg"
        await q.message.reply_text(
            "📢 *BROADCAST MODE ACTIVATED*\n\n"
            "Admin, kripya wo message bhejein jo aap sabhi bot users ko broadcast karna chahte hain.\n\n"
            "❌ Action cancel karne ke liye `/cancel` likhein.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "action:send_text":
        u.mode = "awaiting_banner_text"
        await q.edit_message_caption(
            caption="💬 Please transmit your text now to generate your banner!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" 🔙 Return", callback_data="menu:banner")]])
        )
        return

    if data == "menu:main":
        u.mode = "idle"
        try:
            await q.message.reply_text(welcome_text(u), parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_kb())
            await q.message.delete()
        except Exception:
            await q.edit_message_text(welcome_text(u), parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_kb())
        return

    if data == "menu:banner":
        u.mode = "awaiting_banner_text"
        try:
            await q.message.reply_photo(
                photo="https://files.catbox.moe/95j7vf.png",
                caption=banner_screen(u),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=banner_menu_kb(u)
            )
            await q.message.delete()
        except Exception:
            await q.edit_message_text(banner_screen(u), parse_mode=ParseMode.MARKDOWN, reply_markup=banner_menu_kb(u))
        return

    if data == "menu:image":
        u.mode = "idle"
        maintenance_msg = (
            "🛠️ IMAGE TO ART ENGINE — SYSTEM NOTICE\n\n"
            " Our Image to Art conversion module is currently undergoing maintenance.\n\n"
            "✨ This feature will be restored soon.\n\n"
            "🔥 7X SNIPER • @TENZOOGAMER"
        )
        try:
            await q.message.reply_photo(
                photo="https://files.catbox.moe/eae6aq.png",
                caption=maintenance_msg,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(" 🔙 Return", callback_data="menu:main")
                ]])
            )
            await q.message.delete()
        except Exception:
            await q.edit_message_text(
                maintenance_msg,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(" 🔙 Return", callback_data="menu:main")
                ]])
            )
        return

    if data == "menu:format":
        await q.edit_message_text(
            f"📥 Export Format\n\n📌 Current Format: `{u.fmt.upper()}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=format_kb(u),
        )
        return

    if data == "menu:presets":
        await q.edit_message_text(
            "📐 Size Presets\n\n✨ Apply curated dimension parameters:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=presets_kb(u),
        )
        return

    if data.startswith("pre:"):
        p = data.split(":", 1)[1]
        if p == "small":
            u.width, u.scale, u.aspect = 80, 1, 0.5
        elif p == "medium":
            u.width, u.scale, u.aspect = 140, 1, 0.5
        elif p == "large":
            u.width, u.scale, u.aspect = 220, 1, 0.5
        elif p == "poster":
            u.width, u.scale, u.aspect = 200, 2, 0.5
        elif p == "huge":
            u.width, u.scale, u.aspect = 250, 3, 0.5
        await q.edit_message_text(
            f"✅ Preset *{p}* successfully applied!\n\n↔️ Width: `{u.width}`\n🔍 Scale: `{u.scale}x`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(" 🔙 Return", callback_data="menu:main"),
            ]]),
        )
        return

    if data == "ban:fonts:0":
        try:
            await q.edit_message_caption(
                caption=f"🔤 Typography Fonts — {FONT_COUNT} available\n\n📌 Current Active: `{u.banner_font}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=font_list_kb(0),
            )
        except Exception:
            await q.edit_message_text(
                f"🔤 Typography Fonts — {FONT_COUNT} available\n\n📌 Current Active: `{u.banner_font}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=font_list_kb(0),
            )
        return

    if data.startswith("ban:fonts:"):
        page = int(data.rsplit(":", 1)[1])
        await q.edit_message_reply_markup(reply_markup=font_list_kb(page))
        return

    if data == "ban:search":
        u.mode = "awaiting_font_search"
        try:
            await q.edit_message_caption(
                caption="🔍 Typography Search\n\n💡 Enter search keywords:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(" 🔙 Return", callback_data="menu:banner")
                ]]),
            )
        except Exception:
            await q.edit_message_text(
                "🔍 Typography Search\n\n💡 Enter search keywords:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(" 🔙 Return", callback_data="menu:banner")
                ]]),
            )
        return

    if data.startswith("ban:setfont:"):
        font = data.split(":", 2)[2]
        u.banner_font = font
        try:
            await q.edit_message_caption(
                caption=f"✅ Typography set to: `{font}`\n\n💬 Now send your text to generate the banner.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=banner_menu_kb(u),
            )
        except Exception:
            await q.edit_message_text(
                f"✅ Typography set to: `{font}`\n\n💬 Now send your text to generate the banner.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=banner_menu_kb(u),
            )
        return

    if data.startswith("ban:w:"):
        op = data.split(":", 2)[2]
        if op == "show":
            try:
                await q.edit_message_caption(
                    caption=f"↔️ Banner Width Dimension\n\n📌 Current Width: `{u.banner_width}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=width_control_kb(u),
                )
            except Exception:
                await q.edit_message_text(
                    f"↔️ Banner Width Dimension\n\n📌 Current Width: `{u.banner_width}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=width_control_kb(u),
                )
            return
        if op == "type":
            u.mode = "awaiting_banner_width"
            try:
                await q.edit_message_caption(
                    caption=f"✍️ Type your precise banner width dimension ({MIN_BANNER_WIDTH}–{MAX_BANNER_WIDTH}):",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(" 🔙 Return", callback_data="menu:banner")
                    ]]),
                )
            except Exception:
                await q.edit_message_text(
                    f"✍️ Type your precise banner width dimension ({MIN_BANNER_WIDTH}–{MAX_BANNER_WIDTH}):",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(" 🔙 Return", callback_data="menu:banner")
                    ]]),
                )
            return
        if op.startswith("+"):
            u.banner_width = min(MAX_BANNER_WIDTH, u.banner_width + int(op[1:]))
        elif op.startswith("-"):
            u.banner_width = max(MIN_BANNER_WIDTH, u.banner_width - int(op[1:]))
        
        await q.edit_message_reply_markup(reply_markup=width_control_kb(u))
        return

    if data.startswith("ban:s:"):
        val = data.split(":", 2)[2]
        if val == "show":
            row = [InlineKeyboardButton(_mark(u.banner_scale == s, f"{s}x"), callback_data=f"ban:s:{s}") for s in range(MIN_SCALE, MAX_SCALE + 1)]
            try:
                await q.edit_message_caption(
                    caption=f"🔍 Banner Scale Factor\n\n📌 Current Scale: `{u.banner_scale}x`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([row, [InlineKeyboardButton(" 🔙 Return", callback_data="menu:banner")]]),
                )
            except Exception:
                await q.edit_message_text(
                    f"🔍 Banner Scale Factor\n\n📌 Current Scale: `{u.banner_scale}x`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([row, [InlineKeyboardButton(" 🔙 Return", callback_data="menu:banner")]]),
                )
            return
        u.banner_scale = max(MIN_SCALE, min(MAX_SCALE, int(val)))
        row = [InlineKeyboardButton(_mark(u.banner_scale == s, f"{s}x"), callback_data=f"ban:s:{s}") for s in range(MIN_SCALE, MAX_SCALE + 1)]
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([row, [InlineKeyboardButton("🔙 Return", callback_data="menu:banner")]]))
        return

    if data.startswith("fmt:"):
        u.fmt = data.split(":", 1)[1]
        await q.edit_message_reply_markup(reply_markup=format_kb(u))
        return


# ===========================================================================
#  TEXT HANDLER
# ===========================================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or not msg.text:
        return
    user = update.effective_user
    track_user(user)
    u = get_user(user.id)
    text = msg.text.strip()

    if text.endswith("ADMIN PANEL"):
        user_uname = user.username or ""
        # Strictly verify Admin ID & Username
        if user.id != ADMIN_ID or user_uname.lower() != ADMIN_USERNAME.lower():
            await msg.reply_text("⚠️ *Access Denied!* Aapke paas Admin Panel ka access nahi hai.", parse_mode=ParseMode.MARKDOWN)
            return

        genz_caption = (
            "🚨 *YO BOSS, ADMIN HQ MEIN WELCOME HAI!* 👑\n\n"
            "Yahan se aap Poore Bot Ka Empire Control Kar Sakte Ho. "
            "Sare Users Ka Activity Data Dekhna Ho Ya Sabhi Ko Ek Saath Mass Broadcast "
            "Drop Karna Ho, Aape Master Controls Live Hain! 🔥\n\n"
            "✨ *Choose Your Power Option Below:* 👇"
        )
        try:
            await msg.reply_photo(
                photo=ADMIN_PANEL_PHOTO,
                caption=genz_caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=admin_inline_kb()
            )
        except Exception as exc:
            log.warning("Admin panel photo send failed: %s", exc)
            await msg.reply_text(
                genz_caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=admin_inline_kb()
            )
        return

    if text.endswith("FF Free Likes"):
        await msg.reply_photo(
            photo="https://files.catbox.moe/g0oe0j.png",
            caption=(
                "⚡ Free Fire Likes Portal 🚀\n\n"
                "🔥 Boost your reputation instantly below:\n\n"
                "🔗 https://t.me/FreeFire20Likes\n\n"
                "👑 7X SNIPER • @TENZOOGAMER"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    elif text.endswith("FF Hologram"):
        await msg.reply_photo(
            photo="https://files.catbox.moe/vu2m6d.png",
            caption=(
                "🎨 Free Fire Hologram Collection ✨\n\n"
                "💎 Experience holographic assets.\n\n"
                "🔗 Direct Portal: https://t.me/snpdaksh\n\n"
                "👑 7X SNIPER • @TENZOOGAMER"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if text.startswith("/"):
        return

    if u.mode == "awaiting_broadcast_msg":
        if user.id != ADMIN_ID:
            return
        u.broadcast_pending_msg = text
        u.mode = "awaiting_broadcast_confirm"
        await msg.reply_text(
            f"📥 *BROADCAST MESSAGE RECEIVED!*\n\n"
            f"*Preview Your Message:* \n---\n{text}\n---\n\n"
            f"⚠️ *Final Confirmation:* Kya aap yeh message sabhi bot users ko bhejna chahte hain?\n\n"
            f"👉 Confirm karne ke liye `/confirm` likhein.\n"
            f"❌ Cancel karne ke liye `/cancel` likhein.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if u.mode == "awaiting_banner_width":
        if not text.isdigit():
            await msg.reply_text(f"⚠️ Please provide a valid numeric dimension ({MIN_BANNER_WIDTH}–{MAX_BANNER_WIDTH}).")
            return
        u.banner_width = max(MIN_BANNER_WIDTH, min(MAX_BANNER_WIDTH, int(text)))
        u.mode = "awaiting_banner_text"
        await msg.reply_text(f"✅ Width dimension configured: `{u.banner_width}`\n\n💬 Now send your text!", parse_mode=ParseMode.MARKDOWN)
        return

    if u.mode == "awaiting_font_search":
        matches = find_fonts(text)
        if not matches:
            await msg.reply_text(f"❌ No typography style matched `{text}`.", parse_mode=ParseMode.MARKDOWN)
            return
        u.mode = "idle"
        await msg.reply_text(
            f"🔍 `{text}` → {len(matches)} styles located:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=font_list_kb(0, query=text),
        )
        return

    if not HAS_FIGLET:
        await msg.reply_text("❌ pyfiglet module is missing.", parse_mode=ParseMode.MARKDOWN)
        return
    await _send_banner(msg, u, text)


async def _send_banner(msg, u: UserState, text: str) -> None:
    status = await msg.reply_text(
        f"⏳ Crafting your banner…\n\n  🔤 Font   : `{u.banner_font}`\n  ↔️ Width  : `{u.banner_width}`",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        banner = render_banner(text, u.banner_font, u.banner_width, u.banner_scale)

        if u.fmt == "txt":
            await msg.reply_document(
                document=io.BytesIO(banner.encode("utf-8")),
                filename=f"banner_{u.banner_font}.txt",
                caption=f"🔤 Typography Font: `{u.banner_font}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            grid = banner_to_grid(banner)
            c1 = resolve_color(u.banner_color)
            grid = _apply_color_mode(grid, "mono", c1, c1, "vertical")
            file_bytes, filename, _ = _export_grid(grid, u.fmt)
            await msg.reply_document(
                document=io.BytesIO(file_bytes),
                filename=f"banner_{u.banner_font}.{u.fmt}",
                caption=f"🔤 Typography Font: `{u.banner_font}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        if len(banner) <= MAX_PREVIEW:
            await msg.reply_text(f"<pre>{html.escape(banner)}</pre>", parse_mode=ParseMode.HTML)
        else:
            await msg.reply_text(f"<pre>{html.escape(banner[:MAX_PREVIEW])}</pre>\n…(truncated)", parse_mode=ParseMode.HTML)
        await status.delete()
    except Exception as exc:
        log.exception("Banner render failed")
        try:
            await status.edit_text(f"❌ Error encountered: `{exc}`", parse_mode=ParseMode.MARKDOWN)
        except TelegramError:
            pass


# ===========================================================================
#  ENTRY POINT
# ===========================================================================

async def main() -> None:
    if not BOT_TOKEN:
        print("\n[ERROR] ❌ BOT_TOKEN Environment Variable nahi mila.\n")
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("banner", cmd_banner))
    app.add_handler(CommandHandler("fonts", cmd_fonts))
    app.add_handler(CommandHandler("font", cmd_font))
    app.add_handler(CommandHandler("color", cmd_color))
    app.add_handler(CommandHandler("width", cmd_width))
    app.add_handler(CommandHandler("scale", cmd_scale))
    app.add_handler(CommandHandler("format", cmd_format))
    app.add_handler(CommandHandler("confirm", cmd_confirm))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("BOT running. Press Ctrl+C to stop.")
    
    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nBot stopped.\n")
