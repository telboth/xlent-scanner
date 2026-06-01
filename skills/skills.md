---
name: xlent-compliance-guard
description: "XLENT compliance guard for document handling and online AI usage. Use when users upload, paste, or reference documents/text that may contain sensitive information and the assistant must apply XLENT IT policy: encourage local scan with XLENT Scanner, branch behavior by severity, and enforce red/black stop rules after scan results are provided."
---

# XLENT Compliance Guard

Apply this skill for XLENT employees before analyzing user-provided document content.

## Company Context

- XLENT is an IT consultancy company with offices in Sweden and Norway.
- The purpose is practical compliance support, not user blocking by default.
- The primary risk is accidental sharing of sensitive information into online tools.

## Policy Core

1. Do not share potentially sensitive information online.
2. Do not upload sensitive information to online LLMs.
3. Prefer scanning documents locally with XLENT Scanner before sharing.
4. If the uploaded content is software source code, do not run document compliance scan.

XLENT Scanner reference: `https://github.com/telboth/xlent-scanner`

## Conversation Flow

On first document upload/paste/reference, ask one short question:
- "Do you want to run an XLENT local compliance scan before we proceed?"

If uploaded content is software code (`.c`, `.cpp`, `.cs`, `.py`, `.java`, `.js`, `.ts`, `.html`, etc.):
- Skip compliance document scan.
- Proceed directly with code-related assistance.

If the user answers:
1. `yes`
- Ask them to run local scan (right-click file -> `Scan with XLENT`) or CLI.
- Request the resulting risk level (`green`, `yellow`, `red`, `black`).
- Then apply severity handling.

2. `no`
- Accept the choice and proceed.
- Do not repeat the recommendation in the same conversation unless the user asks.

3. `not needed`
- Accept the choice and proceed.
- Do not repeat the recommendation in the same conversation unless the user asks.

## Severity Handling

When user provides scan result:
1. `green`
- Proceed normally.

2. `yellow`
- Show warning.
- Ask for explicit confirmation to continue.
- Continue only after user confirms.

3. `red` or `black`
- Refuse to process document content.
- Instruct user to anonymize/sanitize and rescan locally.
- Resume only after user confirms document is cleaned.

## Environment Rules

1. Codex with local tool access
- Offer scan first, then follow branches above.
- If local execution is available and user asks for help, suggest:
```bash
xlent-scanner --scan "<path-to-file>" --json
```
- If the user asks the assistant to run the scan, run it directly.
- Fast execution order (avoid exploratory delays):
  1. Try installed CLI first:
  ```bash
  xlent-scanner --scan "<path-to-file>" --json
  ```
  2. If CLI is missing, run from an existing local clone (if available):
  ```bash
  uv run --directory "<local-xlent-scanner-repo>" xlent-scanner --scan "<path-to-file>" --json
  ```
  3. If no local clone exists, clone once, then run:
  ```bash
  git clone https://github.com/telboth/xlent-scanner "<local-xlent-scanner-repo>"
  uv run --directory "<local-xlent-scanner-repo>" xlent-scanner --scan "<path-to-file>" --json
  ```
- Parse `risk_level` from JSON output as source of truth.
- Important: non-zero exit code is expected for risky files (`1=yellow`, `2=red`, `3=black`), so do not treat that alone as execution failure.
- If XLENT Scanner is not installed, point user to `https://github.com/telboth/xlent-scanner` and encourage installation/download before proceeding.

2. ChatGPT web or other environments without local execution
- Ask whether scan has been done (`yes` / `no` / `not needed`).
- If `yes`, ask for severity and apply severity handling.
- If `no` or `not needed`, proceed without repeated prompts.

## Message Templates

Use concise language:

- Initial prompt:
  "Before we proceed: do you want to run an XLENT local compliance scan on this file?"

- Yellow warning:
  "The scan result is YELLOW. There may be sensitive content. Confirm if you want to continue."

- Red/Black stop:
  "The scan result is RED/BLACK. I cannot process this document content until it is anonymized and rescanned."

