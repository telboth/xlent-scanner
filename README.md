# XLENT Compliance-scanner

> **v1.7.0** — Lokal scanner som oppdager sensitiv kundeinfo i dokumenter _før_ du limer dem inn i ChatGPT, Claude eller Copilot.

Alt kjøres 100 % lokalt — ingen dokumenter, tekst eller funn sendes over internett.

---

## Funksjoner

### Scanner

- **Drag-and-drop** — slipp én eller **flere filer** rett på vinduet (flere filer → batch-oversikt)
- **Bla-til-fil** — velg fil fra disk
- **Lim inn tekst** — skann tekst direkte (uten å lagre en fil)
- **Mappeskann** — velg en mappe og skann støttede filer i én operasjon, valgfritt også i undermapper
- **Kategorifilter** — velg hvilke typer funn du vil se (personnummer/ID inkl. passnummer, bankdetaljer, finansielle nøkkeltall inkl. lønn, navn, secrets, …)

### AI-dybdeskann (Ollama) — innebygd i scanner-fanen

- Huk av **🔬 Kjør AI-dybdeskann** før du skanner, så analyseres dokumentet også av en lokal AI-modell (Ollama)
- Fanger funn som regelmotoren kan misse (adresser, selskapsnavn, kontekstuelle navn)
- AI-funnene **flettes rett inn i den vanlige funnlisten** med samme alvorlighetsgrad-klassifisering
- AI-dybdeskann fokuserer på kategorier der kontekst hjelper, mens regex-dekkede kategorier (e-post, URL/IP, telefon, org.nummer, personnummer/ID, kredittkort og konfidensielle ord) håndteres av vanlig scan for bedre hastighet
- Regelbaserte detektorer (personnummer, e-post, konto, IBAN, URL) **supplerer** AI-en automatisk for pålitelig dekning uten å bruke Ollama på samme mønstre på nytt
- **Konfidensfilter**: `høy` / `medium` / `lav`
- **Re-skann**-knapp + inline statusindikator med fremdriftsbar, delstatus og estimert gjenstående tid
- **Stopp aktiv AI-modell** i Innstillinger for å frigjøre minne/CPU/GPU uten å stoppe Ollama-tjenesten
- Ollama-adresse kan overstyres med miljøvariabelen `OLLAMA_BASE_URL`

### Resultater og eksport

- **Trafikklysnivå**: grønn / gul / rød / svart
- **Sammendragsrad** øverst: fargede badges med antall per alvorlighetsgrad (⛔ / 🚫 / ⚠️)
- **📋 Kopier funn** — kopier alle funn (regel + AI) til utklippstavlen
- **🗑 Tøm** — nullstill resultatet
- Klikk-til-hviteliste for falske positive
- Anonymisering med konsistente etiketter: `<Person A>`, `<Konto 1>`, `[ANONYMISERT]`
- Eksporter funn som **JSON** eller **CSV**
- Generer anonymisert fil som **`.md`** eller **PDF**, eller in-place i `.docx` / `.pptx` / `.xlsx` / `.pdf`
- For innskannede bilde-/OCR-PDF-er kan appen lage **anonymisert bilde-PDF** ved å maskere OCR-treff direkte på sidebildene
- **HTML-rapport** og **PDF-rapport** — begge inkluderer både regelbaserte funn **og** AI-dybdeskann-funn
- **Persistent historikk** mellom øktene
- Valgt **språk og AI-modell huskes** mellom øktene (localStorage)
- Valgfri **Microsoft 365 / Graph-integrasjon** for å lese sensitivity/retention labels, vise rødt policyvarsel og skrive scan-metadata til SharePoint-felt

---

## Hva oppdages

| Kategori | Alvorlighetsgrad | Eksempler |
|---|---|---|
| Fødselsnummer / D-nummer (NO) | ⛔ Svart | Mod-11-validering |
| Personnummer / Samordningsnummer (SE) | ⛔ Svart | Mod-11-validering |
| CPR-nummer (DK) | ⛔ Svart | Mod-11-validering |
| Bankkontonummer (NO) | ⛔ Svart | 11 siffer, mod-11 |
| Kredittkort | ⛔ Svart | Luhn-validering |
| Bankgiro / Plusgiro (SE) | ⛔ Svart | Nøkkelord + siffer |
| UK NI / US SSN | ⛔ Svart | Nasjonale ID-numre |
| API-nøkler og hemmeligheter | 🚫 Rød | OpenAI, GitHub, AWS, JWT, private keys |
| IBAN | 🚫 Rød | MOD-97-validering |
| Passord i konfig | 🚫 Rød | `password=…`, connection strings |
| Konfidensielt (overskrift) | 🚫 Rød | «KONFIDENSIELT» i tittel/heading |
| Personnavn | ⚠️ Gul | Via spaCy NER (NO, SE, EN, DA, DE, FR, ES) |
| E-postadresser | ⚠️ Gul | Regex |
| Telefonnummer | ⚠️ Gul | NO/SE, 8 siffer + landkode |
| Organisasjonsnummer (NO) | ⚠️ Gul | Mod-11-validering |
| «Mulig personnummer (format)» | ⚠️ Gul | Riktig datoformat, men feil kontrollsiffer |
| Kommersielle nøkkeltall | ⚠️ Gul | Timepris, dagspris, prosjektsum, budsjett, margin, rabatt |
| Konfidensielle nøkkelord | ⚠️ Gul | «konfidensielt», «hemmelig», «intern», «fortrolig» |
| Nettadresser | ⚠️ Gul | http/https/www |
| Klientnavn | ⚠️ Gul | Intern klientliste (`clients.toml`) |
| Høy-entropi-strenger | ⚠️ Gul | Mulige hemmelige nøkler (Base64, hex) |

