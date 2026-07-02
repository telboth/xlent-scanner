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
    assert "app-updated" not in html
    assert "__APP_STARTED__" not in html
    assert "Oppdatert __APP_STARTED__" not in html


def test_header_uses_redaction_scanner_title():
    html = HTML.read_text(encoding="utf-8")

    assert "<h1>Compliance redaction scanner</h1>" in html
    assert "<h1>Compliance-scanner</h1>" not in html
    assert "Sjekker og anonymiserer dokumenter for sensitiv informasjon" in html
    assert "Sjekker dokumenter for sensitiv informasjon før opplasting" not in html


def test_scan_category_grid_order_matches_requested_columns():
    html = HTML.read_text(encoding="utf-8")
    start = html.index('<div class="scan-cat-grid">')
    end = html.index("</div>", start)
    block = html[start:end]

    assert "grid-auto-flow: column;" in html
    assert "grid-template-rows: repeat(4, auto);" in html
    assert "manual-redaction" not in block
    values = []
    for fragment in block.split('class="scan-cat" value="')[1:]:
        values.append(fragment.split('"', 1)[0])
    assert values == [
        "navn",
        "epost",
        "telefon",
        "id",
        "klient",
        "nettadresse",
        "konto",
        "hemmeligheter",
        "finansielt",
        "medisinsk",
        "adresse",
    ]


def test_manual_redaction_terms_are_available_in_redaction_payload():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="manual-redaction-terms"' in html
    assert html.count('id="manual-redaction-terms"') == 1
    grid_start = html.index('<div class="scan-cat-grid">')
    grid_end = html.index("</div>", grid_start)
    ai_toggle = html.index("<!-- AI-dybdeskann toggle -->", grid_start)
    manual_panel = html.index('<details class="manual-redaction">', grid_end)
    manual_field = html.index('id="manual-redaction-terms"', manual_panel)
    secrets_category = html.index('value="hemmeligheter"', grid_start)
    assert secrets_category < grid_end < manual_panel < manual_field < ai_toggle
    assert '<details class="manual-redaction" open' not in html
    assert ".scan-cat-grid .manual-redaction" not in html
    assert "function _manualRedactionTerms()" in html
    assert "function updateManualRedactionPreview()" in html
    assert "manual-redaction-preview" in html
    assert 'category: "Egendefinert tekst"' in html
    assert "const aiTextsUnique = [...new Set(aiTexts)];" in html
    assert "function _redactionPayloadHasSelection(body)" in html
    assert 'document.getElementById("manual-redaction-terms")?.addEventListener("input", () => {' in html
    assert "updateRedactionReport(_currentResultExt())" in html
    for key in [
        "manualRedactionLabel",
        "manualRedactionPlaceholder",
        "manualRedactionNote",
        "manualPreviewEmpty",
        "manualPreviewScanFirst",
        "manualPreviewFound",
        "manualPreviewNotFound",
    ]:
        assert html.count(f"{key}:") == 6


def test_about_page_links_to_source_code():
    html = HTML.read_text(encoding="utf-8")

    assert 'href="https://github.com/telboth/xlent-scanner"' in html
    assert 'data-i18n="sourceCodeTitle"' in html
    assert 'data-i18n="sourceCodeLink"' in html
    assert html.count("sourceCodeTitle:") == 6
    assert html.count("sourceCodeLink:") == 6


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


def test_update_install_script_controls_exist_for_supported_desktop_platforms():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="update-banner-script-btn"' in html
    assert 'id="btn-run-install-script"' in html
    assert 'id="update-install-script-msg"' in html
    assert 'fetch(`${API}/updates/install-script/run`, { method: "POST" })' in html
    assert 'function canRunInstallScript()' in html
    assert 'APP_PLATFORM === "darwin"' in html
    assert '.startsWith("win")' in html
    assert 'updateBannerScriptBtnEl.onclick = runInstallScript;' in html
    assert 'document.getElementById("btn-run-install-script").addEventListener("click", runInstallScript);' in html

    for key in [
        "updateRunScript",
        "updateRunScriptShort",
        "updateInstallScriptRunning",
        "updateInstallScriptStarted",
        "updateInstallScriptFailed",
        "updateInstallScriptUnsupported",
    ]:
        assert html.count(f"{key}:") == 6


def test_top_update_check_button_is_wired():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="btn-check-updates-top"' in html
    assert 'class="ctrl-btn top-update-btn"' in html
    assert 'data-i18n="updateCheckTop"' in html
    assert 'class="top-menu"' in html
    assert 'id="top-menu"' in html
    assert ".top-menu {" in html
    assert ".top-menu-body {" in html
    assert "background: var(--panel2); color: var(--text);" in html
    assert ".top-menu[open] summary { border-color: var(--accent); color: var(--accent); }" in html
    assert ".top-update-btn {" in html
    assert "margin-left: auto;" in html
    assert 'const topUpdateCheckBtnEl = document.getElementById("btn-check-updates-top");' in html
    assert "function setTopUpdateCheckBusy(busy)" in html
    assert 'document.getElementById("btn-check-updates-top").addEventListener("click", () => runUpdateCheck(true));' in html
    assert html.count("updateCheckTop:") == 6
    assert html.count("updateCheckNow:") == 6
    assert html.count("updateCheckFailed:") == 6


