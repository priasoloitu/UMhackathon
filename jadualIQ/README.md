# JadualIQ 🗓️

**JadualIQ** is an AI-powered smart scheduling assistant built for UMHackathon 2026. It uses a multi-agent agentic pipeline to help users intelligently plan their week — factoring in weather, traffic, lifestyle restrictions, and real-time conflict detection.

---

## 🚀 Features

- **Conversational Scheduling** — Chat naturally to add events ("Schedule a meeting next Monday at 3pm")
- **Multi-Agent AI Pipeline** — Intake, Clarification, Conflict, and Logistics agents powered by Z.AI (GLM-4-Flash)
- **Weather & Traffic Context** — Integrates OpenWeatherMap and Google Maps to suggest optimal transport modes and estimate RM savings
- **Smart Conflict Resolution** — Detects overlapping calendar events and uses AI to decide which task to keep and which to reschedule
- **Lifestyle Restrictions** — Block entire days, time ranges, or add custom rules (e.g. "No meetings after 8pm")
- **Weekly Impact Dashboard** — Tracks hours saved and RM saved from AI-driven transport recommendations
- **Graceful Degradation** — Falls back to deterministic mock responses if the AI API is unavailable, ensuring demo stability

---

## 🏗️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML, CSS, JavaScript |
| Backend | Python 3.11, Flask 3.0 |
| Database | SQLite3 (3NF normalized) |
| AI Model | Z.AI ilmu-glm-5.1 |
| Weather API | OpenWeatherMap (free tier) |
| Traffic API | Google Maps Distance Matrix |

---

## 📁 Project Structure

```
jadualIQ/
├── backend/
│   ├── app.py               # Flask application entry point
│   ├── config.py            # Environment variable loader
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Environment variable template
│   ├── agents/
│   │   ├── orchestrator.py  # Core multi-agent pipeline
│   │   ├── guardrail.py     # Input filtering agent
│   │   ├── weather.py       # Weather context agent
│   │   └── traffic.py       # Traffic context agent
│   ├── models/
│   │   └── schedule_store.py # All database logic (CRUD + analytics)
│   └── routes/
│       ├── auth.py          # Register / Login / Logout
│       ├── chat.py          # POST /api/chat
│       ├── schedule.py      # CRUD /api/schedule
│       ├── restrictions.py  # CRUD /api/restrictions
│       ├── impact.py        # GET /api/impact
│       └── conflict.py      # POST /api/conflicts/resolve
└── frontend/
    ├── index.html           # Main app shell
    ├── login.html           # Auth page
    ├── src/
    │   ├── main.js          # App bootstrap
    │   ├── auth.js          # Auth logic
    │   ├── chat.js          # AI chat interface
    │   ├── calendar.js      # Calendar grid rendering
    │   ├── impact.js        # Dashboard analytics
    │   └── restrictions.js  # Restrictions panel
    └── styles/
        └── calendar.css     # All styles
```

---

## ⚙️ Setup & Running Locally

### Prerequisites
- Python 3.11+
- A [Z.AI API Key](https://open.bigmodel.cn) (GLM-4-Flash)

### 1. Clone the repository
```bash
git clone https://github.com/your-username/jadualIQ.git
cd jadualIQ
```

### 2. Install dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure environment variables
```bash
cp .env.example .env
# Edit .env and fill in your ZAI_API_KEY
```

### 4. Run the server
```bash
python app.py
```

### 5. Open the app
Navigate to [http://localhost:5000](http://localhost:5000) in your browser.

---

## 🔑 Environment Variables

See [`backend/.env.example`](backend/.env.example) for the full list. The only **required** key is:

| Variable | Description |
|----------|-------------|
| `ZAI_API_KEY` | Your Z.AI API key for GLM-4-Flash |

Optional keys (system falls back to simulated data if missing):

| Variable | Description |
|----------|-------------|
| `OWM_API_KEY` | OpenWeatherMap API key |
| `GOOGLE_MAPS_KEY` | Google Maps Distance Matrix API key |

---

## 🤖 AI Pipeline

```
User Message
    ↓
Intake Agent (Z.AI)         — Guardrail, Intent Extraction, Priority Scoring
    ↓
Context Aggregation         — Weather + Traffic + Calendar Conflicts + Restrictions
    ↓
GLM Logistics Agent (Z.AI)  — Schedules task, suggests transport, estimates RM saved
    ↓
Response Parser             — Sanitizes JSON, handles LLM quirks
    ↓
Frontend                    — Renders suggestion card with "Add to Calendar"
```

---

## 👥 Team

Built for **UMHackathon 2026** — Track: Agentic AI Systems.
