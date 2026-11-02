"""
On-page heads-up display for visible runs (ship-readiness plan E4).

Two things the watching user sees in the Chrome window:
1. A fixed banner at the top, e.g. "J09 step 3/7: Book shipment".
2. A short outline flash on every element right before it is clicked or typed into.

Both are injected with `page.evaluate`, live only in the page DOM, never touch
app state, and are re-applied after every navigation (a full page load wipes
the DOM). They are test chrome, not app UI, so the fixed colours here do not
fall under the runtime-theming rule.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:  # Playwright is only needed when a page is actually driven.
    from playwright.async_api import Locator, Page

HUD_ELEMENT_ID = "ui-golden-hud"
HUD_TEST_ID = "ui-golden.hud.banner"
HIGHLIGHT_OUTLINE = "3px solid #f59e0b"
HUD_Z_INDEX = 2147483647

_SHOW_BANNER_JS = """
([elementId, testId, text, zIndex]) => {
  let el = document.getElementById(elementId);
  if (!el) {
    el = document.createElement('div');
    el.id = elementId;
    el.setAttribute('data-testid', testId);
    el.setAttribute('aria-live', 'polite');
    el.style.cssText = [
      'position:fixed', 'top:0', 'left:50%', 'transform:translateX(-50%)',
      'z-index:' + zIndex, 'pointer-events:none', 'padding:6px 14px',
      'border-radius:0 0 10px 10px', 'background:rgba(15,23,42,0.92)',
      'color:#fde68a', 'font:600 13px/1.4 ui-monospace,monospace',
      'box-shadow:0 4px 14px rgba(0,0,0,0.35)', 'max-width:92vw',
      'white-space:nowrap', 'overflow:hidden', 'text-overflow:ellipsis'
    ].join(';');
    (document.body || document.documentElement).appendChild(el);
  }
  el.textContent = text;
  return el.textContent;
}
"""

_READ_BANNER_JS = """
(elementId) => {
  const el = document.getElementById(elementId);
  return el ? el.textContent : null;
}
"""

_HIGHLIGHT_JS = """
(el, [outline, ms]) => {
  const previous = el.style.outline;
  const previousOffset = el.style.outlineOffset;
  el.style.outline = outline;
  el.style.outlineOffset = '2px';
  el.scrollIntoView({block: 'center', inline: 'nearest'});
  setTimeout(() => { el.style.outline = previous; el.style.outlineOffset = previousOffset; }, ms);
  return true;
}
"""


def format_step_label(journey: str, step: int, total: int, text: str) -> str:
    """
    Builds the banner text, e.g. `format_step_label("J09", 3, 7, "Book")`
    returns `"J09 step 3/7: Book"`.

    Raises:
        ValueError: When `step` is outside `1..total`.
    """
    if total < 1 or not 1 <= step <= total:
        raise ValueError(f"step must be within 1..{total}, got {step}")
    label = f"{journey} step {step}/{total}"
    return f"{label}: {text}" if text else label


@dataclass
class StepBanner:
    """
    Keeps the current banner text per page and re-applies it after navigations.

    Spring analogy: a small stateful `@Component` that a test injects, like a
    MockMvc result printer that stays attached for the whole test.
    """

    highlight_ms: int
    _labels: Dict[int, str] = field(default_factory=dict)
    _attached: Dict[int, bool] = field(default_factory=dict)

    def _attach(self, page: Page) -> None:
        """Registers a one-time `load` listener that re-draws the banner on the new DOM."""
        key = id(page)
        if self._attached.get(key):
            return

        async def _redraw(_: object) -> None:
            label = self._labels.get(key)
            if label is not None:
                try:
                    await _draw(page, label)
                except Exception:  # noqa: BLE001 - a closing page must not fail the test
                    pass

        page.on("load", _redraw)
        self._attached[key] = True

    async def show(self, page: Page, journey: str, step: int, total: int, text: str = "") -> str:
        """Shows `"<journey> step <step>/<total>: <text>"` and returns the label."""
        label = format_step_label(journey, step, total, text)
        return await self.show_text(page, label)

    async def show_text(self, page: Page, label: str) -> str:
        """Shows a free-text banner (used for setup steps such as role login)."""
        self._labels[id(page)] = label
        self._attach(page)
        return await _draw(page, label)

    async def highlight(self, locator: Locator) -> None:
        """Outlines the element for `highlight_ms`, then waits that long so the user can see it."""
        if self.highlight_ms <= 0:
            return
        handle = await locator.element_handle()
        if handle is None:
            return
        await handle.evaluate(_HIGHLIGHT_JS, [HIGHLIGHT_OUTLINE, self.highlight_ms])
        await asyncio.sleep(self.highlight_ms / 1000)


async def _draw(page: Page, label: str) -> str:
    """Creates or updates the banner element and returns the text the DOM now shows."""
    return await page.evaluate(
        _SHOW_BANNER_JS, [HUD_ELEMENT_ID, HUD_TEST_ID, label, HUD_Z_INDEX]
    )


async def read_banner(page: Page) -> Optional[str]:
    """Returns the banner text currently in the DOM (None when absent)."""
    return await page.evaluate(_READ_BANNER_JS, HUD_ELEMENT_ID)
