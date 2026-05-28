"""Dybdeskanning via lokal Ollama LLM.

Sender tekstbiter til en Ollama-modell og ber den identifisere
GDPR-sensitive personopplysninger som regel-baserte detektorer kan misse.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any

LOGGER = logging.getLogger(__name__)
OLLAMA_BASE = "http://localhost:11434"

# Chunk-størrelse i ord. 900 ord gir ~1200 tokens – passer alle 1B-7B-modeller.
_CHUNK_WORDS   = 900
_CHUNK_OVERLAP = 80   # overlappende ord mellom påfølgende chunks

# Anbefalte modeller i prioritert rekkefølge (vises som forslag i UI)
RECOMMENDED_MODELS = [
    "llama3.2:3b",
    "llama3.2:1b",
    "llama3:8b",
    "gemma2:2b",
    "mistral:7b",
    "phi3.5:mini",
]

# Søkekategorier – nøkkel → norsk beskrivelse til LLM-prompt
CATEGORIES: dict[str, str] = {
    "navn":          "personnavn – fornavn OG etternavn på virkelige enkeltpersoner",
    "adresse":       "fullstendige fysiske adresser med gatenavn OG husnummer",
    "telefon":       "telefonnumre (norske og internasjonale)",
    "personnummer":  "norske fødselsnumre (11 siffer) og personnumre",
    "bankkonto":     "bankkontonumre (11 siffer) og IBAN-numre",
    "selskapsnavn":  "selskapsnavn, firmanavn og organisasjonsnavn",
    "budsjett_tall": "konkrete pengebeløp med valutasymbol/kode (kr, NOK, EUR, USD, $, €) eller prosentandeler av verdi",
}

# Én aktiv jobb om gangen
_job: dict[str, Any] = {}
_job_lock = threading.Lock()


# ── Ollama REST-hjelpere ────────────────────────────────────────────────

def _get(path: str, timeout: int = 5) -> Any:
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{path}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path: str, data: dict, timeout: int = 180) -> Any:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Status ──────────────────────────────────────────────────────────────

def ollama_status() -> dict[str, Any]:
    """Sjekk om Ollama kjører og hent liste over installerte modeller."""
    try:
        data = _get("/api/tags")
        models = [m["name"] for m in (data.get("models") or [])]
        return {"running": True, "models": sorted(models)}
    except (urllib.error.URLError, OSError):
        return {"running": False, "models": []}
    except Exception as exc:
        return {"running": False, "models": [], "error": str(exc)}


def ollama_hardware_info() -> dict[str, Any]:
    """Sjekk om Ollama bruker GPU eller CPU via /api/ps.

    Returnerer:
        mode: "gpu" | "hybrid" | "cpu"
        gpu:  True/False
        vram_mb:  VRAM i bruk (MB)
        total_mb: Modellstørrelse (MB)
    """
    try:
        data = _get("/api/ps", timeout=3)
        models = data.get("models") or []
        if not models:
            return {"mode": "cpu", "gpu": False, "vram_mb": 0, "total_mb": 0}
        m = models[0]
        size      = int(m.get("size", 0) or 0)
        size_vram = int(m.get("size_vram", 0) or 0)
        total_mb  = round(size / 1024 / 1024)
        vram_mb   = round(size_vram / 1024 / 1024)
        if size_vram == 0:
            mode = "cpu"
            gpu  = False
        elif size_vram >= size * 0.85:
            mode = "gpu"
            gpu  = True
        else:
            mode = "hybrid"
            gpu  = True
        return {"mode": mode, "gpu": gpu, "vram_mb": vram_mb, "total_mb": total_mb}
    except Exception:
        return {"mode": "cpu", "gpu": False, "vram_mb": 0, "total_mb": 0}


# ── Prompt-builder (dynamisk basert på valgte kategorier) ───────────────

_SYS = (
    "Du er en GDPR-ekspert med høy presisjon. "
    "Rapporter KUN funn du er sikker på. "
    "Svar ALLTID med gyldig JSON, aldri med annen tekst."
)

# Eksplisitte eksklusjonsregler per kategori og språk
_EXCLUSIONS_NB = """\
Strenge regler – IKKE flag:
- Personnavn: bynavn, selskapsnavn, produktnavn, fraser i store bokstaver (f.eks. «YARA PAYS FOR»), funksjonstitler, land, organisasjoner. Personnavn MÅ bestå av fornavn + etternavn.
- Adresse: enkelt bynavn (Oslo, Bergen, Trondheim, Ålesund), land, regioner, destinasjonsnavn. Adresse MÅ ha gatenavn OG husnummer.
- Budsjett/beløp: tidsuttrykk (uker, måneder, «4-6 week»), antall personer/enheter, generelle prosentandeler uten pengesammenheng, generelle tall. Beløp MÅ ha valutasymbol (kr, NOK, €, $) eller tydelig budsjett/prissammenheng.
"""

_EXCLUSIONS_SV = """\
Strikta regler – flagga INTE:
- Personnamn: stadsnamn, företagsnamn, produktnamn, fraser med versaler, titlar, länder. Personnamn MÅSTE bestå av förnamn + efternamn.
- Adress: enbart stadsnamn (Stockholm, Göteborg, Oslo), länder, regioner. Adress MÅSTE ha gatunamn OCH husnummer.
- Budget/belopp: tidsuttryck (veckor, månader), antal personer/enheter, allmänna procentsatser utan penningsammanhang. Belopp MÅSTE ha valutasymbol (kr, SEK, €, $) eller tydligt pris-/budgetsammanhang.
"""

_EXCLUSIONS_EN = """\
Strict rules – do NOT flag:
- Personal names: city names, company names, product names, ALL-CAPS phrases (e.g. «YARA PAYS FOR»), job titles, countries, organisations. Personal names MUST have both first name AND last name.
- Address: city or country names alone (London, Oslo, Germany), regions, destinations. Address MUST include a street name AND house/building number.
- Budget/amounts: time expressions (weeks, months, «4-6 week»), headcounts, generic percentages without monetary context, plain numbers. Amounts MUST have a currency symbol (NOK, EUR, USD, $, £, €) or clear price/budget context.
"""


def _build_prompt(categories: list[str], chunk: str, lang: str = "nb") -> str:
    """Bygg LLM-prompt dynamisk basert på valgte søkekategorier."""
    active = [CATEGORIES[c] for c in categories if c in CATEGORIES]
    if not active:
        active = list(CATEGORIES.values())
    cat_list = "\n".join(f"- {a}" for a in active)

    if lang == "sv":
        return (
            f"Analysera texten och identifiera följande typer av känslig information:\n{cat_list}\n\n"
            f"{_EXCLUSIONS_SV}\n"
            "Svara BARA med JSON i detta format (ingen annan text):\n"
            '{{"findings":[{{"category":"Kategori","text":"hittad text","context":"omgivande ord"}}]}}\n'
            "Inga fynd → {{\"findings\":[]}}\n\nText:\n" + chunk
        )
    elif lang == "en":
        return (
            f"Analyse the text and identify the following types of sensitive information:\n{cat_list}\n\n"
            f"{_EXCLUSIONS_EN}\n"
            "Respond ONLY with JSON in this format (no other text):\n"
            '{{"findings":[{{"category":"Category","text":"found text","context":"surrounding words"}}]}}\n'
            "No findings → {{\"findings\":[]}}\n\nText:\n" + chunk
        )
    else:  # nb
        return (
            f"Analyser teksten og identifiser følgende typer sensitiv informasjon:\n{cat_list}\n\n"
            f"{_EXCLUSIONS_NB}\n"
            "Svar KUN med JSON på denne formen (ingen annen tekst):\n"
            '{{"findings":[{{"category":"Kategori","text":"funnet tekst","context":"noen ord rundt funnet"}}]}}\n'
            "Ingen funn → {{\"findings\":[]}}\n\nTekst:\n" + chunk
        )


# ── Tekst-oppdeling ─────────────────────────────────────────────────────

def _split_chunks(text: str) -> list[str]:
    words = text.split()
    if len(words) <= _CHUNK_WORDS:
        return [text] if text.strip() else []
    chunks: list[str] = []
    step = _CHUNK_WORDS - _CHUNK_OVERLAP
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + _CHUNK_WORDS])
        chunks.append(chunk)
        if i + _CHUNK_WORDS >= len(words):
            break
        i += step
    return chunks


# ── LLM-kall ────────────────────────────────────────────────────────────

def _parse_findings(raw: str) -> list[dict]:
    """Forsøk å parse JSON fra LLM-respons. Tolererer litt ekstra tekst."""
    raw = raw.strip()
    try:
        return json.loads(raw).get("findings") or []
    except (json.JSONDecodeError, AttributeError):
        pass
    # Finn første {...} blokk
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start >= 0 < end and end > start:
        try:
            return json.loads(raw[start:end]).get("findings") or []
        except (json.JSONDecodeError, AttributeError):
            pass
    return []


def _call_ollama(model: str, prompt: str) -> list[dict]:
    try:
        result = _post("/api/generate", {
            "model":   model,
            "prompt":  prompt,
            "system":  _SYS,
            "stream":  False,
            "format":  "json",
            "options": {"temperature": 0.05, "num_predict": 1024},
        })
        return _parse_findings(result.get("response", ""))
    except Exception as exc:
        LOGGER.warning("Ollama-kall feilet: %s", exc)
        return []


# ── Dybdeskann-bakgrunnstråd ────────────────────────────────────────────

def _deduplicate(raw: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for f in raw:
        key = (f.get("category", "") + "|" + f.get("text", "")).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _run_deep_scan(
    text: str, model: str, lang: str, job_id: str, categories: list[str]
) -> None:
    chunks = _split_chunks(text)
    n = len(chunks)
    all_raw: list[dict] = []

    for idx, chunk in enumerate(chunks, 1):
        with _job_lock:
            if _job.get("job_id") != job_id or _job.get("cancelled"):
                return
            _job["progress"] = f"Analyserer del {idx} av {n}…"

        prompt = _build_prompt(categories, chunk, lang)
        findings = _call_ollama(model, prompt)
        all_raw.extend(findings)

    deduped = _deduplicate(all_raw)
    # Legg til 🤖-prefiks på kategori
    for f in deduped:
        cat = str(f.get("category") or "AI-funn").strip()
        if not cat.startswith("🤖"):
            f["category"] = f"🤖 {cat}"

    with _job_lock:
        if _job.get("job_id") == job_id:
            _job.update({
                "status":   "done",
                "progress": f"Ferdig – {len(deduped)} nye funn",
                "findings": deduped,
            })
    LOGGER.info("Dybdeskann ferdig: job=%s model=%s funn=%d", job_id, model, len(deduped))


# ── Offentlige API-er ───────────────────────────────────────────────────

def start_deep_scan(
    text: str, model: str, lang: str = "nb", categories: list[str] | None = None
) -> str:
    """Start dybdeskanning i bakgrunn. Returnerer job_id."""
    import uuid
    job_id = str(uuid.uuid4())[:8]
    cats = categories or list(CATEGORIES.keys())
    with _job_lock:
        _job.clear()
        _job.update({
            "job_id":     job_id,
            "status":     "running",
            "progress":   "Starter…",
            "findings":   [],
            "cancelled":  False,
            "model":      model,
            "categories": cats,
            "started_at": time.time(),
        })
    t = threading.Thread(
        target=_run_deep_scan,
        args=(text, model, lang, job_id, cats),
        daemon=True,
        name=f"deep-scan-{job_id}",
    )
    t.start()
    LOGGER.info("Dybdeskann startet: job=%s model=%s lang=%s cats=%s", job_id, model, lang, cats)
    return job_id


def get_deep_scan_status() -> dict[str, Any]:
    """Hent status/resultat for siste dybdeskann."""
    with _job_lock:
        return dict(_job)


def cancel_deep_scan() -> None:
    """Avbryt pågående dybdeskann."""
    with _job_lock:
        _job["cancelled"] = True
        _job["status"]    = "cancelled"
        _job["progress"]  = "Avbrutt"
