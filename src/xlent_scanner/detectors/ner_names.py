"""NER-detektor for personnavn via spaCy.

Støttede språk og modeller:
  nb – nb_core_news_sm  (norsk bokmål)
  sv – sv_core_news_sm  (svensk)
  en – en_core_web_sm   (engelsk)

Modeller lastes lazy og caches per språk.

Filtrering for å redusere falske positiver:
  - Krav om minst 2 ord
  - Hvert ord må starte med stor bokstav, ikke være hel-caps (akronymer)
  - Minimumlengde per del: 2 tegn
  - Felles stoppord-liste for engelske tekniske termer
  - Forkast organisasjoner, offentlige etater, teamnavn og generiske roller
"""
from __future__ import annotations

import re
import sys
from typing import Any, Iterator

from xlent_scanner.language import SPACY_CONFIG

# Er vi inne i en PyInstaller-bundle? Pip-basert nedlasting vil alltid feile der.
_IS_FROZEN = getattr(sys, "frozen", False)
from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx

# Modell-cache og feil-cache per språk
_nlp_cache: dict[str, Any] = {}
_load_errors: dict[str, str] = {}

_MAX_CHARS = 100_000


# ── Stoppord ──────────────────────────────────────────────────────────────────

_STOPWORDS: frozenset[str] = frozenset({
    # Generelle tekniske termer
    "xlent", "database", "audit", "check", "automatically", "blacklist", "green",
    "scoring", "threshold", "hybrid", "rag", "box", "entry", "custom",
    "consulting", "tune", "phase", "kick", "state", "country", "rigid",
    "officer", "model", "system", "service", "client", "server", "pipeline",
    "process", "type", "class", "method", "function", "module", "package",
    "import", "export", "table", "index", "query", "schema", "config",
    "token", "api", "data", "user", "admin", "root", "host", "port",
    "node", "edge", "graph", "list", "array", "object", "value", "key",
    "test", "debug", "log", "error", "warning", "info", "status", "true",
    "false", "null", "none", "done", "open", "close", "start", "stop",
    "source", "target", "input", "output", "result", "response", "request",
    "cluster", "agent", "chain", "step", "task", "job", "queue", "event",
    "trigger", "action", "rule", "policy", "role", "group", "team",
    "junior", "senior", "lead", "manager", "director", "analyst",
    # Sky- og produktnavn
    "azure", "aws", "gcp", "google", "microsoft", "amazon",
    "stripe", "visma", "hubspot", "dynamics", "salesforce", "servicenow",
    "blob", "storage", "billing", "insight", "insights", "monitor",
    "app", "apps", "function", "functions", "gateway", "firewall",
    "container", "kubernetes", "docker", "helm", "terraform", "ansible",
    "compute", "cloud", "platform", "solution", "solutions", "product",
    "business", "enterprise", "professional", "standard", "premium",
    "devops", "devex", "github", "gitlab", "bitbucket", "jenkins",
    "redis", "kafka", "elastic", "opensearch", "postgres", "mysql",
    "payment", "invoice", "subscription", "account", "dashboard",
    "report", "summary", "overview", "analytics", "metrics", "kpi",
    "integration", "connector", "adapter", "broker", "registry",
    # Svenske ord som kan forveksles med navn
    "aktiebolag", "handelsbolag", "ekonomi", "styrelse", "direktion",
    "avdelning", "verksamhet", "tjänst", "produkt",
    # Norske/svenske rolleord som modeller ofte forveksler med personer
    "bruker", "brukeren", "brukere", "brukerne",
    "veileder", "veilederen", "veiledere", "veilederne",
    "saksbehandler", "saksbehandleren", "saksbehandlere", "saksbehandlerne",
    "kunde", "kunden", "kunder", "klient", "klienten", "klienter",
    "leverandør", "leverandøren", "leverandører",
})

_ORG_KEYWORDS: frozenset[str] = frozenset({
    "as", "asa", "ab", "oy", "ltd", "limited", "gmbh", "inc", "llc",
    "kommune", "kommunen", "kommunes", "kommunal", "fylkeskommune",
    "direktorat", "direktoratet", "departement", "departementet",
    "etat", "etaten", "tilsyn", "tilsynet", "nav", "ks",
    "team", "teamet", "fasit-team", "digital", "digirogland",
    "arbeids-", "velferdsdirektoratet",
})

_ORG_NAMES: frozenset[str] = frozenset({
    "visma", "tieto", "tietoevry", "microsoft", "google", "amazon",
    "dnb", "equinor", "yara", "xlent",
    "arbeids- og velferdsdirektoratet",
    "trondheim digital", "digirogland", "oslo kommune",
})

_LIST_SEPARATORS_RE = re.compile(r"[,;:/|]|\s+(?:og|och|and|samt|eller|or)\s+", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-zæøåäöüéèáàóòíìñß]+", re.IGNORECASE)


# ── Hjelpefunksjoner ──────────────────────────────────────────────────────────


