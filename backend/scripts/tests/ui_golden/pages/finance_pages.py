"""Finance screens: wallet, GST invoices/notes, COD remittances."""

from decimal import Decimal
from pathlib import Path

from ..pdf import download_via_click
from ..testids import AppShellIds, InvoiceIds, RemittanceIds, WalletIds
from .base_page import BasePage


class WalletPage(BasePage):
    """`/wallet`: balance card and ledger."""

    ROUTE = "/wallet"

    async def balance(self) -> Decimal:
        """The ₹ balance on the wallet summary card."""
        return await self.money(WalletIds.BALANCE)

    async def header_balance(self) -> Decimal:
        """The ₹ balance in the header pill (present on every app page)."""
        return await self.money(AppShellIds.WALLET_BALANCE)

    async def txn_amount(self, receipt_number: str) -> Decimal:
        """The ₹ amount of one ledger row, found by its receipt number."""
        return await self.money(WalletIds.txn_amount(receipt_number))


class InvoicesPage(BasePage):
    """`/finances/invoices`: All / Invoices / Debit notes / Credit notes tabs."""

    ROUTE = "/finances/invoices"

    _TABS = {
        "ALL": InvoiceIds.TAB_ALL,
        "INVOICE": InvoiceIds.TAB_INVOICES,
        "DEBIT_NOTE": InvoiceIds.TAB_DEBIT,
        "CREDIT_NOTE": InvoiceIds.TAB_CREDIT,
    }

    async def show_tab(self, note_type: str) -> None:
        """Clicks the tab for `ALL`, `INVOICE`, `DEBIT_NOTE` or `CREDIT_NOTE`."""
        await self.click(self._TABS[note_type])

    async def row_total(self, invoice_number: str) -> Decimal:
        """The ₹ total of one document row."""
        return await self.money(InvoiceIds.row_total(invoice_number))

    async def download_pdf(self, invoice_number: str) -> Path:
        """Opens the document and downloads its PDF."""
        await self.click(InvoiceIds.row(invoice_number))
        return await download_via_click(
            self.page, self.by_testid(InvoiceIds.DOWNLOAD_PDF), f"invoice_{invoice_number}"
        )


class RemittancesPage(BasePage):
    """`/finances/remittances`: COD remittance batches."""

    ROUTE = "/finances/remittances"

    async def row_total(self, remittance_number: str) -> Decimal:
        """The ₹ total of one remittance batch."""
        return await self.money(RemittanceIds.row_total(remittance_number))

    async def download_csv(self, remittance_number: str) -> Path:
        """Opens the batch and downloads its transaction CSV."""
        await self.click(RemittanceIds.row(remittance_number))
        return await download_via_click(
            self.page, self.by_testid(RemittanceIds.DOWNLOAD_CSV), f"remittance_{remittance_number}"
        )
