"""Validate generated FA(2) XML against the KSeF XSD schema.

Schema source: http://crd.gov.pl/wzor/2023/06/29/12648/schemat.xsd
Dependencies are downloaded recursively and resolved locally via a custom URL resolver.

Schemas are cached locally. If the oldest file is >60 days old, all schemas are
re-downloaded. After a freshness check (even if remote hasn't changed), all files
are touched to reset the 60-day clock.

Force refresh: ``ksef-deel schema-update`` or ``_ensure_schemas(force_refresh=True)``.
"""

from __future__ import annotations

import logging
import os
import re
import time
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

SCHEMA_MAX_AGE_DAYS = 60


def _oldest_schema_age_days() -> float | None:
    """Return age in days of the oldest .xsd file in SCHEMA_DIR, or None if no files."""
    xsd_files = list(SCHEMA_DIR.glob("*.xsd"))
    if not xsd_files:
        return None
    oldest_mtime = min(f.stat().st_mtime for f in xsd_files)
    return (time.time() - oldest_mtime) / 86400


def _touch_all_schemas() -> None:
    """Touch all .xsd files to reset the staleness clock."""
    now = time.time()
    for f in SCHEMA_DIR.glob("*.xsd"):
        os.utime(f, (now, now))


def _download(url: str, dest: Path) -> None:
    logger.info("Downloading schema: %s", url)
    urllib.request.urlretrieve(url, dest)


def _download_all() -> Path:
    """Download main schema and all dependencies recursively."""
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)

    main_path = SCHEMA_DIR / MAIN_SCHEMA_LOCAL
    _download(MAIN_SCHEMA_URL, main_path)

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
            _download(url, local_path)
            if str(local_path) not in checked:
                to_check.append(local_path)

    return main_path


def _ensure_schemas(force_refresh: bool = False) -> Path:
    """Ensure schemas are present and fresh. Re-downloads if >60 days old or forced."""
    main_path = SCHEMA_DIR / MAIN_SCHEMA_LOCAL

    age = _oldest_schema_age_days()

    if force_refresh or age is None or age > SCHEMA_MAX_AGE_DAYS:
        if age is not None and age > SCHEMA_MAX_AGE_DAYS:
            logger.info("Schemas are %.0f days old (max %d) — refreshing...", age, SCHEMA_MAX_AGE_DAYS)
        _download_all()
        _touch_all_schemas()
    elif not main_path.exists():
        _download_all()
        _touch_all_schemas()

    if not main_path.exists():
        raise FileNotFoundError(f"Schema not found: {main_path}. Run 'ksef-deel schema-update' to download.")

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
