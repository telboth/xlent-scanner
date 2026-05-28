# XLENT Compliance-scanner

> **v1.0.0** — Lokal scanner som oppdager sensitiv kundeinfo i dokumenter _før_ du limer dem inn i ChatGPT, Claude eller Copilot.

Alt kjøres 100 % lokalt — ingen dokumenter, tekst eller funn sendes over internett.

---

## Funksjoner

### Rask scanner

- **Drag-and-drop** — slipp en fil rett på vinduet
- **Bla-til-fil** — velg fil fra disk
- **Lim inn tekst** — skann tekst direkte (uten å lagre en fil)
- **Mappeskann** — velg en mappe og skann alle støttede filer i én operasjon; resultat vises som en sorterbar oversikt

### Dybdeskann med AI (Ollama)

- Sender dokumentteksten til en lokal AI-modell (Ollama) for å fange funn som regex-motoren kan misse
- Velg kategorier: navn, adresser, e-post, telefon, personnummer, bankkontonummer, selskapsnavn, budsjett/beløp
- **Konfidensfilter**: filtrer funn på `høy` / `medium` / `lav` konfidensgrad
- Viser GPU/CPU-badge under kjøring
- Anonymiser valgte AI-funn direkte til `.docx`, `.pptx`, `.xlsx`, `.pdf` eller `.txt`

### Resultater og eksport

- Trafikklysnivå: grønn / gul / rød / svart
- Klikk-til-hviteliste for falske positive
- Anonymisering med konsistente etiketter: `<Person A>`, `<Konto 1>`, `[ANONYMISERT]`
- Eksporter funn som **JSON** eller **CSV**
- Last ned **PDF-rapport** direkte fra scanner-tabben
- **Persistent historikk** lagres mellom øktene (`%APPDATA%/xlent-scanner/scan_history.jsonl`)

---

## Hva oppdages

| Kategori | Alvorlighetsgrad | Eksempler |
|---|---|---|
| Fødselsnummer / D-nummer (NO) | ⛔ Svart | Mod-11-validering |
| Personnummer / Samordningsnummer (SE) | ⛔ Svart | Mod-11-validering |
| CPR-nummer (DK) | ⛔ Svart | Mod-11-validering |
| Bankkontonummer (NO) | ⛔ Svart | 11 siffer, mod-11 |
| Kredittkort | ⛔ Svart | Luhn-validering |
| IBAN | ⛔ Svart | Internasjonal bank-ID |
| API-nøkler og hemmeligheter | 🚫 Rød | OpenAI-nøkler, GitHub-tokens, AWS-nøkler, JWT, private keys |
| Personnavn | 🚫 Rød | Via spaCy NER (NO, SE, EN, DA) |
| E-postadresser | 🚫 Rød | Regex |
| Telefonnummer (NO) | 🚫 Rød | 8 siffer + `+47`/`0047`-prefiks |
| UK NI / US SSN | ⛔ Svart | Nasjonale ID-numre |
| Organisasjonsnummer (NO) | ⚠️ Gul | Mod-11-validering |
| Bankgiro / Plusgiro (SE) | ⚠️ Gul | Regex |
| Kommersielle nøkkeltall | ⚠️ Gul | Timepris, dagspris, prosjektsum, margin, rabatt |
| Konfidensielle nøkkelord | ⚠️ Gul | «konfidensielt», «hemmelig», «intern», «fortrolig» |
| Klientnavn | ⚠️ Gul | Intern klientliste (`ignore.toml`) |
| Høy-entropi-strenger | ⚠️ Gul | Mulige hemmelige nøkler (Base64, hex) |

---

## Filformater

`.pdf` · `.docx` · `.pptx` · `.xlsx` · `.md` · `.txt` · `.html`

---

## Språkstøtte

| Flagg | Språk | Mønstre |
|---|---|---|
| 🇳🇴 | Norsk | Fødselsnummer, D-nummer, organisasjonsnummer, kontonummer, telefon |
| 🇸🇪 | Svensk | Personnummer, samordningsnummer, org.nummer, bankgiro, plusgiro |
| 🇩🇰 | Dansk | CPR-nummer (mod-11) |
| 🇬🇧 | Engelsk | UK NI, US SSN; norske og svenske mønstre gjelder også |

