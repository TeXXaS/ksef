"""Test FA(2) XML generation and XSD validation."""

from datetime import date
from decimal import Decimal

from lxml import etree

from ksef_deel.invoice_model import DeelInvoice, LineItem, Party, ServicePeriod
from ksef_deel.invoice_xml import FA_NAMESPACE, generate_invoice_xml
from ksef_deel.validator import validate_invoice_xml_report

TEST_NIP = "1234567890"


def _make_seller(**overrides) -> Party:
    defaults = dict(
        name="Test Seller",
        country_code="PL",
        address_line1="ul. Testowa 1",
        address_line2="00-001 Warszawa",
        nip=TEST_NIP,
    )
    defaults.update(overrides)
    return Party(**defaults)


def _make_buyer(**overrides) -> Party:
    defaults = dict(
        name="Piano Software Inc",
        country_code="US",
        address_line1="111 S. Independence Mall West,",
        address_line2="Suite 950",
        vat_id="453637947",
    )
    defaults.update(overrides)
    return Party(**defaults)


def _make_invoice(**overrides) -> DeelInvoice:
    defaults = dict(
        invoice_number="INV202510",
        issue_date=date(2025, 10, 26),
        due_date=date(2025, 11, 5),
        currency="PLN",
        seller=_make_seller(),
        buyer=_make_buyer(),
        service_period=ServicePeriod(
            date_from=date(2025, 10, 1),
            date_to=date(2025, 10, 31),
        ),
        line_items=[
            LineItem(
                description="Fixed contract — October 1, 2025 to October 31, 2025",
                quantity=Decimal("1"),
                unit_price_net=Decimal("27000.00"),
                net_amount=Decimal("27000.00"),
                vat_rate="np",
                vat_amount=Decimal("0"),
                gross_amount=Decimal("27000.00"),
            ),
        ],
        total_net=Decimal("27000.00"),
        total_vat=Decimal("0"),
        total_gross=Decimal("27000.00"),
        deel_reference="P8fdth52pEe5PpaGeY7KP",
    )
    defaults.update(overrides)
    return DeelInvoice(**defaults)


class TestXmlGeneration:
    def test_generates_valid_xml(self):
        xml_bytes = generate_invoice_xml(_make_invoice())
        root = etree.fromstring(xml_bytes)
        assert root.tag == f"{{{FA_NAMESPACE}}}Faktura"

    def test_contains_required_sections(self):
        xml_bytes = generate_invoice_xml(_make_invoice())
        root = etree.fromstring(xml_bytes)
        ns = {"fa": FA_NAMESPACE}
        assert root.find("fa:Naglowek", ns) is not None
        assert root.find("fa:Podmiot1", ns) is not None
        assert root.find("fa:Podmiot2", ns) is not None
        assert root.find("fa:Fa", ns) is not None

    def test_naglowek_has_correct_form_code(self):
        xml_bytes = generate_invoice_xml(_make_invoice())
        root = etree.fromstring(xml_bytes)
        ns = {"fa": FA_NAMESPACE}
        kod = root.find("fa:Naglowek/fa:KodFormularza", ns)
        assert kod.text == "FA"
        assert kod.get("kodSystemowy") == "FA (2)"
        assert kod.get("wersjaSchemy") == "1-0E"

    def test_podmiot1_has_seller_nip(self):
        invoice = _make_invoice(seller=_make_seller(nip="1234567890"))
        xml_bytes = generate_invoice_xml(invoice)
        root = etree.fromstring(xml_bytes)
        ns = {"fa": FA_NAMESPACE}
        nip = root.find("fa:Podmiot1/fa:DaneIdentyfikacyjne/fa:NIP", ns)
        assert nip.text == "1234567890"

    def test_podmiot2_non_eu_buyer_uses_brak_id(self):
        invoice = _make_invoice(buyer=_make_buyer(country_code="US", vat_id="453637947"))
        xml_bytes = generate_invoice_xml(invoice)
        root = etree.fromstring(xml_bytes)
        ns = {"fa": FA_NAMESPACE}
        brak_id = root.find("fa:Podmiot2/fa:DaneIdentyfikacyjne/fa:BrakID", ns)
        assert brak_id.text == "1"

    def test_podmiot2_eu_buyer_uses_vat_ue(self):
        invoice = _make_invoice(
            buyer=_make_buyer(country_code="DE", vat_id="DE123456789"),
        )
        xml_bytes = generate_invoice_xml(invoice)
        root = etree.fromstring(xml_bytes)
        ns = {"fa": FA_NAMESPACE}
        kod_ue = root.find("fa:Podmiot2/fa:DaneIdentyfikacyjne/fa:KodUE", ns)
        assert kod_ue.text == "DE"
        nr_vat = root.find("fa:Podmiot2/fa:DaneIdentyfikacyjne/fa:NrVatUE", ns)
        assert nr_vat.text == "123456789"

    def test_fa_section_amounts(self):
        invoice = _make_invoice(
            total_net=Decimal("27000.00"),
            total_gross=Decimal("27000.00"),
        )
        xml_bytes = generate_invoice_xml(invoice)
        root = etree.fromstring(xml_bytes)
        ns = {"fa": FA_NAMESPACE}
        p13_11 = root.find("fa:Fa/fa:P_13_11", ns)
        assert p13_11.text == "27000.00"
        p15 = root.find("fa:Fa/fa:P_15", ns)
        assert p15.text == "27000.00"

    def test_okres_fa_from_service_period(self):
        invoice = _make_invoice(
            service_period=ServicePeriod(date(2025, 10, 1), date(2025, 10, 31)),
        )
        xml_bytes = generate_invoice_xml(invoice)
        root = etree.fromstring(xml_bytes)
        ns = {"fa": FA_NAMESPACE}
        p6_od = root.find("fa:Fa/fa:OkresFa/fa:P_6_Od", ns)
        p6_do = root.find("fa:Fa/fa:OkresFa/fa:P_6_Do", ns)
        assert p6_od.text == "2025-10-01"
        assert p6_do.text == "2025-10-31"

    def test_line_items_generated(self):
        items = [
            LineItem("Service A", Decimal("1"), Decimal("1000"), Decimal("1000"), "np", Decimal("0"), Decimal("1000")),
            LineItem("Service B", Decimal("2"), Decimal("500"), Decimal("1000"), "np", Decimal("0"), Decimal("1000")),
        ]
        invoice = _make_invoice(
            line_items=items,
            total_net=Decimal("2000.00"),
            total_gross=Decimal("2000.00"),
        )
        xml_bytes = generate_invoice_xml(invoice)
        root = etree.fromstring(xml_bytes)
        ns = {"fa": FA_NAMESPACE}
        wiersze = root.findall("fa:Fa/fa:FaWiersz", ns)
        assert len(wiersze) == 2
        assert wiersze[0].find("fa:NrWierszaFa", ns).text == "1"
        assert wiersze[0].find("fa:P_7", ns).text == "Service A"
        assert wiersze[1].find("fa:NrWierszaFa", ns).text == "2"


