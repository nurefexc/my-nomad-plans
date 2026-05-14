"""Service layer package for external integrations."""

from dataclasses import dataclass

from .country_service import CountryService
from .image_service import ImageService
from .immich_service import ImmichService
from .weather_service import WeatherService


@dataclass(frozen=True)
class ServiceRegistry:
    weather: WeatherService
    countries: CountryService
    images: ImageService


def build_service_registry() -> ServiceRegistry:
    """Factory to keep service wiring in one place."""
    return ServiceRegistry(
        weather=WeatherService(),
        countries=CountryService(),
        images=ImageService(),
    )


services = build_service_registry()

__all__ = [
    "CountryService",
    "ImageService",
    "ImmichService",
    "WeatherService",
    "ServiceRegistry",
    "build_service_registry",
    "services",
]
