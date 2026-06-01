---
name: xlent-upload-compliance-check
description: "Prompt users to confirm whether uploaded or pasted files/text have been checked for sensitive information before analysis."
---

# XLENT Upload Compliance Check

Apply this skill whenever a user uploads, pastes, or references a document, image, spreadsheet, slide deck, email, or other file that may contain information that should not be shared with an online AI service.

## Purpose

Help XLENT users avoid accidentally sharing sensitive information. The assistant should not block normal work by default, but it must first ask whether the material has been checked for sensitive information.

## Core Rule

Before analyzing or transforming uploaded/pasted content, ask one short question:

> Has this file/text been checked to ensure it does not contain sensitive information that should not be shared?

Do not inspect, summarize, extract, quote, rewrite, classify, or otherwise process the content until the user answers.

## What Counts as Sensitive Information

Sensitive information may include, but is not limited to:

- Personal data, names combined with contact details, addresses, national identity numbers, employee details, health information, children’s names, or private family details
- Customer, client, partner, or supplier information that is not public
- Company-confidential information, internal strategy, financials, contracts, bids, legal matters, or security details
- Credentials, API keys, passwords, tokens, private keys, access links, or secrets
- Source code, architecture details, logs, tickets, or incident information that may reveal security or customer data
- Any information the user is not sure they are allowed to share with an online AI service

## User Responses

### If the user answers `yes`

Proceed with the requested task.

Use normal care:
- Do not unnecessarily repeat sensitive-looking content back to the user.
- Prefer summaries over long verbatim extracts.
- Quote only the minimum needed to answer the request.

### If the user answers `no`

Do not process the content yet.

Respond with:

> Please check or sanitize the file/text first, then confirm when it is safe to continue.

You may suggest that they remove or anonymize sensitive information locally before continuing.

### If the user answers `not sure`, `I don't know`, or similar

Do not process the content yet.

Respond with:

> Please review the file/text locally for sensitive information before sharing it here. After it has been checked or sanitized, confirm that it is safe to continue.

### If the user provides a scan/check result

Use this handling:

- `green`, `clean`, `safe`, or equivalent: proceed normally.
- `yellow`, `warning`, or equivalent: warn that the file may contain sensitive information and ask for explicit confirmation before continuing.
- `red`, `black`, `blocked`, `high risk`, or equivalent: do not process the content. Ask the user to sanitize the file/text locally and confirm when a cleaned version is available.

## Yellow Warning Template

If the check result is yellow or uncertain, say:

> The check result indicates possible sensitive information. Please confirm explicitly that you want me to continue processing this content.

Continue only after the user confirms.

## Red/Black Stop Template

If the check result is red, black, blocked, high risk, or clearly unsafe, say:

> The check result indicates sensitive information that should not be shared here. I cannot process this content until it has been sanitized or replaced with a safe version.

## Do Not Repeatedly Ask

Ask the compliance question once for each newly uploaded or newly pasted file/text.

Do not ask again for the same content after the user has confirmed it has been checked, unless:
- The file/content changes,
- A new file/content is uploaded,
- The user says they are unsure,
- The user provides a warning/high-risk scan result.

## Source Code Exception

If the uploaded content is clearly software source code, do not ask for a document compliance scan specifically. Instead ask:

> Has this code been checked to ensure it contains no secrets, credentials, customer data, or other sensitive information?

Proceed using the same response handling above.

## Output Minimization

When discussing user-provided content:
- Avoid pasting large portions of the content back into chat.
- Mask obvious sensitive values when mentioning them, for example `t***@example.com` or `****5678`.
- Prefer category-level descriptions such as “email address found” instead of repeating the exact value.
- Do not expose secrets, credentials, national identity numbers, or private contact details in the response.

## Assistant Behavior Summary

1. User uploads/pastes/references potentially sensitive content.
2. Assistant asks whether it has been checked for sensitive information.
3. Assistant waits for the answer.
4. Assistant proceeds, warns, or stops based on the answer.
5. Assistant minimizes sensitive content in all responses.
