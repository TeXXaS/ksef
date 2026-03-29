"""Parse Deel.com contractor invoice PDFs into structured DeelInvoice objects.

Deel contractor invoices have a two-column layout (BILL FROM / BILL TO)
that merges when extracted as plain text. This parser uses word positions
to correctly separate the left (seller) and right (buyer) columns.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pdfplumber

from ksef_deel.invoice_model import DeelInvoice, LineItem, Party, ServicePeriod

# Unicode Private Use Area — Deel PDFs embed these as font artifacts
_PUA_RE = re.compile(r"[\ue000-\uf8ff]")

_DATE_FORMATS = [
    "%B %d, %Y",  # "October 26, 2025"
    "%b %d, %Y",  # "Oct 26, 2025"
    "%d %B %Y",  # "26 October 2025"
    "%Y-%m-%d",  # "2025-10-26"
    "%d/%m/%Y",  # "26/10/2025"
]


def _clean(text: str) -> str:
    return _PUA_RE.sub("", text).strip()


def _parse_date(text: str) -> date:
    text = _clean(text).rstrip(".")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: '{text}'")


def _parse_amount(text: str) -> Decimal:
    cleaned = re.sub(r"[^\d.,\-]", "", _clean(text))
    if "." in cleaned:
        cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(f"Cannot parse amount: '{text}'") from e


def _group_words_into_lines(words: list[dict[str, Any]], x_split: float) -> tuple[list[str], list[str]]:
    """Group words by vertical position into left-column and right-column lines."""
    if not words:
        return [], []

    # Group by approximate y-coordinate (top)
    rows: dict[int, list[dict[str, Any]]] = {}
    for w in words:
        row_key = round(w["top"])
        rows.setdefault(row_key, []).append(w)

    left_lines = []
    right_lines = []

    for row_key in sorted(rows):
        row_words = sorted(rows[row_key], key=lambda w: w["x0"])
        left_parts = []
        right_parts = []
        for w in row_words:
            text = _clean(w["text"])
            if not text:
                continue
            if w["x0"] < x_split:
                left_parts.append(text)
            else:
                right_parts.append(text)

        if left_parts:
            left_lines.append(" ".join(left_parts))
        if right_parts:
            right_lines.append(" ".join(right_parts))

    return left_lines, right_lines


def _find_column_splits(words: list[dict[str, Any]]) -> tuple[float, float]:
    """Find x-coordinates separating BILL FROM / BILL TO / TOTAL DUE columns."""
    bill_to_x = 170.0
    total_due_x = 420.0
    for w in words:
        text = _clean(w["text"])
        if text == "BILL TO":
            bill_to_x = w["x0"]
        elif text == "TOTAL DUE":
            total_due_x = w["x0"] - 80  # amount starts before the header
    return bill_to_x, total_due_x


def _parse_party_lines(lines: list[str]) -> Party:
    """Parse party data from column lines.

    Expected order:
      Name
      Address line 1
      City, ZIP
      Country
      Phone (optional)
      Registration number: XXXX
      VAT ID XXXX
      Tax ID XXXX
    """
    name = lines[0] if lines else "Unknown"
    address_parts: list[str] = []
    country_code = "US"
    nip = None
    vat_id = None
    tax_id = None
    phone = None
    registration = None

    for line in lines[1:]:
        if re.match(r"Registration number:", line, re.IGNORECASE):
            reg_match = re.search(r"Registration number:\s*(\S+)", line)
            if reg_match:
                registration = reg_match.group(1)
            continue

        vat_match = re.match(r"VAT\s+ID\s+(\S+)", line)
        if vat_match:
            raw_vat = vat_match.group(1)
            # Polish NIP with PL prefix
            pl_match = re.match(r"PL(\d{10})", raw_vat)
            if pl_match:
                nip = pl_match.group(1)
                vat_id = raw_vat
                country_code = "PL"
            else:
                vat_id = raw_vat
            continue

        tax_match = re.match(r"Tax\s+ID\s+(\S+)", line)
        if tax_match:
            tax_id = tax_match.group(1)
            continue

        if re.match(r"Group:", line):
            continue

        # Country detection
        country_lower = line.lower().strip()
        if country_lower == "poland":
            country_code = "PL"
            continue
        if country_lower == "united states":
            country_code = "US"
            continue
        if country_lower == "united kingdom":
            country_code = "GB"
            continue
        if country_lower in ("germany", "deutschland"):
            country_code = "DE"
            continue
        if country_lower == "netherlands":
            country_code = "NL"
            continue

        # Phone number (digits only, 10-12 chars)
        if re.match(r"^\d{10,12}$", line):
            phone = line
            continue

        address_parts.append(line)

    address_line1 = address_parts[0] if address_parts else ""
    address_line2 = address_parts[1] if len(address_parts) > 1 else None

    return Party(
        name=name,
        country_code=country_code,
        address_line1=address_line1,
        address_line2=address_line2,
        nip=nip,
        vat_id=vat_id,
        tax_id=tax_id or registration,
        phone=phone,
    )


def _extract_bill_parties(page: Any) -> tuple[Party, Party]:
    """Extract BILL FROM and BILL TO using word positions for column separation."""
    words = page.extract_words(keep_blank_chars=True)
    x_left_right, x_right_total = _find_column_splits(words)

    # Find y-range of the billing section: from BILL FROM to Scope/Description
    bill_y_start = None
    bill_y_end = None
    for w in words:
        text = _clean(w["text"])
        if text == "BILL FROM":
            bill_y_start = w["top"]
        if text in ("Scope", "Description") and bill_y_start and w["top"] > bill_y_start + 20:
            bill_y_end = w["top"]
            break

    if bill_y_start is None:
        raise ValueError("Cannot find BILL FROM section")
    if bill_y_end is None:
        bill_y_end = bill_y_start + 200

    # Filter words: skip header row, exclude TOTAL DUE column
    billing_words = [w for w in words if bill_y_start + 8 < w["top"] < bill_y_end and w["x0"] < x_right_total]

    left_lines, right_lines = _group_words_into_lines(billing_words, x_left_right)

    seller = _parse_party_lines(left_lines)
    buyer = _parse_party_lines(right_lines)

    return seller, buyer


def parse_deel_pdf(pdf_path: Path) -> DeelInvoice:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        full_text = _clean("\n".join(p.extract_text() or "" for p in pdf.pages))

        if not full_text.strip():
            raise ValueError(f"No text extracted from {pdf_path}")

        seller, buyer = _extract_bill_parties(page)

    # Invoice number
    inv_match = re.search(r"Invoice\s*#\s*(\S+)", full_text)
    if not inv_match:
        raise ValueError("Cannot find invoice number")
    invoice_number = inv_match.group(1)

    # Dates
    issue_match = re.search(r"Issue\s+date\s+(.+?)(?:\n|Due)", full_text, re.IGNORECASE)
    if not issue_match:
        raise ValueError("Cannot find issue date")
    issue_date = _parse_date(issue_match.group(1))

    due_match = re.search(r"Due\s+date\s+(.+?)(?:\n|BILL)", full_text, re.IGNORECASE)
    due_date = _parse_date(due_match.group(1)) if due_match else None

    # Currency
    curr_match = re.search(r"\b(PLN|USD|EUR|GBP|CHF)\b", full_text)
    currency = curr_match.group(1) if curr_match else "PLN"

    # Amounts
    total_match = re.search(r"^Total\s+(.+)$", full_text, re.MULTILINE)
    total_gross = _parse_amount(total_match.group(1)) if total_match else Decimal("0")
    sub_match = re.search(r"Sub\s*total\s+(.+)$", full_text, re.MULTILINE)
    total_net = _parse_amount(sub_match.group(1)) if sub_match else total_gross
    vat_match = re.search(r"VAT\s+(\d+)%\s+(.+)$", full_text, re.MULTILINE)
    total_vat = _parse_amount(vat_match.group(2)) if vat_match else Decimal("0")

    # VAT rate
    vat_rate = "np"
    if vat_match:
        rate_pct = vat_match.group(1)
        vat_rate = "np" if rate_pct == "0" else rate_pct

    # Service period
    period_match = re.search(
        r"Invoice\s+for\s+work\s+between\s+(.+?)\s+to\s+(.+?)(?:\n|$)",
        full_text,
        re.IGNORECASE,
    )
    service_period = None
    if period_match:
        service_period = ServicePeriod(
            date_from=_parse_date(period_match.group(1)),
            date_to=_parse_date(period_match.group(2)),
        )

    # Line items
    rate_match = re.search(r"Fixed\s+rate:\s+Monthly\s+payment\s+(.+)$", full_text, re.MULTILINE)
    if rate_match:
        amount = _parse_amount(rate_match.group(1))
        if period_match:
            period_desc = f"{period_match.group(1).strip()} to {period_match.group(2).strip()}"
        else:
            period_desc = "monthly payment"
        line_items = [
            LineItem(
                description=f"Fixed contract — {period_desc}",
                quantity=Decimal("1"),
                unit_price_net=amount,
                net_amount=amount,
                vat_rate=vat_rate,
                vat_amount=total_vat,
                gross_amount=amount + total_vat,
            )
        ]
    else:
        line_items = [
            LineItem(
                description="Deel platform services",
                quantity=Decimal("1"),
                unit_price_net=total_net,
                net_amount=total_net,
                vat_rate=vat_rate,
                vat_amount=total_vat,
                gross_amount=total_gross,
            )
        ]

    # Deel reference
    ref_match = re.search(r"Deel\s+Ref\.?:\s*(\S+)", full_text)
    deel_reference = ref_match.group(1) if ref_match else None

    return DeelInvoice(
        invoice_number=invoice_number,
        issue_date=issue_date,
        due_date=due_date,
        currency=currency,
        seller=seller,
        buyer=buyer,
        service_period=service_period,
        line_items=line_items,
        total_net=total_net,
        total_vat=total_vat,
        total_gross=total_gross,
        deel_reference=deel_reference,
    )