---

## Filformater

`.pdf` · `.docx` · `.pptx` · `.xlsx` · `.md` · `.txt` · `.html` · `.csv` · `.eml` · `.rtf` · `.odt`

### Bilde-/OCR-PDF-er

Vanlig PDF-anonymisering fungerer på PDF-ens tekstlag. Innskannede PDF-er har ofte ingen tekstlag; teksten ligger bare som piksler i sidebildet. For slike filer tilbyr appen en egen **Lagre anonymisert bilde-PDF**-flyt:

1. PDF-siden rendres til bilde.
2. OCR kjøres på sidebildet med koordinater.
3. Valgte funn matches mot OCR-ord/-linjer.
4. Treff maskeres direkte på sidebildet.
5. En ny bildebasert PDF skrives til disk.

Dette bevarer den skannede layouten langt bedre enn en OCR-tekst-PDF, men resultatet er rasterisert og normalt ikke søkbart. OCR kan også bomme på tekst eller koordinater, så den anonymiserte bilde-PDF-en må alltid kontrolleres før deling.

---

## Språkstøtte

| Flagg | Språk | Mønstre |
|---|---|---|
| 🇳🇴 | Norsk | Fødselsnummer, D-nummer, organisasjonsnummer, kontonummer, telefon |
| 🇸🇪 | Svensk | Personnummer, samordningsnummer, org.nummer, bankgiro, plusgiro |
| 🇩🇰 | Dansk | CPR-nummer (mod-11) |
| 🇬🇧 | Engelsk | UK NI, US SSN; norske og svenske mønstre gjelder også |
| 🇩🇪 | Tysk | Steuer-ID og sosialforsikringsnummer |
| 🇫🇷 | Fransk | Franske ID-/telefonmønstre |
| 🇪🇸 | Spansk | Spanske ID-/telefonmønstre |

Hele grensesnittet oversettes til **norsk, svensk, engelsk, tysk, fransk og spansk** via språkvelgeren øverst til høyre.
Dokumentspråk auto-detekteres, eller velges manuelt i Innstillinger-fanen.

---

## Installasjon (utvikling)