def test_open_in_browser_top_button_is_wired():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="btn-open-in-browser-top"' in html
    assert 'class="ctrl-btn top-browser-btn"' in html
    assert 'data-i18n="openInBrowserTop"' in html
    assert 'data-i18n-title="openInBrowserTooltip"' in html
    assert "Åpne i nettleser" in html
    assert ".top-browser-btn {" in html
    assert "async function openInSystemBrowser()" in html
    assert 'setStatus(t("openInBrowserStarting"));' in html
    assert 'if (d.ok) setStatus(t("openInBrowserStarted"));' in html
    assert 'fetch(`${API}/open-in-browser`, { method: "POST" })' in html
    assert 'document.getElementById("btn-open-in-browser-top").addEventListener("click", openInSystemBrowser);' in html
    assert html.count("openInBrowserTop:") == 6
    assert html.count("openInBrowserTooltip:") == 6
    assert html.count("openInBrowserStarting:") == 6
    assert html.count("openInBrowserStarted:") == 6
    assert html.count("openInBrowserFailed:") == 6


def test_diagnostics_controls_exist_for_all_languages():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="btn-run-health"' in html
    assert 'id="btn-export-debug"' in html
    assert 'id="health-msg"' in html
    assert 'fetch(`${API}/diagnostics/health`)' in html
    assert 'fetch(`${API}/diagnostics/export`, { method: "POST" })' in html
    assert 'document.getElementById("btn-run-health").addEventListener("click", runHealthCheck);' in html
    assert 'document.getElementById("btn-export-debug").addEventListener("click", exportDebugPackage);' in html
    for key in [
        "runHealthCheck",
        "healthCheckOk",
        "healthCheckFailed",
        "exportDebugPackage",
        "debugExported",
        "debugExportFailed",
    ]:
        assert html.count(f"{key}:") == 6


def test_redaction_preview_and_report_are_available():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="g-preview"' in html
    assert 'id="redaction-report"' in html
    assert 'id="redaction-preview"' in html
    assert "function _redactionPayload" in html
    assert "function updateRedactionReport" in html
    assert "function previewRedaction" in html
    assert 'fetch(`${API}/redaction/preview`' in html
    assert 'document.getElementById("g-preview")?.addEventListener("click", previewRedaction);' in html
    for key in [
        "previewRedaction",
        "redactionReport",
        "redactionSelected",
        "redactionNotSelected",
        "redactionUnsafe",
        "redactionPreviewEmpty",
        "redactionPreviewMatches",
    ]:
        assert html.count(f"{key}:") == 6


def test_settings_profile_and_ollama_pull_controls_exist_for_all_languages():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="btn-export-settings"' in html
    assert 'id="btn-import-settings"' in html
    assert 'id="settings-import-file"' in html
    assert 'id="btn-pull-ollama-model"' in html
    assert 'id="btn-test-ollama-hardware"' in html
    assert 'id="ollama-hardware-test-msg"' in html
    assert 'id="ollama-settings-model-select"' in html
    assert 'id="ollama-hardware-info"' in html
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
        "settingsSearchPlaceholder",
        "settingsSearchCount",
        "settingsApiTitle",
        "settingsApiNote",
        "apiDocsOpen",
        "apiOpenapiJson",
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
        "ollamaSettingsModelLabel",
        "ollamaHardwareLabel",
        "ollamaHardwareChecking",
        "ollamaHardwareGpu",
        "ollamaHardwareHybrid",
        "ollamaHardwareCpu",
        "ollamaHardwareInactive",
        "ollamaHardwareUnknown",
        "ollamaHardwareTest",
        "ollamaHardwareTesting",
        "ollamaHardwareTestDone",
        "ollamaHardwareTestFailed",
    ]:
        assert html.count(f"{key}:") == 6


def test_ollama_settings_model_select_and_hardware_status_are_wired():
    html = HTML.read_text(encoding="utf-8")

    assert "function _renderOllamaSettingsModelSelect" in html
    assert "function loadOllamaHardwareInfo" in html
    assert "function testOllamaHardware" in html
    assert 'fetch(`${API}/ollama/hardware-info`)' in html
    assert 'fetch(`${API}/ollama/hardware-test`' in html
    assert "_rememberOllamaModel(settingsModelSelect.value)" in html
    assert "_rememberOllamaModel(sel.value)" in html


def test_microsoft_365_graph_controls_exist_for_all_languages():
    html = HTML.read_text(encoding="utf-8")

    for marker in [
        'id="section-m365"',
        'id="m365-drive-id"',
        'id="m365-item-id"',
        'id="m365-sync-root"',
        'id="m365-sensitivity-label-id"',
        'id="m365-retention-label-name"',
        'id="m365-map-gronn"',
        'id="m365-map-gul"',
        'id="m365-map-rod"',
        'id="m365-map-svart"',
        'id="btn-m365-status"',
        'id="btn-m365-read-tags"',
        'id="btn-m365-read-local-tags"',
        'id="btn-m365-assign-sensitivity"',
        'id="btn-m365-set-retention"',
        'id="btn-m365-write-metadata"',
        'id="m365-msg"',
        "function m365ReadTags",
        "function m365ReadLocalTags",
        "function buildM365TagsHtml",
        'fetch(`${API}/microsoft/graph/status`)',
        'fetch(`${API}/microsoft/graph/tags`',
        'fetch(`${API}/microsoft/graph/tags-for-local-file`',
        'fetch(`${API}/microsoft/graph/assign-sensitivity`',
        'fetch(`${API}/microsoft/graph/set-retention`',
        'fetch(`${API}/microsoft/graph/write-scan-metadata`',
        '_folderPost("/microsoft/graph/write-folder-metadata"',
        'id="folder-m365-metadata"',
        "policy-warning-banner",
        "policy_warning_level",
    ]:
        assert marker in html

    for key in [
        "settingsM365Title",
        "settingsM365Note",
        "m365DriveId",
        "m365ItemId",
        "m365SyncRoot",
        "m365SensitivityLabelId",
        "m365RetentionLabelName",
        "m365CheckStatus",
        "m365ReadTags",
        "m365ReadLocalTags",
        "m365AssignSensitivity",
        "m365SetRetention",
        "m365WriteMetadata",
        "m365LabelMappingNote",
        "m365MapGreen",
        "m365MapYellow",
        "m365MapRed",
        "m365MapBlack",
        "m365TokenConfigured",
        "m365TokenMissing",
        "m365Done",
        "m365Failed",
        "m365PolicyWarning",
        "m365SensitivityLabels",
        "m365RetentionLabel",
        "m365SuggestedLabel",
        "m365FolderMetadataRunning",
        "m365FolderMetadataWritten",
        "m365FolderMetadataErrors",
        "folderM365Metadata",
    ]:
        assert html.count(f"{key}:") == 6


