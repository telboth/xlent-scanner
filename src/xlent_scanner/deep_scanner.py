"""Dybdeskanning via lokal Ollama LLM.

Sender tekstbiter til en Ollama-modell og ber den identifisere
GDPR-sensitive personopplysninger som regel-baserte detektorer kan misse.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from xlent_scanner.detectors.ner_names import looks_like_person_name

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
    "navn":          "personnavn – fornavn OG etternavn (ikke roller, organisasjoner, kommuner, etater, team eller leverandører)",
    "adresse":       "fysisk adresse – gatenavn OG husnummer (ikke bynavn alene eller tekniske termer)",
    "epost":         "e-postadresser – format: navn@domene.tld",
    "telefon":       "telefonnumre – 8-sifret norsk eller internasjonal med landkode",
    "personnummer":  "norske fødselsnumre – nøyaktig 11 siffer",
    "bankkonto":     "bankkontonumre – 11-sifret norsk eller IBAN",
    "selskapsnavn":  "offisielle firma- og organisasjonsnavn (ikke produkter eller teknologier)",
    "budsjett_tall": "pengebeløp MED valutasymbol/-kode: kr, NOK, EUR, USD, $, € (ikke tidsuttrykk eller tall uten valuta)",
    "nettadresse":   "nettadresser/URL-er som begynner med http://, https:// eller www.",
    "medisinsk":     "medisinske opplysninger – sykdommer, diagnoser, symptomer, behandlinger og legemidler når de gjelder en person",
}
DEFAULT_CATEGORIES: tuple[str, ...] = tuple(c for c in CATEGORIES if c != "medisinsk")

# GUI-et bruker fortsatt "siste jobb", men API-et kan hente/cancelle konkret job_id.
_job: dict[str, Any] = {}
_jobs: dict[str, dict[str, Any]] = {}
_job_lock = threading.Lock()
_JOB_TTL_SECONDS = 60 * 60
_MAX_JOBS = 20

_pull_job: dict[str, Any] = {}
_pull_lock = threading.Lock()


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


def _cleanup_jobs_locked(now: float | None = None) -> None:
    now = now or time.time()
    expired = [
        jid for jid, job in _jobs.items()
        if now - float(job.get("started_at", 0)) > _JOB_TTL_SECONDS
    ]
    for jid in expired:
        _jobs.pop(jid, None)
    while len(_jobs) > _MAX_JOBS:
        oldest = min(_jobs, key=lambda jid: float(_jobs[jid].get("started_at", 0)))
        _jobs.pop(oldest, None)


# ── Status ──────────────────────────────────────────────────────────────

def ollama_status() -> dict[str, Any]:
    """Sjekk om Ollama kjører og hent liste over installerte modeller."""
    recommended = RECOMMENDED_MODELS[0]
    try:
        data = _get("/api/tags")
        models = [m["name"] for m in (data.get("models") or [])]
        sorted_models = sorted(models)
        return {
            "running": True,
            "models": sorted_models,
            "ollama_base": OLLAMA_BASE,
            "recommended_model": recommended,
            "recommended_installed": recommended in sorted_models,
            "install_command": f"ollama pull {recommended}",
        }
    except (urllib.error.URLError, OSError):
        return {
            "running": False,
            "models": [],
            "ollama_base": OLLAMA_BASE,
            "recommended_model": recommended,
            "recommended_installed": False,
            "install_command": f"ollama pull {recommended}",
        }
    except Exception as exc:
        return {
            "running": False,
            "models": [],
            "error": str(exc),
            "ollama_base": OLLAMA_BASE,
            "recommended_model": recommended,
            "recommended_installed": False,
            "install_command": f"ollama pull {recommended}",
        }


def _run_pull_model(model: str, job_id: str) -> None:
    with _pull_lock:
        if _pull_job.get("job_id") != job_id:
            return
        _pull_job.update({"status": "running", "progress": f"Laster ned {model}…"})
    try:
        _post("/api/pull", {"name": model, "stream": False}, timeout=900)
        with _pull_lock:
            if _pull_job.get("job_id") == job_id:
                _pull_job.update({"status": "done", "progress": f"{model} er installert."})
    except (urllib.error.URLError, OSError) as exc:
        with _pull_lock:
            if _pull_job.get("job_id") == job_id:
                _pull_job.update({"status": "error", "progress": "Ollama kjører ikke.", "error": str(exc)})
    except Exception as exc:
        with _pull_lock:
            if _pull_job.get("job_id") == job_id:
                _pull_job.update({"status": "error", "progress": str(exc), "error": str(exc)})


def pull_ollama_model(model: str | None = None) -> dict[str, Any]:
    """Start nedlasting av en Ollama-modell i bakgrunnstråd."""
    model = (model or RECOMMENDED_MODELS[0]).strip()
    if model not in RECOMMENDED_MODELS:
        return {"ok": False, "error": f"Ukjent eller ikke-anbefalt modell: {model}"}
    job_id = str(uuid.uuid4())[:8]
    with _pull_lock:
        if _pull_job.get("status") in {"queued", "running"}:
            return {"ok": True, "already_running": True, **dict(_pull_job)}
        _pull_job.clear()
        _pull_job.update({
            "job_id": job_id,
            "status": "queued",
            "progress": f"Køet nedlasting av {model}…",
            "model": model,
            "started_at": time.time(),
        })
    threading.Thread(
        target=_run_pull_model,
        args=(model, job_id),
        daemon=True,
        name=f"ollama-pull-{job_id}",
    ).start()
    return {"ok": True, **get_ollama_pull_status()}


def get_ollama_pull_status() -> dict[str, Any]:
    with _pull_lock:
        return dict(_pull_job) if _pull_job else {"status": "idle", "progress": ""}


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


def stop_ollama_model(model: str) -> dict[str, Any]:
    """Unload a model from Ollama without stopping the Ollama service."""
    model = (model or "").strip()
    if not model:
        return {"ok": False, "error": "Ingen Ollama-modell oppgitt."}

    try:
        _post(
            "/api/generate",
            {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": 0,
            },
            timeout=30,
        )
        LOGGER.info("Ollama model unloaded: %s", model)
        return {"ok": True, "model": model}
    except (urllib.error.URLError, OSError) as exc:
        LOGGER.warning("Ollama model unload failed, service unavailable: %s", exc)
        return {"ok": False, "model": model, "error": "Ollama kjører ikke."}
    except Exception as exc:
        LOGGER.warning("Ollama model unload failed for %s: %s", model, exc)
        return {"ok": False, "model": model, "error": str(exc)}


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
  ❌ roller/generiske ord: «brukeren», «veilederen», «saksbehandler»
  ❌ organisasjoner/etater/team: «Visma, Tieto og Oslo kommunes Fasit-team», «Arbeids- og velferdsdirektoratet», «Trondheim Digital», «DigiRogland»

Adresse – MÅ ha gatenavn OG husnummer (eller postboks):
  ✅ «Storgata 14»  ✅ «Karl Johans gate 1, 0154 Oslo»  ✅ «Pb 123, 1234 Sted»
  ❌ «Oslo»  ❌ «Trondheim»  ❌ «Ålesund»  ❌ «Østersund/ÅRE»  ❌ «kontorene vi besøkte»  ❌ «Azure App Service»  ❌ «Cosmos DB»  ❌ sky-tjenester  ❌ tekniske termer  ❌ bynavn alene

E-postadresse – MÅ ha @-tegn og domenenavn:
  ✅ «thomas@xlent.no»  ✅ «kontakt@firma.com»  ✅ «user.name+tag@example.co.uk»
  ❌ «Digdir»  ❌ URL-er uten @  ❌ brukernavn uten @  ❌ organisasjonsnavn uten @

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
  ✅ I regneark/tabeller: rapporter tall i økonomiske kolonner som «Cost», «Amount», «Price», «Total», «Budget», «Revenue», «Fee», «Rate», «Invoice»
  ✅ Ta med små tall som «30», «60», «100» når de står i slike økonomiske kolonner
  ❌ «4-6 week pilot»  ❌ «4-6 weeks»  ❌ «Q1 2025»  ❌ «50 ansatte»  ❌ «15 %»  ❌ tidsuttrykk
  ❌ tall i kolonner som «Hours», «Quantity», «Qty», «Count», «Year», «Date», «ID», «No.»
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
  ❌ roller/generiska ord: «användaren», «handledaren», «handläggare»
  ❌ organisationer/myndigheter/team: «Visma, Tieto och Oslo kommunes Fasit-team», «Arbeids- og velferdsdirektoratet», «Trondheim Digital», «DigiRogland»

Adress – MÅSTE ha gatunamn OCH husnummer (eller postbox):
  ✅ «Storgatan 14»  ✅ «Kungsgatan 1, 111 43 Stockholm»
  ❌ «Stockholm»  ❌ «Göteborg»  ❌ «Östersund»  ❌ «kontoren vi besökte»  ❌ «Azure App Service»  ❌ molntjänster  ❌ stadsnamn ensamt

E-postadress – MÅSTE ha @-tecken och domännamn:
  ✅ «anna@xlent.se»  ✅ «kontakt@foretag.com»
  ❌ «Digdir»  ❌ URL-er utan @  ❌ användarnamn utan @  ❌ organisationsnamn utan @

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
  ✅ I kalkylblad/tabeller: rapportera tal i ekonomiska kolumner som «Kostnad», «Belopp», «Pris», «Totalt», «Budget», «Intäkt», «Avgift», «Timpris», «Faktura»
  ✅ Ta med små tal som «30», «60», «100» när de står i sådana ekonomiska kolumner
  ❌ «4-6 veckor»  ❌ «Q1 2025»  ❌ «50 anställda»  ❌ tidsuttryck
  ❌ tal i kolumner som «Timmar», «Antal», «År», «Datum», «ID», «Nr.»  ❌ lösa tal utan kontext

Webbadress – URL som börjar med http://, https:// eller www.:
  ✅ «www.vg.no»  ✅ «https://xlent.se»  ✅ «http://intern.foretag.se/dokument»
  ❌ e-postadresser  ❌ filsökvägar  ❌ domännamn utan protokoll eller www.
"""