def looks_like_person_name(name: str) -> bool:
    """Returner True bare for konkrete personnavn.

    Brukes både av spaCy-detektoren og AI-dypscann som siste sikkerhetsnett.
    """
    name = " ".join(str(name or "").strip().split())
    if not name:
        return False
    folded = name.casefold()
    if folded in _ORG_NAMES:
        return False
    if _LIST_SEPARATORS_RE.search(name):
        return False
    words = set(_WORD_RE.findall(folded))
    if any(keyword in words for keyword in _ORG_KEYWORDS if "-" not in keyword):
        return False
    if any(keyword in folded for keyword in _ORG_KEYWORDS if "-" in keyword):
        return False

    parts = name.split()
    if len(parts) < 2 or len(parts) > 4:
        return False
    for part in parts:
        part = part.strip(".,;:()[]{}«»\"'")
        if len(part) < 2:
            return False
        # Personnavn inneholder aldri sifre – filtrer bort "G3 Legemiddelbruk" o.l.
        if any(c.isdigit() for c in part):
            return False
        # Forkast deler med apostrof/backtick (possessiver som "XLENT’s", koderef)
        if any(c in part for c in ("’", "’", "’", "`")):
            return False
        if part.lower() in _STOPWORDS:
            return False
        if "-" in part:
            # Bindestreksnavn: sjekk hvert delord (f.eks. "Anne-Marie")
            subparts = [sp for sp in part.split("-") if sp]
            for sp in subparts:
                if not sp[0].isupper():
                    return False   # "RAG-based" → "based" starter med liten → forkast
                if sp.isupper() and len(sp) > 2:
                    return False   # "RAG-Based" → "RAG" er akronym → forkast
                if sp.lower() in _STOPWORDS:
                    return False
        else:
            if not part[0].isupper():
                return False
            if part.isupper() and len(part) > 2:
                return False
    return True


def _looks_like_name(name: str) -> bool:
    return looks_like_person_name(name)


# ── Modellhåndtering ──────────────────────────────────────────────────────────

def reset_cache_for_model(model_name: str) -> None:
    """Tøm NER-cache for en gitt modell (kalles etter nedlasting).

    Neste kall til _get_nlp() vil da laste modellen på nytt fra disk.
    """
    lang_for_model = {cfg["model"]: lang for lang, cfg in SPACY_CONFIG.items()}
    lang = lang_for_model.get(model_name)
    if lang:
        _nlp_cache.pop(lang, None)
        _load_errors.pop(lang, None)


def _get_nlp(lang: str = "nb") -> Any | None:
    if lang in _nlp_cache:
        return _nlp_cache[lang]

    cfg = SPACY_CONFIG.get(lang, SPACY_CONFIG["nb"])
    model_name = cfg["model"]

    # Sjekk om modellen er lastet ned til bruker-data-mappen.
    # Gjøres før feil-cache-sjekk: hvis modellen ble lastet ned etter forrige forsøk,
    # skal vi prøve igjen.
    try:
        from xlent_scanner.model_manager import model_path as _user_model_path  # noqa: PLC0415
        user_path = _user_model_path(model_name)
    except Exception:
        user_path = None

    # Hvis vi har en cachet feil, men modellen nå finnes via bruker-path → prøv igjen
    if lang in _load_errors:
        if user_path is not None:
            del _load_errors[lang]  # Modell er nå tilgjengelig — prøv på nytt
        else:
            return None  # Fortsatt ikke tilgjengelig

    try:
        import spacy  # type: ignore

        if user_path is not None:
            # Last fra bruker-data-mappen (nedlastet via UI)
            nlp = spacy.load(str(user_path))
        else:
            # Last fra installert pakke (vanlig dev-miljø)
            nlp = spacy.load(model_name)

        _nlp_cache[lang] = nlp
        return nlp

    except OSError:
        # Modellen mangler.
        # I en installert .exe (frozen) er pip utilgjengelig — brukeren må laste ned via UI.
        if _IS_FROZEN:
            _load_errors[lang] = (
                f"spaCy-modell ({model_name}) er ikke installert. "
                f"Gå til Innstillinger → Navnemodeller for å laste ned."
            )
            return None
        # I utviklingsmiljø: prøv automatisk nedlasting via pip.
        try:
            from spacy.cli import download as spacy_download  # type: ignore
            print(f"[ner] Laster ned manglende modell: {model_name}…", flush=True)
            spacy_download(model_name)
            nlp = spacy.load(model_name)
            _nlp_cache[lang] = nlp
            print(f"[ner] ✓ {model_name} lastet.", flush=True)
            return nlp
        except BaseException as exc:   # fanger også SystemExit fra pip-subprosess
            _load_errors[lang] = (
                f"Klarte ikke å laste ned spaCy-modell ({model_name}): {exc}"
            )
            return None
    except BaseException as exc:       # fanger SystemExit og andre BaseException
        _load_errors[lang] = f"Klarte ikke å laste spaCy-modell ({model_name}): {exc}"
        return None


def get_load_error(lang: str = "nb") -> str | None:
    _get_nlp(lang)
    return _load_errors.get(lang)


# ── Deteksjon ─────────────────────────────────────────────────────────────────

def find_names(text: str, lang: str = "nb") -> Iterator[Finding]:
    nlp = _get_nlp(lang)
    if nlp is None:
        return

    cfg = SPACY_CONFIG.get(lang, SPACY_CONFIG["nb"])
    ner_label = cfg["ner_label"]   # "PER" for nb/sv, "PERSON" for en

    doc = nlp(text[:_MAX_CHARS])
    seen: set[str] = set()
    for ent in doc.ents:
        if ent.label_ != ner_label:
            continue
        name = ent.text.strip()
        if "#" in name or name.startswith("-"):
            continue
        if not _looks_like_name(name):
            continue
        if name not in seen:
            seen.add(name)
            yield Finding(
                "navn (person)",
                name,
                _ctx(text, ent.start_char, ent.end_char),
            )


def detect_names(text: str, lang: str = "nb") -> list[Finding]:
    return list(find_names(text, lang))