def test_scan_category_translations_exist_for_all_languages():
    html = HTML.read_text(encoding="utf-8")

    for key in [
        "scanCatId",
        "scanCatKonto",
        "scanCatNavn",
        "scanCatHemmeligheter",
        "scanCatFinansielt",
        "scanCatKlient",
        "scanCatPassnummer",
        "scanCatLonn",
        "dstCatMedisinsk",
    ]:
        assert html.count(f"{key}:") == 6


def test_bank_details_category_combines_account_iban_and_swift():
    html = HTML.read_text(encoding="utf-8")

    assert 'class="scan-cat" value="konto" checked' in html
    assert 'class="scan-cat" value="swift"' not in html
    assert 'class="scan-cat" value="kredittkort"' not in html
    assert 'scanCatKonto:        "Bankdetaljer"' in html
    assert 'scanCatKonto:        "Bankuppgifter"' in html
    assert 'scanCatKonto:        "Bank details"' in html
    assert 'scanCatKonto:        "Bankdaten"' in html
    assert 'scanCatKonto:        "Coordonnées bancaires"' in html
    assert 'scanCatKonto:        "Datos bancarios"' in html
    assert '"konto":         c => ["kontonummer","bankgiro","plusgiro","iban","swift/bic","kredittkort"].some(p => c.startsWith(p))' in html
    assert '"konto":       ["bankkonto", "swift"]' in html


def test_scan_menu_combines_birthdate_passport_creditcard_and_salary_categories():
    html = HTML.read_text(encoding="utf-8")

    assert 'class="scan-cat" value="fodselsdato"' not in html
    assert 'class="scan-cat" value="passnummer"' not in html
    assert 'class="scan-cat" value="lonn"' not in html
    assert 'class="scan-cat" value="id" checked' in html
    assert 'class="scan-cat" value="finansielt" checked' in html
    assert '"id":            c => ["fødselsdato","fødselsnummer","d-nummer","personnummer","samordningsnummer","cpr-nummer","uk national insurance","us social security","mulig personnummer","passnummer"].some(p => c.startsWith(p))' in html
    assert '"finansielt":    c => ["timepris","dagspris","prosjektsum","enhetspris","margin","rabatt","budsjett","lønn"].some(p => c.startsWith(p))' in html
    assert '"id":          ["personnummer", "passnummer"]' in html
    assert '"finansielt":  ["budsjett_tall", "lonn"]' in html


def test_recursive_folder_scan_controls_are_wired():
    html = HTML.read_text(encoding="utf-8")

    for key in [
        "folderRecursive",
        "folderMaxFiles",
        "folderMaxDepth",
        "folderPreview",
        "folderPreviewTruncated",
        "folderTruncated",
        "folderTooltipTitle",
        "folderTooltipNone",
        "folderTooltipMore",
        "folderCancel",
        "folderProgress",
        "folderFilterSearch",
        "folderFilterRisk",
        "folderFilterAll",
        "folderOnlyFindings",
        "folderOnlyErrors",
        "folderExportJson",
        "folderExportCsv",
        "folderAuditHtml",
        "folderAuditPdf",
        "folderRedactSelected",
        "folderM365Metadata",
        "folderNoSelection",
        "folderOpenFile",
        "folderRevealFile",
        "folderSelect",
        "folderActions",
        "folderActionDone",
        "folderActionFailed",
        "folderRedactDone",
    ]:
        assert html.count(f"{key}:") == 6
    assert 'id="folder-recursive"' in html
    assert 'id="folder-max-files"' in html
    assert 'id="folder-max-depth"' in html
    assert 'id="btn-cancel-folder"' in html
    assert 'id="folder-progress"' in html
    assert 'fetch(`${API}/scan-folder/preview`' in html
    assert '_folderPost("/scan-folder/start"' in html
    assert 'fetch(`${API}/scan-folder/status/${encodeURIComponent(jobId)}`)' in html
    assert '_folderPost(`/scan-folder/cancel/${encodeURIComponent(_folderJobId)}`)' in html
    assert "function getFolderOpts()" in html
    assert "recursive: document.getElementById(\"folder-recursive\")?.checked === true" in html
    assert "relative_path || file.file_name" in html
    assert "function _folderTooltipHtml(file)" in html
    assert "findings_summary" in html
    assert 'class="batch-file-link"' in html
    assert "window.open(`${API}/folder-report/${encodeURIComponent(id)}`, \"_blank\")" in html
    assert "function _folderVisibleRows(files)" in html
    assert "function _sortButton(key, label)" in html
    assert 'id="folder-filter-search"' in html
    assert 'id="folder-filter-risk"' in html
    assert 'id="folder-export-json"' in html
    assert 'id="folder-export-csv"' in html
    assert 'id="folder-audit-html"' in html
    assert 'id="folder-audit-pdf"' in html
    assert 'id="folder-m365-metadata"' in html
    assert 'id="folder-redact-selected"' in html
    assert 'class="folder-row-cb"' in html
    assert '_folderRunOutputAction("/folder-export/json", "folderActionDone")' in html
    assert '_folderRunOutputAction("/folder-export/csv", "folderActionDone")' in html
    assert '_folderRunOutputAction("/folder-audit/html", "folderActionDone")' in html
    assert '_folderRunOutputAction("/folder-audit/pdf", "folderActionDone")' in html
    assert "function writeFolderM365Metadata()" in html
    assert '_folderPost("/folder-redact"' in html
    assert '_folderPost(url, { report_id: id })' in html


