"""Validate generated FA(2) XML against the KSeF XSD schema.

Schema source: http://crd.gov.pl/wzor/2023/06/29/12648/schemat.xsd
Dependencies are downloaded recursively and resolved locally via a custom URL resolver.
"""

from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree

if TYPE_CHECKING:
    from lxml.etree import _InputDocument

logger = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schema"
MAIN_SCHEMA_URL = "https://crd.gov.pl/wzor/2023/06/29/12648/schemat.xsd"
MAIN_SCHEMA_LOCAL = "FA_2_schemat.xsd"


def _ensure_schemas() -> Path:
    """Download main schema and all dependencies recursively."""
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)

    main_path = SCHEMA_DIR / MAIN_SCHEMA_LOCAL
    if not main_path.exists():
        logger.info("Downloading main schema: %s", MAIN_SCHEMA_URL)
        urllib.request.urlretrieve(MAIN_SCHEMA_URL, main_path)

    # Recursively find and download all referenced schemas
    to_check = [main_path]
    checked: set[str] = set()

    while to_check:
        xsd_file = to_check.pop()
        if str(xsd_file) in checked:
            continue
        checked.add(str(xsd_file))

        content = xsd_file.read_text(encoding="utf-8")
        for url in re.findall(r'schemaLocation="([^"]+\.xsd)"', content):
            filename = url.rsplit("/", 1)[-1]
            local_path = SCHEMA_DIR / filename
            if not local_path.exists():
                logger.info("Downloading dependency: %s", url)
                urllib.request.urlretrieve(url, local_path)
            if str(local_path) not in checked:
                to_check.append(local_path)

    return main_path


class _LocalResolver(etree.Resolver):
    """Resolve any remote schema URL to a local file if we have it cached."""

    def resolve(self, system_url: str, public_id: str, context: Any) -> _InputDocument | None:  # type: ignore[override]
        if system_url and ("crd.gov.pl" in system_url or system_url.endswith(".xsd")):
            filename = system_url.rsplit("/", 1)[-1]
            local_path = SCHEMA_DIR / filename
            if local_path.exists():
                return self.resolve_filename(str(local_path), context)  # type: ignore[attr-defined]
        return None


class ValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"XML validation failed with {len(errors)} error(s):\n" + "\n".join(errors))


def validate_invoice_xml(xml_bytes: bytes) -> None:
    """Validate invoice XML against FA(2) XSD schema.

    Raises ValidationError if the XML does not conform.
    """
    schema_path = _ensure_schemas()

    parser = etree.XMLParser()
    parser.resolvers.add(_LocalResolver())

    with open(schema_path, "rb") as f:
        schema_doc = etree.parse(f, parser)

    schema = etree.XMLSchema(schema_doc)
    doc = etree.fromstring(xml_bytes)

    if not schema.validate(doc):
        errors = [str(err) for err in schema.error_log]  # type: ignore[attr-defined]
        raise ValidationError(errors)

    logger.info("XML validation passed")


def validate_invoice_xml_report(xml_bytes: bytes) -> list[str]:
    """Validate and return list of errors (empty if valid)."""
    try:
        validate_invoice_xml(xml_bytes)
        return []
    except ValidationError as e:
        return e.errors
