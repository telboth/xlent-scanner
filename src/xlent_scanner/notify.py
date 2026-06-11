"""Systemnotifikasjoner på tvers av plattformer — kun standardbibliotek.

  Windows: WinRT-toast via PowerShell (bruker PowerShells AppUserModelID,
           som gjør at toasts vises uten egen app-registrering)
  macOS:   osascript «display notification»
  Linux:   notify-send (libnotify) hvis tilgjengelig

Alle varianter er best-effort og fire-and-forget: feiler notifikasjonen,
logges det stille uten å forstyrre kallende kode.
"""
from __future__ import annotations

import logging
import subprocess
import sys

LOGGER = logging.getLogger("xlent_scanner")

# PowerShells registrerte AppUserModelID — toasts fra upakkede apper vises
# pålitelig når de sendes via en allerede registrert AUMID.
_POWERSHELL_AUMID = (
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
)


def _ps_quote(s: str) -> str:
    """Escaper en streng for bruk i enkeltfnutter i PowerShell."""
    return s.replace("'", "''")


def _windows_toast_script(title: str, message: str) -> str:
    return f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName('text')
$texts.Item(0).AppendChild($template.CreateTextNode('{_ps_quote(title)}')) | Out-Null
$texts.Item(1).AppendChild($template.CreateTextNode('{_ps_quote(message)}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_ps_quote(_POWERSHELL_AUMID)}').Show($toast)
"""


def _osascript_args(title: str, message: str) -> list[str]:
    # osascript-strenger escapes med backslash for " og \
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    return [
        "osascript", "-e",
        f'display notification "{esc(message)}" with title "{esc(title)}"',
    ]


def notify(title: str, message: str) -> bool:
    """Vis en systemnotifikasjon. Returnerer True hvis kommandoen ble startet.

    Kjører fire-and-forget (Popen) slik at kallende tråd aldri blokkeres.
    """
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                [
                    "powershell", "-NoProfile", "-NonInteractive",
                    "-WindowStyle", "Hidden",
                    "-Command", _windows_toast_script(title, message),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                _osascript_args(title, message),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["notify-send", "--app-name=XLENT Scanner", title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as exc:  # noqa: BLE001 — notifikasjon skal aldri velte appen
        LOGGER.warning("Systemnotifikasjon feilet: %s", exc)
        return False