def test_client_names_are_presented_as_company_and_org_number():
    html = HTML.read_text(encoding="utf-8")

    assert 'scanCatKlient:       "Firma / org.nr."' in html
    assert 'scanCatKlient:       "Företag / org.nr."' in html
    assert 'scanCatKlient:       "Company / org. no."' in html
    assert 'scanCatKlient:       "Firma / Registernr."' in html
    assert 'scanCatKlient:       "Société / n° org."' in html
    assert 'scanCatKlient:       "Empresa / n.º org."' in html
    assert 'class="scan-cat" value="orgnummer"' not in html
    assert "Klientnavn" not in html
    assert "Client names" not in html


def test_secrets_category_combines_confidential_keywords():
    html = HTML.read_text(encoding="utf-8")

    assert 'class="scan-cat" value="hemmeligheter" checked' in html
    assert 'class="scan-cat" value="konfidensielt"' not in html
    assert 'scanCatHemmeligheter:"Hemmeligheter / konfidensielt"' in html
    assert 'scanCatHemmeligheter:"Secrets / confidential"' in html
    assert '"konfidensielt": "hemmeligheter"' in html
    assert '"orgnummer": "klient"' in html
    assert '"hemmeligheter": ["sensitiv_personkontekst", "personalsak", "juridisk", "barn_skole"]' in html


def test_empty_document_warning_translations_exist_for_all_languages():
    html = HTML.read_text(encoding="utf-8")

    assert "function warningText" in html
    assert 'r.warning_code === "no_text_extracted"' in html
    assert 'r.warning_code === "little_text_extracted"' in html
    for key in ["warnNoText", "warnLittleText"]:
        assert html.count(f"{key}:") == 6


def test_guard_watch_custom_patterns_and_ocr_ui_are_wired():
    html = HTML.read_text(encoding="utf-8")

    for element_id in [
        "background-panel",
        "background-panel-body",
        "custom-patterns-editor",
        "custom-pattern-name",
        "custom-pattern-regex",
        "custom-pattern-severity",
        "custom-pattern-sample",
        "btn-custom-pattern-test",
        "btn-custom-pattern-add",
        "btn-custom-patterns-reload",
        "btn-custom-patterns-save",
        "clipguard-toggle",
        "watch-toggle",
        "btn-watch-choose",
    ]:
        assert f'id="{element_id}"' in html

    for snippet in [
        'fetch(`${API}/custom-patterns/get`,',
        'fetch(`${API}/custom-patterns/save`,',
        'fetch(`${API}/custom-patterns/test`,',
        'fetch(`${API}/clipboard-guard/${enabled ? "start" : "stop"}`',
        'fetch(`${API}/folder-watch/start`,',
        'fetch(`${API}/folder-watch/stop`,',
        'fetch(`${API}/folder-watch/status`)',
        "refreshBackgroundPanel",
        "startWatchStatusPolling",
        "stopWatchStatusPolling",
        "setInterval(pollWatchStatus, 4000)",
        "At most 3 folders",
        "loadHistoryFromApi();",
        'item.source === "watch"',
        "addCustomPatternFromForm",
        "testCustomPatternForm",
        "rescanRedacted",
        "loadCustomPatternsEditor();",
        "restoreClipGuard();",
        "restoreWatch();",
        'fd.append("ocr", "true")',
        'ocr: true',
        'const IMAGE_EXT   = new Set(["png","jpg","jpeg","bmp","tif","tiff","webp"]);',
        'function _isOcrCandidateResult(r, ext)',
        '.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp',
    ]:
        assert snippet in html

    for key in [
        "settingsCustomPatternsTitle",
        "customPatternsNote",
        "customPatternsReload",
        "customPatternsSave",
        "customPatternsLoadErr",
        "customPatternsSaveErr",
        "customPatternsSaved",
        "customPatternName",
        "customPatternRegex",
        "customPatternSeverity",
        "customPatternIgnoreCase",
        "customPatternSample",
        "customPatternTest",
        "customPatternAdd",
        "customPatternMatches",
        "customPatternMissing",
        "customPatternAdded",
        "settingsClipGuardTitle",
        "clipGuardNote",
        "clipGuardToggle",
        "clipGuardActive",
        "clipGuardInactive",
        "settingsWatchTitle",
        "watchNote",
        "watchChoose",
        "watchToggle",
        "watchNoFolder",
        "watchMaxFolders",
        "watchActive",
        "watchInactive",
        "watchScanned",
        "historySourceWatch",
        "backgroundTitle",
        "backgroundWatch",
        "backgroundClipboard",
        "backgroundLast",
        "backgroundLastClipboard",
        "settingsWhitelistTitle",
        "whitelistPersonalNote",
        "whitelistStructuredNote",
        "whitelistReload",
        "whitelistSave",
        "whitelistPathLabel",
        "whitelistSaved",
        "whitelistLoadErr",
        "rescanRedacted",
        "ocrRescanBtn",
        "ocrRescanTooltip",
        "ocrRunning",
        "autoOcrRunning",
        "autoOcrLabel",
        "autoOcrNote",
        "ocrResultNotice",
        "saveOcrPdf",
        "saveImagePdf",
        "pdfImageCaveat",
        "pdfImagePatchUnsafe",
        "imagePdfRedactionFailed",
        "imagePdfMasks",
        "imagePdfUnmatched",
        "aiToggleTooltip",
        "folderRecursiveTooltip",
        "folderRedactSelectedTooltip",
        "updateRunScriptTooltip",
        "m365WriteMetadataTooltip",
    ]:
        assert html.count(f"{key}:") == 6