Språk auto-detekteres, eller velges manuelt i Innstillinger-tabben.

---

## Installasjon (utvikling)

Krever [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/telboth/xlent-scanner.git
cd xlent-scanner
uv sync
uv run xlent-scanner
```

Ved første oppstart lastes spaCy-språkmodeller ned automatisk (~50 MB per modell).

---

## Installasjon (Windows — intern MVP)

Last ned `xlent-scanner-setup-<versjon>.exe` fra [Releases](https://github.com/telboth/xlent-scanner/releases) og kjør installasjonsprogrammet.

---

## Installasjon (macOS — intern MVP)

Last ned `xlent-scanner-macos-<versjon>.dmg` fra [Releases](https://github.com/telboth/xlent-scanner/releases).

1. Åpne DMG-filen og dra **XLENTScanner** til **Applications**-mappen
2. **Første gangs oppstart**: macOS Gatekeeper kan blokkere appen fordi den ikke er signert. Høyreklikk på appen og velg **Åpne**, deretter bekreft i dialogboksen.

> Appen er bygget for Apple Silicon (M-series). Intel Mac-brukere kan kjøre fra kildekode med `uv run xlent-scanner`.

---

## Bruk

1. Start appen (`uv run xlent-scanner` eller dobbeltklikk på installert snarvei)
2. Velg modus øverst i scanner-tabben:
   - **Fil** — dra og slipp, eller klikk «Velg fil»
   - **Lim inn** — lim inn tekst direkte i tekstfeltet
   - **Mappe** — velg en mappe for å skanne alle filer
3. Se gjennom funnene — hvert funn viser kategori, alvorlighetsgrad og tekstkontekst
4. Klikk **+ Hviteliste** på falske positive for å filtrere dem ut i fremtiden
5. Bruk **Anonymiser valgte** for å generere en renset versjon av filen
6. Last ned **PDF-rapport** fra toolbar-raden for en fullstendig rapport
7. For dypere analyse, bytt til **Dybdeskann**-tabben (krever Ollama)

---

## Dybdeskann (Ollama)

1. Installer [Ollama](https://ollama.ai) og last ned en modell:
   ```bash
   ollama pull llama3.2:3b
   ```
2. Skann en fil i Rask scanner-tabben
3. Bytt til **Dybdeskann**-tabben — filen er automatisk lastet inn
4. Velg kategorier og **konfidensfilter** (høy = bare sikre funn)
5. Klikk **Start dybdeskann**

Anbefalt maskin: minst 8 GB RAM. GPU-akselerasjon (NVIDIA/AMD) brukes automatisk.

---

## Bygg og pakking (Windows)

```powershell
# Bygg app-bundle med PyInstaller
.\scripts\build_win.ps1

# Pakk installer (.exe) med Inno Setup 6
.\scripts\package_win.ps1
```

Resultater:
- App-bundle: `artifacts\windows\app\dist\XLENTScanner\`
- Installer: `artifacts\windows\installer\xlent-scanner-setup-<versjon>.exe`

---

## Utgivelse

```powershell
# Tag og push
git tag v0.9.19
git push origin v0.9.19

# Opprett GitHub Release med installer
$env:GH_TOKEN = "<token>"
gh release create "v0.9.19" "artifacts/windows/installer/xlent-scanner-setup-0.9.19.exe" `
  --title "v0.9.19 – ..." --notes "..."
```

---

## Arkitektur

```
src/xlent_scanner/
├── app.py              # Flask-server + PyWebView-vindu
├── scanner.py          # Orkestrerer alle detektorer; scan_file / scan_text / scan_folder
├── deep_scanner.py     # Chunked Ollama-analyse med konfidensfiltrering
├── anonymize.py        # build_replacements() + patch_file() for docx/pptx/xlsx/pdf
├── history.py          # Persistent JSONL-historikk (%APPDATA%/xlent-scanner/)
├── language.py         # Språkdeteksjon + spaCy-konfigurasjon (nb/sv/en/da)
├── utils.py            # Felles ctx()-hjelpefunksjon
├── patch.py            # Teksterstattning i docx/pptx/xlsx/pdf
├── report.py           # HTML-rapportgenerering
├── whitelist.py        # Personlig hviteliste
├── ignore.py           # ignore.toml (XLENT-interne navn etc.)
├── update_check.py     # Sjekker GitHub Releases for ny versjon
├── models.py           # Finding + ScanResult dataklasser
├── detectors/
│   ├── regex_no.py     # Norske mønstre (fnr, orgnr, konto, telefon)
│   ├── regex_sv.py     # Svenske mønstre (personnummer, bankgiro)
│   ├── regex_da.py     # Danske mønstre (CPR-nummer, mod-11)
│   ├── regex_en.py     # Engelske mønstre (NI, SSN)
│   ├── ner_names.py    # spaCy NER for personnavn
│   ├── secrets.py      # API-nøkler, tokens, høy-entropi-strenger
│   ├── creditcards.py  # Kredittkort (Luhn)
│   ├── iban.py         # IBAN
│   ├── financials.py   # Kommersielle nøkkeltall
│   ├── keywords.py     # Konfidensielle nøkkelord
│   └── clients.py      # Klientnavn fra ignore.toml
└── web/
    └── index.html      # Komplett frontend (PyWebView + embedded Flask)
```

**Teknologistakk:**
- Dokumentekstraksjon: [Docling](https://github.com/DS4SD/docling) (IBM) — PDF/DOCX/PPTX/XLSX → tekst
- NER: [spaCy](https://spacy.io/) med `nb_core_news_sm`, `sv_core_news_sm`, `en_core_web_sm`, `da_core_news_sm`
- GUI: [PyWebView](https://pywebview.flowrl.com/) med innebygd Flask-server
- AI-dybdeskann: [Ollama](https://ollama.ai) REST API (`/api/generate`)
- PDF-anonymisering og -rapport: [PyMuPDF](https://pymupdf.readthedocs.io/) (fitz)
- Risikomotor: fire nivåer — grønn / gul / rød / svart

---

## Endringslogg

### v1.0.0
- Dansk NER bruker norsk bokmål-modell (nb_core_news_sm) — da_core_news_sm fjernet

### v0.9.20
- **Test suite** — automatiske tester for alle detektorer (`tests/`); integrasjonstest mot `i_english.docx`
- **URL-kategori i dybdeskann** — ny kategori «Nettadresser» (http/https/www) i AI-dybdeskann
- **Inline dybdeskann** — kollapsibelt 🔬 dybdeskann-panel vises direkte i scanner-tabben etter fil-skanning

### v0.9.19
- Paste-tekst-modus og mappeskann-modus i scanner-tabben
- Persistent historikk (JSONL) mellom øktene
- PDF-rapport-nedlasting
- Konfidensfilter i dybdeskann (høy/medium/lav)
- Dansk CPR-nummer (mod-11)
- Konsistente anonymiserings-etiketter
- `0047 12345678` (telefon med 1-prefiks) gjenkjennes nå
- Teknisk gjeld: felles `utils.py`, ny `history.py`, ny `regex_da.py`

### v0.9.18
- Støtte for anonymisering til original filformat (`.docx`, `.pptx`, `.xlsx`, `.pdf`)
- Dynamisk etikett på anonymiserings-knapp
- Telefon: `0047`-prefiks + ny regex-struktur
- AI-dybdeskann: e-post som ny kategori; forbedrede eksempler i systempromptet

### v0.9.17
- Kontonummer i 4-4-3-format med mellomrom (`1730 1777 922`) støttes nå

### v0.9.16
- NER-filter for svenske personnavn (spaCy)
- Ny regex for kontonummer og personnummer
- E-postkategori i dybdeskann

### v0.9.15 og tidligere
- Grunnfunksjoner: scanner, dybdeskann, hviteliste, NER, innstillinger, oppdateringssjekk

---

*Skrevet av thomas.elboth@xlent.no*
