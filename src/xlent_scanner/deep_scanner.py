"""Dybdeskanning via lokal Ollama LLM.

Sender tekstbiter til en Ollama-modell og ber den identifisere
GDPR-sensitive personopplysninger som regel-baserte detektorer kan misse.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

LOGGER = logging.getLogger(__name__)

# URL kan overstyres med miljøvariabelen OLLAMA_BASE_URL.
# Eksempel: OLLAMA_BASE_URL=http://192.168.1.10:11434 xlent-scanner
OLLAMA_BASE: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")

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

# Søkekategorier – nøkkel → kort beskrivelse (vises i UI og sendes til LLM som kontekst)
CATEGORIES: dict[str, str] = {
    "navn":          "personnavn – fornavn OG etternavn (ikke bynavn, titler eller CAPS-fraser)",
    "adresse":       "fysisk adresse – gatenavn OG husnummer (ikke bynavn alene eller tekniske termer)",
    "epost":         "e-postadresser – format: navn@domene.tld",
    "telefon":       "telefonnumre – 8-sifret norsk eller internasjonal med landkode",
    "personnummer":  "norske fødselsnumre – nøyaktig 11 siffer",
    "bankkonto":     "bankkontonumre – 11-sifret norsk eller IBAN",
    "selskapsnavn":  "offisielle firma- og organisasjonsnavn (ikke produkter eller teknologier)",
    "budsjett_tall": "pengebeløp MED valutasymbol/-kode: kr, NOK, EUR, USD, $, € (ikke tidsuttrykk eller tall uten valuta)",
    "nettadresse":   "nettadresser/URL-er som begynner med http://, https:// eller www.",
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
    "Du er en personvernekspert med svært høy presisjon. "
    "Rapporter KUN funn du er helt sikker på. "
    "Gi hvert funn en konfidens: \"high\" (helt sikkert), \"medium\" (sannsynlig) eller \"low\" (usikkert). "
    "Svar ALLTID med gyldig JSON, aldri med annen tekst."
)

# Regler med ✅/❌ eksempler – mer effektivt enn rene tekstlige eksklusjoner
_RULES_NB = """\
Finn KUN personopplysninger som KONKRET identifiserer enkeltpersoner. Bruk disse reglene:

Personnavn – MÅ ha fornavn OG etternavn på en virkelig person:
  ✅ «Thomas Elboth»  ✅ «Maria Hansen»  ✅ «John Smith»
  ❌ «YARA»  ❌ «YARA PAYS FOR»  ❌ «Oslo»  ❌ «CEO»  ❌ «Microsoft»  ❌ enkelt fornavn  ❌ enkelt etternavn

Adresse – MÅ ha gatenavn OG husnummer (eller postboks):
  ✅ «Storgata 14»  ✅ «Karl Johans gate 1, 0154 Oslo»  ✅ «Pb 123, 1234 Sted»
  ❌ «Oslo»  ❌ «Trondheim»  ❌ «Ålesund»  ❌ «Østersund/ÅRE»  ❌ «Azure App Service»  ❌ «Cosmos DB»  ❌ sky-tjenester  ❌ tekniske termer  ❌ bynavn alene

E-postadresse – MÅ ha @-tegn og domenenavn:
  ✅ «thomas@xlent.no»  ✅ «kontakt@firma.com»  ✅ «user.name+tag@example.co.uk»
  ❌ URL-er uten @  ❌ brukernavn uten @

Telefon – 8-sifret norsk eller internasjonal med landkode:
  ✅ «90123456»  ✅ «+47 901 23 456»  ✅ «+47 91717678»  ✅ «0047 12345678»  ✅ «91 23 45 67»
  ❌ årstall  ❌ postnummer  ❌ 4-6 siffer  ❌ interne koder

Personnummer – nøyaktig 11 siffer i norsk fødselsdatoformat (DDMMÅÅ + individnr + 2 kontrollsifre):
  ✅ «21057234161»  ✅ «210572 34161»  ✅ «12034567891»  (med eller uten mellomrom)
  ❌ korte tall  ❌ kontonummer  ❌ datoer  ❌ tall med færre enn 11 siffer

Bankkonto – 11-sifret norsk kontonummer eller IBAN:
  ✅ «1234.56.78901»  ✅ «1730.1777.922»  ✅ «1730 1777 922»  ✅ «17301777922»  ✅ «NO9386011117947»
  ❌ telefonnummer  ❌ personnummer  ❌ korte tall

