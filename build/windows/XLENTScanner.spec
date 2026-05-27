# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for XLENT Compliance-scanner
#
# Bygg fra repo-rot:
#   pyinstaller build\windows\XLENTScanner.spec
#
# Alle stier er relative til SPECPATH slik at bygget virker på alle maskiner.
#
import os
from PyInstaller.utils.hooks import collect_data_files

# ── Stier ──────────────────────────────────────────────────────────────────────
# Spec-fil: build/windows/XLENTScanner.spec
# Repo-rot: ../..  (to nivåer opp)
_repo_root = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
_src       = os.path.join(_repo_root, 'src')
_entry     = os.path.join(SPECPATH, 'entrypoint.py')

# ── Data-filer ─────────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files('xlent_scanner')    # web/index.html, data/*.toml, logo.svg
datas += collect_data_files('langdetect')       # språkprofiler som langdetect trenger

# ── Analyse ────────────────────────────────────────────────────────────────────
a = Analysis(
    [_entry],
    pathex=[_src],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # ── PyWebView / Windows ──────────────────────────────────────────────
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',   # WebView2-backend i pywebview 6.x

        # ── Dokumentlesere (lazy-importert i scanner.py / patch.py) ─────────
        # PyInstaller oppdager IKKE imports inne i funksjoner
        'docx',
        'docx.oxml',
        'docx.oxml.ns',
        'docx.enum.text',
        'docx.shared',
        'pptx',
        'pptx.util',
        'pptx.enum',
        'pptx.enum.text',
        'pptx.dml.color',
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        'openpyxl.utils.exceptions',

        # ── Språkdeteksjon ───────────────────────────────────────────────────
        'langdetect',
        'langdetect.detector',
        'langdetect.detector_factory',
        'langdetect.language',
        'langdetect.utils.lang_detect_exception',
        'langdetect.utils.unicode_block',

        # ── PDF-redaksjon (pymupdf / fitz) ───────────────────────────────────
        'fitz',

        # ── spaCy (NER – modeller installeres separat) ───────────────────────
        'spacy',
        'spacy.lang.nb',
        'spacy.lang.sv',
        'spacy.lang.en',

        # ── Standardbibliotek brukt dynamisk ────────────────────────────────
        'tomllib',
        'dataclasses',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Docling er ikke i bruk – eksplisitt ekskludert for å holde .exe liten
        # (docling + torch drar inn flere GB)
        'docling',
        'torch',
        'torchvision',
        'transformers',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='XLENTScanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='XLENTScanner',
)
