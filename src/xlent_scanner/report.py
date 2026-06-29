"""Genererer HTML-rapport fra ScanResult.

Rapporten slår sammen regelbaserte funn og AI-dybdeskann-funn
til én enkelt, sortert funnliste med full whitelist-støtte.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, select_autoescape

from xlent_scanner.models import ScanResult
from xlent_scanner.risk import assessment_for_level

_LEVEL_ORDER = {"grønn": 0, "gul": 1, "rød": 2, "svart": 3}

_JINJA_ENV = Environment(
    autoescape=select_autoescape(
        enabled_extensions=("html", "htm", "xml"),
        default_for_string=True,
    )
)

_TEMPLATE = _JINJA_ENV.from_string("""<!DOCTYPE html>
<html lang="nb">
<head>
<meta charset="UTF-8">
<title>XLENT Compliance-scanner – {{ result.file_name }}</title>
<style>
  :root {
    --bg: #0f1620; --panel: #1a2331; --panel2: #232f42;
    --text: #e8edf3; --muted: #8a96a8; --border: #2a3648;
    --grønn: #4caf50; --gul: #ffb84d; --rød: #f44336; --svart: #9c27b0;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: var(--bg); color: var(--text); padding: 32px; }
  .top-bar { display: flex; align-items: center; gap: 16px;
             margin-bottom: 28px; padding-bottom: 20px;
             border-bottom: 1px solid var(--border); }
  .top-bar img { height: 36px; width: auto; }
  .top-bar .app-title { font-size: 15px; font-weight: 600; color: var(--muted); }
  .header { display: flex; align-items: flex-start; gap: 24px;
            border-bottom: 1px solid var(--border); padding-bottom: 24px; margin-bottom: 24px; }
  .traffic-light { width: 72px; height: 72px; border-radius: 50%; flex-shrink: 0;
                   background: var(--{{ assessment.risk_level }}); display: flex;
                   align-items: center; justify-content: center; font-size: 28px; }
  .header-text h1 { font-size: 22px; margin-bottom: 4px; }
  .header-text .meta { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
  .verdict { font-size: 16px; font-weight: 600;
             color: var(--{{ assessment.risk_level }}); margin-bottom: 6px; }
  .action { font-size: 13px; color: var(--text); max-width: 680px; line-height: 1.5; }
  .stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  .stat { background: var(--panel); border: 1px solid var(--border);
          border-radius: 8px; padding: 12px 18px; text-align: center; }
  .stat .n { font-size: 28px; font-weight: 700; }
  .stat .lbl { color: var(--muted); font-size: 12px; margin-top: 2px; }
  .stat.svart .n { color: var(--svart); }
  .stat.rød   .n { color: var(--rød); }
  .stat.gul   .n { color: var(--gul); }
  .stat.grønn .n { color: var(--grønn); }
  h2 { font-size: 15px; color: var(--muted); text-transform: uppercase;
       letter-spacing: .06em; margin: 24px 0 10px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 500;
       padding: 6px 10px; border-bottom: 1px solid var(--border); }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  tr.whitelisted td { opacity: 0.55; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 3px;
           font-size: 11px; font-weight: 600; text-transform: uppercase; color: #111; }
  .badge-svart { background: var(--svart); color: #fff; }
  .badge-rød   { background: var(--rød);   color: #fff; }
  .badge-gul   { background: var(--gul); }
  .badge-grønn { background: var(--grønn); }
  .ai-badge { font-size: 10px; color: var(--muted); margin-left: 4px; }
  .ctx { color: var(--muted); font-style: italic; font-size: 12px; margin-top: 3px; }
  .anon-section { background: var(--panel); border: 1px solid var(--border);
                  border-radius: 8px; padding: 12px 16px; margin-bottom: 14px; }
  .anon-title { font-size: 12px; color: var(--muted); text-transform: uppercase;
                letter-spacing: .06em; margin-bottom: 10px; }
  .anon-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .btn { padding: 5px 13px; border-radius: 5px; border: 1px solid var(--border);
         background: var(--panel2); color: var(--text); cursor: pointer; font-size: 13px; }
  .btn:hover { background: #2e3f58; }
  .btn-primary { background: #1a4a8a; border-color: #2060b0; font-weight: 600; }
  .btn-primary:hover { background: #1f5aa8; }
  .btn-accent  { background: #2d5a1b; border-color: #3a7a22; font-weight: 600; }
  .btn-accent:hover  { background: #366820; }
  .anon-msg { font-size: 13px; margin-left: 4px; flex: 1; }
  .sep { width: 1px; height: 22px; background: var(--border); margin: 0 4px; }
  input[type=checkbox] { width: 15px; height: 15px; cursor: pointer; accent-color: #4caf50; }
  .wl-btn { padding: 3px 9px; border-radius: 4px; border: 1px solid var(--border);
            background: transparent; color: var(--muted); cursor: pointer;
            font-size: 11px; white-space: nowrap; }
  .wl-btn:hover { border-color: var(--grønn); color: var(--grønn); }
  .wl-btn:disabled { opacity: .5; cursor: default; }
  .wl-tag { font-size: 11px; color: var(--grønn); padding: 0 4px; }
  .preview { background: var(--panel); border: 1px solid var(--border); border-radius: 4px;
             padding: 14px; font-family: ui-monospace, monospace; font-size: 12px;
             max-height: 500px; overflow-y: auto; white-space: pre-wrap; color: var(--muted); }
  .warning-banner { background: rgba(255,184,77,.1); border: 1px solid rgba(255,184,77,.4);
                    border-left: 4px solid #ffb84d; border-radius: 6px;
                    padding: 10px 14px; font-size: 13px; color: #ffb84d;
                    line-height: 1.5; margin-bottom: 16px; }
  .policy-warning { background: rgba(244,67,54,.12); border: 1px solid rgba(244,67,54,.45);
                    border-left: 4px solid #f44336; border-radius: 6px;
                    padding: 10px 14px; font-size: 13px; color: #ff8a80;
                    line-height: 1.5; margin-bottom: 16px; }
  .m365-tags { background: var(--panel); border: 1px solid var(--border);
               border-radius: 6px; padding: 9px 12px; margin-bottom: 16px;
               font-size: 12px; color: var(--muted); line-height: 1.5; }
  .audit { background: var(--panel); border: 1px solid var(--border);
           border-radius: 6px; padding: 10px 12px; margin-bottom: 16px;
           font-size: 12px; color: var(--muted); line-height: 1.6; }
  footer { margin-top: 32px; color: var(--muted); font-size: 12px;
           border-top: 1px solid var(--border); padding-top: 16px; }
</style>
</head>
<body>

<div class="top-bar">
  {% if api_base %}<img src="{{ api_base }}/logo.svg" alt="XLENT">{% endif %}
  <span class="app-title">Compliance-scanner</span>
</div>

<div class="header">
  <div class="traffic-light">{{ ICONS[assessment.risk_level] }}</div>
  <div class="header-text">
    <h1>{{ result.file_name }}</h1>
    <div class="meta">Skannet {{ timestamp }} &middot; {{ "%.1f"|format(result.file_size/1024) }} KB &middot; {{ result.text_length }} tegn lest{% if result.language %} &middot; {{ LANG_LABELS.get(result.language, result.language) }}{% endif %}{% if has_ai_findings %} &middot; inkl. AI-dybdeskann{% endif %}</div>
    <div class="verdict">{{ LABELS[assessment.risk_level] }} &mdash; {{ assessment.risk_summary }}</div>
    <div class="action">{{ assessment.recommended_action }}</div>
  </div>
</div>

{% if result.warning %}
<div class="warning-banner">⚠️ {{ result.warning }}</div>
{% endif %}

{% if result.policy_warning %}
<div class="policy-warning">⛔ {{ result.policy_warning }}</div>
{% endif %}

{% if result.microsoft_tags %}
<div class="m365-tags">
  <strong>Microsoft 365:</strong>
  {% set labels = result.microsoft_tags.get("sensitivity", {}).get("labels", []) %}
  Sensitivity:
  {% if labels %}
    {% for label in labels -%}
      {{ label.get("name") or label.get("displayName") or label.get("labelName") or label.get("sensitivityLabelName") or label.get("id") }}{% if not loop.last %}, {% endif %}
    {%- endfor %}
  {% else %}ikke funnet{% endif %}
  {% set retention = result.microsoft_tags.get("retention", {}) %}
  {% if retention.get("name") or retention.get("displayName") %} · Retention: {{ retention.get("name") or retention.get("displayName") }}{% endif %}
</div>
{% endif %}

<div class="audit">
  <strong>Revisjonsspor:</strong>
  Regelbasert scanner{% if has_ai_findings %} + AI-dybdeskann{% endif %}.
  {% if audit_metadata.get("model") %} Modell: {{ audit_metadata.get("model") }}.{% endif %}
  {% if audit_metadata.get("categories") %} Kategorier: {{ audit_metadata.get("categories")|join(", ") }}.{% endif %}
  {% if audit_metadata.get("min_confidence") %} Minimum konfidens: {{ audit_metadata.get("min_confidence") }}.{% endif %}
  Samlet risiko er beregnet fra {{ merged_findings|length }} flettede funn.
  {% if redaction_audit %}
  <br><strong>Siste anonymisering:</strong>
  {{ redaction_audit.get("output_file") }} via {{ redaction_audit.get("method") }}.
  {{ redaction_audit.get("selected_count", 0) }} funn valgt.
  {% set verification = redaction_audit.get("verification", {}) %}
  Kontrollskann:
  {% if verification.get("passed") %}bestått{% else %}krever kontroll{% endif %}
  ({{ verification.get("removed_count", 0) }} fjernet,
  {{ verification.get("finding_count", 0) }} gjenværende).
  {% endif %}
</div>

{% if redaction_audit and redaction_audit.get("selected_findings") %}
<h2>Faktisk anonymiserte funn ({{ redaction_audit.get("selected_findings")|length }})</h2>
<table>
  <thead><tr><th>Kategori</th><th>Kilde</th><th>Konfidens</th><th>Verdi</th></tr></thead>
  <tbody>
  {% for item in redaction_audit.get("selected_findings") %}
    <tr>
      <td>{{ item.get("category") }}</td>
      <td>{{ item.get("engine") }}</td>
      <td>{{ item.get("confidence") or "—" }}</td>
      <td><strong>{{ item.get("text") }}</strong></td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

{# Stats over alle funn (regular + AI, ekskl. grønne) #}
<div class="stats">
  {% for level in ["svart","rød","gul"] %}
  {% set count = merged_findings|selectattr("severity","equalto",level)|list|length %}
  <div class="stat {{ level }}">
    <div class="n">{{ count }}</div>
    <div class="lbl">{{ level|capitalize }}</div>
  </div>
  {% endfor %}
  {% set wl_count = merged_findings|selectattr("whitelisted")|list|length %}
  {% if wl_count %}
  <div class="stat grønn">
    <div class="n">{{ wl_count }}</div>
    <div class="lbl">Hvitelistet</div>
  </div>
  {% endif %}
  <div class="stat">
    <div class="n">{{ merged_findings|length }}</div>
    <div class="lbl">Totalt</div>
  </div>
</div>

{% if merged_findings %}
<h2>Funn ({{ merged_findings|length }})</h2>

{% if api_base %}
<div class="anon-section">
  <div class="anon-title">Anonymiser regelbaserte funn</div>
  <div class="anon-bar">
    <button class="btn" id="sel-all">Velg alle</button>
    <button class="btn" id="sel-none">Fjern alle</button>
    <div class="sep"></div>
    {% if patch_supported %}
    <button class="btn btn-accent" id="patch-btn">Lagre anonymisert .{{ file_suffix }}</button>
    {% endif %}
    <button class="btn btn-primary" id="anon-btn">Generer .md-fil</button>
    <span class="anon-msg" id="anon-msg"></span>
  </div>
</div>
{% endif %}

<table>
  <thead>
    <tr>
      {% if api_base %}<th style="width:32px" title="Anonymiser valgt funn"></th>{% endif %}
      <th>Alvor</th><th>Kategori</th><th>Kilde</th><th>Konfidens</th><th>Verdi</th><th>Kontekst</th>
      {% if api_base %}<th style="width:110px"></th>{% endif %}
    </tr>
  </thead>
  <tbody>
  {% for f in merged_findings %}
  <tr class="finding-row{% if f.whitelisted %} whitelisted{% endif %}">
    {% if api_base %}
    <td>
      {# Kun regelbaserte funn kan anonymiseres via indeks #}
      {% if f.finding_index is not none and not f.category.startswith('⚠') and not f.whitelisted %}
      <input type="checkbox" class="cb" value="{{ f.finding_index }}" checked>
      {% endif %}
    </td>
    {% endif %}
    <td><span class="badge badge-{{ f.severity }}">{{ f.severity }}</span></td>
    <td>
      {{ f.category }}
      {% if f.is_ai %}<span class="ai-badge">🔬</span>{% endif %}
    </td>
    <td>{{ f.engine }}</td>
    <td>{{ f.confidence or "—" }}</td>
    <td><strong>{{ f.text }}</strong></td>
    <td><span class="ctx">{{ f.context }}</span></td>
    {% if api_base %}
    <td>
      {% if f.whitelisted %}
      <span class="wl-tag">✓ Hvitelistet</span>
      {% elif f.whitelist_allowed and not f.category.startswith('⚠') %}
      <button class="wl-btn" data-text="{{ f.text|e }}"
              data-category="{{ f.category|e }}"
              title="Ikke varsle om denne verdien i fremtidige skanninger">
        + Hviteliste
      </button>
      {% endif %}
    </td>
    {% endif %}
  </tr>
  {% endfor %}
  </tbody>
</table>

{% else %}
<p style="color:var(--grønn);margin-top:16px;">&#10003; Ingen sensitive funn oppdaget.</p>
{% endif %}

{% if result.text_preview %}
<h2>Ekstrahert tekst</h2>
<div class="preview">{{ result.text_preview }}</div>
{% endif %}

<footer>
  Generert av XLENT Compliance-scanner &middot; {{ timestamp }}
</footer>

{% if api_base %}
<script>
const API = {{ api_base | tojson }};

document.getElementById('sel-all').onclick = () =>
  document.querySelectorAll('.cb').forEach(cb => cb.checked = true);
document.getElementById('sel-none').onclick = () =>
  document.querySelectorAll('.cb').forEach(cb => cb.checked = false);

function setMsg(text, color) {
  const el = document.getElementById('anon-msg');
  el.textContent = text;
  el.style.color = color || 'var(--muted)';
}

async function postAction(endpoint) {
  const indices = [...document.querySelectorAll('.cb:checked')].map(cb => +cb.value);
  if (!indices.length) { setMsg('Velg minst ett funn.', '#ffb84d'); return; }
  setMsg('Behandler…', 'var(--muted)');
  try {
    const r = await fetch(`${API}/${endpoint}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({indices})
    });
    const d = await r.json();
    if (d.ok) setMsg(`✓ Lagret: ${d.path}`, '#4caf50');
    else      setMsg(`Feil: ${d.error}`, '#f44336');
  } catch(e) { setMsg(`Nettverksfeil: ${e}`, '#f44336'); }
}

document.getElementById('anon-btn').onclick = () => postAction('anonymize');
{% if patch_supported %}
document.getElementById('patch-btn').onclick = () => postAction('patch');
{% endif %}

// Whitelist-knapper (fungerer for alle funn – regel + AI)
document.querySelectorAll('.wl-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const text = btn.dataset.text;
    const category = btn.dataset.category || '';
    try {
      await fetch(`${API}/add-to-whitelist`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text, category})
      });
      const row = btn.closest('.finding-row');
      row.style.opacity = '0.4';
      row.style.textDecoration = 'line-through';
      btn.disabled = true;
      btn.textContent = '✓ Lagt til';
    } catch(e) { btn.textContent = 'Feil!'; }
  });
});
</script>
{% endif %}

</body>
</html>
""")

_ICONS = {"grønn": "✅", "gul": "⚠️", "rød": "🚫", "svart": "⛔"}
_LABELS = {"grønn": "GRØNN", "gul": "GUL", "rød": "RØD", "svart": "SVART"}
_LANG_LABELS = {
    "nb": "🇳🇴 Norsk", "sv": "🇸🇪 Svenska", "en": "🇬🇧 English",
    "da": "🇩🇰 Dansk", "de": "🇩🇪 Deutsch", "fr": "🇫🇷 Français", "es": "🇪🇸 Español",
}
_PATCH_SUFFIXES = {"pdf", "docx", "pptx", "xlsx"}


def ai_severity(category: str) -> str:
    """Alvorlighetsgrad for et AI-funn — samme klassifisering som regelbasert."""
    from xlent_scanner.risk import _category_severity  # noqa: PLC0415
    cat = category.lstrip("🤖").strip()
    return _category_severity(cat)


def _build_merged_findings(
    result: ScanResult,
    ai_findings: list[dict] | None,
    audit_metadata: dict | None = None,
) -> tuple[list[SimpleNamespace], bool]:
    """Bygger én flettet og deduplisert funnliste (regelbasert + AI).

    Returns:
        (merged_findings, has_ai_findings)

    Regelbaserte funn har finding_index satt (brukes for /anonymize).
    AI-funn har finding_index=None og is_ai=True.
    Whitelist-matchede funn har whitelisted=True og severity='grønn'.
    Duplikate AI-funn (tekst finnes allerede i regelbaserte) hoppes over.
    """
    from xlent_scanner.whitelist import category_allows_whitelist, load_whitelist  # noqa: PLC0415

    wl = load_whitelist()
    audit_metadata = audit_metadata or {}
    model = str(audit_metadata.get("model") or "").strip()
    existing_texts: set[str] = set()
    merged: list[SimpleNamespace] = []

    # ── Regelbaserte funn ─────────────────────────────────────────────────
    for idx, f in enumerate(result.findings):
        whitelist_allowed = category_allows_whitelist(f.category)
        existing_texts.add(f.text.lower())
        merged.append(SimpleNamespace(
            category=f.category,
            text=f.text,
            context=f.context,
            severity=f.severity,
            finding_index=idx,
            is_ai=False,
            whitelisted=(f.severity == "grønn" and whitelist_allowed),
            whitelist_allowed=whitelist_allowed,
            engine="Regelbasert",
            confidence="deterministisk",
        ))

    # ── AI-funn: whitelist, dedup, merge ─────────────────────────────────
    has_ai = bool(ai_findings)
    for f in (ai_findings or []):
        text = str(f.get("text") or "")
        if not text:
            continue
        # Dedup: hopp over hvis tekst allerede finnes i regelbaserte funn
        if text.lower() in existing_texts:
            continue
        existing_texts.add(text.lower())

        cat = str(f.get("category") or "AI-funn")
        whitelist_allowed = category_allows_whitelist(cat)
        # Sjekk om allerede merket grønn av deep_scanner (whitelisted der)
        raw_sev = str(f.get("severity") or "")
        if whitelist_allowed and (raw_sev == "grønn" or text.lower() in wl):
            sev = "grønn"
            is_wl = True
        else:
            sev = ai_severity(cat)
            is_wl = False

        merged.append(SimpleNamespace(
            category=cat,
            text=text,
            context=str(f.get("context") or ""),
            severity=sev,
            finding_index=None,
            is_ai=True,
            whitelisted=is_wl,
            whitelist_allowed=whitelist_allowed,
            engine=f"AI ({model})" if model else "AI",
            confidence=str(f.get("confidence") or ""),
        ))

    # Sorter: svart→rød→gul→grønn
    merged.sort(key=lambda f: _LEVEL_ORDER.get(f.severity, 1), reverse=True)
    return merged, has_ai


def combined_assessment(
    result: ScanResult,
    ai_findings: list[dict] | None = None,
    audit_metadata: dict | None = None,
) -> SimpleNamespace:
    merged, _ = _build_merged_findings(result, ai_findings, audit_metadata)
    overall = result.risk_level if result.risk_level in _LEVEL_ORDER else "grønn"
    policy_level = str(result.policy_warning_level or "")
    if policy_level in _LEVEL_ORDER and _LEVEL_ORDER[policy_level] > _LEVEL_ORDER[overall]:
        overall = policy_level
    for finding in merged:
        if finding.severity == "grønn":
            continue
        if _LEVEL_ORDER.get(finding.severity, 1) > _LEVEL_ORDER[overall]:
            overall = finding.severity
    summary, action = assessment_for_level(overall)
    return SimpleNamespace(
        risk_level=overall,
        risk_summary=summary,
        recommended_action=action,
        finding_count=len(merged),
    )


def generate_html(
    result: ScanResult,
    api_base: str = "",
    ai_findings: list[dict] | None = None,
    audit_metadata: dict | None = None,
    redaction_audit: dict | None = None,
) -> str:
    audit_metadata = audit_metadata or {}
    merged_findings, has_ai_findings = _build_merged_findings(
        result,
        ai_findings,
        audit_metadata,
    )
    assessment = combined_assessment(result, ai_findings, audit_metadata)
    file_suffix = Path(result.file_name).suffix.lstrip(".").lower()
    return _TEMPLATE.render(
        result=result,
        assessment=assessment,
        merged_findings=merged_findings,
        has_ai_findings=has_ai_findings,
        audit_metadata=audit_metadata,
        redaction_audit=redaction_audit,
        timestamp=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ICONS=_ICONS,
        LABELS=_LABELS,
        LANG_LABELS=_LANG_LABELS,
        api_base=api_base,
        file_suffix=file_suffix,
        patch_supported=(file_suffix in _PATCH_SUFFIXES),
    )


def save_report(result: ScanResult) -> Path:
    """Lagrer statisk HTML-rapport til midlertidig fil."""
    html = generate_html(result)
    suffix = Path(result.file_name).stem
    fd, path = tempfile.mkstemp(prefix=f"xlent-scan-{suffix}-", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    return Path(path)
