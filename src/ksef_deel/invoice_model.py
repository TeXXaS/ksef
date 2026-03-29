from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Party:
    """Invoice party — seller or buyer."""

    name: str
    country_code: str  # ISO 3166-1 alpha-2
    address_line1: str
    address_line2: str | None = None
    nip: str | None = None  # Polish NIP (10 digits), if applicable
    vat_id: str | None = None
    tax_id: str | None = None  # Tax ID / registration number
    phone: str | None = None


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: Decimal
    unit_price_net: Decimal
    net_amount: Decimal
    vat_rate: str  # "np" for not-taxable, "zw" for exempt, "23", "8", "0", etc.
    vat_amount: Decimal
    gross_amount: Decimal
    unit: str = "usł."  # "usługa" (service) by default


@dataclass(frozen=True)
class ServicePeriod:
    date_from: date
    date_to: date


@dataclass(frozen=True)
class DeelInvoice:
    invoice_number: str
    issue_date: date
    due_date: date | None
    currency: str  # ISO 4217
    seller: Party  # The contractor (Polish taxpayer)
    buyer: Party  # The client company (foreign)
    service_period: ServicePeriod | None
    line_items: list[LineItem] = field(default_factory=list)
    total_net: Decimal = Decimal("0")
    total_vat: Decimal = Decimal("0")
    total_gross: Decimal = Decimal("0")
    deel_reference: str | None = None