Krever [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/telboth/xlent-scanner.git
cd xlent-scanner
uv sync
uv run xlent-scanner
```

spaCy-språkmodeller lastes ned fra **Innstillinger → Name models (NER)** ved behov.

### Kommandolinje-modus (uten GUI)

```bash
uv run xlent-scanner --scan dokument.pdf            # menneskelesbar utskrift
uv run xlent-scanner --scan dokument.pdf --json     # JSON på stdout
uv run xlent-scanner --scan fil.docx --lang nb      # tving språk
```

Exit-kode reflekterer risikonivå: `0` grønn · `1` gul · `2` rød · `3` svart — nyttig i CI-pipelines.

---

## Installasjon (Windows — intern MVP)

Anbefalt: last ned og kjør `install_windows.ps1` fra [Releases](https://github.com/telboth/xlent-scanner/releases). Scriptet henter siste `xlent-scanner-setup-<versjon>.exe` og starter installasjonsprogrammet. Det krever **ikke** administrator.

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
```

Direkte fra GitHub uten å laste ned scriptet manuelt:

```powershell
$p = "$env:TEMP\install_windows.ps1"; Invoke-WebRequest "https://github.com/telboth/xlent-scanner/releases/latest/download/install_windows.ps1" -OutFile $p; powershell -ExecutionPolicy Bypass -File $p
```

Silent install:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 -Silent
```

Alternativt kan du laste ned `xlent-scanner-setup-<versjon>.exe` fra Releases og kjøre installasjonsprogrammet manuelt.

Installasjonen legger til **«Skann med XLENT»** i Windows høyreklikk-meny for alle filtyper. Høyreklikk en fil → filen åpnes og skannes automatisk. Kjører appen allerede, sendes filen til det eksisterende vinduet (single-instans IPC).

---

## Installasjon (Linux — intern MVP)

Last ned `xlent-scanner-linux-<versjon>-x86_64.AppImage` fra [Releases](https://github.com/telboth/xlent-scanner/releases).

```bash
chmod +x xlent-scanner-linux-*-x86_64.AppImage
./xlent-scanner-linux-*-x86_64.AppImage
```

AppImage-filen krever **ingen installasjon** og ingen root-rettigheter. Den kjører på Ubuntu 20.04+, Fedora 36+, Debian 11+ og de fleste andre moderne distros.

**Systemkrav:** `libwebkit2gtk-4.0` — er vanligvis allerede installert, men kan installeres med:
```bash
# Ubuntu/Debian:
sudo apt install libwebkit2gtk-4.0-dev

# Fedora:
sudo dnf install webkit2gtk4.0
```

> For tekniske brukere: `uv sync && uv run xlent-scanner` fra kildekoden er et godt alternativ (krever Python 3.13).

---

## Installasjon (macOS — intern MVP)

Anbefalt MVP-installasjon er via `install_macos.sh` fra [Releases](https://github.com/telboth/xlent-scanner/releases). Scriptet laster ned DMG, kopierer appen til `/Applications`, og fjerner macOS quarantine-attributtet som ellers kan gi meldingen «appen er skadet».

```bash
bash install_macos.sh
```

Ikke start scriptet med `sudo`; scriptet bruker selv `sudo` der det trengs. Hvis det likevel kjøres via `sudo`, forsøker det nå å installere Finder-hurtighandlingen for den opprinnelige innloggede brukeren, ikke for `root`.

Manuell DMG-installasjon kan fortsatt fungere, men kan kreve:

```bash
xattr -dr com.apple.quarantine /Applications/XLENTScanner.app
```

Finder-hurtighandlingen installeres automatisk av `install_macos.sh`. Hvis den må installeres manuelt: åpne **Innstillinger → macOS Finder-hurtighandling** og trykk **Installer Finder-hurtighandling**.

> macOS-DMG-en er for Apple Silicon (M-series). Intel Mac er ikke støttet som ferdig DMG i MVP; Intel-brukere kan kjøre fra kildekode med `uv run xlent-scanner`.

---

## Bruk

1. Start appen (`uv run xlent-scanner` eller dobbeltklikk på installert snarvei)
2. Velg modus øverst i scanner-fanen:
   - **Fil** — dra og slipp (én eller flere filer), eller klikk «Velg fil»
   - **Lim inn** — lim inn tekst direkte i tekstfeltet
   - **Mappe** — velg en mappe for å skanne støttede filer
3. (Valgfritt) Huk av **🔬 Kjør AI-dybdeskann** for også å analysere med lokal AI (krever Ollama)
4. Se gjennom funnene — sammendragsraden øverst viser antall per alvorlighetsgrad
5. Klikk **+ Hviteliste** på falske positive for å filtrere dem ut i fremtiden
6. Bruk **Generer .md-fil** / **Generer PDF** / **Lagre anonymisert .<format>** for å lage en renset versjon
7. Åpne **HTML-rapport** eller last ned **PDF-rapport** for full dokumentasjon (inkl. AI-funn)

### Mappeskann

Mappe-modus skanner som standard bare filer direkte i valgt mappe. Huk av **Skann også undermapper** for rekursiv skanning.

Sikkerhetsgrenser:
- **Maks filer**: default `500`, hard grense `10000`
- **Maks dybde**: default `5`, hard grense `50`
- Før scanning teller appen støttede filer og ber bruker bekrefte
- Resultatlisten viser relativ sti, slik at like filnavn i ulike undermapper kan skilles
- Skjulte/tunge mapper hoppes over, bl.a. `.git`, `.venv`, `node_modules`, `build`, `dist`, `__pycache__`

Støttede filtyper: `pdf`, `docx`, `pptx`, `xlsx`, `txt`, `md`, `html`, `csv`, `eml`, `rtf`, `odt`.

---

## AI-dybdeskann (Ollama)

1. Installer [Ollama](https://ollama.ai) og last ned en modell:
   ```bash
   ollama pull llama3.2:3b
   ```
2. Huk av **🔬 Kjør AI-dybdeskann** i scanner-fanen og velg modell
3. Skann en fil — AI-analysen kjører automatisk etter den regelbaserte skannen
4. AI-funnene flettes inn i funnlisten. Bruk **🔄 Re-skann** for å kjøre på nytt med andre innstillinger

Dybdeskann kjøres lokalt og kan ta opptil flere minutter avhengig av maskin og dokumentstørrelse. Appen viser fremdriftsbar, antall tekstdeler og estimert gjenstående tid mens analysen kjører.
Anbefalt: minst **16 GB RAM** og en relativt moderne CPU. GPU-akselerasjon (NVIDIA/AMD) brukes automatisk.

Ytelse:
- Standardmodus bruker nå en balansert chunking: ca. `1600` ord per del med `60` ord overlapp.
- Ollama-kall bruker `num_ctx=8192` og `num_predict=512` for å redusere unødvendig outputtid.
- AI-dybdeskann sender ikke kategorier som allerede fanges presist av vanlig regex-scan: e-post, URL/IP, telefon, org.nummer, personnummer/ID, kredittkort og konfidensielle ord.
- Vanlig scan kjører fortsatt med alle valgte kategorier; AI-optimaliseringen påvirker bare hva som sendes til Ollama.

Egendefinert Ollama-adresse:
```bash
OLLAMA_BASE_URL=http://192.168.1.10:11434 uv run xlent-scanner
```

---

## Microsoft 365 dokumentmerking (MVP)

Appen kan kobles til Microsoft Graph for dokumenter som ligger i SharePoint/OneDrive. Dette er et valgfritt tillegg og påvirker ikke lokal scanning når det ikke er konfigurert.

Funksjoner:
- Leser sensitivity labels via Graph `extractSensitivityLabels`
- Leser retention label og SharePoint-felt for dokumentet
- Viser Microsoft 365-labels i GUI og HTML/PDF-rapport
- Gir rødt policyvarsel hvis label-navn matcher konfidensielle nøkkelord, f.eks. `confidential`, `restricted`, `hemmelig`
- Kan sette sensitivity label og retention label når tenant/app-token har nødvendige rettigheter
- Kan skrive scan-metadata til SharePoint-felt: `XLENTScanStatus`, `XLENTRiskLevel`, `XLENTFindingCount`, `XLENTSuggestedLabel`, `XLENTLastScanned`
- Kan mappe en lokal OneDrive/SharePoint-synket fil til Graph `driveItem` når `driveId` og lokal sync-root er konfigurert
- Kan skrive scan-metadata for en hel mappeskann-jobb, eller bare valgte filer i mappeskann-tabellen

Konfigurasjon:
```powershell
$env:XLENT_GRAPH_TOKEN = "<bearer-token>"
$env:XLENT_GRAPH_DRIVE_ID = "<drive-id>"
$env:XLENT_GRAPH_SYNC_ROOT = "C:\Users\<bruker>\OneDrive - XLENT\<bibliotek>"
uv run xlent-scanner
```

Alternativt kan `MICROSOFT_GRAPH_TOKEN`, `MICROSOFT_GRAPH_DRIVE_ID` og `MICROSOFT_GRAPH_SYNC_ROOT` brukes. Hvis `XLENT_GRAPH_SYNC_ROOT` ikke er satt, forsøker appen også `OneDriveCommercial` og `OneDrive` som lokal sync-root. Token lagres ikke i nettleser/localStorage.

Bruk:
1. Åpne **Innstillinger → Microsoft 365 dokumentmerking**
2. Fyll inn `Drive ID` og `Lokal sync-root`, eller sett miljøvariablene over
3. Etter lokal filskann: trykk **Les fra sist skannet fil** for å mappe lokal fil til Graph og lese labels
4. Alternativt lim inn `Drive ID` og `Item ID` manuelt og trykk **Les dokumentmerking**
5. Etter mappeskann: bruk **Skriv M365-metadata** i mappeskann-tabellen for å skrive metadata til SharePoint for valgte filer, eller hele jobben hvis ingen er valgt

Begrensninger i MVP:
- Appen gjør ikke OAuth-login selv; token må leveres via miljøvariabel
- Automatisk mapping krever at lokal sync-root og `driveId` peker til samme SharePoint/OneDrive-bibliotek
- SharePoint-kolonnene må opprettes i dokumentbiblioteket før metadata kan skrives
- Label-skriving avhenger av Microsoft Graph-rettigheter, tenant policy og admin consent
- Ved nettverkstilgang krever Microsoft 365-endepunktene `XLENT_SCANNER_API_KEY`; lokalt `127.0.0.1` kan brukes uten API-nøkkel

Swagger/OpenAPI viser Graph-endepunktene på `/api/docs`.

---

## Høyreklikk-integrasjon

### Windows
Inkludert automatisk ved installasjon (registrert via HKCU\Software\Classes, krever ikke admin).

### macOS — Finder-hurtighandling
```bash
bash install_macos.sh --quick-action-only
# Høyreklikk fil i Finder → Hurtighandlinger → Skann med XLENT
```
Kan også installeres direkte fra appen under **Innstillinger**. Krever at `XLENTScanner.app` er i `/Applications`. `install_macos.sh` installerer en Automator Finder-hurtighandling som sender filstien som argument til appen. Hvis scriptet kjøres med `sudo`, installeres den for `SUDO_USER`, ikke for `root`.

Ved feilsøking: åpne **Innstillinger → Feilsøking** og kjør health check eller eksporter feilsøkingspakke. Pakken inkluderer app-logg og `~/Library/Logs/XLENTScannerQuickAction.log`, men ikke dokumentinnhold.

### macOS — Åpne med
macOS-builden deklarerer støttede dokumenttyper (`pdf/docx/pptx/xlsx/txt/md/html/csv/eml/rtf/odt`) i app-bundlen. Finder kan derfor bruke **Åpne med → XLENTScanner** for disse filene.

### Linux — «Åpne med» via .desktop-registrering
Etter at AppImage er nedlastet:
```bash
# Gjør kjørbar og registrer
chmod +x xlent-scanner-linux-*.AppImage
./xlent-scanner-linux-*.AppImage --appimage-integrate   # noen AppImage-versjoner
# Eller manuelt:
cp xlent-scanner-linux-*.AppImage ~/.local/bin/xlent-scanner
# Kopier .desktop-filen og oppdater PATH
xdg-mime default xlent-scanner.desktop application/pdf
```
Etter registrering dukker «Åpne med XLENT Compliance-scanner» opp i høyreklikk-menyen for PDF, DOCX, PPTX, XLSX, TXT, CSV m.fl.

---

## Bygg og pakking

### Windows
```powershell
.\scripts\build_win.ps1     # Bygg app-bundle med PyInstaller
.\scripts\package_win.ps1   # Pakk installer (.exe) med Inno Setup 6
```
Resultater: `artifacts\windows\installer\xlent-scanner-setup-<versjon>.exe`

### macOS
```bash
bash scripts/build_mac.sh
bash scripts/package_mac.sh
```
Resultater: `artifacts/macos/installer/xlent-scanner-macos-<versjon>.dmg`

### Linux (AppImage)
```bash
bash scripts/build_linux.sh
bash scripts/package_linux.sh
```
Resultater: `artifacts/linux/installer/xlent-scanner-linux-<versjon>-x86_64.AppImage`

Krever `libwebkit2gtk-4.0-dev` og `libfuse2` installert lokalt (GitHub Actions installerer disse automatisk).

---

## Utgivelse

Bygg og opplasting er automatisert via GitHub Actions (`.github/workflows/build-release.yml`).
En egen `create-release`-jobb oppretter releasen, deretter bygger Windows- og macOS-jobbene parallelt og laster opp `.exe`/`.dmg`.

```bash
# Oppdater versjon i pyproject.toml + src/xlent_scanner/__init__.py, så:
git tag v1.3.5
git push origin master --tags
```

Tag-push (`v*`) trigger bygget automatisk. Manuell kjøring: bruk **workflow_dispatch** fra Actions-fanen med tag-navnet.

---

## Test

```bash
uv run pytest        # hele test-suiten (detektorer, anonymisering, integrasjon mot fixtures)
```

Fixtures ligger i `tests/fixtures/` (`sensitiv_nb.txt` + `sensitiv_nb.pdf` med alle typer sensitiv testdata).

---

## Arkitektur

```
src/xlent_scanner/
├── app.py              # Flask-server + PyWebView-vindu, CLI-modus, kontekstmeny-IPC
├── paths.py            # Sentralisert app-data-mappe (Windows/macOS/Linux)
├── scanner.py          # Orkestrerer alle detektorer; scan_file / scan_text / scan_folder
├── deep_scanner.py     # Chunked Ollama-analyse + regex-supplement + konfidensfilter + hviteliste
├── anonymize.py        # build_replacements() + to-fase tokenisert teksterstatning
├── patch.py            # In-place teksterstatning i docx/pptx/xlsx/pdf
├── report.py           # HTML-rapportgenerering (inkl. AI-funn-seksjon)
├── history.py          # Persistent JSONL-historikk
├── language.py         # Språkdeteksjon + spaCy-konfigurasjon (nb/sv/en/da/de/fr/es)
├── whitelist.py        # Personlig hviteliste
├── ignore.py           # ignore.toml (XLENT-interne navn etc.)
├── update_check.py     # Sjekker GitHub Releases for ny versjon
├── model_manager.py    # Nedlasting av spaCy-modeller
├── microsoft_graph.py  # Valgfri Microsoft Graph-integrasjon for labels og SharePoint metadata
├── utils.py            # Felles ctx()-hjelpefunksjon
├── models.py           # Finding + ScanResult dataklasser
├── detectors/
│   ├── regex_no.py     # Norske mønstre (fnr, orgnr, konto, telefon)
│   ├── regex_sv.py     # Svenske mønstre (personnummer, bankgiro)
│   ├── regex_da.py     # Danske mønstre (CPR-nummer, mod-11)
│   ├── regex_en.py     # Engelske mønstre (NI, SSN)
│   ├── regex_url.py    # Nettadresser (http/https/www)
│   ├── ner_names.py    # spaCy NER for personnavn (filtrerer bort sifre/akronymer)
│   ├── secrets.py      # API-nøkler, tokens, høy-entropi-strenger
│   ├── creditcards.py  # Kredittkort (Luhn)
│   ├── iban.py         # IBAN (MOD-97)
│   ├── financials.py   # Kommersielle nøkkeltall + budsjett
│   ├── keywords.py     # Konfidensielle nøkkelord
│   └── clients.py      # Klientnavn fra clients.toml
└── web/
    └── index.html      # Komplett frontend (PyWebView + embedded Flask), full i18n nb/sv/en/de/fr/es
```

**Teknologistakk:**
- Dokumentekstraksjon: Docling for PDF (med PyMuPDF fallback) + native ekstraksjon for DOCX/PPTX/XLSX/TXT/MD/HTML/CSV/EML/RTF/ODT
- NER: [spaCy](https://spacy.io/) med `nb_core_news_sm`, `sv_core_news_sm`, `en_core_web_sm`, `de_core_news_sm`, `fr_core_news_sm`, `es_core_news_sm` (dansk gjenbruker norsk modell)
- GUI: [PyWebView](https://pywebview.flowrl.com/) med innebygd Flask-server
- AI-dybdeskann: [Ollama](https://ollama.ai) REST API (`/api/generate`)
- PDF-anonymisering og -rapport: [PyMuPDF](https://pymupdf.readthedocs.io/) (fitz)
- Bilde-PDF-redaction: PyMuPDF-rendering + RapidOCR-koordinater + Pillow-maskering
- Risikomotor: fire nivåer — grønn / gul / rød / svart
- Mappeskann: `scan_folder()` bruker en delt planlegger for preview og scanning, med rekursiv modus, maksgrenser og ekskluderte mapper

---

## Endringslogg

### v1.7.0
- Tømmer feltet «Ekstrahert tekst» straks ny fil-, tekst- eller mappeskann starter, slik at tekst fra forrige dokument ikke vises mens ny skann pågår.
- Ignorerer DOI-resolver-lenker som `doi.org` og `dx.doi.org` i URL-detektoren for å redusere støy i akademiske referanselister.
- Strammer inn personnavnfilteret for tekniske tittelcase-fraser som «Conversion Tool» og «Frequency Range».

### v1.6.10
- La til rasterbasert **anonymisert bilde-PDF** for innskannede/OCR-baserte PDF-er.
- Maskerer valgte OCR-treff direkte på rendret sidebilde og bygger ny PDF av de maskerte sidene.
- Endrer bilde-/OCR-PDF-flyten i GUI-et slik at «Åpne anonymisert fil» og AI-redaction bruker bilde-PDF-maskering i stedet for OCR-tekst-PDF.
- Deklarerer Pillow som direkte avhengighet fordi bilde-PDF-redaction bruker PIL-maskering.

### v1.5.8
- Gjør «Åpne anonymisert fil» tilgjengelig direkte etter skann og lar knappen lagre, kontrollskanne og åpne filen i én handling.
- Bruker originalformatet for DOCX, PDF, PPTX og XLSX når filen lagres via åpne-knappen, med Markdown som fallback for øvrige dokumenttyper.
- Samler forhåndsvisning, Markdown-/PDF-generering og JSON-/CSV-eksport under en lukket «Flere valg»-ekspander for et enklere visuelt grensesnitt.

### v1.5.7
- Beregner samlet risikonivå i backend fra både regelbaserte funn, AI-dypscan og policyvarsler, slik at HTML-, PDF- og eksporterte rapporter viser samme status som GUI-et.
- Kjører automatisk kontrollskann etter anonymisering og rapporterer fjernede funn, gjenværende funn og bestått/krever kontroll.
- Lagrer historikk for anonymiserte filer med handlinger for å åpne filen, vise den i mappe og kjøre kontrollskann på nytt.
- Utvider revisjonssporet med deteksjonsmotor, AI-modell, konfidens, valgte kategorier og hvilke funn som faktisk ble anonymisert.
- Avviser finansielle AI-funn uten et faktisk tall eller beløp, inkludert falske funn som «opprinnelige budsjetter».
- Beholder regelbaserte personnavnfunn og samlet gult risikonivå når AI-dypscan ikke finner ytterligere data.
- Legger til knappen «Åpne anonymisert fil» ved anonymiseringskontrollene.

### v1.5.6
- Tilpasser Ollamas systeminstruksjon og medisinske instruksjon til dokumentets språk for norsk, svensk, dansk, engelsk, tysk, fransk og spansk.
- Bruker engelsk instruksjon når dokumentets språk er ukjent, ugyldig eller for uklart til sikker språkdeteksjon.
- Utvider systeminstruksjonen slik at modellen eksplisitt leter etter personnavn, fysiske adresser og budsjett-/finansielle tall.
- Legger til regresjonstester for språkvalg og engelsk fallback i AI-dybdeskann.

### v1.5.5
- Øker AI-dybdeskannens outputgrense fra 512 til 1024 tokens og varsler i loggen dersom Ollama fortsatt avkorter svaret.
- Kjører valgt medisinsk analyse i en separat, fokusert modellpassering og beholder eksakte, kildeverifiserte funn med høy konfidens.
- Utvider medisinsk kontekst for legemidler og behandling, inkludert Paracetamol, antibiotika, Malarone og generiske medisinuttrykk.
- Hindrer falske SWIFT/BIC-funn på stedsnavn som Horten gjennom gyldig ISO-landkode og strammere bankkontekst.
- Sikrer release-scriptet mot feil branch, usynkronisert `master`, versjonsavvik og tag som peker på feil commit.
- Flytter mappe-, API- og Ollama-ruter til egne Blueprints og innfører en felles `JobManager` for bakgrunnsjobber.

### v1.5.4
- Skiller teknisk skannstatus (`success`, `partial`, `failed`) fra dokumentets risikonivå, og CLI returnerer nå exit-kode 4 ved tekniske skannfeil.
- Samler detektorpipelinen for tekst- og filskanning, og lar `KeyboardInterrupt` og `SystemExit` propagere normalt.
- Sikrer modellinstallasjon mot katalogtraversering og symbolske lenker, og gjør samtidige modellnedlastinger atomiske.
- Retter restart av mappeovervåkning slik at gammel tråd stoppes før ny overvåkning starter.
- Deler Flask-applikasjonen i Blueprints og samler muterbar apptilstand i eksplisitt `AppState`.

### v1.5.3
- Gjorde AI-dybdeskann raskere med balansert chunking (`1600` ord, `60` ord overlapp), eksplisitt `num_ctx=8192` og kortere `num_predict=512`.
- AI-dybdeskann hopper nå over regex-dekkede kategorier (e-post, URL/IP, telefon, org.nummer, personnummer/ID, kredittkort og konfidensielle ord), mens vanlig scan fortsatt kjører som før.
- La til synlig AI-fremdriftsbar med delstatus og estimert gjenstående tid.

### v1.4.8
- Oppdaterte «Om programmet»-teksten på alle språk slik at den dekker dagens funksjoner, inkludert webmodus, mappevakt, OCR, M365, redaction-profiler og AI-dybdeskann.
- Forbedret lesbarhet på redaction-, eksport- og innstillingsknapper ved å bruke outline-stil i stedet for fylte farger.
- Standardiserte knappestil: fylte knapper brukes til scan/analyse, mens lagring, eksport, installasjon og konfigurasjon bruker outline.
- La til tooltips for tunge eller eksterne handlinger: AI-dybdeskann, OCR, rekursiv mappeskann, batch-redaction, installasjonsscript og Microsoft 365 metadata.
- La til regresjonstest som hindrer fylte primærknapper i Innstillinger.

### v1.4.7
- La til manuell re-scan-knapp etter redaction, uten automatisk re-scan.
- La til bakgrunnsstatus for mappeovervåkning og utklippstavlevakt.
- Forbedret egendefinerte regex-mønstre med skjema og test mot eksempeltekst.
- La til redaction-profiler, OCR-status i diagnostikk, flere samtidige mappeovervåkninger og konfigurerbar Microsoft 365-labelmapping.
- La til release-gate som validerer installer-artifacts før opplasting til GitHub Release.

### v1.4.3
- La til valgfri Microsoft 365 / Graph-integrasjon for sensitivity labels, retention labels og SharePoint scan-metadata.
- Microsoft 365-labels vises i GUI/rapport, og konfidensielle labels gir rødt policyvarsel uten å blokkere lokal scan-flyt.
- OpenAPI/Swagger dokumenterer de nye Graph-endepunktene.
- La til automatisk mapping fra lokal OneDrive/SharePoint-synket fil til Graph `driveItem` via `driveId` + sync-root.
- La til batch-skriving av scan-metadata til SharePoint-felt for mappeskann-resultater.

### v1.4.2
- Fikset AI-dybdeskann slik at LLM-funn forkastes hvis teksten modellen rapporterer ikke faktisk finnes i dokumentteksten.
- Hindrer dermed hallucinerte personnummer eller andre verdier fra tidligere/testkontekst.
- Nullstiller server-side AI-funn ved ny scan, slik at gamle AI-funn ikke kan følge med inn i ny rapport.

### v1.4.1
- Forbedret mappeskann-tabellen med tooltip per fil, full rapport ved klikk, filter, sortering, eksport, audit-rapport og batch-redaction av valgte filer.
- Mappeskann kjører nå som bakgrunnsjobb med progress og avbryt-knapp for bedre håndtering av store mapper.
- Gjorde macOS Finder Quick Action mer robust: runneren leser både argumenter og stdin, starter appen via `open --args`, har direkte `nohup`-fallback og skriver mer nyttig diagnostikk til logg.

### v1.4.0
- La til rekursiv mappeskann som eksplisitt valg, med preview/telling før scan, maks filer, maks dybde og ekskluderte tunge/skjulte mapper.
- Mappeskann-resultater viser relativ sti for filer i undermapper.
- Forenklet kategorimenyen: `Personnummer / ID` dekker også passnummer, og `Finansielle nøkkeltall` dekker også lønn/salary.
- Forbedret macOS Finder Quick Action-diagnostikk og runner-logikk for Finder/Automator-input.

### v1.3.10
- Fikset macOS Finder/Open With-oppstart ved å ignorere Finder sitt `-psn_...` argument og bruke første faktiske filsti.
- Gjorde macOS `Info.plist`-registrering for støttede dokumenter mer robust for Launch Services.

### v1.3.9
- La til brukerredigerbar blacklist under Innstillinger. Ord og uttrykk i blacklist flagges alltid og fjernes ved redaction.
- La til valg for å fjerne kommentarer og speaker notes ved redaction av støttede originalformater.
- Fjerner DOCX-kommentarer, PPTX speaker notes/kommentarer, XLSX-kommentarer og PDF-annotasjoner når valget er aktivert.
- Gjorde AI-dybdeskann mer treffsikker for finansielle tall i tabell-/regnearkkontekst, uten å blanke løse tall globalt.
- La til opt-in medisinsk kategori for AI-dybdeskann.
- Strammet inn telefon-/URL-regler for amerikanske telefonnummer, årstallintervaller og datoer.
- Forbedret ignore-støtte for e-postfunn i AI-dybdeskann.

### v1.3.8
- Fikset macOS «Open With»/Finder-filåpning ved å registrere støttede dokumenttyper separat i app-bundlen.
- macOS-installer oppdaterer nå Launch Services-cache etter installasjon.
- AI-dybdeskann bruker nå `ignore.toml`, slik at interne e-postdomener og eksakte e-postadresser ignoreres også der.
- `ignore.toml` støtter nå `emails = []` i tillegg til `email_domains`.

### v1.3.7
- Fikset engelsk kategorioversettelse i «What do you want to find?» der manglende `scanCat...`-nøkler ble vist i UI.
- Endret engelsk terminologi fra anonymisation/anonymised til redaction/redacted der appen beskriver dokumentredigering.
- Fikset AI-dybdeskann-regresjon der re-scan-knappen kunne bli stående som spinner fordi frontend pollet siste jobb i stedet for konkret `job_id`.
- La til GUI-endepunkter for dybdeskann-status og cancel per `job_id`.

### v1.3.6
- Light mode er nå standard for nye brukere, mens lagret dark mode beholdes.
- API-dybdeskann kan hente/cancelle status per `job_id`, slik at parallelle API-jobber ikke overskriver hverandre.
- API nekter nettverksbinding (`--host 0.0.0.0`) uten `XLENT_SCANNER_API_KEY`.
- La til import/eksport av lokal innstillingsprofil: tema, dokumentspråk, hviteliste og `ignore.toml`.
- La til nedlasting/status for anbefalt Ollama-modell fra Innstillinger.
- La til release-smoketest for runtime-data, `python-docx` templates og PyMuPDF-redaction API.

### v1.3.5
- La til stabilt `/api/...`-lag for Power Apps/custom connectors, med `--api --port` startmodus, API-key-støtte og OpenAPI-dokumentasjon.
- La til Light/Dark mode under Innstillinger, med grå header i light mode slik at XLENT-logoen forblir synlig.
- Fikset WebView-layout der hvit høyre-/bunnflate kunne dekke innhold i store vinduer.

### v1.3.4
- Fikset DOCX-anonymisering/generering for dokumenter uten definert header/footer.
- Unngår at `python-docx` oppretter default header/footer under patching, som kunne feile i pakket macOS-app.
- La til regresjonstest for DOCX uten header/footer.

### v1.3.3
- Fikset manglende `python-docx` templatefiler i pakkede builds, som kunne gi feil ved DOCX-generering/anonymisering på macOS.
- Bundler nå package-data for både `docx` og `pptx` i Windows-, macOS- og Linux-buildscript.

### v1.3.2
- Gjorde `install_macos.sh` til full macOS-installer for MVP: laster ned DMG, monterer den, kopierer `XLENTScanner.app` til `/Applications`, og fjerner `com.apple.quarantine`.
- Oppdaterte macOS-dokumentasjon fordi manuell DMG-installasjon uten notarization kan gi «appen er skadet».

### v1.3.1
- Fikset macOS-feilen «XLENTScanner.app er skadet og kan ikke åpnes».
- Re-signerer app-bundlen med ad-hoc `codesign` etter at `Info.plist` patches med dokumenttyper.
- Verifiserer macOS-signaturen i build-scriptet før DMG pakkes.

### v1.3.0
- La til `Stopp aktiv AI-modell` i Ollama-innstillinger.
- Stopper valgt Ollama-modell via API (`keep_alive: 0`) uten å stoppe Ollama-tjenesten.
- Modellen lastes automatisk inn igjen ved neste dybdeskann.
- La til test som sikrer korrekt Ollama-payload for modellstopp.

### v1.2.10
- Fikset macOS `Åpne med XLENTScanner` for støttede filtyper ved å deklarere dokumenttyper i appens `Info.plist`.
- Aktivert PyInstaller `--argv-emulation`, slik at Finder `Open With` sender filstien til appen ved oppstart.
- La til test som sikrer at macOS-buildscriptet beholder denne konfigurasjonen.

### v1.2.9
- Fikset PDF-anonymisering på macOS/nyere PyMuPDF (`apply_redactions`).
- La til regresjonstest for PDF-redaksjon.
- La til Finder Quick Action-installasjon direkte fra appens Innstillinger på macOS.
- La til loggvisning og «Åpne loggfil» i Innstillinger.
- Forbedret PDF-feilmeldinger slik at teknisk detalj havner i loggfil, ikke bare i brukerfeilen.
- Tydeliggjorde at macOS-DMG i MVP er Apple Silicon-build; Intel Mac må kjøre fra kildekode.

### v1.2.8
- Fikset språkbug i statusfeltet slik at «Klar/Bereit/Ready/…» alltid følger valgt UI-språk.
- La til web-modus fra desktop: ny knapp i Innstillinger som starter lokal `--web`-modus i nettleser.
- Forbedret filvelger-fallback i web-modus slik at alle støttede filformater kan velges via nettleserens filopplaster.

### v1.2.7
- La til avhuking for AI-dybdeskann-funn i den sammenslåtte funnlisten.
- Knyttet avhukede AI-funn til anonymisering/patch, slik at de faktisk tas med eller utelates.
- Oppdateringsbanner har egen knapp for direkte nedlasting av riktig installer for maskintype.

### v1.2.6
- La til full «Om programmet»-tekst på tysk, fransk og spansk.
- Utvidet manuelt dokumentspråkvalg i Innstillinger med DE/FR/ES.
- Fikset Linux-release-upload slik at kun sluttproduktet `xlent-scanner-linux-*.AppImage` lastes opp (ikke `appimagetool`).

### v1.2.5
- Release-bump til 1.2.5 med samme distribusjonsoppsett som 1.2.4 (`.exe`, `.dmg`, `.AppImage`).

### v1.2.4
- Rettet Linux-buildscript (`scripts/build_linux.sh`) med korrekt escaping for hidden imports.
- Filvelger støtter nå alle skannbare formater i dialogfilteret (`pdf/docx/pptx/xlsx/txt/md/html/csv/eml/rtf/odt`).
- Rettet stabilitetsfeil i nedlasting av spaCy-modeller (`model_manager.py`).
- Oppdateringsvarsel i appen viser nå direkte installasjonslenke når release har matchende installer-asset.
- Mindre forbedringer i tysk validering (Steuer-ID).

### v1.2.0
- **Flerfil-batch** — slipp flere filer samtidig i scanner-fanen for en samlet oversikt
- **📋 Kopier funn** — kopier alle funn (regel + AI) til utklippstavlen
- **Sammendragsrad** med fargede alvorlighets-badges øverst i resultatet
- **PDF som anonymiseringsoutput** (i tillegg til `.md` og in-place-formater)
- **HTML- og PDF-rapport inkluderer nå AI-dybdeskann-funn** i egen seksjon
- **Husker språk og AI-modell** mellom øktene (localStorage)
- Bugfix: CPR-nummer (DK) klassifiseres nå korrekt som ⛔ svart (var ⚠️ gul)
- Bugfix: PDF-rapport og PDF-anonymisering (ugyldig font-alias `helv-b` → `hebo`)

### v1.1.x
- Fjernet død «Dybdeskann»-fane; funksjonaliteten er innebygd i scanner-fanen (−365 linjer)
- Full i18n-dekning av AI-statusmeldinger (nb/sv/en)
- AI-funn flettes inn i hovedfunnlisten med korrekt alvorlighetsgrad
- AI-dybdeskann suppleres med regelbasert deteksjon (personnummer, e-post, konto, URL)
- To-nivå personnummer-deteksjon: «mulig personnummer (format)» for feil kontrollsiffer
- Budsjett-/beløpsdeteksjon utvidet («Total NOK 180,-» m.m.)
- AI-funn filtreres mot brukerens hviteliste
- «Oppdatert»-tidsstempel ved versjonsnummeret

### v1.0.x
- Windows høyreklikk-kontekstmeny («Skann med XLENT») via HKCU (krever ikke admin)
- CLI-modus (`--scan`), single-instans-IPC, Linux-støtte (XDG)
- Nye filformater: `.csv`, `.eml`, `.rtf`, `.odt`
- Sentralisert app-data-mappe (`paths.py`); `jinja2` som eksplisitt avhengighet
- Bugfix: fødselsnummer dobbelt-flagget som kontonummer
- Bugfix: anonymisering lekket etternavn ved overlappende navn (to-fase tokenisering)
- Full enhets-test-suite for alle detektorer + anonymisering (`tests/`)

### v0.9.x
- Grunnfunksjoner: scanner, dybdeskann, hviteliste, NER, mappeskann, paste-modus,
  persistent historikk, PDF-rapport, konfidensfilter, dansk CPR, konsistente
  anonymiserings-etiketter

---

*Skrevet av thomas.elboth@xlent.no*

