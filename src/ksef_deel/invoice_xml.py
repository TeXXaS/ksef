"""Generate KSeF FA(2) compliant XML from parsed Deel invoice data.

Schema: http://crd.gov.pl/wzor/2023/06/29/12648/
FormCode: FA (2), SchemaVersion: 1-0E

Deel contractor invoices: Polish freelancer → foreign client.
- Podmiot1 = Polish taxpayer / contractor (the one uploading to KSeF)
- Podmiot2 = Foreign buyer (e.g. Piano Software Inc, US)
- VAT rate = "np" (nie podlega — export of services, not subject to Polish VAT)
- Currency = PLN
- RodzajFaktury = "VAT"
"""

from datetime import datetime
from decimal import Decimal

from lxml import etree

from ksef_deel.invoice_model import DeelInvoice, Party

FA_NAMESPACE = "http://crd.gov.pl/wzor/2023/06/29/12648/"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"

NSMAP = {
    None: FA_NAMESPACE,
    "xsi": XSI_NAMESPACE,
}

_EU_COUNTRIES = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
    "XI",
}


def _ksef_eu_code(country: str) -> str | None:
    """Map ISO country code to KSeF EU code. Only GR→EL differs."""
    if country not in _EU_COUNTRIES:
        return None
    return "EL" if country == "GR" else country


def _el(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    elem = etree.SubElement(parent, tag)
    if text is not None:
        elem.text = str(text)
    return elem


def _format_amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _format_quantity(value: Decimal) -> str:
    return f"{value:.6f}"


def generate_invoice_xml(invoice: DeelInvoice) -> bytes:
    """Generate FA(2) XML for a Deel contractor invoice.

    - Podmiot1 = invoice.seller (Polish contractor, NIP required)
    - Podmiot2 = invoice.buyer (foreign company)
    """
    root = etree.Element("Faktura", nsmap=NSMAP)  # type: ignore[arg-type]

    _build_naglowek(root)
    _build_podmiot1(root, invoice.seller)
    _build_podmiot2(root, invoice.buyer)
    _build_fa(root, invoice)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _build_naglowek(root: etree._Element) -> None:
    naglowek = _el(root, "Naglowek")

    kod_formularza = _el(naglowek, "KodFormularza", "FA")
    kod_formularza.set("kodSystemowy", "FA (2)")
    kod_formularza.set("wersjaSchemy", "1-0E")

    _el(naglowek, "WariantFormularza", "2")
    _el(naglowek, "DataWytworzeniaFa", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    _el(naglowek, "SystemInfo", "ksef-deel")


def _build_podmiot1(root: etree._Element, seller: Party) -> None:
    """Podmiot1 = Polish taxpayer (contractor issuing the invoice via Deel)."""
    if not seller.nip:
        raise ValueError("Seller (Podmiot1) must have a Polish NIP")

    podmiot1 = _el(root, "Podmiot1")

    dane_id = _el(podmiot1, "DaneIdentyfikacyjne")
    _el(dane_id, "NIP", seller.nip)
    _el(dane_id, "Nazwa", seller.name)

    adres = _el(podmiot1, "Adres")
    _el(adres, "KodKraju", "PL")
    _el(adres, "AdresL1", seller.address_line1)
    if seller.address_line2:
        _el(adres, "AdresL2", seller.address_line2)


def _build_podmiot2(root: etree._Element, buyer: Party) -> None:
    """Podmiot2 = Foreign buyer (client company)."""
    podmiot2 = _el(root, "Podmiot2")

    dane_id = _el(podmiot2, "DaneIdentyfikacyjne")

    country = buyer.country_code
    eu_code = _ksef_eu_code(country)

    if buyer.nip:
        # Polish buyer (unlikely for Deel but handle it)
        _el(dane_id, "NIP", buyer.nip)
    elif eu_code and buyer.vat_id:
        # EU buyer with VAT ID
        _el(dane_id, "KodUE", eu_code)
        vat_id = buyer.vat_id
        if vat_id.upper().startswith(country):
            vat_id = vat_id[len(country) :]
        _el(dane_id, "NrVatUE", vat_id)
    else:
        # Non-EU buyer or no VAT ID
        _el(dane_id, "BrakID", "1")

    _el(dane_id, "Nazwa", buyer.name)

    adres = _el(podmiot2, "Adres")
    _el(adres, "KodKraju", country)
    _el(adres, "AdresL1", buyer.address_line1)
    if buyer.address_line2:
        _el(adres, "AdresL2", buyer.address_line2)


def _build_fa(root: etree._Element, invoice: DeelInvoice) -> None:
    """Fa section: invoice financial details + line items.

    Element order per XSD:
    KodWaluty, P_1, P_1M?, P_2, WZ*, [P_6|OkresFa]?,
    P_13_*?, P_15, KursWalutyZ?,
    Adnotacje, RodzajFaktury, ..., FaWiersz*, ...
    """
    fa = _el(root, "Fa")

    _el(fa, "KodWaluty", invoice.currency)
    _el(fa, "P_1", invoice.issue_date.isoformat())
    _el(fa, "P_2", invoice.invoice_number)

    # Service period → OkresFa (P_6_Od / P_6_Do)
    if invoice.service_period:
        okres = _el(fa, "OkresFa")
        _el(okres, "P_6_Od", invoice.service_period.date_from.isoformat())
        _el(okres, "P_6_Do", invoice.service_period.date_to.isoformat())

    # P_13_11 = net amount not subject to Polish VAT (np rate)
    _el(fa, "P_13_11", _format_amount(invoice.total_net))

    # P_15 = total gross amount (required)
    _el(fa, "P_15", _format_amount(invoice.total_gross))

    # Adnotacje — required, strict element order per XSD
    adnotacje = _el(fa, "Adnotacje")
    _el(adnotacje, "P_16", "2")  # not cash method
    _el(adnotacje, "P_17", "2")  # not self-billing
    _el(adnotacje, "P_18", "2")  # not reverse charge annotation
    _el(adnotacje, "P_18A", "2")  # not split payment mechanism

    # Zwolnienie: P_19N=1 (not VAT-exempt — services are "np", not "zw")
    zwolnienie = _el(adnotacje, "Zwolnienie")
    _el(zwolnienie, "P_19N", "1")

    # NoweSrodkiTransportu: P_22N=1 (not new means of transport)
    nst = _el(adnotacje, "NoweSrodkiTransportu")
    _el(nst, "P_22N", "1")

    _el(adnotacje, "P_23", "2")  # not simplified triangular procedure

    # PMarzy: P_PMarzyN=1 (no margin procedures)
    p_marzy = _el(adnotacje, "PMarzy")
    _el(p_marzy, "P_PMarzyN", "1")

    # RodzajFaktury (required, after Adnotacje)
    _el(fa, "RodzajFaktury", "VAT")

    # FaWiersz — line items (direct children of Fa)
    for idx, item in enumerate(invoice.line_items, start=1):
        wiersz = _el(fa, "FaWiersz")
        _el(wiersz, "NrWierszaFa", str(idx))
        _el(wiersz, "P_7", item.description)
        _el(wiersz, "P_8A", item.unit)
        _el(wiersz, "P_8B", _format_quantity(item.quantity))
        _el(wiersz, "P_9A", _format_amount(item.unit_price_net))
        _el(wiersz, "P_11", _format_amount(item.net_amount))
        _el(wiersz, "P_12", item.vat_rate)
