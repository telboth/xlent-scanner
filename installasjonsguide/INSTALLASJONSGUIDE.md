# Installasjonsguide – XLENT Scanner

Denne guiden beskriver installasjon på lokal maskin for Windows og macOS.

Kilde for nedlasting:
- [https://github.com/telboth/xlent-scanner/releases](https://github.com/telboth/xlent-scanner/releases)

## Windows

1. Gå til releases-siden og last ned siste `xlent-scanner-windows-setup-<versjon>.exe`.
2. Dobbeltklikk `.exe`-filen.
3. Følg installasjonsveiviseren og fullfør installasjonen.
4. Start programmet fra Start-menyen eller skrivebordsikonet.

### Hvis Windows blokkerer installasjonen (SmartScreen)

Det kan skje fordi installasjonspakken ikke er signert i MVP-fasen.

1. Når varselet **"Windows beskyttet PC-en din"** vises, trykk **"Mer informasjon"**.
2. Trykk **"Kjør likevel"**.
3. Fortsett installasjonen.

Anbefaling:
- Verifiser at filen kommer fra riktig GitHub-repo før du velger **Kjør likevel**.

## macOS

1. Gå til releases-siden og last ned siste `xlent-scanner-macos-<versjon>.dmg`.
2. Åpne `.dmg`-filen.
3. Dra `XLENT Scanner.app` til `Applications`.
4. Åpne programmet fra `Applications`.

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

## Verifisering etter installasjon

1. Start appen.
2. Last inn en testfil (`.pdf`, `.docx` eller `.pptx`).
3. Bekreft at skanningen kjører uten feilmelding.
4. Sjekk at språkvalg og oppdateringsvarsel fungerer.

## Vanlige feil

- **"Failed to fetch"**:
  - Start appen på nytt.
  - Kontroller at lokal backend kjører (for desktop starter den automatisk).

- **Fil kan ikke leses**:
  - Test med en annen fil.
  - Bekreft at filformatet er støttet.

## Intern bruk i XLENT

- Bruk kun release-filer fra `telboth/xlent-scanner`.
- Ikke del sensitive kundedokumenter utenfor godkjent miljø.