Selskapsnavn – offisielt firma, org. eller stiftelse:
  ✅ «XLENT AS»  ✅ «Equinor ASA»  ✅ «DNB Bank»
  ❌ produktnavn  ❌ teknologier («Azure», «Terraform», «Python»)  ❌ generelle termer  ❌ prosjektnavn

Pengebeløp – beløp med valutasymbol/-kode ELLER tall i en tydelig budsjettkontekst:
  ✅ «500 000 kr»  ✅ «NOK 1 200»  ✅ «€50 000»  ✅ «3 MNOK»  ✅ «15 mill kr»
  ✅ «Total NOK 180»  ✅ «Total Cost (NOK)» etterfulgt av tall
  ✅ Tall i kolonne merket «Cost (NOK)», «Amount», «Price» i et budsjett (eks: «30», «60», «100»)
  ❌ «4-6 week pilot»  ❌ «4-6 weeks»  ❌ «Q1 2025»  ❌ «50 ansatte»  ❌ «15 %»  ❌ tidsuttrykk
  ❌ løse tall uten noen form for budsjettkontekst

Nettadresse – URL som begynner med http://, https:// eller www.:
  ✅ «www.vg.no»  ✅ «https://xlent.no»  ✅ «http://intern.firma.com/dokument»
  ❌ e-postadresser  ❌ fil-stier  ❌ domenenavn uten protokoll eller www.
"""

_RULES_SV = """\
Hitta BARA personuppgifter som KONKRET identifierar enskilda personer. Använd dessa regler:

Personnamn – MÅSTE ha förnamn OCH efternamn på en verklig person:
  ✅ «Anna Svensson»  ✅ «Erik Lindqvist»
  ❌ «Stockholm»  ❌ «YARA PAYS FOR»  ❌ «CEO»  ❌ «Azure»  ❌ enbart förnamn  ❌ enbart efternamn

Adress – MÅSTE ha gatunamn OCH husnummer (eller postbox):
  ✅ «Storgatan 14»  ✅ «Kungsgatan 1, 111 43 Stockholm»
  ❌ «Stockholm»  ❌ «Göteborg»  ❌ «Östersund»  ❌ «Azure App Service»  ❌ molntjänster  ❌ stadsnamn ensamt

E-postadress – MÅSTE ha @-tecken och domännamn:
  ✅ «anna@xlent.se»  ✅ «kontakt@foretag.com»
  ❌ URL-er utan @  ❌ användarnamn utan @

Telefon – 8-siffrigt svenskt/norskt eller internationellt med landskod:
  ✅ «070-123 45 67»  ✅ «+46 701 23 45 67»  ✅ «+47 91717678»  ✅ «0047 12345678»
  ❌ årtal  ❌ postnummer  ❌ 4-6 siffror

Personnummer – 10-11 siffror i personnummerformat (med eller utan bindestreck/mellanrum):
  ✅ «19900101-1234»  ✅ «811218-0008»  ✅ «210572 34161»  ✅ «21057234161»
  ❌ korta tal  ❌ kontonummer  ❌ datum  ❌ tal med färre än 10 siffror

Bankkonto – IBAN eller kontonummer:
  ✅ «SE4550000000058398257466»  ✅ «1730.1777.922»  ✅ «1730 1777 922»  ✅ «17301777922»
  ❌ telefonnummer  ❌ personnummer

Företagsnamn – officiellt bolag, org. eller stiftelse:
  ✅ «Volvo AB»  ✅ «Ericsson AB»
  ❌ produktnamn  ❌ teknologier  ❌ projektnamn

Penningbelopp – belopp med valutasymbol/-kod ELLER tal i tydlig budgetkontext:
  ✅ «500 000 kr»  ✅ «SEK 1 200»  ✅ «€50 000»  ✅ «Totalt SEK 180»
  ✅ Tal i kolumn märkt «Kostnad (SEK)», «Belopp», «Pris» i ett budget (t.ex. «30», «60»)
  ❌ «4-6 veckor»  ❌ «Q1 2025»  ❌ «50 anställda»  ❌ tidsuttryck  ❌ lösa tal utan kontext

Webbadress – URL som börjar med http://, https:// eller www.:
  ✅ «www.vg.no»  ✅ «https://xlent.se»  ✅ «http://intern.foretag.se/dokument»
  ❌ e-postadresser  ❌ filsökvägar  ❌ domännamn utan protokoll eller www.
"""

_RULES_EN = """\
Find ONLY personal data that CONCRETELY identifies individuals. Use these rules:

