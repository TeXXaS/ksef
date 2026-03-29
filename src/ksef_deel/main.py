"""CLI entry point for ksef-deel: upload, list, and download KSeF invoices."""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from ksef_deel.config import KsefConfig, load_config

logger = logging.getLogger("ksef_deel")


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to config file (default: config.toml)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _load_config(args: argparse.Namespace) -> KsefConfig:
    if not args.config.exists():
        logger.error("Config file not found: %s", args.config)
        logger.error("Copy config.example.toml to config.toml and fill in your details")
        sys.exit(1)
    return load_config(args.config)


def _cmd_upload(args: argparse.Namespace) -> None:
    from ksef_deel.deel_parser import parse_deel_pdf
    from ksef_deel.invoice_xml import generate_invoice_xml
    from ksef_deel.ksef_upload import upload_invoice
    from ksef_deel.validator import ValidationError, validate_invoice_xml

    _setup_logging(args.verbose)
    config = _load_config(args)

    if not args.pdf.exists():
        logger.error("PDF file not found: %s", args.pdf)
        sys.exit(1)

    # Step 1: Parse Deel PDF
    logger.info("Parsing Deel invoice: %s", args.pdf)
    invoice = parse_deel_pdf(args.pdf)
    logger.info(
        "Parsed: %s | %s | %s %s | %s",
        invoice.invoice_number,
        invoice.issue_date,
        invoice.total_gross,
        invoice.currency,
        invoice.seller.name,
    )

    if invoice.seller.nip != config.nip:
        logger.warning(
            "Invoice seller NIP (%s) differs from config NIP (%s)",
            invoice.seller.nip,
            config.nip,
        )

    # Step 2: Generate FA(2) XML
    logger.info("Generating FA(2) XML...")
    xml_bytes = generate_invoice_xml(invoice)

    # Step 3: Validate against XSD
    logger.info("Validating against FA(2) XSD schema...")
    try:
        validate_invoice_xml(xml_bytes)
        logger.info("Validation PASSED")
    except ValidationError as e:
        logger.error("Validation FAILED:")
        for err in e.errors:
            logger.error("  %s", err)
        sys.exit(2)

    # Step 4: Save XML if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(xml_bytes)
        logger.info("XML saved to %s", args.output)

    # Step 5: Upload to KSeF
    should_upload = not args.dry_run and (not args.output or args.upload)
    if not should_upload:
        if args.dry_run:
            logger.info("Dry run — skipping upload")
        else:
            logger.info("XML saved to %s — skipping upload (use --upload to force)", args.output)
        sys.exit(0)

    logger.info("Uploading to KSeF (%s)...", config.environment.value)
    result = upload_invoice(config, xml_bytes)
    logger.info("Upload successful!")
    logger.info("  Invoice reference:  %s", result.invoice_reference)
    if result.ksef_number:
        logger.info("  KSeF number:        %s", result.ksef_number)
    logger.info("  Status:             %s", result.status)


def _cmd_list(args: argparse.Namespace) -> None:
    from ksef_deel.ksef_fetch import list_invoices

    _setup_logging(args.verbose)
    config = _load_config(args)

    date_from = args.date_from
    date_to = args.date_to

    invoices = list_invoices(config, date_from=date_from, date_to=date_to)

    if not invoices:
        print("No invoices found.")
        return

    print(f"{'KSeF number':<50} {'Invoice #':<20} {'Issue date':<12} {'Gross':>12} {'Currency':<5} {'Buyer'}")
    print("-" * 130)
    for inv in invoices:
        print(
            f"{inv.ksef_number:<50} {inv.invoice_number:<20} {inv.issue_date!s:<12} "
            f"{inv.gross_amount:>12.2f} {inv.currency:<5} {inv.buyer_name}"
        )


def _cmd_download(args: argparse.Namespace) -> None:
    from ksef_deel.ksef_fetch import download_invoice

    _setup_logging(args.verbose)
    config = _load_config(args)

    xml_bytes = download_invoice(config, args.ksef_number)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(xml_bytes)
        logger.info("Invoice saved to %s", args.output)
    else:
        sys.stdout.buffer.write(xml_bytes)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload Deel.com invoices to KSeF (Krajowy System e-Faktur)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- upload ---
    upload_parser = subparsers.add_parser("upload", help="Parse Deel PDF, validate, and upload to KSeF")
    _add_common_args(upload_parser)
    upload_parser.add_argument("pdf", type=Path, help="Path to Deel invoice PDF")
    upload_parser.add_argument("--dry-run", action="store_true", help="Generate and validate XML without uploading")
    upload_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Save generated XML to file (implies --dry-run unless --upload also specified)",
    )
    upload_parser.add_argument("--upload", action="store_true", help="Force upload even when --output is specified")
    upload_parser.set_defaults(func=_cmd_upload)

    # --- list ---
    list_parser = subparsers.add_parser("list", help="List invoices stored in KSeF")
    _add_common_args(list_parser)
    list_parser.add_argument(
        "--from",
        dest="date_from",
        type=_parse_date,
        default=date.today() - timedelta(days=90),
        help="Start date (YYYY-MM-DD, default: 90 days ago)",
    )
    list_parser.add_argument(
        "--to",
        dest="date_to",
        type=_parse_date,
        default=None,
        help="End date (YYYY-MM-DD, default: today)",
    )
    list_parser.set_defaults(func=_cmd_list)

    # --- download ---
    download_parser = subparsers.add_parser("download", help="Download invoice XML from KSeF")
    _add_common_args(download_parser)
    download_parser.add_argument("ksef_number", help="KSeF invoice number")
    download_parser.add_argument("-o", "--output", type=Path, help="Save XML to file (default: stdout)")
    download_parser.set_defaults(func=_cmd_download)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
