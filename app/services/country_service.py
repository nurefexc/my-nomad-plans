import time
import os
from urllib.parse import quote

import requests
from .cache_utils import FileCache


class CountryService:
    """Service wrapper for REST Countries metadata lookups."""

    BASE_URL = "https://restcountries.com/v3.1/name/"
    TIMEOUT_SECONDS = 5.0
    CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
    _cache_instance = FileCache(os.path.join("app", "cache", "countries"), CACHE_TTL_SECONDS)
    _regional_cache_instance = FileCache(os.path.join("app", "cache", "regional"), CACHE_TTL_SECONDS)
    
    _regional_fallback: dict[str, set[str]] = {
        "africa": {
            "Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde", "Cameroon",
            "Central African Republic", "Chad", "Comoros", "Congo", "Congo, Democratic Republic of the",
            "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon", "Gambia",
            "Ghana", "Guinea", "Guinea-Bissau", "Ivory Coast", "Kenya", "Lesotho", "Liberia", "Libya",
            "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia",
            "Niger", "Nigeria", "Rwanda", "Sao Tome and Principe", "Senegal", "Seychelles", "Sierra Leone",
            "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda",
            "Zambia", "Zimbabwe",
        },
        "asia": {
            "Afghanistan", "Armenia", "Azerbaijan", "Bahrain", "Bangladesh", "Bhutan", "Brunei", "Cambodia",
            "China", "Cyprus", "Georgia", "India", "Indonesia", "Iran", "Iraq", "Israel", "Japan", "Jordan",
            "Kazakhstan", "Kuwait", "Kyrgyzstan", "Laos", "Lebanon", "Malaysia", "Maldives", "Mongolia",
            "Myanmar", "Nepal", "North Korea", "Oman", "Pakistan", "Palestine", "Philippines", "Qatar",
            "Saudi Arabia", "Singapore", "South Korea", "Sri Lanka", "Syria", "Taiwan", "Tajikistan",
            "Thailand", "Timor-Leste", "Turkey", "Turkmenistan", "United Arab Emirates", "Uzbekistan",
            "Vietnam", "Yemen",
        },
        "americas": {
            "Antigua and Barbuda", "Argentina", "Bahamas", "Barbados", "Belize", "Bolivia", "Brazil", "Canada",
            "Chile", "Colombia", "Costa Rica", "Cuba", "Dominica", "Dominican Republic", "Ecuador", "El Salvador",
            "Grenada", "Guatemala", "Guyana", "Haiti", "Honduras", "Jamaica", "Mexico", "Nicaragua", "Panama",
            "Paraguay", "Peru", "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines",
            "Suriname", "Trinidad and Tobago", "United States", "Uruguay", "Venezuela",
        },
        "oceania": {
            "Australia", "Fiji", "Kiribati", "Marshall Islands", "Micronesia", "Nauru", "New Zealand", "Palau",
            "Papua New Guinea", "Samoa", "Solomon Islands", "Tonga", "Tuvalu", "Vanuatu",
        },
    }

    @classmethod
    def _get_cached_metadata(cls, cache_key: str) -> dict[str, str] | None:
        return cls._cache_instance.get(cache_key)

    @classmethod
    def _set_cached_metadata(cls, cache_key: str, payload: dict[str, str]) -> None:
        cls._cache_instance.set(cache_key, payload)

    @staticmethod
    def _build_dial_code(raw_idd: dict[str, object]) -> str:
        root = str(raw_idd.get("root") or "")
        suffixes = raw_idd.get("suffixes") or []
        if isinstance(suffixes, list) and suffixes:
            return f"{root}{suffixes[0] or ''}".strip()
        return root.strip()

    @staticmethod
    def _extract_currency_name(currencies: object, currency_code: str) -> str:
        if not isinstance(currencies, dict) or not currency_code:
            return ""
        details = currencies.get(currency_code)
        if isinstance(details, dict):
            return str(details.get("name") or "").strip()
        return ""

    @staticmethod
    def _extract_primary_language(languages: object) -> str:
        if not isinstance(languages, dict) or not languages:
            return ""
        return str(next(iter(languages.values()), "") or "").strip()

    @classmethod
    def get_country_metadata(cls, country_name: str) -> dict[str, str] | None:
        """Return minimal country metadata and gracefully fallback to None on errors."""
        normalized = (country_name or "").strip()
        if not normalized:
            return None

        cache_key = normalized.casefold()
        cached = cls._get_cached_metadata(cache_key)
        if cached is not None:
            return cached

        url = f"{cls.BASE_URL}{quote(normalized)}"
        params = {"fullText": "true"}

        try:
            response = requests.get(url, params=params, timeout=cls.TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                return None

            data = payload[0]
            currencies = data.get("currencies", {})
            currency_code = next(iter(currencies.keys()), "") if isinstance(currencies, dict) else ""
            currency_name = cls._extract_currency_name(currencies, currency_code)
            spoken_language = cls._extract_primary_language(data.get("languages", {}))

            idd = data.get("idd", {})
            dial_code = cls._build_dial_code(idd if isinstance(idd, dict) else {})

            result = {
                "flag_svg": str(data.get("flags", {}).get("svg") or ""),
                "currency_code": str(currency_code or ""),
                "currency_name": currency_name,
                "spoken_language": spoken_language,
                "dial_code": dial_code,
                "iso_code": str(data.get("cca2") or ""),
                "capital": str(data.get("capital", [""])[0] if data.get("capital") else ""),
                "region": str(data.get("region") or ""),
                "subregion": str(data.get("subregion") or ""),
                "population": int(data.get("population") or 0),
                "timezone": str(data.get("timezones", [""])[0] if data.get("timezones") else ""),
            }
            cls._set_cached_metadata(cache_key, result)
            return result
        except (requests.RequestException, IndexError, KeyError, TypeError, ValueError):
            return None

    @classmethod
    def get_regional_countries(cls) -> dict[str, set[str]]:
        """Return regional country sets with API fetch + file-based cache."""
        cached = cls._regional_cache_instance.get("all_regions")
        if cached:
            # Sets are stored as lists in JSON
            return {r: set(countries) for r, countries in cached.items()}

        try:
            response = requests.get(
                "https://restcountries.com/v3.1/all?fields=name,region",
                timeout=cls.TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()

            regional: dict[str, set[str]] = {
                "africa": set(),
                "asia": set(),
                "americas": set(),
                "oceania": set(),
            }
            for country in data:
                name = country.get("name", {}).get("common")
                region = str(country.get("region", "")).lower()
                if name and region in regional:
                    regional[region].add(name)

            # Convert sets to lists for JSON serialization
            serializable_regional = {r: list(countries) for r, countries in regional.items()}
            cls._regional_cache_instance.set("all_regions", serializable_regional)
            return regional
        except (requests.RequestException, TypeError, ValueError, KeyError):
            return cls._regional_fallback

