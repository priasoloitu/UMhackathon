"""
Weather agent — tries OpenWeatherMap free tier, falls back to simulated data.
"""

import requests
from config import OWM_API_KEY, DEFAULT_LOCATION


def get_weather(date: str, location: str = None) -> dict:
    """
    Fetch weather for a given date and location.
    Falls back to simulated data if OWM_API_KEY is missing or the call fails.
    """
    location = location or DEFAULT_LOCATION

    if OWM_API_KEY:
        try:
            return _fetch_owm(date, location)
        except Exception:
            pass  # fall through to simulated

    return _simulated(date, location)


def _fetch_owm(date: str, location: str) -> dict:
    """Call OpenWeatherMap 5-day forecast API (free tier)."""
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": location,
        "appid": OWM_API_KEY,
        "units": "metric",
        "cnt": 40,
    }
    resp = requests.get(url, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    # Find the forecast closest to noon on target date
    best = None
    for item in data.get("list", []):
        if item["dt_txt"].startswith(date):
            best = item
            if "12:00" in item["dt_txt"]:
                break

    if not best:
        return _simulated(date, location)

    rain_prob  = best.get("pop", 0.1)
    temp       = best["main"]["temp"]
    desc       = best["weather"][0]["description"].capitalize()
    suitable   = rain_prob < 0.5 and temp < 37

    return {
        "summary": f"{desc} in {location} on {date}. Rain chance {int(rain_prob*100)}%.",
        "suitable_outdoor": suitable,
        "temperature_c": round(temp, 1),
        "rain_probability": round(rain_prob, 2),
        "source": "openweathermap",
    }


def _simulated(date: str, location: str) -> dict:
    import hashlib
    # Use deterministic hash of the date string so same date = same weather
    h = int(hashlib.md5(date.encode('utf-8')).hexdigest(), 16)
    
    conditions = [
        ("Sunny", 34, 0.05),
        ("Partly cloudy", 31, 0.15),
        ("Overcast", 29, 0.30),
        ("Light rain", 27, 0.60),
        ("Heavy rain", 26, 0.90)
    ]
    
    idx = h % len(conditions)
    desc, temp, rain_prob = conditions[idx]
    
    return {
        "summary": f"{desc} in {location} on {date}. Rain chance {int(rain_prob*100)}%.",
        "suitable_outdoor": rain_prob < 0.5,
        "temperature_c": temp,
        "rain_probability": rain_prob,
        "source": "simulated",
    }
