"""
Security response headers (B-11 / A6-21). The API serves JSON (and PDFs) only, so it can deny
framing and MIME sniffing outright; HSTS is sent only in production (served over HTTPS).
Spring Boot Equivalent: Spring Security's `HttpSecurity.headers()` defaults.
"""

from typing import Awaitable, Callable, Dict

from fastapi import Request, Response

from app.core.config import is_production

BASE_SECURITY_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
HSTS_HEADER = ("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


def security_headers() -> Dict[str, str]:
    """The headers added to every response (HSTS only in production)."""
    headers = dict(BASE_SECURITY_HEADERS)
    if is_production():
        headers[HSTS_HEADER[0]] = HSTS_HEADER[1]
    return headers


async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """HTTP middleware: sets the security headers unless a route already set them."""
    response = await call_next(request)
    for name, value in security_headers().items():
        response.headers.setdefault(name, value)
    return response
