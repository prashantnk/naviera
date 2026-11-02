"""
Fails a UI test on any unexpected HTTP 4xx/5xx or browser console error.

Every page opened by the harness gets one `NetworkGuard`. It records:
- console messages of type `error` (this includes React hydration errors);
- uncaught page exceptions (`pageerror`);
- responses with status >= 400 from the app's own origins (frontend + API proxy).

A test that expects an error (e.g. a 409 on a duplicate manual LR) declares it
first with `guard.expect_http(pattern, status)`. Unexpected entries fail the test at teardown.
Spring analogy: a MockMvc `ResultHandler` that asserts "no 4xx/5xx unless the
test said so", applied to every request automatically.
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional, Pattern, Sequence

from playwright.async_api import ConsoleMessage, Page, Response

HTTP_ERROR_THRESHOLD = 400

IGNORED_CONSOLE_PATTERNS: Sequence[Pattern[str]] = (
    re.compile(r"Download the React DevTools", re.IGNORECASE),
    re.compile(r"\[Fast Refresh\]", re.IGNORECASE),
    re.compile(r"\[HMR\]", re.IGNORECASE),
)
"""Next.js dev-server chatter that is not an app error."""

IGNORED_URL_PATTERNS: Sequence[Pattern[str]] = (
    re.compile(r"/_next/webpack-hmr"),
    re.compile(r"/__nextjs_original-stack-frame"),
    re.compile(r"/favicon\.ico$"),
)


@dataclass(frozen=True)
class ExpectedHttpError:
    """One HTTP error the test expects: URL regex + status code."""

    url_pattern: Pattern[str]
    status: int

    def matches(self, url: str, status: int) -> bool:
        """True when the response URL and status match this expectation."""
        return status == self.status and bool(self.url_pattern.search(url))


@dataclass(frozen=True)
class ExpectedConsoleError:
    """One console error text the test expects (regex)."""

    pattern: Pattern[str]


@dataclass
class NetworkGuard:
    """Collects violations for one page; `assert_clean()` raises on any unexpected one."""

    app_origins: Sequence[str]
    violations: List[str] = field(default_factory=list)
    _expected_http: List[ExpectedHttpError] = field(default_factory=list)
    _expected_console: List[ExpectedConsoleError] = field(default_factory=list)

    def attach(self, page: Page) -> "NetworkGuard":
        """Registers the console / pageerror / response listeners on `page`."""
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("response", self._on_response)
        return self

    def expect_http(self, url_regex: str, status: int) -> None:
        """Declares an HTTP error this test expects (e.g. `r"/api/v1/shipments$"`, 409)."""
        self._expected_http.append(ExpectedHttpError(re.compile(url_regex), status))

    def expect_console(self, text_regex: str) -> None:
        """Declares a console error text this test expects."""
        self._expected_console.append(ExpectedConsoleError(re.compile(text_regex)))

    def _is_app_url(self, url: str) -> bool:
        """True for the frontend origin and anything proxied through it."""
        return any(url.startswith(origin) for origin in self.app_origins)

    def _on_console(self, message: ConsoleMessage) -> None:
        """Records console errors that are neither noise nor expected."""
        if message.type != "error":
            return
        text = message.text
        if any(p.search(text) for p in IGNORED_CONSOLE_PATTERNS):
            return
        if any(e.pattern.search(text) for e in self._expected_console):
            return
        location = message.location or {}
        self.violations.append(f"console.error: {text} @ {location.get('url', '')}")

    def _on_page_error(self, error: Exception) -> None:
        """Records uncaught exceptions thrown inside the page."""
        self.violations.append(f"pageerror: {error}")

    def _on_response(self, response: Response) -> None:
        """Records unexpected >= 400 responses from the app's own origins."""
        status = response.status
        url = response.url
        if status < HTTP_ERROR_THRESHOLD or not self._is_app_url(url):
            return
        if any(p.search(url) for p in IGNORED_URL_PATTERNS):
            return
        if any(e.matches(url, status) for e in self._expected_http):
            return
        method: Optional[str] = response.request.method if response.request else None
        self.violations.append(f"HTTP {status} {method or ''} {url}".strip())

    def assert_clean(self) -> None:
        """Raises `AssertionError` listing every unexpected console error or HTTP error."""
        if self.violations:
            joined = "\n  - ".join(self.violations)
            raise AssertionError(f"Unexpected browser errors ({len(self.violations)}):\n  - {joined}")
