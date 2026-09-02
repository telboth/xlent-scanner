# Syntetisk korpus for AI-dybdeskann

Dette korpuset måler bare funnene fra lokal AI-dybdeskann. Det blandes ikke med
den deterministiske standardrapporten eller dens releaseport.

Kjør tre repetisjoner med en eksplisitt lokal modell:

```powershell
uv run python scripts/evaluate_ai_accuracy.py `
  --model llama3.2:3b `
  --repetitions 3 `
  --output artifacts/evaluation/ai-current.json `
  --html-output artifacts/evaluation/ai-current.html
```

Rapporten lagrer modellnavn, modell-digest, Ollama-adresse, resultater per
repetisjon og om resultatet var stabilt. Dokumenttekst sendes gjennom den samme
Ollama-forbindelsen og den samme eksplisitte tillatelseskontrollen som vanlig
AI-dybdeskann.

AI-baselinen blokkerer foreløpig ikke release. Resultatene er modellspesifikke
og må vurderes over flere kjøringer før en terskel fastsettes.

Korpuset inneholder bare syntetiske navn, adresser og situasjoner.
