# Jon — a private job application workspace

A working local-first application for collecting job opportunities, selecting evidence-backed resume content, reviewing application packets, and tracking outcomes. Python 3.12+; FastAPI; SQLite; vanilla HTML/CSS/JavaScript. No frontend build step, tracking scripts, or CDN dependency.

**Status: personal-use MVP, not an independently audited production release.** This version does not claim universal job-board coverage, autonomous browser applications, or improved shortlist probabilities. Its complete usable path is discovery/import → verified evidence → draft → review → employer-form handoff → recorded outcome → CSV export. A limited employer-authorized Greenhouse submission adapter is also implemented and contract-tested.

## Run on Windows

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.lock
.venv/Scripts/python.exe run.py
```

Open http://127.0.0.1:8765. Keep the terminal running. On this workspace the virtual environment is already installed. `requirements.lock` captures the environment that passed the tests; `requirements.txt` contains upgrade ranges. Rebuild the lock and rerun checks deliberately when upgrading dependencies.

The app binds only to loopback. Run one process/worker. Do not expose it through a public tunnel or change the bind address: it has a local-session security boundary, not multi-user authentication. If a restricted Windows execution environment hangs while creating an asyncio socket, allow the local server/tests to run with normal local socket access; do not disable TLS verification or firewall protections globally.

## First session

1. Save your name, contact details, target roles, locations, job types, real skills, salary minimum and target companies. Companies are an allowlist when provided. Role matching uses phrases, so include relevant title variants.
2. Upload a resume or add evidence entries. PDF, DOCX, TXT and Markdown extraction is supported; scanned PDFs need pasted text. Split a long resume into individual roles, projects and education records, retaining dates and context. Verify each entry. Public GitHub import reads metadata from up to 30 recent repositories, skips forks/archives and never assumes authorship; review your specific contribution.
3. Add company boards using their provider and board slug, then use **Discover jobs**. For other platforms, import the listing URL and full description. There is no automatic company-to-board lookup yet.
4. Open a job and prepare its resume. Review, edit if needed, download PDF/DOCX/TXT, and approve the saved version. Edits invalidate approval. Changing your profile does not silently change previous application snapshots.
5. Use the employer form for manual handoff. Record submission only after the employer confirms it, then track interview, offer, rejection or withdrawal. Export the application tracker as an Excel-compatible CSV.

No sample jobs or candidate identity are inserted into your personal database.

## Open-source model configuration

The initial configurable model is **Qwen/Qwen3.5-35B-A3B**, an Apache-2.0 open-weight model. The [official model card](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) documents 35B total parameters / 3B active and compatible serving options. It is an efficiency-oriented candidate, not a proven universal best. Evaluate the larger [Qwen3.5-397B-A17B](https://huggingface.co/Qwen/Qwen3.5-397B-A17B) only if hosting cost and latency permit. Sparse active parameters do not mean the full weights fit a small GPU.

Use any compatible chat-completions server that supports JSON output:

```powershell
$env:JON_MODEL_URL = 'http://127.0.0.1:8000/v1'
$env:JON_MODEL = 'Qwen/Qwen3.5-35B-A3B'
# If your server requires authentication, set JON_MODEL_KEY in the environment.
.venv/Scripts/python.exe run.py
```

Remote endpoints require HTTPS; plain HTTP is allowed only for loopback. Credentials stay in the server environment, not browser storage. `.env.example` documents all configuration; `.env` is **not** loaded automatically.

The model is optional and not installed or downloaded by this project. In model-assisted mode, the user explicitly selects a checkbox before the job description and verified evidence are sent to the configured endpoint. Contact fields are not separately included, but evidence text may itself contain personal information. Provider privacy/retention terms still apply.

**Current AI boundary:** select/order existing evidence IDs, with strict validation. The renderer copies the corresponding verified text; it ignores invented model prose. Wording changes can be made in the review editor. Generative rewriting, claim entailment checks, semantic matching and comparative model evaluations are future work. No live inference endpoint was available during implementation; model contract behavior is tested with mocked responses.

## Connector support

| Source | Discovery | Submission |
| --- | --- | --- |
| Greenhouse | Public company board API | Limited direct adapter with employer credentials; otherwise manual |
| Lever | Public company postings API | Manual employer-form handoff |
| Ashby | Public company posting API | Manual employer-form handoff |
| LinkedIn, Naukri, Indeed, Wellfound, Internshala, other sites | User imports URL + description | Manual employer-form handoff |
| GitHub | Public repository metadata | Evidence only |

[LinkedIn prohibits third-party automated activity](https://www.linkedin.com/help/linkedin/answer/a1341543). [Lever submission requires an employer API key](https://github.com/lever/postings-api#apply-to-a-job-posting). [Greenhouse documents authenticated application submission and client-side required-field validation](https://docs.greenhouse.io/job-board.html). [Ashby documents its public posting API](https://developers.ashbyhq.com/docs/public-job-posting-api). Adding a new adapter requires verifying its current permitted integration path.

Job records deduplicate by provider + board + posting ID, or exact imported URL. Cross-platform copies and tracking-parameter URL variants are not merged. Last-seen timestamps are shown; disappearance from a feed is not yet interpreted as closure. Salary comparisons require annual figures in the same currency; missing/non-comparable salary is explicitly unknown. No exchange-rate or location eligibility assumptions are made.

### Optional Greenhouse direct submission

This usually is not available to an ordinary applicant. Only configure credentials for an employer/board that has authorized this integration:

```powershell
# Set a JSON mapping of board slug to employer-issued Job Board API key:
# $env:JON_GREENHOUSE_KEYS = '{"authorized-board":"credential"}'
```

The adapter refetches job questions and fails closed when it cannot inspect them, encounters required fields outside its supported contact/resume fields, or sees consent/demographic sections. Those cases use the employer form. It requires an approved immutable resume/profile snapshot. It atomically claims the application before sending one POST. Unknown responses, timeouts and interrupted requests stay **unknown** and are never retried automatically. Successful HTTP acknowledgement is recorded separately from manual user confirmation. There is no real employer submission in the test suite and none was made during development.

## Data and security

SQLite stores the profile, jobs, evidence, resume snapshots and audit events in `data/jon.sqlite3`. Original upload bytes are not saved. Data is not encrypted by this app; use device encryption and protect your user account. External network calls are made only for discovery, explicit GitHub import, explicitly selected model inference, or approved direct submission. No analytics are sent.

To back up, stop the app and copy the **entire data directory** to encrypted storage. For deletion, stop the app and delete the data directory and any exports/backups you created. Removing an evidence entry does not remove it from historical application snapshots. Git ignores data, secrets, virtual environments and test artifacts. See [SECURITY.md](SECURITY.md) for the trust model and known limits.

## Verification

```powershell
New-Item -ItemType Directory -Force test-results
.venv/Scripts/python.exe -m pytest -q --basetemp=test-results/tests
node --check static/app.js
# Optional live read-only provider check (network required):
.venv/Scripts/python.exe -m tests.live_discovery
# Optional separate browser-test workspace, port 8766:
.venv/Scripts/python.exe -m tests.preview
```

Tests cover state transitions, stale approvals, frozen evidence/profile snapshots, concurrency, ambiguous network outcomes, model response validation, source normalization, salary/currency handling, unsafe URLs, cross-origin access, CSV injection and document extraction/exports. Manual browser verification covers onboarding through approval/handoff using synthetic data in `test-results/ui`, separate from your personal workspace.

## Before a production launch

See [docs/ROADMAP.md](docs/ROADMAP.md). Principal gaps: independently reviewed security and dependencies, isolated document parsing with CPU/memory budgets, model evaluation on representative resumes/jobs, validated live submission contracts with authorized test employers, authenticated accounts if exposed beyond loopback, observability, retention controls, migration/version tooling, and permissioned integrations for broader coverage. The application is designed to preserve truthful state while those integrations are added, not to pretend they already exist.
