"""Конфигурация приложения. Все значения берутся из переменных окружения (.env)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# backend/ корень
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ── AI ────────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("MODEL", "claude-sonnet-4-6")
MODEL_FAST = os.getenv("MODEL_FAST", "claude-haiku-4-5-20251001")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "16000"))

# ── Медиа ───────────────────────────────────────────────────────────────────
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")

# ── Авторизация (Этап 1 — один общий пароль; настоящая авторизация в Этапе 2) ──
APP_PASSWORD = os.getenv("APP_PASSWORD", "remtechnika")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "168"))  # 7 дней

# ── Хранилище ─────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "app.db")))
FILES_DIR = Path(os.getenv("FILES_DIR", str(DATA_DIR / "files")))

DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

# ── Генерация документов ──────────────────────────────────────────────────────
# Путь к TTF-шрифту с кириллицей для PDF (Win: Arial, Linux: DejaVuSans).
_default_font = (
    "C:/Windows/Fonts/arial.ttf" if sys.platform == "win32"
    else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)
PDF_FONT_PATH = os.getenv("PDF_FONT_PATH", _default_font)
# Необязательный логотип (PNG) для колонтитулов документов
LOGO_PATH = os.getenv("LOGO_PATH", "")

# ── Сервер ────────────────────────────────────────────────────────────────────
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
