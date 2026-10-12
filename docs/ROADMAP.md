# Implementation and expansion plan

## Architecture now

Browser → same-origin FastAPI API → SQLite.

Read-only discovery adapters normalize postings into one schema. Preference matching is deterministic and explainable. Evidence comes from user input, local document extraction or explicitly requested public GitHub metadata. Optional AI selects validated evidence IDs. The resume builder renders verified content into plain text, single-column DOCX and PDF. Application records freeze contact details, evidence, job content and resume hash at creation. A state machine separates drafts, approvals, browser handoffs, submissions and outcomes.

```text
needs_review --approve exact hash--> approved
      ^                                 |
      | edit invalidates approval       +--unsupported form--> needs_manual
      +---------------------------------+                          |
                                        +--atomic claim--> submitting
                                                                 |
                                     confirmed HTTP response ----+--> submitted
                                     timeout/crash/other ---------+--> unknown

approved / needs_manual / unknown --user confirms--> submitted_manual
submitted / submitted_manual --> interview --> offer / rejected / withdrawn
```

GET discovery calls have bounded retries and concurrency. Application POSTs do not retry. This sacrifices automatic recovery when the result is ambiguous to avoid accidentally submitting twice. The job description is never an instruction source. No CAPTCHA bypass or private-session scraping is implemented.

## Next increments, in order

1. **Measure quality before choosing a model.** Curate consented/anonymized job/resume pairs and evidence annotations. Compare Qwen3.5-35B-A3B, a larger Qwen model and other currently licensed candidates against the deterministic baseline. Measure evidence precision/recall, unsupported-claim rate, required-fact retention, reviewer edits, malformed-output rate, p50/p95 latency and cost per packet. Reject any model-generated content that cannot be tied to evidence. No model was run or benchmarked during initial implementation.
2. **Richer resume tailoring.** Extract structured experience, dates, project links and education; present extraction for user verification. Offer evidence-linked wording suggestions side by side with originals. Preserve titles, employers, dates, qualifications and measurable results. Treat suggestions as unverified until accepted; combine numeric/entity checks with human review rather than assuming semantic entailment is solved.
3. **More precise matching.** Canonical roles, seniority, work authorization, geography for remote roles, salary periods/currency normalization with dated exchange-rate provenance, source freshness and eligibility warnings. Do not infer protected traits from a resume or optimize matching on them.
4. **Broader discovery.** User-authorized job alerts/imports, company-to-ATS directory resolution, permitted search APIs and official job-platform partnerships. Add per-provider test fixtures and terms/version records. Do not claim to search every platform.
5. **Application automation.** Validate authorized employer sandboxes and full form schemas. Add permissioned browser-assisted form filling where permitted, handle uploads and explicit screening answers, pause for consent, sensitive questions and CAPTCHA. Store employer receipts and reconciliation results; never label a clicked button as successful submission.
6. **Reliable agent execution.** Persistent task queue, cancellable discovery/ranking runs, per-provider rate limits, daily search scheduling, metrics and structured redacted logs. Deduplicate across job boards with canonical URLs and company/requisition identity; reconcile closed postings. Add opt-in notification delivery with source-specific consent.
7. **Production hardening.** Resource-isolated parsers, encrypted backups and restore tests, retention/deletion UI, app data migrations, locked dependency audit, accessibility audit, structured endpoint health/evaluation tests, packaging and update process. For multi-user service, introduce authenticated sessions, tenant-scoped authorization, secret storage and audited deployment infrastructure first.

## Helpful product additions

- Application gap checklist: identify evidence missing for a requirement without inventing it.
- Resume fact ledger: show which source supports each bullet and what changed between versions.
- Response funnel: track replies and interviews by role/source/resume version without presenting correlations as causal improvements.
- Follow-up reminders, interview preparation drawn from the exact submitted packet, and duplicate/repost detection.
- Search budget: user-set daily limits for discovery, model spending and applications, with a pause/kill switch.

These are planned increments, not features the current UI silently simulates.
