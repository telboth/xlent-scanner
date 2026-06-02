# XLENT Compliance-scanner

> **v1.2.10** — Lokal scanner som oppdager sensitiv kundeinfo i dokumenter _før_ du limer dem inn i ChatGPT, Claude eller Copilot.

Alt kjøres 100 % lokalt — ingen dokumenter, tekst eller funn sendes over internett.

---

## Funksjoner

### Scanner

- **Drag-and-drop** — slipp én eller **flere filer** rett på vinduet (flere filer → batch-oversikt)
- **Bla-til-fil** — velg fil fra disk
- **Lim inn tekst** — skann tekst direkte (uten å lagre en fil)
- **Mappeskann** — velg en mappe og skann alle støttede filer i én operasjon
- **Kategorifilter** — velg hvilke typer funn du vil se (personnummer, konto, navn, secrets, …)

### AI-dybdeskann (Ollama) — innebygd i scanner-fanen

- Huk av **🔬 Kjør AI-dybdeskann** før du skanner, så analyseres dokumentet også av en lokal AI-modell (Ollama)
- Fanger funn som regelmotoren kan misse (adresser, selskapsnavn, kontekstuelle navn)
- AI-funnene **flettes rett inn i den vanlige funnlisten** med samme alvorlighetsgrad-klassifisering
- Regelbaserte detektorer (personnummer, e-post, konto, IBAN, URL) **supplerer** AI-en automatisk for 100 % pålitelig dekning
- **Konfidensfilter**: `høy` / `medium` / `lav`
- **Re-skann**-knapp + inline statusindikator
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
- **HTML-rapport** og **PDF-rapport** — begge inkluderer både regelbaserte funn **og** AI-dybdeskann-funn
- **Persistent historikk** mellom øktene
- Valgt **språk og AI-modell huskes** mellom øktene (localStorage)

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

Last ned `xlent-scanner-setup-<versjon>.exe` fra [Releases](https://github.com/telboth/xlent-scanner/releases) og kjør installasjonsprogrammet (krever **ikke** administrator).

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

Last ned `xlent-scanner-macos-<versjon>.dmg` fra [Releases](https://github.com/telboth/xlent-scanner/releases).

1. Åpne DMG-filen og dra **XLENTScanner** til **Applications**-mappen
2. **Første gangs oppstart**: macOS Gatekeeper kan blokkere appen fordi den ikke er signert. Høyreklikk på appen og velg **Åpne**, deretter bekreft i dialogboksen.
3. Valgfritt: åpne **Innstillinger → macOS Finder Quick Action** og trykk **Installer Finder Quick Action**.
4. Alternativt kan Quick Action installeres fra release-scriptet:
   ```bash
   bash install_mac_quick_action.sh
   killall Finder
   ```

> macOS-DMG-en er for Apple Silicon (M-series). Intel Mac er ikke støttet som ferdig DMG i MVP; Intel-brukere kan kjøre fra kildekode med `uv run xlent-scanner`.

---

## Bruk

1. Start appen (`uv run xlent-scanner` eller dobbeltklikk på installert snarvei)
2. Velg modus øverst i scanner-fanen:
   - **Fil** — dra og slipp (én eller flere filer), eller klikk «Velg fil»
   - **Lim inn** — lim inn tekst direkte i tekstfeltet
   - **Mappe** — velg en mappe for å skanne alle filer
3. (Valgfritt) Huk av **🔬 Kjør AI-dybdeskann** for også å analysere med lokal AI (krever Ollama)
4. Se gjennom funnene — sammendragsraden øverst viser antall per alvorlighetsgrad
5. Klikk **+ Hviteliste** på falske positive for å filtrere dem ut i fremtiden
6. Bruk **Generer .md-fil** / **Generer PDF** / **Lagre anonymisert .<format>** for å lage en renset versjon
7. Åpne **HTML-rapport** eller last ned **PDF-rapport** for full dokumentasjon (inkl. AI-funn)

---

## AI-dybdeskann (Ollama)

1. Installer [Ollama](https://ollama.ai) og last ned en modell:
   ```bash
   ollama pull llama3.2:3b
   ```
2. Huk av **🔬 Kjør AI-dybdeskann** i scanner-fanen og velg modell
3. Skann en fil — AI-analysen kjører automatisk etter den regelbaserte skannen
4. AI-funnene flettes inn i funnlisten. Bruk **🔄 Re-skann** for å kjøre på nytt med andre innstillinger

Dybdeskann kjøres lokalt og kan ta opptil flere minutter avhengig av maskin og dokumentstørrelse.
Anbefalt: minst **16 GB RAM** og en relativt moderne CPU. GPU-akselerasjon (NVIDIA/AMD) brukes automatisk.

Egendefinert Ollama-adresse:
```bash
OLLAMA_BASE_URL=http://192.168.1.10:11434 uv run xlent-scanner
```

---

## Høyreklikk-integrasjon

### Windows
Inkludert automatisk ved installasjon (registrert via HKCU\Software\Classes, krever ikke admin).

### macOS — Quick Action
```bash
bash install_mac_quick_action.sh
# Følg instruksjonene — logg ut og inn igjen for å aktivere
# Høyreklikk fil i Finder → Hurtighandlinger → Skann med XLENT
```
Kan også installeres direkte fra appen under **Innstillinger**. Krever at `XLENTScanner.app` er i `/Applications`. Scriptet installerer en Automator Quick Action som sender filstien som argument til appen.
`scripts/install_mac_service.sh` finnes fortsatt som bakoverkompatibel wrapper.

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
git tag v1.2.10
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
- Risikomotor: fire nivåer — grønn / gul / rød / svart

---

## Endringslogg

### v1.2.10
- Fikset macOS `Åpne med XLENTScanner` for støttede filtyper ved å deklarere dokumenttyper i appens `Info.plist`.
- Aktivert PyInstaller `--argv-emulation`, slik at Finder `Open With` sender filstien til appen ved oppstart.
- La til test som sikrer at macOS-buildscriptet beholder denne konfigurasjonen.

### v1.2.9
- Fikset PDF-anonymisering på macOS/nyere PyMuPDF (`apply_redactions`).
- La til regresjonstest for PDF-redaksjon.
- La til Finder Quick Action-installasjon direkte fra appens Innstillinger på macOS.
- Laster opp `install_mac_quick_action.sh` som release-asset og beholder `install_mac_service.sh` som wrapper.
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