Personal name – MUST have both first name AND last name of a real person:
  ✅ «John Smith»  ✅ «Maria Hansen»
  ❌ «YARA»  ❌ «YARA PAYS FOR»  ❌ «London»  ❌ «CEO»  ❌ «Microsoft»  ❌ first name only  ❌ last name only

Address – MUST have a street name AND house/building number:
  ✅ «14 Baker Street»  ✅ «Karl Johans gate 1, Oslo»
  ❌ «Oslo»  ❌ «Trondheim»  ❌ «London»  ❌ «Azure App Service»  ❌ «Cosmos DB vector store»  ❌ cloud services  ❌ city name alone  ❌ technical terms

Email address – MUST have @ sign and domain name:
  ✅ «john@xlent.com»  ✅ «contact@company.co.uk»
  ❌ URLs without @  ❌ usernames without @

Phone – 8-digit national or international with country code:
  ✅ «+44 7911 123456»  ✅ «90123456»  ✅ «+47 91717678»  ✅ «0047 12345678»
  ❌ years  ❌ postal codes  ❌ 4-6 digit numbers

ID/SSN – national identity number format (11-digit Norwegian, with or without space):
  ✅ «21057234161»  ✅ «210572 34161»  ✅ «12034567891»
  ❌ numbers with fewer than 11 digits  ❌ account numbers  ❌ dates

Bank account – national account number or IBAN:
  ✅ «GB29 NWBK 6016 1331 9268 19»  ✅ «1730.1777.922»  ✅ «1730 1777 922»  ✅ «17301777922»
  ❌ phone numbers  ❌ ID numbers

Company name – official company, org., or foundation:
  ✅ «XLENT AS»  ✅ «Equinor ASA»
  ❌ product names  ❌ technologies («Azure», «Terraform»)  ❌ project names  ❌ generic terms

Monetary amount – amounts with a currency symbol/code OR numbers in a clear budget context:
  ✅ «NOK 500 000»  ✅ «$1,200»  ✅ «€50 000»  ✅ «3 MNOK»  ✅ «Total NOK 180»
  ✅ Numbers in columns labelled «Cost (NOK)», «Amount», «Price» in a budget table (e.g. «30», «60», «100»)
  ❌ «4-6 week pilot»  ❌ «4-6 weeks»  ❌ «Q1 2025»  ❌ «50 employees»  ❌ time expressions
  ❌ isolated numbers with no budget or price context

Web address – URL starting with http://, https:// or www.:
  ✅ «www.vg.no»  ✅ «https://xlent.com»  ✅ «http://internal.company.com/doc»
  ❌ email addresses  ❌ file paths  ❌ domain names without a protocol or www.