_RULES_EN = """\
Find ONLY personal data that CONCRETELY identifies individuals. Use these rules:

Personal name – MUST have both first name AND last name of a real person:
  ✅ «John Smith»  ✅ «Maria Hansen»
  ❌ «YARA»  ❌ «YARA PAYS FOR»  ❌ «London»  ❌ «CEO»  ❌ «Microsoft»  ❌ first name only  ❌ last name only
  ❌ roles/generic words: «the user», «case worker», «supervisor»
  ❌ organizations/agencies/teams: «Visma, Tieto and Oslo municipality's Fasit team», «Arbeids- og velferdsdirektoratet», «Trondheim Digital», «DigiRogland»

Address – MUST have a street name AND house/building number:
  ✅ «14 Baker Street»  ✅ «Karl Johans gate 1, Oslo»
  ❌ «Oslo»  ❌ «Trondheim»  ❌ «London»  ❌ «the offices we visited»  ❌ «Azure App Service»  ❌ «Cosmos DB vector store»  ❌ cloud services  ❌ city name alone  ❌ technical terms

Email address – MUST have @ sign and domain name:
  ✅ «john@xlent.com»  ✅ «contact@company.co.uk»
  ❌ «Digdir»  ❌ URLs without @  ❌ usernames without @  ❌ organization names without @

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
  ✅ In spreadsheets/tables: report numbers in financial columns such as «Cost», «Amount», «Price», «Total», «Budget», «Revenue», «Fee», «Rate», «Invoice»
  ✅ Include small numbers such as «30», «60», «100» when they are in those financial columns
  ❌ «4-6 week pilot»  ❌ «4-6 weeks»  ❌ «Q1 2025»  ❌ «50 employees»  ❌ time expressions
  ❌ numbers in columns such as «Hours», «Quantity», «Qty», «Count», «Year», «Date», «ID», «No.»
  ❌ isolated numbers with no budget or price context

Web address – URL starting with http://, https:// or www.:
  ✅ «www.vg.no»  ✅ «https://xlent.com»  ✅ «http://internal.company.com/doc»
  ❌ email addresses  ❌ file paths  ❌ domain names without a protocol or www.
"""

