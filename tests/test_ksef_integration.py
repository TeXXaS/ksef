"""Integration tests against KSeF TEST environment.

Run explicitly:  pytest -m integration
Skip by default: pytest -m 'not integration'

Requires config.toml with [ksef] nip = "..." to be present.
"""

import pytest

from ksef_deel.config import KsefConfig
from ksef_deel.invoice_model import DeelInvoice
from ksef_deel.invoice_xml import generate_invoice_xml
from ksef_deel.ksef_fetch import download_invoice, list_invoices
from ksef_deel.ksef_upload import upload_invoice
from ksef_deel.validator import validate_invoice_xml

pytestmark = pytest.mark.integration


class TestKsefFetchInvoices:
    def test_list_invoices_returns_results(self, ksef_config: KsefConfig) -> None:
        from datetime import date, timedelta

        invoices = list_invoices(ksef_config, date_from=date.today() - timedelta(days=7))

        assert len(invoices) >= 1
        inv = invoices[0]
        assert inv.ksef_number
        assert inv.invoice_number
        assert inv.gross_amount > 0

    def test_download_first_invoice(self, ksef_config: KsefConfig) -> None:
        from datetime import date, timedelta

        from lxml import etree

        invoices = list_invoices(ksef_config, date_from=date.today() - timedelta(days=7))
        assert invoices, "No invoices found to download"

        xml_bytes = download_invoice(ksef_config, ksef_number=invoices[0].ksef_number)

        assert b"<Faktura" in xml_bytes
        doc = etree.fromstring(xml_bytes)
        ns = {"fa": "http://crd.gov.pl/wzor/2023/06/29/12648/"}
        assert doc.tag == f"{{{ns['fa']}}}Faktura"

        nip = doc.findtext(".//fa:Podmiot1/fa:DaneIdentyfikacyjne/fa:NIP", namespaces=ns)
        assert nip == ksef_config.nip


class TestKsefUploadTestInvoice:
    def test_upload_and_fetch_test_invoice(self, ksef_config: KsefConfig, test_invoice: DeelInvoice) -> None:
        """Full round-trip: generate random invoice -> validate -> upload -> list -> download."""
        xml_bytes = generate_invoice_xml(test_invoice)
        validate_invoice_xml(xml_bytes)

        result = upload_invoice(ksef_config, xml_bytes)
        assert result.ksef_number
        assert result.invoice_reference

        from datetime import date

        invoices = list_invoices(ksef_config, date_from=date.today())
        ksef_numbers = [inv.ksef_number for inv in invoices]
        assert result.ksef_number in ksef_numbers

        downloaded = download_invoice(ksef_config, ksef_number=result.ksef_number)
        assert test_invoice.invoice_number.encode() in downloaded
        assert b"good work" in downloaded
        assert b"1.00" in downloaded
