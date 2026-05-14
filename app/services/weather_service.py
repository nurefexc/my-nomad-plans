import time
import os
import requests
from .cache_utils import FileCache


class WeatherService:
    """Service wrapper for Open-Meteo weather lookups with caching."""

    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    TIMEOUT_SECONDS = 3.0
    CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
    _cache_instance = FileCache(os.path.join("app", "cache", "weather"), CACHE_TTL_SECONDS)

    @classmethod
    def get_current_weather(cls, lat: float, lon: float) -> dict:
        """Fetch current weather for coordinates and return None on failure. Includes caching."""
        if lat is None or lon is None:
            return None
            
        try:
            cache_key = f"{round(float(lat), 4)}_{round(float(lon), 4)}"
        except (TypeError, ValueError):
            return None
        
        cached = cls._cache_instance.get(cache_key)
        if cached:
            return cached

        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": True,
        }
        try:
            response = requests.get(cls.BASE_URL, params=params, timeout=cls.TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            current = data.get("current_weather")
            if isinstance(current, dict):
                cls._cache_instance.set(cache_key, current)
                return current
            return None
        except (requests.RequestException, ValueError, TypeError):
            return None

