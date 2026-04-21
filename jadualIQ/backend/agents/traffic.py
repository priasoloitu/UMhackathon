"""
Traffic agent — tries Google Maps Distance Matrix API, falls back to simulated data.
"""

import requests
from config import GOOGLE_MAPS_KEY, DEFAULT_LOCATION

PEAK_WINDOWS = ["07:00", "08:00", "17:00", "18:00", "19:00"]


def get_traffic(origin: str, destination: str, departure_time: str) -> dict:
    """
    Estimate travel time between origin and destination.
    Falls back to simulated data if GOOGLE_MAPS_KEY is missing or call fails.
    """
    origin      = origin      or DEFAULT_LOCATION
    destination = destination or DEFAULT_LOCATION

    if GOOGLE_MAPS_KEY:
        try:
            return _fetch_gmaps(origin, destination, departure_time)
        except Exception:
            pass

    return _simulated(origin, destination, departure_time)


def _fetch_gmaps(origin: str, destination: str, departure_time: str) -> dict:
    """Call Google Maps Distance Matrix API."""
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins":      origin,
        "destinations": destination,
        "departure_time": "now",
        "traffic_model":  "best_guess",
        "key": GOOGLE_MAPS_KEY,
    }
    resp = requests.get(url, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    element = data["rows"][0]["elements"][0]
    if element["status"] != "OK":
        return _simulated(origin, destination, departure_time)

    duration_sec = element.get("duration_in_traffic", element["duration"])["value"]
    minutes = round(duration_sec / 60)
    is_peak = _is_peak(departure_time)

    return {
        "summary": (
            f"{'Heavy' if is_peak else 'Moderate'} traffic from {origin} to {destination}"
            f" at {departure_time}. ~{minutes} min travel time."
        ),
        "travel_minutes": minutes,
        "peak_hour_warning": is_peak,
        "source": "google_maps",
    }


def _simulated(origin: str, destination: str, departure_time: str) -> dict:
    is_peak = _is_peak(departure_time)
    minutes = 40 if is_peak else 25
    return {
        "summary": (
            f"{'Heavy' if is_peak else 'Moderate'} traffic from {origin} to {destination}"
            f" at {departure_time}. ~{minutes} min travel time."
        ),
        "travel_minutes": minutes,
        "peak_hour_warning": is_peak,
        "source": "simulated",
    }


def _is_peak(time_str: str) -> bool:
    if not time_str:
        return False
    hour = time_str[:5]
    return any(hour.startswith(p[:2]) for p in PEAK_WINDOWS)
