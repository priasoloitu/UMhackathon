"""
Traffic agent — tries Google Maps Distance Matrix API, falls back to simulated data.
"""

import time
import requests
from datetime import datetime, date as date_type
from config import GOOGLE_MAPS_KEY, DEFAULT_LOCATION

PEAK_WINDOWS = ["07:00", "08:00", "17:00", "18:00", "19:00"]


def _departure_time_epoch(time_str: str) -> int:
    """Convert 'HH:MM' for today into a Unix epoch for Google Maps API.
    Falls back to current epoch if parsing fails.
    """
    try:
        today = date_type.today()
        h, m = map(int, time_str.split(':'))
        dt = datetime(today.year, today.month, today.day, h, m)
        epoch = int(dt.timestamp())
        # If the time is already in the past today, use now+60s
        if epoch < int(time.time()):
            epoch = int(time.time()) + 60
        return epoch
    except Exception:
        return int(time.time())


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
        "departure_time": _departure_time_epoch(departure_time),
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
    
    if is_peak:
        minutes = 45
        desc = "Heavy"
    else:
        minutes = 20
        desc = "Light to moderate"

    return {
        "summary": (
            f"{desc} traffic from {origin} to {destination}"
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
