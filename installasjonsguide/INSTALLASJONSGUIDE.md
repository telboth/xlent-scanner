# Installasjonsguide – XLENT Scanner

Denne guiden beskriver installasjon på lokal maskin for Windows og macOS.

Kilde for nedlasting:
- [https://github.com/telboth/xlent-scanner/releases](https://github.com/telboth/xlent-scanner/releases)

## Windows

Anbefalt installasjon:

1. Gå til releases-siden og last ned `install_windows.ps1`.
2. Åpne PowerShell i mappen der scriptet ligger.
3. Kjør:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
   ```
4. Følg installasjonsveiviseren og fullfør installasjonen.
5. Start programmet fra Start-menyen eller skrivebordsikonet.

Direkte installasjon uten å laste ned scriptet manuelt:

```powershell
$p = "$env:TEMP\install_windows.ps1"; Invoke-WebRequest "https://github.com/telboth/xlent-scanner/releases/latest/download/install_windows.ps1" -OutFile $p; powershell -ExecutionPolicy Bypass -File $p
```

Alternativt kan du laste ned siste `xlent-scanner-setup-<versjon>.exe` og dobbeltklikke den manuelt.

### Hvis Windows blokkerer installasjonen (SmartScreen)

Det kan skje fordi installasjonspakken ikke er signert i MVP-fasen.

1. Når varselet **"Windows beskyttet PC-en din"** vises, trykk **"Mer informasjon"**.
2. Trykk **"Kjør likevel"**.
3. Fortsett installasjonen.

Anbefaling:
- Verifiser at filen kommer fra riktig GitHub-repo før du velger **Kjør likevel**.

## macOS

Anbefalt MVP-installasjon:

1. Gå til releases-siden og last ned `install_macos.sh`.
2. Kjør:
   ```bash
   bash ~/Downloads/install_macos.sh
   ```
3. Start `XLENTScanner.app` fra `Applications`.
4. Finder-hurtighandlingen `Skann med XLENT` installeres automatisk for brukeren som kjører scriptet.
5. Alternativt kan bare Finder-hurtighandlingen installeres på nytt med:
   ```bash
   bash ~/Downloads/install_macos.sh --quick-action-only
   ```

Merk:
- Ikke start `install_macos.sh` med `sudo`; scriptet bruker selv `sudo` der det trengs. Hvis det likevel kjøres via `sudo`, forsøker installasjonen å legge Finder-hurtighandlingen på den opprinnelige brukeren, ikke på `root`.
- macOS-DMG-en i MVP er for Apple Silicon (M-series).
- Intel Mac er ikke støttet som ferdig DMG foreløpig. Kjør fra kildekode med `uv run xlent-scanner`.
- Manuell DMG-installasjon kan trigge Gatekeeper-meldingen «appen er skadet» fordi appen ikke er notarisert. `install_macos.sh` fjerner quarantine-attributtet etter kopiering.

### Hvis macOS blokkerer appen (Gatekeeper)

Det kan skje fordi appen ikke er signert/notarisert i MVP-fasen.

Alternativ A (raskest):
1. Finn appen i `Applications`.
2. Høyreklikk (eller `Ctrl` + klikk) på appen.
3. Velg **Open**.
4. Velg **Open** igjen i bekreftelsesdialogen.

Alternativ B (System Settings):
1. Forsøk å åpne appen én gang og lukk varselet.
2. Gå til `System Settings` -> `Privacy & Security`.
3. Finn meldingen om blokkert app nederst.
4. Velg **Open Anyway** og bekreft.

Hvis macOS sier at appen er skadet:
```bash
xattr -dr com.apple.quarantine /Applications/XLENTScanner.app
```

## Verifisering etter installasjon

1. Start appen.
2. Last inn en testfil (`.pdf`, `.docx` eller `.pptx`).
3. Bekreft at skanningen kjører uten feilmelding.
4. Sjekk at språkvalg og oppdateringsvarsel fungerer.

## Høyreklikk-skanning fra filutforsker

### Windows

1. Høyreklikk på en støttet fil.
2. Velg `Scan with XLENT Scanner` (eller tilsvarende menyvalg).
3. Appen åpner seg og starter skanning av valgt fil.

### macOS

Etter at `install_macos.sh` er kjørt:

1. Høyreklikk på en støttet fil i Finder.
2. Velg `Hurtighandlinger` -> `Skann med XLENT`.
3. Appen åpner seg og starter skanning av valgt fil.

Alternativt kan du bruke `Åpne med` -> `XLENTScanner` for støttede filtyper (`pdf/docx/pptx/xlsx/txt/md/html/csv/eml/rtf/odt`).

## Nedlasting av spaCy-modeller

Appen bruker spaCy-modeller for navnegjenkjenning (NER). Modellene lastes normalt ned automatisk ved første kjøring ved behov.

Hvis automatisk nedlasting feiler:
1. Åpne appen på nytt og prøv en ny skann (triggere ofte ny nedlasting).
2. Kontroller at maskinen har internettilgang mot GitHub/PyPI.
3. Kontakt intern IT hvis nettverkspolicy blokkerer nedlasting av Python-pakker.

Merk:
- Når modellene først er lastet ned, brukes de lokalt videre.
- Dette påvirker primært navnedeteksjon, ikke de rene regex-basert kontrollene.

## Ollama (kun hvis du skal bruke AI-dypskann)

AI-dypskann krever lokal Ollama-installasjon. Uten Ollama fungerer vanlig skann fortsatt.

1. Installer Ollama fra [https://ollama.com/download](https://ollama.com/download).
2. Start Ollama lokalt.
3. Åpne XLENT Scanner og aktiver dypskann.
4. Velg ønsket modell i appen.

Hvis dypskann ikke fungerer:
1. Bekreft at Ollama kjører.
2. Bekreft at modell er lastet ned i Ollama.
3. Sjekk at lokal URL/port for Ollama ikke er blokkert av sikkerhetsprogramvare.

## Vanlige feil

- **"Failed to fetch"**:
  - Start appen på nytt.
  - Kontroller at lokal backend kjører (for desktop starter den automatisk).

- **Feil ved nedlasting av spaCy-modell**:
  - Kontroller internettilgang og at sikkerhetsløsninger ikke blokkerer Python/GitHub/PyPI.
  - Prøv igjen etter restart av appen.

- **AI-dypskann feiler**:
  - Kontroller at Ollama er installert og kjører.
  - Bekreft at riktig modell er tilgjengelig i Ollama.

- **Fil kan ikke leses**:
  - Test med en annen fil.
  - Bekreft at filformatet er støttet.

## Intern bruk i XLENT

- Bruk kun release-filer fra `telboth/xlent-scanner`.
- Ikke del sensitive kundedokumenter utenfor godkjent miljø.
