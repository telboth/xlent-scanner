from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "src" / "xlent_scanner" / "web" / "index.html"
APP = ROOT / "src" / "xlent_scanner" / "app.py"


def test_root_layout_fills_webview_viewport():
    html = HTML.read_text(encoding="utf-8")

    assert "html {" in html
    assert "width: 100%;" in html
    assert "height: 100%;" in html
    assert "min-width: 100vw;" in html
    assert "min-height: 100vh;" in html
    assert "overflow: hidden;" in html
    assert "background: var(--bg);" in html
    assert "body {" in html
    assert "width: 100vw;" in html
    assert "height: 100vh;" in html
    assert "min-height: 0;" in html
    assert "main { flex: 1; min-height: 0;" in html
    assert ".tab-panel { display: none; flex-direction: column; flex: 1; min-height: 0;" in html


def test_wide_panels_fill_window_but_keep_readable_content_width():
    html = HTML.read_text(encoding="utf-8")

    assert "#panel-about { padding: 26px 30px; gap: 0; width: 100%; }" in html
    assert "#panel-settings { padding: 24px 28px; gap: 0; width: 100%; }" in html
    assert ".about-content, #panel-settings > .settings-section, #panel-settings > .settings-note" in html
    assert "max-width: 820px;" in html


def test_pywebview_background_is_not_default_white():
    app = APP.read_text(encoding="utf-8")

    assert "background_color=\"#eef2f6\"" in app


def test_theme_selector_is_available_in_settings():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="themeSelect"' in html
    assert 'value="dark" data-i18n="themeDark"' in html
    assert 'value="light" data-i18n="themeLight"' in html
    assert html.index('value="light" data-i18n="themeLight"') < html.index('value="dark" data-i18n="themeDark"')
    assert 'data-i18n="settingsThemeTitle"' in html
    assert 'data-i18n="themeNote"' in html


def test_light_theme_is_default():
    html = HTML.read_text(encoding="utf-8")

    assert 'document.documentElement.dataset.theme = s.theme === "dark" ? "dark" : "light";' in html
    assert 'return theme === "dark" ? "dark" : "light";' in html
    assert "--fg:" not in html
    assert "var(--fg)" not in html


def test_light_theme_has_non_white_header_for_white_logo():
    html = HTML.read_text(encoding="utf-8")

    assert ':root[data-theme="light"]' in html
    assert "--header-bg: #5b6673;" in html
    assert "--header-text: #ffffff;" in html
    assert "--header-muted: #d7dde5;" in html
    assert "background: var(--header-bg); color: var(--header-text);" in html
    assert ".app-version {" in html
    assert "color: var(--header-text);" in html


def test_theme_translations_exist_for_all_ui_languages():
    html = HTML.read_text(encoding="utf-8")

    for key in [
        "settingsThemeTitle",
        "themeLabel",
        "themeDark",
        "themeLight",
        "themeNote",
    ]:
        assert html.count(f"{key}:") == 6


def test_settings_profile_and_ollama_pull_controls_exist_for_all_languages():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="btn-export-settings"' in html
    assert 'id="btn-import-settings"' in html
    assert 'id="settings-import-file"' in html
    assert 'id="btn-pull-ollama-model"' in html
    assert 'id="stripAnnotations"' in html
    assert 'id="blacklist-editor"' in html
    assert 'id="btn-blacklist-save"' in html
    assert "function exportSettingsProfile" in html
    assert "function importSettingsProfile" in html
    assert "function pullRecommendedOllamaModel" in html
    assert "function loadBlacklistEditor" in html
    assert "strip_annotations: stripAnnotations" in html
    for key in [
        "settingsProfileTitle",
        "settingsProfileNote",
        "settingsRedactionTitle",
        "stripAnnotationsLabel",
        "stripAnnotationsNote",
        "settingsBlacklistTitle",
        "blacklistNote",
        "blacklistReload",
        "blacklistSave",
        "blacklistPathLabel",
        "blacklistHint",
        "blacklistSaved",
        "blacklistLoadErr",
        "blacklistSaveErr",
        "settingsExport",
        "settingsImport",
        "settingsExported",
        "settingsImported",
        "settingsExportErr",
        "settingsImportErr",
        "ollamaPullRecommended",
        "ollamaPullStarting",
        "ollamaPullFailed",
        "ollamaRecommendedMissing",
    ]:
        assert html.count(f"{key}:") == 6


def test_scan_category_translations_exist_for_all_languages():
    html = HTML.read_text(encoding="utf-8")

    for key in [
        "scanCatId",
        "scanCatKonto",
        "scanCatKredittkort",
        "scanCatNavn",
        "scanCatHemmeligheter",
        "scanCatFinansielt",
        "scanCatKonfidensielt",
        "scanCatKlient",
        "scanCatOrgnummer",
        "scanCatPassnummer",
        "scanCatFodselsdato",
        "scanCatSwift",
        "scanCatLonn",
        "dstCatMedisinsk",
    ]:
        assert html.count(f"{key}:") == 6


def test_medical_ai_category_is_available_but_default_off():
    html = HTML.read_text(encoding="utf-8")

    assert 'class="scan-cat" value="medisinsk"' in html
    assert 'class="scan-cat" value="medisinsk" checked' not in html
    assert 'data-i18n="dstCatMedisinsk"' in html
    assert '"medisinsk":   "medisinsk"' in html


def test_ai_rescan_uses_spinner_instead_of_duplicate_analyzing_text():
    html = HTML.read_text(encoding="utf-8")

    assert ".btn-spinner" in html
    assert "@keyframes spin" in html
    assert "function _setRescanBtnLoading" in html
    assert '<span class="btn-spinner" aria-label="Loading"></span>' in html
    assert "${escapeHtml(t(\"aiAnalyzing\"))}" in html
    assert "rescanBtn.textContent = t(\"aiAnalyzingBtn\")" not in html


def test_ai_deep_scan_polling_uses_job_id_and_restores_rescan_button():
    html = HTML.read_text(encoding="utf-8")

    assert 'let _aiCurrentJobId = "";' in html
    assert '_aiCurrentJobId = String(r.job_id || "");' in html
    assert 'const startedJobId = _aiCurrentJobId;' in html
    assert 'setInterval(() => _pollAiScan(startedJobId), 1500)' in html
    assert 'fetch(`${API}/ollama/deep-scan/status/${encodeURIComponent(jobId)}`)' in html
    assert 'fetch(cancelUrl, { method:"POST" })' in html
    assert "function _stopAiPolling()" in html
    assert "_restoreRescanBtn(`✅ ${n} ${t(\"metaFindings\")}`);" in html


def test_about_hardware_requirement_is_16gb_in_all_languages():
    html = HTML.read_text(encoding="utf-8")

    assert "8 GB RAM" not in html
    assert "8 Go de RAM" not in html
    assert "minst 16 GB RAM" in html
    assert "at least 16 GB RAM" in html
    assert "mindestens 16 GB RAM" in html
    assert "au moins 16 Go de RAM" in html
    assert "al menos 16 GB de RAM" in html
