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
"""
from __future__ import annotations

import sys
from typing import Any, Iterator

from xlent_scanner.language import SPACY_CONFIG

# Er vi inne i en PyInstaller-bundle? Pip-basert nedlasting vil alltid feile der.
_IS_FROZEN = getattr(sys, "frozen", False)
from xlent_scanner.models import Finding

# Modell-cache og feil-cache per språk
_nlp_cache: dict[str, Any] = {}
_load_errors: dict[str, str] = {}

_MAX_CHARS = 100_000


# ── Stoppord ──────────────────────────────────────────────────────────────────

_STOPWORDS: frozenset[str] = frozenset({
    # Generelle tekniske termer
    "database", "audit", "check", "automatically", "blacklist", "green",
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
})


# ── Hjelpefunksjoner ──────────────────────────────────────────────────────────

def _ctx(text: str, start: int, end: int, radius: int = 40) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = text[lo:hi].replace("\n", " ")
    return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(text) else "")


def _looks_like_name(name: str) -> bool:
    parts = name.split()
    if len(parts) < 2:
        return False
    for part in parts:
        if not part[0].isupper():
            return False
        if part.isupper() and len(part) > 2:
            return False
        if len(part) < 2:
            return False
        if part.lower() in _STOPWORDS:
            return False
    return True


# ── Modellhåndtering ──────────────────────────────────────────────────────────

def _get_nlp(lang: str = "nb") -> Any | None:
    if lang in _nlp_cache:
        return _nlp_cache[lang]
    if lang in _load_errors:
        return None
    cfg = SPACY_CONFIG.get(lang, SPACY_CONFIG["nb"])
    model_name = cfg["model"]
    try:
        import spacy  # type: ignore
        nlp = spacy.load(model_name)
        _nlp_cache[lang] = nlp
        return nlp
    except OSError:
        # Modellen mangler.
        # I en installert .exe (frozen) er pip utilgjengelig — skip nedlasting.
        if _IS_FROZEN:
            _load_errors[lang] = (
                f"spaCy-modell ({model_name}) er ikke installert. "
                f"Navnegjenkjenning (NER) er ikke tilgjengelig i denne versjonen."
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