_MEDICAL_RULES_NB = """\
Medisinsk informasjon – sykdommer, diagnoser, symptomer, behandlinger eller legemidler knyttet til en person:
  ✅ «Anne har diabetes type 2»  ✅ «diagnose: ADHD»  ✅ «bruker Metformin»  ✅ «behandles med Sertralin»
  ✅ «sykmeldt for depresjon»  ✅ «astma», «kreft», «migrene» når teksten beskriver en person/pasient
  ❌ «fysisk betydning for brukeren»  ❌ generelle medisinske ord uten diagnose/sykdom/medisin/behandling  ❌ firmanavn  ❌ produktnavn uten helse-/pasientkontekst
  Rapporter den eksakte teksten som må redigeres bort, for eksempel sykdomsnavnet, diagnosen eller medisinnavnet.
"""

_MEDICAL_RULES_SV = """\
Medicinsk information – sjukdomar, diagnoser, symtom, behandlingar eller läkemedel kopplade till en person:
  ✅ «Anna har typ 2-diabetes»  ✅ «diagnos: ADHD»  ✅ «använder Metformin»  ✅ «behandlas med Sertralin»
  ✅ «sjukskriven för depression»  ✅ «astma», «cancer», «migrän» när texten beskriver en person/patient
  ❌ «fysisk betydelse för användaren»  ❌ generella medicinska ord utan diagnos/sjukdom/läkemedel/behandling  ❌ företagsnamn  ❌ produktnamn utan vård-/patientkontext
  Rapportera den exakta text som ska redigeras bort, till exempel sjukdomsnamnet, diagnosen eller läkemedelsnamnet.
"""

