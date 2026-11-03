"""
Download + PDF text helpers (labels, run-sheets, GST invoices, receipts).

`download_via_click` clicks a button, waits for the browser download and saves
it under `/tmp/naviera_ui_golden_artifacts/`. `pdf_text` extracts every page's
text with `pypdf` so a journey can assert content (GSTINs, SAC 996812, the LR
number, `1/5` child labels), not just the `%PDF-` header.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

import pytest
from playwright.async_api import Locator, Page

from .ui_config import ARTIFACT_DIR

PDF_MAGIC = b"%PDF-"
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class PdfContent:
    """Text of a downloaded PDF, one string per page."""

    path: Path
    pages: List[str]

    @property
    def text(self) -> str:
        """All pages joined, with whitespace collapsed to single spaces."""
        return _WHITESPACE_RE.sub(" ", " ".join(self.pages)).strip()

    def assert_contains(self, needles: Sequence[str]) -> None:
        """
        Asserts every needle appears in the PDF text (whitespace-insensitive).

        Raises:
            AssertionError: Listing the missing needles.
        """
        haystack = self.text
        missing = [n for n in needles if _WHITESPACE_RE.sub(" ", n) not in haystack]
        assert not missing, f"{self.path.name} is missing {missing}"


async def download_via_click(page: Page, trigger: Locator, file_stem: str) -> Path:
    """
    Clicks `trigger`, waits for the download and saves it as `<file_stem><ext>`.

    Returns:
        The saved file path.
    """
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    async with page.expect_download() as download_info:
        await trigger.click()
    download = await download_info.value
    suffix = Path(download.suggested_filename).suffix or ".bin"
    target = ARTIFACT_DIR / f"{file_stem}{suffix}"
    await download.save_as(target)
    return target


def pdf_text(path: Path) -> PdfContent:
    """
    Reads a PDF file and returns its per-page text.

    Raises:
        AssertionError: When the file is not a PDF.
        pytest.skip.Exception: When `pypdf` (dev group `e2e`) is not installed.
    """
    reader_cls = pytest.importorskip("pypdf").PdfReader
    head = path.read_bytes()[: len(PDF_MAGIC)]
    assert head == PDF_MAGIC, f"{path.name} is not a PDF (starts with {head!r})"
    reader = reader_cls(str(path))
    return PdfContent(path=path, pages=[page.extract_text() or "" for page in reader.pages])
