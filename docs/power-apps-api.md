# Power Apps API for XLENT Scanner

Dette API-laget er et tillegg til eksisterende desktop/web-GUI. Det bruker egne `/api/...`-endepunkter og egen `scan_id`-state, slik at eksisterende app-funksjonalitet ikke påvirkes.

## Start API-server lokalt

Fra kildekode:

```powershell
$env:XLENT_SCANNER_API_KEY = "bytt-denne-til-en-lang-hemmelig-verdi"
uv run xlent-scanner --api --port 51291
```

Fra installert Windows-app:

```powershell
$env:XLENT_SCANNER_API_KEY = "bytt-denne-til-en-lang-hemmelig-verdi"
& "$env:LOCALAPPDATA\Programs\XLENT Compliance-scanner\XLENTScanner.exe" --api --port 51291
```

Serveren lytter på `http://127.0.0.1:51291`. Dette er bevisst lokalt. Hvis Power Apps skal nå API-et, bruk Power Platform on-premises data gateway på samme maskin eller en bevisst intern gateway/proxy.

## Sikkerhet

- Sett alltid `XLENT_SCANNER_API_KEY` når API-et skal brukes fra Power Apps/gateway.
- Send API-nøkkelen som header: `X-API-Key: <nøkkel>`.
- API-et returnerer ikke `original_text`, for å unngå at hele dokumentinnholdet flyttes inn i Power Platform.
- Standard maks filstørrelse er 25 MB. Kan endres med `XLENT_SCANNER_API_MAX_FILE_MB`.

## Power Apps Custom Connector

1. Start API-serveren på maskinen som skal kjøre scanneren.
2. Installer/konfigurer Power Platform on-premises data gateway hvis Power Apps skal nå lokal maskin.
3. I Power Apps: opprett en Custom Connector fra OpenAPI/Swagger-filen `docs/power-apps-openapi.json`.
4. Sett host/base URL til API-serveren, normalt `http://localhost:51291` når gateway kjører på samme maskin.
5. Sett authentication til API Key.
6. Bruk header-navn `X-API-Key`.
7. Test først `Health`, deretter `ScanText`.


## Eksempel i Power Apps

Etter at Custom Connector er importert, kan tekstskanning typisk kalles slik fra en knapp:

```powerfx
Set(
    scanResult,
    XLENTScannerAPI.ScanText({
        text: TextInput_DocumentText.Text,
        language: "auto"
    })
)
```

Vis risikonivå:

```powerfx
scanResult.risk_level
```

Vis funn i en gallery:

```powerfx
scanResult.findings
```

Filskanning er mer krevende i Canvas Apps. Anbefalt MVP er:

1. Bruk Dataverse eller SharePoint som midlertidig attachment-kilde.
2. Start en Power Automate-flow fra Power Apps.
3. La flowen lese filinnholdet som base64.
4. Kall `ScanFile` i XLENT Scanner Custom Connector.
5. Returner `ScanResult` til Power Apps.

Dette er bedre enn å forsøke å bygge filopplasting direkte i Canvas App-formler, fordi Power Apps sitt Attachments-kontroll er tett knyttet til SharePoint/Dataverse-former.

## Viktigste kall

### Health

`GET /api/health`

Respons:

```json
{
  "ok": true,
  "service": "xlent-scanner",
  "version": "1.3.4",
  "api_key_configured": true,
  "max_file_mb": 25
}
```

### ScanText

`POST /api/scan-text`

```json
{
  "text": "Kari Nordmann, kari@example.com, 01017012345",
  "language": "auto"
}
```

### ScanFile

`POST /api/scan-file`

```json
{
  "file_name": "kundeavtale.pdf",
  "content_base64": "<base64-innhold>",
  "language": "auto",
  "ignore_xlent": false
}
```

Respons fra `ScanText` og `ScanFile`:

```json
{
  "ok": true,
  "scan_id": "uuid",
  "file_name": "kundeavtale.pdf",
  "risk_level": "rød",
  "risk_summary": "...",
  "recommended_action": "...",
  "findings": [
    {
      "category": "e-post",
      "text": "kari@example.com",
      "context": "...",
      "severity": "gul"
    }
  ]
}
```

### DeepScan

`POST /api/deep-scan`

```json
{
  "scan_id": "uuid-fra-scan",
  "model": "llama3.2:3b",
  "min_confidence": "medium"
}
```

Respons:

```json
{
  "ok": true,
  "scan_id": "uuid-fra-scan",
  "job_id": "deep-scan-job"
}
```

Hent status:

`GET /api/deep-scan/{job_id}`

Avbryt:

`POST /api/deep-scan/{job_id}/cancel`

## Praktisk begrensning

Power Apps er egnet som tynn frontend for tekst og moderate filer. Store dokumenter, mange samtidige brukere og batch-scanning bør heller løses med en dedikert intern webapp eller kø-basert backend.


