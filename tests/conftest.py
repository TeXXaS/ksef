"""Shared test fixtures."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from faker import Faker

from ksef_deel.config import KsefConfig, KsefEnvironment, load_config
from ksef_deel.invoice_model import DeelInvoice, LineItem, Party, ServicePeriod

fake = Faker()

CONFIG_PATH = Path("config.toml")


@pytest.fixture(scope="session")
def ksef_config() -> KsefConfig:
    """Load KSeF config from config.toml, forcing TEST environment."""
    if not CONFIG_PATH.exists():
        pytest.skip("config.toml not found — cannot run integration tests")
    config = load_config(CONFIG_PATH)
    return KsefConfig(environment=KsefEnvironment.TEST, nip=config.nip)


@pytest.fixture()
def test_invoice(ksef_config: KsefConfig) -> DeelInvoice:
    """Minimal test invoice: anonymized seller (NIP from config), random buyer, 1 PLN."""
    today = date.today()

    seller = Party(
        name="Test Seller",
        country_code="PL",
        address_line1="ul. Testowa 1",
        address_line2="00-001 Warszawa",
        nip=ksef_config.nip,
    )

    buyer = Party(
        name=fake.company(),
        country_code="US",
        address_line1=f"{fake.building_number()} {fake.street_name()}",
        address_line2=f"{fake.city()}, {fake.state_abbr()} {fake.zipcode()}",
        tax_id=fake.ein(),
    )

    return DeelInvoice(
        invoice_number=f"TEST-{fake.unique.random_int(min=100000, max=999999)}",
        issue_date=today,
        due_date=None,
        currency="PLN",
        seller=seller,
        buyer=buyer,
        service_period=ServicePeriod(date_from=today.replace(day=1), date_to=today),
        line_items=[
            LineItem(
                description="good work",
                quantity=Decimal("1"),
                unit_price_net=Decimal("1.00"),
                net_amount=Decimal("1.00"),
                vat_rate="np",
                vat_amount=Decimal("0.00"),
                gross_amount=Decimal("1.00"),
            ),
        ],
        total_net=Decimal("1.00"),
        total_vat=Decimal("0.00"),
        total_gross=Decimal("1.00"),
    )
