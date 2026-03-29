# ksef-deel

Yes. That stupid new thing...

Upload Deel.com contractor invoices (PDF) to KSeF (Krajowy System e-Faktur). Because apparently we have to.

Parses Deel PDF invoices, generates FA(2) XML conforming to the KSeF schema, validates against XSD, and uploads via the KSeF API.

## Requirements

- Python 3.12+
- System dependencies: none (pure Python, `lxml` ships pre-built wheels)

## Setup

### Option A: virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Option B: system-wide

```bash
pip install --user -e .
```

Make sure `~/.local/bin` is in your `PATH`.

### Dev dependencies (ruff, mypy, pytest, faker)

```bash
pip install -e ".[dev]"
```

### Configuration

```bash
cp config.example.toml config.toml
```

Edit `config.toml`:

```toml
[ksef]
environment = "test"       # "test", "demo", or "prod"
nip = "YOUR_NIP_HERE"     # Polish taxpayer NIP (10 digits)
token = ""                 # KSeF token, required only for prod/demo
```

For **test** environment, only `nip` is needed -- authentication uses auto-generated test certificates.

For **prod/demo**, generate a token via the [KSeF web portal](https://ksef.mf.gov.pl).

## Usage

### Upload a Deel invoice

```bash
# Dry run -- parse, generate XML, validate, but don't upload
ksef-deel upload invoice.pdf --dry-run

# Save generated XML to file
ksef-deel upload invoice.pdf -o output.xml

# Upload to KSeF
ksef-deel upload invoice.pdf

# Save XML and upload
ksef-deel upload invoice.pdf -o output.xml --upload
```

### List invoices stored in KSeF

```bash
# Last 90 days (default)
ksef-deel list

# Custom date range
ksef-deel list --from 2025-10-01 --to 2025-12-31
```

### Download invoice XML from KSeF

```bash
# Print to stdout
ksef-deel download <ksef-number>

# Save to file
ksef-deel download <ksef-number> -o invoice.xml
```

### Update XSD schemas

Schemas are cached locally in `schema/` and checked for freshness every 60 days. To force a refresh:

```bash
ksef-deel schema-update
```

## Testing

```bash
# Unit tests only
pytest

# Integration tests (requires config.toml, hits KSeF TEST environment)
pytest -m integration

# All tests
pytest -m ""
```

## Linting and type checking

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
```