class TestXsdValidation:
    def test_valid_invoice_passes_xsd(self):
        xml_bytes = generate_invoice_xml(_make_invoice())
        errors = validate_invoice_xml_report(xml_bytes)
        assert errors == [], f"Unexpected validation errors: {errors}"

    def test_multiple_line_items_pass_xsd(self):
        items = [
            LineItem(f"Service {i}", Decimal("1"), Decimal("100"), Decimal("100"), "np", Decimal("0"), Decimal("100"))
            for i in range(5)
        ]
        invoice = _make_invoice(
            line_items=items,
            total_net=Decimal("500.00"),
            total_gross=Decimal("500.00"),
        )
        xml_bytes = generate_invoice_xml(invoice)
        errors = validate_invoice_xml_report(xml_bytes)
        assert errors == [], f"Unexpected validation errors: {errors}"

    def test_eu_buyer_passes_xsd(self):
        invoice = _make_invoice(
            buyer=_make_buyer(country_code="DE", vat_id="DE123456789"),
        )
        xml_bytes = generate_invoice_xml(invoice)
        errors = validate_invoice_xml_report(xml_bytes)
        assert errors == [], f"Unexpected validation errors: {errors}"

    def test_non_eu_buyer_passes_xsd(self):
        invoice = _make_invoice(
            buyer=_make_buyer(country_code="US", vat_id="453637947"),
        )
        xml_bytes = generate_invoice_xml(invoice)
        errors = validate_invoice_xml_report(xml_bytes)
        assert errors == [], f"Unexpected validation errors: {errors}"

    def test_real_invoice_data_passes_xsd(self):
        """Test with exact data matching the parsed Deel invoice."""
        invoice = _make_invoice()
        xml_bytes = generate_invoice_xml(invoice)
        errors = validate_invoice_xml_report(xml_bytes)
        assert errors == [], f"Unexpected validation errors: {errors}"


class TestDeelPdfParsing:
    def test_parse_all_invoices(self):
        from pathlib import Path

        from ksef_deel.deel_parser import parse_deel_pdf

        invoices_dir = Path("invoices")
        if not invoices_dir.exists():
            return

        for pdf_path in sorted(invoices_dir.glob("*.pdf")):
            inv = parse_deel_pdf(pdf_path)
            assert inv.invoice_number
            assert inv.issue_date
            assert inv.seller.nip
            assert inv.seller.name
            assert inv.buyer.name
            assert inv.buyer.country_code
            assert inv.total_gross > 0
            assert inv.currency == "PLN"
            assert inv.service_period is not None
            assert len(inv.line_items) >= 1

    def test_parse_and_validate_all_invoices(self):
        """End-to-end: parse real PDF → generate XML → validate against XSD."""
        from pathlib import Path

        from ksef_deel.deel_parser import parse_deel_pdf

        invoices_dir = Path("invoices")
        if not invoices_dir.exists():
            return

        for pdf_path in sorted(invoices_dir.glob("*.pdf")):
            inv = parse_deel_pdf(pdf_path)
            xml_bytes = generate_invoice_xml(inv)
            errors = validate_invoice_xml_report(xml_bytes)
            assert errors == [], f"{pdf_path.name}: {errors}"
