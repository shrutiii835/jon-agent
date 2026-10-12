# Security model and limits

## Intended deployment

One trusted user, one process, loopback only. Anyone with access to the OS account or unrestricted access to its loopback interface can obtain the local session token. This is not remote authentication or isolation from malicious local processes. The local SQLite database is plaintext. Do not deploy this personal version as a hosted service.

## Implemented boundaries

- Host allowlist and same-origin checks; cross-site Fetch Metadata blocked. A per-process random token is required for API reads, writes and downloads. Session bootstrap returns it only through the local origin. No wildcard CORS.
- Self-only CSP, no remote scripts, no inline execution, frame embedding blocked, no referrer forwarding. All job/evidence/model text is escaped in the UI. SQL uses bound parameters.
- Discovery and GitHub calls use constructed URLs on fixed hosts; untrusted job URLs are never fetched server-side. Imported links require public HTTPS and no credentials. Redirects are disabled for provider/model/submission requests.
- Model endpoint is set by the trusted operator, never by a job listing. Remote inference requires TLS. Model output can only select known evidence IDs. It cannot invoke tools or write candidate claims.
- Resume uploads are limited to 5 MB and validated by supported parser; PDF page/encryption checks and DOCX expanded-size/entry limits apply. No macros or uploaded code are executed. No uploaded files are served back by arbitrary path.
- Exact resume and snapshot hashes tie approval to content. Changes revoke approval. Submission atomically claims an approved record; no automatic POST retries. Crash recovery marks in-flight sends unknown.
- CSV fields beginning with spreadsheet formula prefixes are escaped. Provider exception bodies and credentials are not exposed to the UI. Access logs are disabled by the default launcher.

## Remaining risks / pre-production work

- PDF/DOCX parsers run in a worker thread, not a sandboxed subprocess. Crafted decompression or parser workloads can still exhaust memory/CPU. Add OS-level resource limits and parser subprocess isolation before accepting untrusted uploads at scale. Request-size protection is currently based on Content-Length plus the upload read limit; streaming request bodies need ASGI-level enforcement for public deployments.
- No encryption-at-rest, account login, MFA, multi-tenant separation, secrets vault, database migration system, audit tamper evidence, external monitoring or automatic backup. Use device encryption now; add these features for hosted use.
- Fixed provider domains reduce SSRF exposure, but this is not a general-purpose hardened crawler. Do not extend URL fetching to arbitrary targets without DNS/IP enforcement, redirect validation and egress controls.
- Public repository metadata does not prove authorship. Verification is a user attestation, not independent fact-checking. Editing a draft can add claims; the user must review them before approval.
- A 200 provider acknowledgement is evidence of API acceptance, not guaranteed employer-side completeness, delivery, interview selection or hiring. Additional employer-specific checks are required before production submission.
- Posted jobs can become stale and cross-postings can create duplicate applications. Deduplication is provider-scoped, not entity resolution across platforms.
- Test contracts are not a substitute for live authorized employer integration tests. Keep network submission disabled until those have passed for the target board.

Report issues privately to the repository owner. Do not include real resumes, access tokens or applicant details in public issue reports.