def test_tooltips_exist_for_expensive_or_external_actions():
    html = HTML.read_text(encoding="utf-8")

    assert 'data-i18n-title="aiToggleTooltip"' in html
    assert 'data-i18n-title="folderRecursiveTooltip"' in html
    assert 'data-i18n-title="m365WriteMetadataTooltip"' in html
    assert 'data-i18n-title="updateRunScriptTooltip"' in html
    assert 'title="${escapeHtml(t("ocrRescanTooltip"))}"' in html
    assert 'title="${escapeHtml(t("folderRedactSelectedTooltip"))}"' in html
    assert 'document.querySelectorAll("[data-i18n-title]")' in html
    assert "el.title = t(el.dataset.i18nTitle);" in html


def test_scan_mode_selector_is_removed_and_frontend_uses_auto_scan_mode():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="pdf-mode"' not in html
    assert 'data-i18n="pdfMode"' not in html
    assert 'id="scan-mode-hint"' not in html
    assert "function updateScanModeHint" not in html
    assert 'pdf_mode:     "auto"' in html
    assert 'scan_mode:    "auto"' in html
    assert "pdfMode:" not in html
    assert "scanModeAdvancedHint:" not in html


def test_scan_categories_are_persisted_and_default_button_is_wired():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="scan-sel-default"' in html
    assert 'id="scan-sel-all"' not in html
    assert 'id="scan-sel-none"' not in html
    assert 'data-i18n="selDefault"' in html
    assert "const DEFAULT_SCAN_CATEGORIES = [" in html
    assert '"medisinsk"' not in html.split("const DEFAULT_SCAN_CATEGORIES = [", 1)[1].split("];", 1)[0]
    assert "function _selectedScanCategories()" in html
    assert "function _applyScanCategories(categories)" in html
    assert "function _setDefaultScanCategories()" in html
    assert "if (Array.isArray(s.scanCategories)) _applyScanCategories(s.scanCategories);" in html
    assert "scanCategories: _selectedScanCategories()" in html
    assert 'document.querySelectorAll(".scan-cat").forEach(cb => cb.addEventListener("change", saveSettings));' in html
    assert 'document.getElementById("scan-sel-all").addEventListener("click"' not in html
    assert 'document.getElementById("scan-sel-none").addEventListener("click"' not in html
    assert 'document.getElementById("scan-sel-default").addEventListener("click", _setDefaultScanCategories);' in html
    assert html.count("selDefault:") == 6


def test_auto_ocr_setting_defaults_on_and_is_wired():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="auto-ocr" checked' in html
    assert 'data-i18n="autoOcrLabel"' in html
    assert 'data-i18n="autoOcrNote"' in html
    assert "if (autoOcr) autoOcr.checked = s.autoOcr !== false;" in html
    assert 'autoOcr: document.getElementById("auto-ocr")?.checked !== false' in html
    assert 'document.getElementById("auto-ocr")?.addEventListener("change", saveSettings);' in html
    assert "function _maybeRunAutoOcr(r, ext)" in html
    assert "function _runOcrForLastScan()" in html
    assert "setTimeout(() => _runOcrForLastScan(), 50);" in html
    assert "&& !lastScan?.ocr" in html
    assert "&& !r.ocr_used" in html
    assert "if (!autoOcrStarted) autoAiScan();" in html


def test_scanner_result_sections_use_expanders_and_neutral_scan_buttons():
    html = HTML.read_text(encoding="utf-8")

    assert '<button id="btn-scan-text" class="ctrl-btn" data-i18n="pasteBtn">Skann tekst</button>' in html
    assert '<button id="btn-scan-folder" class="ctrl-btn" data-i18n="folderBtn">📂 Velg og skann mappe</button>' in html
    assert 'id="btn-scan-text" class="ctrl-btn ctrl-btn-primary"' not in html
    assert 'id="btn-scan-folder" class="ctrl-btn ctrl-btn-primary"' not in html

    assert ".result-expander" in html
    assert '<details class="result-expander text-preview-expander">' in html
    assert '<summary>${escapeHtml(t("extractedText"))}</summary>' in html
    assert '<details class="result-expander redaction-report-expander" open>' in html
    assert '<summary>${escapeHtml(t("redactionReport"))}</summary>' in html
    assert 'resultEl.querySelector(".redaction-report-expander .result-expander-body") || resultEl' in html


def test_scan_strategy_is_shown_in_timing_diagnostics():
    html = HTML.read_text(encoding="utf-8")

    assert "timings.scan_strategy" in html
    assert "timings.scan_strategy_reason" in html
    assert "function _scanStrategyLabel(value)" in html
    assert "function _scanStrategyReasonLabel(value)" in html
    for key in [
        "scanStrategyFast",
        "scanStrategyAdvanced",
        "scanStrategyReasonAutoFast",
        "scanStrategyReasonLittleText",
        "scanStrategyReasonTableLayout",
        "scanStrategyReasonOcr",
        "scanStrategyReasonExplicitFast",
        "scanStrategyReasonExplicitAdvanced",
        "scanStrategyReasonFallback",
    ]:
        assert html.count(f"{key}:") == 6