_MEDICAL_RULES_EN = """\
Medical information – diseases, diagnoses, symptoms, treatments, or medication names linked to a person:
  ✅ «Anne has type 2 diabetes»  ✅ «diagnosis: ADHD»  ✅ «uses Metformin»  ✅ «treated with Sertraline»
  ✅ «on sick leave for depression»  ✅ «asthma», «cancer», «migraine» when the text describes a person/patient
  ❌ «physical significance for the user»  ❌ generic medical words without diagnosis/disease/medication/treatment  ❌ company names  ❌ product names without health/patient context
  Report the exact text that should be redacted, for example the disease name, diagnosis, or medication name.
"""


def _build_prompt(categories: list[str], chunk: str, lang: str = "nb") -> str:
    """Bygg LLM-prompt dynamisk basert på valgte søkekategorier."""
    active = [CATEGORIES[c] for c in categories if c in CATEGORIES]
    if not active:
        active = [CATEGORIES[c] for c in DEFAULT_CATEGORIES]
    cat_list = "\n".join(f"- {a}" for a in active)
    include_medical = "medisinsk" in categories

    if lang == "sv":
        rules = _RULES_SV + ("\n" + _MEDICAL_RULES_SV if include_medical else "")
        return (
            f"Analysera texten nedan. Sök efter dessa kategorier:\n{cat_list}\n\n"
            f"{rules}\n"
            "Svara BARA med JSON i detta format (ingen annan text):\n"
            '{{"findings":[{{"category":"Kategori","text":"hittad text","context":"omgivande ord","confidence":"high"}}]}}\n'
            "Inga fynd → {{\"findings\":[]}}\n\nText:\n" + chunk
        )
    elif lang == "en":
        rules = _RULES_EN + ("\n" + _MEDICAL_RULES_EN if include_medical else "")
        return (
            f"Analyse the text below. Search for these categories:\n{cat_list}\n\n"
            f"{rules}\n"
            "Respond ONLY with JSON in this format (no other text):\n"
            '{{"findings":[{{"category":"Category","text":"found text","context":"surrounding words","confidence":"high"}}]}}\n'
            "No findings → {{\"findings\":[]}}\n\nText:\n" + chunk
        )
    else:  # nb
        rules = _RULES_NB + ("\n" + _MEDICAL_RULES_NB if include_medical else "")
        return (
            f"Analyser teksten nedenfor. Søk etter disse kategoriene:\n{cat_list}\n\n"
            f"{rules}\n"
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


def _norm_for_source_match(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _reported_text_exists_in_source(source: str, reported: str) -> bool:
    """LLM-funn må være en faktisk substring i teksten som ble analysert.

    Dette stopper hallucinerte verdier, f.eks. personnummer som modellen har
    sett i en tidligere test eller treningskontekst, men som ikke står i
    dokumentet. Regex-/blacklist-supplementer genereres separat fra kildeteksten.
    """
    value = _norm_for_source_match(reported)
    if not value:
        return False
    haystack = _norm_for_source_match(source)
    if value in haystack:
        return True

    # Tillat forskjeller i whitespace/separatorer for tall og korte tokens.
    compact_value = re.sub(r"[\s.\-_/()]+", "", value)
    compact_source = re.sub(r"[\s.\-_/()]+", "", haystack)
    return len(compact_value) >= 4 and compact_value in compact_source


def _filter_llm_findings_to_source(findings: list[dict], source: str) -> list[dict]:
    result: list[dict] = []
    removed = 0
    for finding in findings:
        text = str(finding.get("text") or "")
        if _reported_text_exists_in_source(source, text):
            result.append(finding)
        else:
            removed += 1
    if removed:
        LOGGER.info("AI-source-filter: fjernet %d hallucinerte funn som ikke finnes i teksten", removed)
    return result


def _category_key(category: str) -> str:
    return category.replace("🤖", "").strip().casefold()


_PERSON_NAME_CATEGORIES = {
    "personnavn",
    "navn",
    "navn (person)",
    "person name",
    "personal name",
    "personnamn",
    "namn",
    "namn (person)",
    "nom",
    "nom (personne)",
    "nombre",
    "nombre (persona)",
}


def _is_person_name_category(category: str) -> bool:
    return _category_key(category) in _PERSON_NAME_CATEGORIES


_BANK_ACCOUNT_CATEGORIES = {
    "bankkonto",
    "bankkontonummer",
    "kontonummer",
    "account number",
    "bank account",
    "iban",
}


def _is_bank_account_category(category: str) -> bool:
    return _category_key(category) in _BANK_ACCOUNT_CATEGORIES


_EMAIL_CATEGORIES = {
    "e-post",
    "epost",
    "e-postadresse",
    "e-postadresser",
    "epostadresse",
    "epostadresser",
    "email",
    "e-mail",
    "email address",
    "email addresses",
    "e-mail address",
    "e-mail addresses",
    "mail",
    "mail address",
    "mail addresses",
    "mailadresse",
    "mailadresser",
    "e-postadress",
    "e-postadresser",
    "e-mailadress",
    "e-mailadresser",
    "correo electronico",
    "correo electrónico",
    "adresse e-mail",
}


def _is_email_category(category: str) -> bool:
    return _category_key(category) in _EMAIL_CATEGORIES


_ADDRESS_CATEGORIES = {
    "adresse",
    "address",
    "fysisk adresse",
    "physical address",
    "postadresse",
    "street address",
}


def _is_address_category(category: str) -> bool:
    return _category_key(category) in _ADDRESS_CATEGORIES


_ADDRESS_NUMBER_RE = re.compile(r"\b\d{1,5}[A-Za-z]?\b")
_PO_BOX_RE = re.compile(r"\b(?:pb|p\.b\.|postboks|postbox|po box|p\.o\. box)\s*\d+\b", re.IGNORECASE)


def _looks_like_physical_address(value: str) -> bool:
    """LLM-adressefunn må ha husnummer eller postboks, ikke bare sted/bygg."""
    text = " ".join(str(value or "").strip().split())
    if not text or len(text) > 140:
        return False
    if _PO_BOX_RE.search(text):
        return True
    if not _ADDRESS_NUMBER_RE.search(text):
        return False
    return bool(re.search(r"[A-Za-zÆØÅæøåÄÖäö]", text))


_MEDICAL_CATEGORIES = {
    "medisinsk",
    "medicinsk",
    "medical",
    "diagnose",
    "diagnosis",
    "legemiddel",
    "läkemedel",
    "medication",
}


def _is_medical_category(category: str) -> bool:
    key = _category_key(category)
    return key in _MEDICAL_CATEGORIES or any(key.startswith(prefix) for prefix in _MEDICAL_CATEGORIES)


_MEDICAL_CONTEXT_RE = re.compile(
    r"\b("
    r"diagnose|diagnosis|sykdom|sjukdom|disease|lidelse|condition|"
    r"symptom|symptomer|symptoms?|behandling|treatment|treated|behandles|"
    r"medisin|medisiner|legemiddel|läkemedel|medication|medicine|"
    r"pasient|patient|helse|health|sykmeldt|sick leave|"
    r"diabetes|adhd|depresjon|depression|astma|asthma|kreft|cancer|"
    r"migrene|migraine|metformin|sertralin|sertraline|insulin"
    r")\b",
    re.IGNORECASE,
)


_GENERIC_MEDICAL_FALSE_POSITIVE_RE = re.compile(
    r"\b(fysisk|physisk|physical|psykisk|mental)\s+betydning\b",
    re.IGNORECASE,
)


def _looks_like_medical_information(value: str, context: str = "") -> bool:
    """Krev konkret medisinsk innhold, ikke generiske uttrykk om betydning."""
    text = " ".join(str(value or "").strip().split())
    ctx = " ".join(str(context or "").strip().split())
    combined = f"{text} {ctx}".strip()
    if not text or len(text) > 180:
        return False
    if _GENERIC_MEDICAL_FALSE_POSITIVE_RE.search(combined):
        return False
    return bool(_MEDICAL_CONTEXT_RE.search(combined))


def _valid_bank_account_text(value: str) -> str | None:
    """Returner presist kontonummer/IBAN bare hvis teksten faktisk validerer."""
    from xlent_scanner.detectors.iban import find_iban  # noqa: PLC0415
    from xlent_scanner.detectors.regex_no import find_kontonummer  # noqa: PLC0415

    konto_hits = list(find_kontonummer(value))
    if konto_hits:
        return konto_hits[0].text

    iban_hits = list(find_iban(value))
    if not iban_hits:
        return None
    raw = " ".join(str(value or "").strip().split())
    compact = re.sub(r"\s+", "", raw).upper()
    # LLM må ha rapportert selve IBAN-verdien, ikke en hel kontekstsetning.
    for hit in iban_hits:
        if compact == str(hit.raw_text or "").upper():
            return raw
    return None


def _valid_email_text(value: str) -> str | None:
    """Returner en faktisk e-postadresse, aldri bare en organisasjon/brukernavn."""
    match = _EMAIL_RE.search(str(value or ""))
    if not match:
        return None
    return match.group(0).strip("<>()[]{}.,;:'\"")


def _filter_llm_findings_by_category_precision(findings: list[dict]) -> list[dict]:
    result: list[dict] = []
    removed = 0
    for f in findings:
        cat = str(f.get("category") or "")
        raw_text = str(f.get("text") or "")
        if _is_email_category(cat):
            email_text = _valid_email_text(raw_text)
            if not email_text:
                removed += 1
                continue
            f = dict(f)
            f["text"] = email_text
            f["category"] = "E-post"
        elif _is_bank_account_category(cat):
            bank_text = _valid_bank_account_text(raw_text)
            if not bank_text:
                removed += 1
                continue
            f = dict(f)
            f["text"] = bank_text
            if _category_key(cat) == "iban":
                f["category"] = "IBAN"
            else:
                f["category"] = "Kontonummer"
        elif _is_address_category(cat):
            if not _looks_like_physical_address(raw_text):
                removed += 1
                continue
        elif _is_medical_category(cat):
            if not _looks_like_medical_information(raw_text, str(f.get("context") or "")):
                removed += 1
                continue
        result.append(f)
    if removed:
        LOGGER.info("AI-presisjonsfilter: fjernet %d ugyldige AI-funn", removed)
    return result


_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_US_PHONE_RE = re.compile(
    r"(?<![\w])"
    r"(?:(?:\+?1|\+01|001)[\s.\-]*)?"
    r"(?:\([2-9]\d{2}\)|[2-9]\d{2})"
    r"[\s.\-]*[2-9]\d{2}[\s.\-]*\d{4}"
    r"(?![\w])"
)
_URL_CATEGORIES = {"nettadresse", "url", "web address", "webbadress", "webadresse"}
_FINANCIAL_HEADER_RE = re.compile(
    r"\b("
    r"cost|amount|price|total|budget|revenue|fee|rate|invoice|quote|value"
    r"|kostnad|beløp|belop|pris|sum|totalt|budsjett|inntekt|avgift|faktura|tilbud"
    r"|kostnad|belopp|intäkt|intakt|offert"
    r")\b",
    re.IGNORECASE,
)
_NON_FINANCIAL_HEADER_RE = re.compile(
    r"\b(hours?|timer|timmar|quantity|qty|count|antall|antal|year|år|aar|date|dato|id|nr|no)\b",
    re.IGNORECASE,
)
_AMOUNT_CELL_RE = re.compile(
    r"^\s*(?:NOK|SEK|DKK|EUR|USD|GBP|CHF|kr|£|€|\$)?\s*"
    r"-?\d{1,9}(?:[ .,\t]\d{3})*(?:[.,]\d{1,2})?\s*"
    r"(?:NOK|SEK|DKK|EUR|USD|GBP|CHF|kr|£|€|\$)?\s*$",
    re.IGNORECASE,
)
_DATE_LIKE_RE = re.compile(
    r"^\s*(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|(?:19|20)\d{2})\s*$"
)


def _email_matches_ignore(value: str, domains: set[str], emails: set[str]) -> bool:
    candidates = {m.group(0).strip().casefold() for m in _EMAIL_RE.finditer(value)}
    raw = value.strip().strip("<>()[]{}.,;:'\"").casefold()
    if "@" in raw:
        candidates.add(raw)

    for email in candidates:
        domain = email.split("@")[-1] if "@" in email else ""
        if email in emails or any(domain == d or domain.endswith("." + d) for d in domains):
            return True
    return False


def _looks_like_us_phone(value: str) -> bool:
    return bool(_US_PHONE_RE.search(value))


def _normalize_misclassified_phone_findings(
    findings: list[dict],
    categories: list[str],
) -> list[dict]:
    include_phone = "telefon" in categories
    result: list[dict] = []
    for f in findings:
        cat = _category_key(str(f.get("category") or ""))
        if cat in _URL_CATEGORIES and _looks_like_us_phone(str(f.get("text") or "")):
            if include_phone:
                f = dict(f)
                f["category"] = "Telefonnummer"
                f["confidence"] = f.get("confidence") or "high"
                result.append(f)
            continue
        result.append(f)
    return result


def _split_table_line(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _financial_columns(cells: list[str]) -> set[int]:
    cols: set[int] = set()
    for idx, cell in enumerate(cells):
        if _FINANCIAL_HEADER_RE.search(cell) and not _NON_FINANCIAL_HEADER_RE.search(cell):
            cols.add(idx)
    return cols


def _looks_like_financial_amount_cell(cell: str) -> bool:
    value = cell.strip()
    if not value or "%" in value:
        return False
    if _DATE_LIKE_RE.match(value):
        return False
    return bool(_AMOUNT_CELL_RE.match(value))


def _find_tabular_financial_values(text: str) -> list[dict]:
    findings: list[dict] = []
    active_cols: set[int] = set()
    active_headers: list[str] = []
    seen: set[tuple[str, str]] = set()

    for line in text.splitlines():
        if "|" not in line:
            active_cols = set()
            active_headers = []
            continue
        cells = _split_table_line(line)
        if not cells or all(not c or set(c) <= {"-"} for c in cells):
            continue

        header_cols = _financial_columns(cells)
        if header_cols:
            active_cols = header_cols
            active_headers = cells
            continue

        if not active_cols or len(cells) <= max(active_cols):
            continue

        for col in sorted(active_cols):
            value = cells[col]
            if not _looks_like_financial_amount_cell(value):
                continue
            header = active_headers[col] if col < len(active_headers) else "financial column"
            key = (header.casefold(), value.casefold())
            if key in seen:
                continue
            seen.add(key)
            findings.append({
                "category": "Budsjettall",
                "text": value,
                "context": line.strip(),
                "confidence": "high",
            })
    return findings


def _filter_ignored_findings(findings: list[dict], ignore: dict) -> list[dict]:
    domains = {str(d).strip().casefold() for d in ignore.get("email_domains", []) if str(d).strip()}
    emails = {str(e).strip().casefold() for e in ignore.get("emails", []) if str(e).strip()}
    names_raw = ignore.get("names", [])
    ignore_names = {str(n).strip().casefold() for n in names_raw if str(n).strip()}
    ignore_name_parts = {
        part.casefold()
        for name in names_raw
        for part in str(name).split()
        if len(part) > 2
    }

    result: list[dict] = []
    for f in findings:
        raw_val = str(f.get("text") or "")
        val = raw_val.strip().casefold()
        cat = _category_key(str(f.get("category") or ""))

        if _email_matches_ignore(raw_val, domains, emails):
            continue

        if _is_person_name_category(str(f.get("category") or "")):
            if not looks_like_person_name(raw_val):
                continue
            if val in ignore_names or val in ignore_name_parts:
                continue

        result.append(f)
    return result


def _run_deep_scan(
    text: str, model: str, lang: str, job_id: str, categories: list[str],
    min_confidence: str = "medium",
) -> None:
    chunks = _split_chunks(text)
    n = len(chunks)
    all_raw: list[dict] = []
    with _job_lock:
        job = _jobs.get(job_id)
        if job:
            job.update({
                "total_chunks": n,
                "current_chunk": 0,
                "completed_chunks": 0,
                "progress_percent": 0,
            })

    for idx, chunk in enumerate(chunks, 1):
        with _job_lock:
            job = _jobs.get(job_id)
            if not job or job.get("cancelled"):
                return
            job.update({
                "progress": f"Analyserer del {idx} av {n}…",
                "current_chunk": idx,
                "completed_chunks": idx - 1,
                "total_chunks": n,
                "progress_percent": int(((idx - 1) / max(n, 1)) * 100),
            })

        prompt = _build_prompt(categories, chunk, lang)
        findings = _call_ollama(model, prompt)
        findings = _filter_llm_findings_to_source(findings, chunk)
        findings = _filter_llm_findings_by_category_precision(findings)
        all_raw.extend(findings)
        with _job_lock:
            job = _jobs.get(job_id)
            if job and not job.get("cancelled"):
                job.update({
                    "completed_chunks": idx,
                    "progress_percent": int((idx / max(n, 1)) * 100),
                })

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

    # Telefon: legg til presise US/NANP-telefoner for engelske/internasjonale dokumenter.
    if "telefon" in categories:
        try:
            from xlent_scanner.detectors.regex_en import find_us_phone  # noqa: PLC0415
            for f in find_us_phone(text):
                all_raw.append({
                    "category":   "Telefonnummer",
                    "text":       f.text,
                    "context":    f.context,
                    "confidence": "high",
                })
        except Exception as exc:
            LOGGER.warning("US-telefon regex-supplement feilet: %s", exc)

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

    # Finansielle tabeller/regneark: vær mer aggressiv når tall står i tydelig
    # økonomiske kolonner, men unngå løse tall uten tabell-/header-kontekst.
    if "budsjett_tall" in categories:
        try:
            all_raw.extend(_find_tabular_financial_values(text))
        except Exception as exc:
            LOGGER.warning("Finansiell tabell-supplement feilet: %s", exc)

    deduped = _deduplicate(all_raw)

    # Filtrer etter minimumskonfidens
    _CONF_ORDER = {"high": 2, "medium": 1, "low": 0}
    min_conf_val = _CONF_ORDER.get(min_confidence, 1)
    deduped = [
        f for f in deduped
        if _CONF_ORDER.get(str(f.get("confidence", "medium")).lower(), 1) >= min_conf_val
    ]
    deduped = _deduplicate(_normalize_misclassified_phone_findings(deduped, categories))

    # Fjern interne/ignorerte funn også for AI-dypscan. Regelbasert scan gjør
    # dette tidligere, men dypscan har egne LLM- og regex-funn.
    try:
        from xlent_scanner.ignore import load_ignore_list  # noqa: PLC0415
        before = len(deduped)
        deduped = _filter_ignored_findings(deduped, load_ignore_list())
        removed = before - len(deduped)
        if removed:
            LOGGER.info("AI-ignore: fjernet %d funn fra ignore.toml", removed)
    except Exception as exc:
        LOGGER.warning("AI-ignore-filter feilet: %s", exc)

    # Marker whitelist-funn som grønne (same logikk som regelbasert skann)
    try:
        from xlent_scanner.whitelist import load_whitelist  # noqa: PLC0415
        wl = load_whitelist()
        if wl:
            marked = 0
            for f in deduped:
                if f.get("text", "").lower() in wl:
                    f["severity"] = "grønn"
                    f["whitelisted"] = True
                    marked += 1
            if marked:
                LOGGER.info("AI-whitelist: markerte %d funn som grønne", marked)
    except Exception as exc:
        LOGGER.warning("AI-whitelist-filter feilet: %s", exc)

    # Blacklist er eksplisitt "fjern alltid" og skal derfor legges til etter
    # ignore/whitelist slik at den ikke kan gjøres grønn ved et uhell.
    try:
        from xlent_scanner.blacklist import detect_blacklist  # noqa: PLC0415
        for f in detect_blacklist(text):
            deduped.append({
                "category": f.category,
                "text": f.text,
                "context": f.context,
                "confidence": "high",
            })
        deduped = _deduplicate(deduped)
    except Exception as exc:
        LOGGER.warning("AI-blacklist-supplement feilet: %s", exc)

    # Legg til 🤖-prefiks på kategori
    for f in deduped:
        cat = str(f.get("category") or "AI-funn").strip()
        if not cat.startswith("🤖"):
            f["category"] = f"🤖 {cat}"

    with _job_lock:
        job = _jobs.get(job_id)
        if job:
            job.update({
                "status":   "done",
                "progress": f"Ferdig – {len(deduped)} nye funn",
                "current_chunk": n,
                "completed_chunks": n,
                "total_chunks": n,
                "progress_percent": 100,
                "completed_at": time.time(),
                "findings": deduped,
            })
    LOGGER.info("Dybdeskann ferdig: job=%s model=%s funn=%d", job_id, model, len(deduped))


# ── Offentlige API-er ───────────────────────────────────────────────────

def start_deep_scan(
    text: str, model: str, lang: str = "nb", categories: list[str] | None = None,
    min_confidence: str = "medium",
) -> str:
    """Start dybdeskanning i bakgrunn. Returnerer job_id."""
    global _job
    job_id = str(uuid.uuid4())[:8]
    cats = categories or list(DEFAULT_CATEGORIES)
    job = {
        "job_id":         job_id,
        "status":         "running",
        "progress":       "Starter…",
        "current_chunk":  0,
        "completed_chunks": 0,
        "total_chunks":   0,
        "progress_percent": 0,
        "findings":       [],
        "cancelled":      False,
        "model":          model,
        "categories":     cats,
        "min_confidence": min_confidence,
        "started_at":     time.time(),
    }
    with _job_lock:
        _cleanup_jobs_locked()
        _jobs[job_id] = job
        _job = job
    t = threading.Thread(
        target=_run_deep_scan,
        args=(text, model, lang, job_id, cats, min_confidence),
        daemon=True,
        name=f"deep-scan-{job_id}",
    )
    t.start()
    LOGGER.info("Dybdeskann startet: job=%s model=%s lang=%s cats=%s", job_id, model, lang, cats)
    return job_id


def get_deep_scan_status(job_id: str | None = None) -> dict[str, Any]:
    """Hent status/resultat for en bestemt jobb, eller siste GUI-jobb."""
    with _job_lock:
        _cleanup_jobs_locked()
        if job_id:
            status = dict(_jobs.get(job_id, {}))
        else:
            status = dict(_job)
    started = status.get("started_at")
    if started:
        end = status.get("completed_at") or time.time()
        status["elapsed_seconds"] = max(0.0, float(end) - float(started))
    return status


def cancel_deep_scan(job_id: str | None = None) -> None:
    """Avbryt en bestemt dybdeskann, eller siste GUI-jobb."""
    with _job_lock:
        job = _jobs.get(job_id) if job_id else _job
        if not job:
            return
        job["cancelled"] = True
        job["status"]    = "cancelled"
        job["progress"]  = "Avbrutt"
