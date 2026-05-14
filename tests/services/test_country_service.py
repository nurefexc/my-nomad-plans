import unittest
from unittest.mock import Mock, patch

import requests

from app.services.country_service import CountryService


class CountryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        CountryService._metadata_cache.clear()
        CountryService._regional_cache = None

    @patch("app.services.country_service.requests.get")
    def test_get_country_metadata_returns_normalized_fields(self, mock_get: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {
                "flags": {"svg": "https://flagcdn.example/hu.svg"},
                "currencies": {"HUF": {"name": "Hungarian forint"}},
                "languages": {"hun": "Hungarian"},
                "idd": {"root": "+3", "suffixes": ["6"]},
                "cca2": "HU",
            }
        ]
        mock_get.return_value = response

        result = CountryService.get_country_metadata("Hungary")

        self.assertEqual(
            result,
            {
                "flag_svg": "https://flagcdn.example/hu.svg",
                "currency_code": "HUF",
                "currency_name": "Hungarian forint",
                "spoken_language": "Hungarian",
                "dial_code": "+36",
                "iso_code": "HU",
            },
        )

    @patch("app.services.country_service.requests.get", side_effect=requests.RequestException)
    def test_get_country_metadata_returns_none_on_error(self, _: Mock) -> None:
        result = CountryService.get_country_metadata("Hungary")
        self.assertIsNone(result)

    @patch("app.services.country_service.requests.get")
    def test_get_country_metadata_uses_cache(self, mock_get: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [{"flags": {}, "currencies": {}, "idd": {}, "cca2": ""}]
        mock_get.return_value = response

        CountryService.get_country_metadata("Hungary")
        CountryService.get_country_metadata("Hungary")

        self.assertEqual(mock_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()