def test_suppressed_candidate_note_warns_to_select_only_sensitive_items():
    html = HTML.read_text(encoding="utf-8")

    assert "Huk av bare hvis dette faktisk er sensitiv informasjon" in html
    assert "Select only if this is actually sensitive information" in html


def test_ocr_rescan_shows_progress_indicator():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="ocr-scan-status"' in html
    assert 'id="ocr-progress-meter"' in html
    assert 'id="ocr-progress-fill" class="ai-progress-fill"' in html
    assert "function setOcrProgress(active)" in html
    assert "setOcrProgress(isOcrScan);" in html
    assert "setOcrProgress(false);" in html
    assert "ocrBtn.disabled = !!active;" in html
    assert 'lastScan = { type:"path", path, ocr: isOcrScan };' in html
    assert 'lastScan = { type:"upload", file, name, ocr: isOcrScan };' in html
    assert 'fill.classList.add("indeterminate")' in html
    assert '<span class="btn-spinner" aria-label="Loading"></span> ${escapeHtml(t("ocrRunning"))}' in html
    assert 'class="ctrl-btn ctrl-btn-primary"' not in html[
        html.index('const ocrBtnHtml = canOcr'):html.index('const warningBanner = warning')
    ]
    assert 'class="ctrl-btn ctrl-btn-outline-primary"' in html[
        html.index('const ocrBtnHtml = canOcr'):html.index('const warningBanner = warning')
    ]
    assert 'if (isOcrScan) {' in html[html.index("async function scanPath"):html.index("async function scanUpload")]
    assert 'resultEl.innerHTML = "";' in html[html.index("async function scanPath"):html.index("async function scanUpload")]
    assert "setOcrProgress(false);" in html[html.index("function clearResult()"):html.index("function renderSeveritySummary()")]


def test_text_preview_is_cleared_when_new_scan_starts():
    html = HTML.read_text(encoding="utf-8")

    assert "function _clearTextPreview()" in html
    assert 'section.innerHTML = "";' in html[html.index("function _clearTextPreview()"):html.index("function clearResult()")]
    assert "_clearTextPreview();" in html[html.index("function clearResult()"):html.index("function renderSeveritySummary()")]
    assert "_clearTextPreview();" in html[html.index("async function scanPath"):html.index("async function scanUpload")]
    assert "_clearTextPreview();" in html[html.index("async function scanUpload"):html.index("/* ══════════════════════════════════════════════════════════════════\n       DRAG-DROP")]
    assert "_clearTextPreview();" in html[html.index('document.getElementById("btn-scan-text").addEventListener'):html.index("/* ══════════════════════════════════════════════════════════════════\n       FOLDER SCAN")]
    assert "_clearTextPreview();" in html[html.index('document.getElementById("btn-scan-folder").addEventListener'):html.index("const dlg = await")]


def test_whitelist_button_is_hidden_for_non_whitelistable_categories():
    html = HTML.read_text(encoding="utf-8")

    assert 'data-i18n="whitelistStructuredNote"' in html
    assert "const NON_WHITELISTABLE_CATEGORY_TOKENS" in html
    for token in ["prosjektsum", "fødselsdato", "budsjettall", "budsjett"]:
        assert f'"{token}"' in html
    assert "function _categoryAllowsWhitelist(category)" in html
    assert 'const whitelistAllowed = _categoryAllowsWhitelist(f.category);' in html
    assert '&& !f.category.startsWith("⚠") && whitelistAllowed' in html
    assert 'const canWl = (sev !== "svart" && sev !== "grønn" && whitelistAllowed);' in html
    assert 'data-category="${escapeHtml(f.category)}"' in html
    assert 'data-category="${escapeHtml(f.category||"")}"' in html
    assert 'category: btn.dataset.category || ""' in html
    assert "body: JSON.stringify({ text, category })" in html


def test_ocr_pdf_redaction_uses_image_pdf_redaction_instead_of_direct_patch():
    html = HTML.read_text(encoding="utf-8")

    assert "function _isOcrOrImagePdfResult" in html
    assert "if (IMAGE_EXT.has(ext)) return Boolean(lastResult?.ocr_used || lastScan?.ocr);" in html
    assert "const isOcrPdf = _isOcrOrImagePdfResult(ext);" in html
    assert "const canPatch = PATCH_EXT.has(ext) && !isOcrPdf;" in html
    assert 'id="g-image-pdf"' in html
    assert 'postAnon("patch-image-pdf")' in html
    assert 'const endpoint = imagePdf ? "patch-image-pdf" : (canPatch ? "patch" : "anonymize");' in html
    assert 'if (_isOcrOrImagePdfResult(ext)) await postAnon("patch-image-pdf", undefined, "ai-anon-msg");' in html
    assert "function _imagePdfRedactionSummary(stats)" in html
    assert "d.image_pdf_redaction" in html
    assert 't("pdfImageCaveat")' in html
    assert 't("ocrResultNotice")' in html


def test_settings_panel_does_not_use_filled_primary_buttons():
    html = HTML.read_text(encoding="utf-8")

    start = html.index('id="panel-settings"')
    end = html.index("<script>", start)
    settings_panel = html[start:end]

    assert "ctrl-btn-primary" not in settings_panel
    assert "ctrl-btn-accent" not in settings_panel
    assert "ctrl-btn-outline-primary" in settings_panel


