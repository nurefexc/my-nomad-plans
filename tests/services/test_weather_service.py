import unittest
from unittest.mock import Mock, patch

import requests

from app.services.weather_service import WeatherService


class WeatherServiceTests(unittest.TestCase):
    @patch("app.services.weather_service.requests.get")
    def test_get_current_weather_returns_payload(self, mock_get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "current_weather": {"temperature": 16.2, "weathercode": 1}
        }
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        result = WeatherService.get_current_weather(47.4979, 19.0402)

        self.assertEqual(result, {"temperature": 16.2, "weathercode": 1})
        mock_get.assert_called_once_with(
            WeatherService.BASE_URL,
            params={"latitude": 47.4979, "longitude": 19.0402, "current_weather": True},
            timeout=WeatherService.TIMEOUT_SECONDS,
        )

    @patch("app.services.weather_service.requests.get", side_effect=requests.RequestException)
    def test_get_current_weather_returns_none_on_request_error(self, _: Mock) -> None:
        result = WeatherService.get_current_weather(47.0, 19.0)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

