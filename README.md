# Compliance Scanner

A local document scanner that detects sensitive and confidential information before you upload files to online AI tools. Everything runs 100% locally — no data is ever sent to the internet.

## What it detects

| Category | Severity | Examples |
|---|---|---|
| National ID numbers (NO/SE) | 🟥 Critical | Fødselsnummer, personnummer, D-nummer, samordningsnummer |
| Bank & payment data | 🟥 Critical | Account numbers, credit cards, IBAN, bankgiro/plusgiro |
| API keys & secrets | 🟧 High | OpenAI keys, GitHub tokens, AWS keys, JWT tokens, private keys |
| National IDs (UK/US) | 🟥 Critical | UK National Insurance, US Social Security Number |
| Business confidential | 🟨 Medium | Hourly rates, project sums, margins, discounts |
| Personal data | 🟨 Medium | E-mail addresses, phone numbers, names (NER), org numbers |
| Confidential documents | 🟧 High | Documents marked as confidential |

## Supported file types

`.pdf` · `.docx` · `.pptx` · `.xlsx` · `.md` · `.txt` · `.html`

## Language support

- 🇳🇴 Norwegian — Norwegian national IDs, org numbers, account numbers, phone numbers
- 🇸🇪 Swedish — personnummer, samordningsnummer, org numbers, bankgiro
- 🇬🇧 English — UK NI numbers, US SSN; also applies Norwegian and Swedish patterns

## Installation

Requires [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/telboth/compliance-scanner.git
cd compliance-scanner
uv sync
uv run xlent-scanner
```

On first run, spaCy language models are downloaded automatically (~50 MB each).

## Windows installer (internal MVP)

Build app bundle:

```powershell
.\scripts\build_win.ps1 -Clean
```

Package installer (`.exe`) with Inno Setup 6:

```powershell
.\scripts\package_win.ps1
```

Outputs:

- App bundle: `artifacts\windows\app\dist\XLENTScanner`
- Installer: `artifacts\windows\installer`

## macOS installer (internal MVP)

Build app bundle:

```bash
./scripts/build_mac.sh --clean
```

Package `.dmg`:

```bash
./scripts/package_mac.sh
```

Outputs:

- App bundle: `artifacts/macos/app/dist/XLENTScanner.app`
- Installer: `artifacts/macos/installer`

## Usage

1. Start the app with `uv run xlent-scanner`
2. Drag and drop a document onto the scanner, or click to browse
3. Review the findings — each finding shows category, severity, and surrounding context
4. Use the **Settings** tab to set document language and filter out internal company names
5. Add false positives to the whitelist so they are not flagged in future scans

## Internal release flow

From repository root:

```powershell
.\push_to_git.ps1 -Visibility public -CommitMessage "chore: update"
.\create_release.ps1 -AutoCommit -CommitMessage "chore: prepare release"
```

`create_release.ps1` reads version from `src/xlent_scanner/__init__.py`, creates tag `v<version>`, pushes tag, creates/fetches GitHub Release, and uploads installer assets found in:

- `artifacts/windows/installer/*`
- `artifacts/macos/installer/*`

## Architecture

- **Document extraction**: [Docling](https://github.com/DS4SD/docling) (IBM) converts PDF/DOCX/PPTX/XLSX → Markdown text
- **Detection**: Regex detectors + [spaCy](https://spacy.io/) NER for person names + entropy-based secret detection
- **GUI**: [PyWebView](https://pywebview.flowrl.com/) with an embedded Flask server (all local, no internet)
- **Risk engine**: Four levels — grønn / gul / rød / svart (green / yellow / red / black)
