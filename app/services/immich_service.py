import time
from typing import Dict, Iterable, Optional, Tuple

import requests


class ImmichError(Exception):
    pass


class ImmichNotConfigured(ImmichError):
    pass


class ImmichUnavailable(ImmichError):
    pass


class ImmichNotFound(ImmichError):
    pass


class ImmichService:
    """Handles all outbound calls to Immich and keeps auth server-side only."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 10, retries: int = 2):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries

        if not self.base_url or not self.api_key:
            raise ImmichNotConfigured("Immich base URL or API key is missing")

    @classmethod
    def from_user(cls, user, timeout: int = 10, retries: int = 2):
        return cls(
            base_url=getattr(user, "immich_base_url", None),
            api_key=getattr(user, "immich_api_key", None),
            timeout=timeout,
            retries=retries,
        )

    def _headers(self) -> Dict[str, str]:
        return {"x-api-key": self.api_key}

    def _request(self, method: str, path: str, allow_not_found: bool = False, **kwargs):
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("headers", self._headers())

        last_exc = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.request(method, url, **kwargs)
                if response.status_code == 404 and allow_not_found:
                    return response
                if response.status_code == 404:
                    raise ImmichNotFound("Immich resource not found")
                if response.status_code >= 500:
                    raise ImmichUnavailable(f"Immich server error: {response.status_code}")
                if response.status_code >= 400:
                    raise ImmichError(f"Immich request failed: {response.status_code}")
                return response
            except (requests.RequestException, ImmichUnavailable) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                break

        if isinstance(last_exc, ImmichError):
            raise last_exc
        raise ImmichUnavailable(str(last_exc) if last_exc else "Immich request failed")

    def get_album(self, album_id: str) -> Dict:
        response = self._request("GET", f"/api/albums/{album_id}")
        return response.json()

    def test_connection(self) -> Tuple[bool, str]:
        """Best-effort health check against known Immich endpoints."""
        probe_paths = (
            "/api/server-info",
            "/api/users/me",
            "/api/albums",
        )
        for path in probe_paths:
            response = self._request("GET", path, allow_not_found=True)
            if response.status_code != 404:
                return True, "Immich connection is healthy."
        raise ImmichNotFound("No known Immich endpoint matched during test")

    def get_album_assets(self, album_id: str) -> Iterable[Dict]:
        album = self.get_album(album_id)
        # Immich versions may return either `assets` or `assetIds` in album payload.
        if isinstance(album.get("assets"), list):
            return album["assets"]

        asset_ids = album.get("assetIds") or []
        return [{"id": asset_id} for asset_id in asset_ids]

    def get_thumbnail(self, asset_id: str, size: str = "preview") -> Tuple[requests.Response, str]:
        # Immich endpoint format changed across versions; try known variants.
        paths = [
            f"/api/assets/thumbnail/{asset_id}",
            f"/api/assets/{asset_id}/thumbnail",
        ]

        response = None
        for path in paths:
            candidate = self._request(
                "GET",
                path,
                allow_not_found=True,
                params={"size": size},
                stream=True,
            )
            if candidate.status_code != 404:
                response = candidate
                break

        if response is None or response.status_code == 404:
            raise ImmichNotFound("Immich thumbnail endpoint not found for asset")

        content_type = response.headers.get("Content-Type", "image/jpeg")
        return response, content_type

    def get_asset_binary(self, asset_id: str) -> Tuple[requests.Response, str]:
        # Try known original/download endpoints across Immich versions.
        paths = [
            f"/api/assets/{asset_id}/original",
            f"/api/assets/{asset_id}/download",
            f"/api/assets/download/{asset_id}",
        ]

        response = None
        for path in paths:
            candidate = self._request(
                "GET",
                path,
                allow_not_found=True,
                stream=True,
            )
            if candidate.status_code != 404:
                response = candidate
                break

        if response is None or response.status_code == 404:
            raise ImmichNotFound("Immich original asset endpoint not found")

        content_type = response.headers.get("Content-Type", "application/octet-stream")
        return response, content_type

