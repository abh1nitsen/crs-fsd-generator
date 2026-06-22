---
title: CRS Blueprint
emoji: "\U0001F4CB"
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 5.33.0
app_file: app.py
pinned: true
license: mit
hf_oauth: true
---

# CRS Blueprint

**Turn CRS obligations into implementation-ready requirements.**

A structured starting point for data mapping, transformation rules, controls, testing and your CRS Functional Specification Document.

## What it does

Select your jurisdiction and institution type, identify where the relevant data lives, and generate a structured Blueprint covering:

- Upstream data requirements mapped to source-system categories and vendor-aware logical hints
- System-to-field matrix: likely source, authoritative source, fallback, unacceptable source and control
- Implementation field catalogue: XML element, requirement state, source of record, logical aliases, transformation, validation and missing-data action
- Derived rules for reportability, aggregation, currency conversion, Passive NFE look-through and income aggregation
- Exception and remediation register for missing TIN, invalid TIN, unreliable self-certification, Passive NFE gaps, reconciliation breaks and duplicates
- Control framework, technology build backlog, operations runbook and UAT scenarios with input data and acceptance criteria
- Official-source health plan and verification tasks that say what to check, where to check, what evidence to retain and what technology must not hard-code
- Evidence and source-layer legends so users can distinguish global CRS baseline, jurisdiction overlays, system hints and user inputs
- Material jurisdiction-specific implementation differences for enriched jurisdictions
- TIN, nil-reporting and self-certification overlay hooks for the 11 enriched jurisdictions
- Action-oriented executive overview that identifies workstreams, owners, build guardrails and evidence expected before implementation lock
- Responsive UI rendering for wide implementation tables without clipping
- Collapsed generation diagnostics for internal technical quality checks
- A simple static next-step CTA linking to Abhinit Sen on LinkedIn for a Blueprint Review

## Coverage

Thirty jurisdictions are pre-loaded in the knowledge base. Starred jurisdictions include enhanced local CRS, FATCA, TIN and submission guidance. Live-source checks are experimental and generation continues from the curated knowledge base if an authority website is unavailable.

The implementation engine uses deterministic CRS templates so a useful Blueprint is still generated even if all LLM providers are unavailable. Vendor names such as Murex, Avaloq, Temenos, Flexcube, Finacle, Calypso/Adenza, Fenergo, Salesforce and Dynamics are treated as logical source-system hints only; client-specific physical field names must be confirmed through the client's data dictionary and source-system owners.

## KB refresh approach

CRS Blueprint uses curated jurisdiction files and registered official-source metadata during generation. The app does not automatically rewrite filing deadlines, TIN handling, schema versions or other compliance facts from live webpages during a user run. Source freshness is shown to users, and stale/changed sources should become verification tasks before curated KB updates are released.

## Review note

Use the generated Blueprint as an implementation starting point. Verify jurisdiction-specific requirements against official guidance before use.

Built by [Abhinit Sen](https://www.linkedin.com/in/abhinit-sen-63443015/).


## Current implementation-intelligence release

- Adds dedicated jurisdiction-specific TIN/local identifier guidance.
- Uses registered official-source metadata, curated KB freshness labels and source-health checks instead of generic web search or runtime fact rewrites.
- Includes vendor-aware system profiles as logical mapping hints only.
- Provides DOCX Blueprint and XLSX implementation workbook downloads.
- Keeps internal generation diagnostics collapsed in the UI and out of the user-facing DOCX.