def test_settings_sections_are_closed_expanders_by_default():
    html = HTML.read_text(encoding="utf-8")

    start = html.index('id="panel-settings"')
    end = html.index('<div class="settings-note" data-i18n="settingsPersistNote"', start)
    settings_sections = html[start:end]

    assert settings_sections.count('<details class="settings-section settings-expander') == 17
    assert settings_sections.count('<summary class="settings-section-title"') == 17
    assert 'id="settings-search"' in html
    assert 'data-i18n-placeholder="settingsSearchPlaceholder"' in html
    assert "sessionStorage.getItem(\"xlent_settings_open_sections\")" in html
    assert "sessionStorage.setItem(\"xlent_settings_open_sections\"" in html
    assert "function applySettingsSearch" in html
    assert '<div class="settings-section">' not in settings_sections
    assert ".settings-expander > .settings-section-title::after" in html
    assert ".settings-expander[open] > .settings-section-title" in html
    assert "if (nerSection) nerSection.open = true;" in html

    for line in settings_sections.splitlines():
        if line.strip().startswith("<details "):
            assert " open" not in line


def test_findings_include_explain_why_details():
    html = HTML.read_text(encoding="utf-8")

    assert "function _findingReasonHtml" in html
    assert 'class="finding-reason"' in html
    assert "${_findingReasonHtml(f)}" in html
    assert "${_findingReasonHtml(f, { isAi: true })}" in html
    for key in [
        "whyFlagged",
        "whySource",
        "whyCategory",
        "whySeverity",
        "whyConfidence",
        "whyContext",
        "whyExplanation",
        "whyRuleEngine",
        "whyNerEngine",
        "whyAiEngine",
        "whySystemEngine",
        "whyRuleExplanation",
        "whyNerExplanation",
        "whyAiExplanation",
        "whySystemExplanation",
        "whySecretExplanation",
        "whyWhitelistExplanation",
        "whyNoContext",
    ]:
        assert html.count(f"{key}:") == 6


def test_medical_ai_category_is_available_but_default_off():
    html = HTML.read_text(encoding="utf-8")

    assert 'class="scan-cat" value="medisinsk"' in html
    assert 'class="scan-cat" value="medisinsk" checked' not in html
    assert 'data-i18n="dstCatMedisinsk"' in html
    assert 'dstCatMedisinsk:     "Medisinsk"' in html
    assert 'dstCatMedisinsk:     "Medical"' in html
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


def test_ai_deep_scan_progress_bar_and_eta_are_wired():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="ai-progress-meter"' in html
    assert 'id="ai-progress-fill"' in html
    assert 'id="ai-inline-progress"' in html
    assert 'id="ai-inline-progress-fill"' in html
    assert 'id="ai-progress-chunks"' in html
    assert 'id="ai-progress-eta"' in html
    assert ".ai-progress-track" in html
    assert ".ai-inline-progress" in html
    assert "ai-progress-indeterminate" in html
    assert "function _updateAiProgressMeter" in html
    assert "function _formatAiDuration" in html
    assert "function _resetAiProgressMeter" in html
    assert "function _showAiProgressPreparing" in html
    assert "_updateAiProgressMeter(s);" in html
    assert "_showAiProgressPreparing(t(\"deepScanRunning\"));" in html
    assert 'inlineFill.style.width = `${percent}%`;' in html
    assert "s.total_chunks" in html
    assert "s.completed_chunks" in html
    assert "s.progress_percent" in html
    for key in ["aiEtaCalculating", "aiEtaRemaining", "aiProgressParts"]:
        assert html.count(f"{key}:") == 6


def test_ai_deep_scan_skips_regex_covered_categories():
    html = HTML.read_text(encoding="utf-8")

    assert "let AI_REGEX_COVERED_SCAN_CATS = new Set([" in html
    assert "await loadScanCategoryConfig();" in html
    assert "AI_REGEX_COVERED_SCAN_CATS = new Set(" in html
    for value in [
        '"epost"',
        '"nettadresse"',
        '"telefon"',
        '"id"',
        '"konto"',
    ]:
        assert value in html
    assert "if (AI_REGEX_COVERED_SCAN_CATS.has(key)) continue;" in html


def test_ai_deep_scan_updates_main_risk_and_redaction_controls():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="ai-redacted-doc-btn"' in html
    assert 'data-i18n="downloadRedactedDoc"' in html
    assert 'id="ai-open-anonymized-btn"' in html
    assert 'data-i18n="openAnonymizedFile"' in html
    assert "function _downloadRedactedDocAfterAi" in html
    assert 'document.getElementById("ai-redacted-doc-btn").addEventListener("click", _downloadRedactedDocAfterAi);' in html
    assert 'document.getElementById("ai-open-anonymized-btn").addEventListener("click"' in html
    assert 'id="result-risk-dot"' in html
    assert 'id="result-risk-title"' in html
    assert 'id="result-action-box"' in html
    assert "function _updateRiskHeaderForAiFindings" in html
    assert "lastResult.risk_level = level;" in html
    assert "resultEl.querySelectorAll(\".no-findings-message\").forEach(el => el.remove());" in html
    assert "function _ensureRedactionControlsForAiFindings" in html

    assert "const summary = level === \"grønn\" ? t(\"aiRiskGreenSummary\") : t(\"aiRiskSummary\");" in html
    assert "let level = \"grønn\";" in html
    assert "(lastResult?.findings || []).forEach(f => {" in html

    for key in ["downloadRedactedDoc", "openAnonymizedFile", "aiRiskGreenSummary", "aiRiskGreenAction", "aiRiskSummary", "aiRiskAction"]:
        assert html.count(f"{key}:") == 6


