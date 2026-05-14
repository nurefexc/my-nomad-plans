import hashlib
import time
import os
from urllib.parse import quote
from .cache_utils import FileCache


class ImageService:
    """Generates Unsplash Source URLs with file-based caching."""

    CACHE_TTL_SECONDS = 24 * 60 * 60  # 1 day cache for URLs
    _cache_instance = FileCache(os.path.join("app", "cache", "images"), CACHE_TTL_SECONDS)

    @classmethod
    def _get_from_cache(cls, key: str) -> str:
        return cls._cache_instance.get(key)

    @classmethod
    def _set_to_cache(cls, key: str, url: str) -> str:
        cls._cache_instance.set(key, url)
        return url

    @classmethod
    def generate_cover_image_url(cls, location_name: str, resolution: str = "1200x400") -> str:
        """Build a deterministic cover image URL for trip headers."""
        # Use a new cache key version to force refresh if needed
        cache_key = f"img_v6_{location_name}_{resolution}"
        cached = cls._get_from_cache(cache_key)
        if cached:
            return cached

        if not (location_name or "").strip():
            url = f"https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&q=80&w=1000"
            return cls._set_to_cache(cache_key, url)

        # Better query construction
        # Split by comma and take the first part (usually city) as primary, country as secondary
        parts = [p.strip() for p in location_name.split(',')]
        primary = parts[0] if parts else ""
        secondary = parts[1] if len(parts) > 1 else ""
        
        # We prioritize the city/primary location heavily
        # Instead of just appending keywords, we use a search-like query
        # Using images.unsplash.com/photos matches more directly than 'featured'
        query_parts = []
        if primary:
            query_parts.append(primary)
        if secondary:
            query_parts.append(secondary)
        
        # Focus query: "Paris, France landmark" instead of "Paris, France, travel, landscape"
        # We try to use a very specific tag for Unsplash
        # We use '+' for spaces to keep it as a single search term for Source API
        search_term = f"{primary} {secondary}".strip()
        focus_query = quote(search_term).replace("%20", "+")
        
        # Consistent seed for the location
        seed = hashlib.sha1(location_name.lower().encode("utf-8")).hexdigest()[:8]
        
        # Unsplash Source with search terms separated by commas works as a set of tags.
        # But putting the location as the FIRST and MOST SPECIFIC term is key.
        # We add 'cityscape' and 'architecture' which are often more relevant for trips than 'landscape'
        url = f"https://source.unsplash.com/featured/?{focus_query},cityscape,architecture&sig={seed}"
        return cls._set_to_cache(cache_key, url)

    @classmethod
    def generate_fallback_cover_image_url(cls, location_name: str, resolution: str = "1200x400") -> str:
        """Build a deterministic picsum fallback URL for resilient cover rendering."""
        cache_key = f"picsum_{location_name}_{resolution}"
        cached = cls._get_from_cache(cache_key)
        if cached:
            return cached

        clean_resolution = (resolution or "1200x400").lower()
        if "x" in clean_resolution:
            parts = clean_resolution.split("x", 1)
            width, height = parts[0], parts[1] if len(parts) > 1 else parts[0]
        else:
            width, height = "1200", "400"

        width = "".join(ch for ch in width if ch.isdigit()) or "1200"
        height = "".join(ch for ch in height if ch.isdigit()) or "400"

        seed_source = (location_name or "nomad-travel").strip().lower() or "nomad-travel"
        seed = hashlib.sha1(seed_source.encode("utf-8")).hexdigest()[:16]
        url = f"https://picsum.photos/seed/{seed}/{width}/{height}"
        return cls._set_to_cache(cache_key, url)

