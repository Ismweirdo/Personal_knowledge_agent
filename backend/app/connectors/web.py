import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.infrastructure.errors import ApplicationError


@dataclass(frozen=True)
class WebSnapshot:
    url: str
    text: str
    etag: str | None
    last_modified: str | None


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ApplicationError("INVALID_SOURCE_URL", "Invalid web source URL", status_code=422)
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ApplicationError(
            "SOURCE_URL_BLOCKED", "Web source host is not allowed", status_code=422
        )
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ApplicationError(
                "SOURCE_URL_BLOCKED", "Web source host is not allowed", status_code=422
            )
    except ValueError:
        pass
    return url


async def fetch_web(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> WebSnapshot | None:
    validate_public_url(url)
    headers = {"User-Agent": "PersonalKnowledgeAgent/0.1"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
    try:
        response = await client.get(url, headers=headers)
        if response.status_code == 304:
            return None
        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            if not location:
                raise ApplicationError("WEB_FETCH_FAILED", "Invalid redirect", status_code=502)
            validate_public_url(str(response.url.join(location)))
            raise ApplicationError(
                "WEB_REDIRECT_REJECTED", "Web redirects require review", status_code=422
            )
        response.raise_for_status()
        if len(response.content) > 5 * 1024 * 1024:
            raise ApplicationError(
                "WEB_CONTENT_TOO_LARGE", "Web content exceeds size limit", status_code=413
            )
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        text = " ".join(soup.get_text(" ").split())
        if not text:
            raise ApplicationError(
                "WEB_CONTENT_EMPTY", "Web page contains no readable text", status_code=422
            )
        return WebSnapshot(
            url=str(response.url),
            text=text,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )
    except httpx.HTTPError as exc:
        raise ApplicationError(
            "WEB_FETCH_FAILED", "Unable to fetch web source", status_code=502
        ) from exc
    finally:
        if owns_client:
            await client.aclose()
