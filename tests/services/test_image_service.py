import unittest

from app.services.image_service import ImageService


class ImageServiceTests(unittest.TestCase):
    def test_generate_cover_image_url_for_location(self) -> None:
        result = ImageService.generate_cover_image_url("Budapest Hungary")
        self.assertEqual(
            result,
            "https://source.unsplash.com/featured/1200x400/?Budapest%20Hungary,city,landmark",
        )

    def test_generate_cover_image_url_uses_random_fallback(self) -> None:
        result = ImageService.generate_cover_image_url("")
        self.assertEqual(
            result,
            "https://source.unsplash.com/random/1200x400/?travel,landscape",
        )

    def test_generate_fallback_cover_image_url_is_deterministic(self) -> None:
        first = ImageService.generate_fallback_cover_image_url("Budapest Hungary")
        second = ImageService.generate_fallback_cover_image_url("Budapest Hungary")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("https://picsum.photos/seed/"))


if __name__ == "__main__":
    unittest.main()

