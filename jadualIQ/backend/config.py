import os
from dotenv import load_dotenv

load_dotenv()

# ─── Z.AI / GLM Settings ────────────────────────────────────────────────────
ZAI_BASE_URL = os.getenv("ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").strip('"').strip()
ZAI_MODEL    = os.getenv("ZAI_MODEL", "glm-4-flash")
ZAI_API_KEY  = os.getenv("ZAI_API_KEY", "")

# ─── Database ────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
if not os.access(BASE_DIR, os.W_OK):
    DB_PATH = "/tmp/jadualiq.db"
else:
    DB_PATH = os.path.join(BASE_DIR, "jadualiq.db")

# ─── Weather (OpenWeatherMap free tier) ──────────────────────────────────────
OWM_API_KEY      = os.getenv("OWM_API_KEY", "")
DEFAULT_LOCATION = os.getenv("DEFAULT_LOCATION", "Kuala Lumpur")

# ─── Traffic (Google Maps Platform) ──────────────────────────────────────────
GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_KEY", "")

# ─── Flask ───────────────────────────────────────────────────────────────────
SECRET_KEY  = os.getenv("SECRET_KEY", "jadualiq-hackathon-secret-2026")
DEBUG       = os.getenv("FLASK_DEBUG", "true").lower() == "true"
