# Syntetisk evalueringskorpus

Dette korpuset måler scannerens regelbaserte standard-skann med eksplisitt fasit.
Det inneholder ikke reelle kundeopplysninger eller fungerende hemmeligheter.

Kjør fra repository-roten:

```powershell
uv run python scripts/evaluate_accuracy.py
```

Resultatet skrives til konsollen med konkrete avvik. Lag både maskinlesbar JSON
og en selvstendig HTML-rapport slik:

```powershell
uv run python scripts/evaluate_accuracy.py `
  --output artifacts/evaluation/current.json `
  --html-output artifacts/evaluation/current.html
```

HTML-filen kan åpnes direkte i nettleseren og bruker ingen eksterne ressurser.
Kontroller rapporten mot forrige release slik:

```powershell
uv run python scripts/check_evaluation_regression.py `
  --baseline evaluation/baselines/v1.9.15.json `
  --current artifacts/evaluation/current.json
```

Porten avviser færre caser, flere falske negative, lavere F1 eller flere
feilklassifiserte risikonivåer. Den kjøres også i CI. AI-dybdeskann inngår ikke
i denne deterministiske porten.

## Fasit

Hver JSON-fil under `cases/` er ett scenario. `expected_findings` er den
menneskesatte fasiten. Alle andre aktive scannerfunn telles som falske positive.
Et forventet funn som ikke finnes, telles som falskt negativt. Verdifeltet kan
utelates for maskerte hemmeligheter.

Kategorinøklene er stabile og defineres i `taxonomy.json`. De er skilt fra
visningsteksten som scanneren returnerer.

## Avgrensning i versjon 1

- Ren tekst via `scan_text()`
- Ingen Ollama. AI-dybdeskann måles separat i `evaluation_ai/`.
- Ingen OCR eller dokumentgenerator
- Ingen reelle person- eller kundedata
- Automatisk regresjonsport mot forrige versjon, men ingen absolutt F1-terskel

Numre og nøkler er gjenbrukte testverdier fra repositoryets eksisterende
detektortester. De skal ikke brukes utenfor testformål.