def test_anonymized_file_button_saves_then_opens_without_prior_save():
    html = HTML.read_text(encoding="utf-8")

    assert html.count('class="ctrl-btn open-anonymized-btn"') == 3
    assert "function _setLastAnonymizedPath(path)" in html
    assert "function _openAnonymizedFile" in html
    assert "function _saveAndOpenAnonymized" in html
    assert '_setLastAnonymizedPath(d.path);' in html
    assert 'fetch(`${API}/open-anonymized-file`' in html
    assert 'id="g-open-anonymized" disabled' not in html
    assert 'id="ai-open-anonymized-btn" data-i18n="openAnonymizedFile" disabled' not in html
    assert 'await postAnon(' in html
    assert 'if (saved?.ok) await _openAnonymizedFile(msgId);' in html
    assert "function _preferredOpenAnonymizedFormat" in html
    assert 'return ext === "pdf" ? "pdf" : "md";' in html


def test_top_rescan_button_is_available_without_ai_toggle():
    html = HTML.read_text(encoding="utf-8")

    assert "function _rescanLastDocument()" in html
    assert 'rescanBtn.style.display = lastResult ? "" : "none";' in html
    assert 'if (document.getElementById("ai-scan-toggle")?.checked) autoAiScan();' in html
    assert "else _rescanLastDocument();" in html
    assert '(this.checked && lastResult)' not in html


def test_suppressed_candidates_can_be_selected_for_redaction():
    html = HTML.read_text(encoding="utf-8")

    assert 'class="suppressed-cb"' in html
    assert 'data-i18n="suppressedUseCandidate"' in html
    assert 'document.querySelectorAll(".suppressed-cb:checked")' in html
    assert '".g-cb:checked, .g-ai-cb:checked, .suppressed-cb:checked"' in html
    assert "category: cb.dataset.category || \"Forkastet kandidat\"" in html
    assert "suppressedUseCandidate:" in html


def test_document_type_selector_is_removed_and_frontend_uses_auto_profile():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="scan-profile"' not in html
    assert 'data-i18n="scanProfile">Dokumenttype' not in html
    assert 'scan_profile: "auto"' in html
    assert "scanProfile:" not in html


def test_redaction_profile_selector_is_removed_from_frontend():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="redaction-profile"' not in html
    assert 'data-i18n="redactionProfile"' not in html
    assert "function applyRedactionProfile" not in html
    assert "SCAN_CATEGORY_PROFILES" not in html
    assert "redactionProfile:" not in html
    assert "profileLowFp:" not in html


def test_secondary_redaction_and_export_actions_are_collapsed():
    html = HTML.read_text(encoding="utf-8")

    assert '<details class="advanced-actions" id="advanced-actions">' in html
    assert "<summary>${t(\"moreOptions\")}</summary>" in html
    assert 'id="g-preview"' in html
    assert 'id="g-anon"' in html
    assert 'id="g-anon-pdf"' in html
    assert 'id="btn-exp-json"' in html
    assert 'id="btn-exp-csv"' in html
    assert html.count("moreOptions:") == 6


def test_redaction_history_and_automatic_verification_are_wired():
    html = HTML.read_text(encoding="utf-8")

    assert 'id="redaction-history-section"' in html
    assert 'id="redaction-history-list"' in html
    assert 'id="btn-clear-redaction-history"' in html
    assert "function loadRedactionHistory()" in html
    assert "function renderRedactionHistory()" in html
    assert "function _verificationSummary(verification)" in html
    assert 'redaction/history/verify' in html
    assert 'reveal-anonymized-file' in html
    assert "loadRedactionHistory();" in html

    for key in [
        "redactionHistoryTitle",
        "redactionHistoryClear",
        "redactionHistoryOpen",
        "redactionHistoryReveal",
        "redactionHistoryVerify",
        "verificationPassed",
        "verificationReview",
        "verificationRemoved",
        "verificationNotFound",
        "verificationStillPresent",
        "verificationRemaining",
    ]:
        assert html.count(f"{key}:") == 6


def test_ai_deep_scan_preserves_rule_based_person_names_and_risk():
    html = HTML.read_text(encoding="utf-8")

    assert "let _aiDeepScanCompleted = false;" in html
    assert "_aiDeepScanCompleted = true;" in html
    assert "function _regularNameIgnoredByAi" not in html
    assert "function _applyAiNameOverrideToRegularRows" not in html
    assert "_regularNameIgnoredByAi(idx)" not in html
    assert 'document.querySelectorAll(".g-cb:not(:disabled), .g-ai-cb")' in html
    assert "ai-name-override-note" not in html
    assert "aiNamesOverride:" not in html


def test_about_hardware_requirement_is_16gb_in_all_languages():
    html = HTML.read_text(encoding="utf-8")

    assert "8 GB RAM" not in html
    assert "8 Go de RAM" not in html
    assert "minst 16 GB RAM" in html
    assert "at least 16 GB RAM" in html
    assert "mindestens 16 GB RAM" in html
    assert "au moins 16 Go de RAM" in html
    assert "al menos 16 GB de RAM" in html


def test_about_text_documents_recent_features_in_all_languages():
    html = HTML.read_text(encoding="utf-8")

    for lang in ["nb", "sv", "en", "de", "fr", "es"]:
        marker = f'id="about-{lang}"'
        start = html.index(marker)
        next_start = html.find('class="about-content"', start + 1)
        section = html[start: next_start if next_start != -1 else len(html)]

        assert "Ollama" in section
        assert "OCR" in section
        assert "Microsoft 365" in section
        assert "Swagger/OpenAPI" in section
        assert "Power Apps" in section
        assert "regex" in section.lower()
        assert "Redaction profiles" not in section
        assert "Redaction-profiler" not in section
        assert "Redaction-Profile" not in section
        assert "profils de redaction" not in section
        assert "perfiles de redaction" not in section

    assert "Automatic scan mode" in html
    assert "OCR can misread text" in html
    assert "redacted image PDF" in html
    assert "Suppressed candidates" in html
