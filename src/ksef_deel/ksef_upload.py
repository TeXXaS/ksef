"""Upload validated invoice XML to KSeF using the ksef2 library.

Flow:
1. Authenticate with KSeF token (or test certificate for TEST env)
2. Open online session
3. Send encrypted invoice
4. Wait for processing confirmation
5. Close session
"""

import logging
from dataclasses import dataclass

from ksef2 import Client, Environment, FormSchema

from ksef_deel.config import KsefConfig, KsefEnvironment

logger = logging.getLogger(__name__)

_ENV_MAP = {
    KsefEnvironment.TEST: Environment.TEST,
    KsefEnvironment.DEMO: Environment.DEMO,
    KsefEnvironment.PROD: Environment.PRODUCTION,
}


@dataclass(frozen=True)
class UploadResult:
    invoice_reference: str
    ksef_number: str | None
    status: str


def upload_invoice(config: KsefConfig, invoice_xml: bytes) -> UploadResult:
    """Upload a single invoice XML to KSeF.

    For TEST environment, uses auto-generated test certificate.
    For DEMO/PROD, uses token from config.
    """
    env = _ENV_MAP[config.environment]
    client = Client(env)

    logger.info("Authenticating with KSeF (%s) for NIP %s", config.environment.value, config.nip)

    if config.environment == KsefEnvironment.TEST:
        auth = client.authentication.with_test_certificate(nip=config.nip)
    else:
        auth = client.authentication.with_token(
            ksef_token=config.token,
            nip=config.nip,
        )

    logger.info("Opening online session...")
    with auth.online_session(form_code=FormSchema.FA2) as session:
        logger.info("Session opened.")

        result = session.send_invoice(invoice_xml=invoice_xml)
        logger.info("Invoice submitted, reference: %s", result.reference_number)

        status = session.wait_for_invoice_ready(
            invoice_reference_number=result.reference_number,
        )
        logger.info("Invoice processed: ksef_number=%s, status=%s", status.ksef_number, status.status)

        return UploadResult(
            invoice_reference=result.reference_number,
            ksef_number=status.ksef_number,
            status=str(status.status),
        )
