"""Fetch invoices stored in KSeF."""

import calendar
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ksef2 import Client, Environment
from ksef2.domain.models.invoices import InvoicesFilter

from ksef_deel.config import KsefConfig, KsefEnvironment

logger = logging.getLogger(__name__)

_ENV_MAP = {
    KsefEnvironment.TEST: Environment.TEST,
    KsefEnvironment.DEMO: Environment.DEMO,
    KsefEnvironment.PROD: Environment.PRODUCTION,
}


@dataclass(frozen=True)
class InvoiceSummary:
    ksef_number: str
    invoice_number: str
    issue_date: date
    seller_name: str
    seller_nip: str | None
    buyer_name: str
    net_amount: float
    gross_amount: float
    vat_amount: float
    currency: str
    acquisition_date: datetime


def _authenticate(config: KsefConfig) -> Any:
    env = _ENV_MAP[config.environment]
    client = Client(env)
    if config.environment == KsefEnvironment.TEST:
        return client.authentication.with_test_certificate(nip=config.nip)
    return client.authentication.with_token(ksef_token=config.token, nip=config.nip)


_MAX_CHUNK_MONTHS = 3


def _add_months(d: date, months: int) -> date:
    """Advance *d* by *months* calendar months, clamping the day to the target month's last day."""
    total_month = d.month + months
    year = d.year + (total_month - 1) // 12
    month = (total_month - 1) % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _date_range_chunks(date_from: date, date_to: date) -> list[tuple[date, date]]:
    """Split [date_from, date_to] into sub-ranges each spanning at most 3 calendar months."""
    chunks: list[tuple[date, date]] = []
    chunk_start = date_from
    while chunk_start <= date_to:
        chunk_end = min(_add_months(chunk_start, _MAX_CHUNK_MONTHS) - timedelta(days=1), date_to)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


def list_invoices(
    config: KsefConfig,
    date_from: date,
    date_to: date | None = None,
) -> list[InvoiceSummary]:
    """Query KSeF for invoices issued by the configured NIP.

    Automatically splits ranges exceeding 3 months into multiple requests.
    """
    auth = _authenticate(config)

    if date_to is None:
        date_to = date.today()

    logger.info("Querying KSeF (%s) for invoices from %s to %s...", config.environment.value, date_from, date_to)

    chunks = _date_range_chunks(date_from, date_to)
    results: list[InvoiceSummary] = []

    for chunk_from, chunk_to in chunks:
        if len(chunks) > 1:
            logger.info("  chunk: %s to %s", chunk_from, chunk_to)

        dt_from = datetime(chunk_from.year, chunk_from.month, chunk_from.day, tzinfo=UTC)
        dt_to = datetime(chunk_to.year, chunk_to.month, chunk_to.day, 23, 59, 59, tzinfo=UTC)

        filters = InvoicesFilter(
            role="seller",
            date_type="invoicing_date",
            date_from=dt_from,
            date_to=dt_to,
            amount_type="brutto",
        )

        response = auth.invoices.query_metadata(filters=filters)

        for inv in response.invoices:
            results.append(
                InvoiceSummary(
                    ksef_number=inv.ksef_number,
                    invoice_number=inv.invoice_number,
                    issue_date=inv.issue_date,
                    seller_name=inv.seller.name,
                    seller_nip=getattr(inv.seller, "nip", None),
                    buyer_name=inv.buyer.name,
                    net_amount=inv.net_amount,
                    gross_amount=inv.gross_amount,
                    vat_amount=inv.vat_amount,
                    currency=inv.currency,
                    acquisition_date=inv.acquisition_date,
                )
            )

    logger.info("Found %d invoice(s)", len(results))
    return results


def download_invoice(config: KsefConfig, ksef_number: str) -> bytes:
    """Download invoice XML from KSeF by its KSeF number."""
    auth = _authenticate(config)
    logger.info("Downloading invoice %s from KSeF (%s)...", ksef_number, config.environment.value)
    result: bytes = auth.invoices.download_invoice(ksef_number=ksef_number)
    return result