"""


def _build_prompt(categories: list[str], chunk: str, lang: str = "nb") -> str:
    """Bygg LLM-prompt dynamisk basert på valgte søkekategorier."""
    active = [CATEGORIES[c] for c in categories if c in CATEGORIES]
    if not active:
        active = list(CATEGORIES.values())
    cat_list = "\n".join(f"- {a}" for a in active)

    if lang == "sv":
        return (
            f"Analysera texten nedan. Sök efter dessa kategorier:\n{cat_list}\n\n"
            f"{_RULES_SV}\n"
            "Svara BARA med JSON i detta format (ingen annan text):\n"
            '{{"findings":[{{"category":"Kategori","text":"hittad text","context":"omgivande ord","confidence":"high"}}]}}\n'
            "Inga fynd → {{\"findings\":[]}}\n\nText:\n" + chunk
        )
    elif lang == "en":
        return (
            f"Analyse the text below. Search for these categories:\n{cat_list}\n\n"
            f"{_RULES_EN}\n"
            "Respond ONLY with JSON in this format (no other text):\n"
            '{{"findings":[{{"category":"Category","text":"found text","context":"surrounding words","confidence":"high"}}]}}\n'
            "No findings → {{\"findings\":[]}}\n\nText:\n" + chunk
        )
    else:  # nb
        return (
            f"Analyser teksten nedenfor. Søk etter disse kategoriene:\n{cat_list}\n\n"
            f"{_RULES_NB}\n"
            "Svar KUN med JSON på denne formen (ingen annen tekst):\n"
            '{{"findings":[{{"category":"Kategori","text":"funnet tekst","context":"noen ord rundt funnet","confidence":"high"}}]}}\n'
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
    text: str, model: str, lang: str, job_id: str, categories: list[str],
    min_confidence: str = "medium",
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

    # ── Regex-supplementer: kategorier der regelbaserte detektorer er mer
    # pålitelige enn LLM-modellen (spesielt små modeller som llama3.2:1b/3b).
    # Funn herfra får confidence="high" og 🤖-prefiks som alle andre AI-funn.

    # Nettadresse: AI-modeller hopper ofte over URL-er som «ikke-sensitive».
    if "nettadresse" in categories:
        try:
            from xlent_scanner.detectors.regex_url import detect_urls  # noqa: PLC0415
            for f in detect_urls(text):
                all_raw.append({
                    "category":   "Nettadresse",
                    "text":       f.text,
                    "context":    f.context,
                    "confidence": "high",
                })
        except Exception as exc:
            LOGGER.warning("Nettadresse regex-supplement feilet: %s", exc)

    # Personnummer / D-nummer: mod-11-validering er 100 % pålitelig.
    # Små LLM-modeller gjenkjenner ikke alltid 11-sifret norsk FNR-format.
    if "personnummer" in categories:
        try:
            from xlent_scanner.detectors.regex_no import find_fnr  # noqa: PLC0415
            for f in find_fnr(text):
                all_raw.append({
                    "category":   f.category.capitalize(),  # "Fødselsnummer" / "D-nummer" / "Mulig personnummer (format)"
                    "text":       f.text,
                    "context":    f.context,
                    "confidence": "high" if f.category in ("fødselsnummer", "d-nummer") else "medium",
                })
        except Exception as exc:
            LOGGER.warning("Personnummer regex-supplement feilet: %s", exc)

    # E-post: regex er deterministisk og fanger alltid korrekte e-poster.
    if "epost" in categories:
        try:
            from xlent_scanner.detectors.regex_no import find_emails  # noqa: PLC0415
            for f in find_emails(text):
                all_raw.append({
                    "category":   "E-post",
                    "text":       f.text,
                    "context":    f.context,
                    "confidence": "high",
                })
        except Exception as exc:
            LOGGER.warning("E-post regex-supplement feilet: %s", exc)

    # Bankkontonummer: mod-11-validering er 100 % pålitelig.
    if "bankkonto" in categories:
        try:
            from xlent_scanner.detectors.regex_no import find_kontonummer  # noqa: PLC0415
            from xlent_scanner.detectors.iban import find_iban  # noqa: PLC0415
            for f in find_kontonummer(text):
                all_raw.append({
                    "category":   "Kontonummer",
                    "text":       f.text,
                    "context":    f.context,
                    "confidence": "high",
                })
            for f in find_iban(text):
                all_raw.append({
                    "category":   "IBAN",
                    "text":       f.text,
                    "context":    f.context,
                    "confidence": "high",
                })
        except Exception as exc:
            LOGGER.warning("Bankkonto regex-supplement feilet: %s", exc)

    deduped = _deduplicate(all_raw)

    # Filtrer etter minimumskonfidens
    _CONF_ORDER = {"high": 2, "medium": 1, "low": 0}
    min_conf_val = _CONF_ORDER.get(min_confidence, 1)
    deduped = [
        f for f in deduped
        if _CONF_ORDER.get(str(f.get("confidence", "medium")).lower(), 1) >= min_conf_val
    ]

    # Filtrer mot brukerens whitelist – samme logikk som regelbasert skann
    try:
        from xlent_scanner.whitelist import load_whitelist  # noqa: PLC0415
        wl = load_whitelist()
        if wl:
            before = len(deduped)
            deduped = [f for f in deduped if f.get("text", "").lower() not in wl]
            removed = before - len(deduped)
            if removed:
                LOGGER.info("AI-whitelist: fjernet %d funn", removed)
    except Exception as exc:
        LOGGER.warning("AI-whitelist-filter feilet: %s", exc)

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
    text: str, model: str, lang: str = "nb", categories: list[str] | None = None,
    min_confidence: str = "medium",
) -> str:
    """Start dybdeskanning i bakgrunn. Returnerer job_id."""
    import uuid
    job_id = str(uuid.uuid4())[:8]
    cats = categories or list(CATEGORIES.keys())
    with _job_lock:
        _job.clear()
        _job.update({
            "job_id":         job_id,
            "status":         "running",
            "progress":       "Starter…",
            "findings":       [],
            "cancelled":      False,
            "model":          model,
            "categories":     cats,
            "min_confidence": min_confidence,
            "started_at":     time.time(),
        })
    t = threading.Thread(
        target=_run_deep_scan,
        args=(text, model, lang, job_id, cats, min_confidence),
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
