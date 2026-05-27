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


# ── Prompt-maler ────────────────────────────────────────────────────────

_SYS = (
    "Du er en GDPR-ekspert. Svar ALLTID med gyldig JSON, aldri med annen tekst."
)

_PROMPT_NB = """\
Analyser teksten for GDPR-sensitive personopplysninger.
Identifiser: personnavn, adresser, telefonnumre, e-poster, fødselsnumre/personnumre, \
bankkontonumre, kredittkortnumre, helseopplysninger, fagforeningsmedlemskap, \
etnisk bakgrunn, religiøs overbevisning, politisk ståsted, biometriske data.

Svar KUN med JSON på denne formen (ingen annen tekst):
{{"findings":[{{"category":"Kategori","text":"funnet tekst","context":"noen ord rundt funnet"}}]}}
Ingen funn → {{"findings":[]}}

Tekst:
{chunk}"""

_PROMPT_SV = """\
Analysera texten för GDPR-känsliga personuppgifter.
Identifiera: personnamn, adresser, telefonnummer, e-postadresser, personnummer, \
bankkontonummer, kreditkortsnummer, hälsoinformation, fackföreningsmedlemskap, \
etnisk bakgrund, religiös övertygelse, politisk ståndpunkt, biometriska data.

Svara BARA med JSON i detta format (ingen annan text):
{{"findings":[{{"category":"Kategori","text":"hittad text","context":"omgivande ord"}}]}}
Inga fynd → {{"findings":[]}}

Text:
{chunk}"""

_PROMPT_EN = """\
Analyse the text for GDPR-sensitive personal data.
Identify: personal names, addresses, phone numbers, emails, national ID numbers, \
bank account numbers, credit card numbers, health information, union membership, \
ethnic background, religious beliefs, political views, biometric data.

Respond ONLY with JSON in this format (no other text):
{{"findings":[{{"category":"Category","text":"found text","context":"surrounding words"}}]}}
No findings → {{"findings":[]}}

Text:
{chunk}"""

_PROMPTS: dict[str, str] = {"nb": _PROMPT_NB, "sv": _PROMPT_SV, "en": _PROMPT_EN}


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


def _run_deep_scan(text: str, model: str, lang: str, job_id: str) -> None:
    chunks = _split_chunks(text)
    n = len(chunks)
    prompt_tpl = _PROMPTS.get(lang, _PROMPTS["nb"])
    all_raw: list[dict] = []

    for idx, chunk in enumerate(chunks, 1):
        with _job_lock:
            if _job.get("job_id") != job_id or _job.get("cancelled"):
                return
            _job["progress"] = f"Analyserer del {idx} av {n}…"

        findings = _call_ollama(model, prompt_tpl.format(chunk=chunk))
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

def start_deep_scan(text: str, model: str, lang: str = "nb") -> str:
    """Start dybdeskanning i bakgrunn. Returnerer job_id."""
    import uuid
    job_id = str(uuid.uuid4())[:8]
    with _job_lock:
        _job.clear()
        _job.update({
            "job_id":    job_id,
            "status":    "running",
            "progress":  "Starter…",
            "findings":  [],
            "cancelled": False,
            "model":     model,
            "started_at": time.time(),
        })
    t = threading.Thread(
        target=_run_deep_scan,
        args=(text, model, lang, job_id),
        daemon=True,
        name=f"deep-scan-{job_id}",
    )
    t.start()
    LOGGER.info("Dybdeskann startet: job=%s model=%s lang=%s", job_id, model, lang)
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
