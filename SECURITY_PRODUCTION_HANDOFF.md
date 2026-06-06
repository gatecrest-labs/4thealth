# Production Security Handoff (OWASP Top 10)

Date: 2026-05-28
Scope: Flask dashboard and supporting frontend/API routes in this repository.
Goal: Convert current dev-friendly posture into production-safe defaults.

## How to use this document

1. Use the finding table to prioritize production fixes.
2. Copy the Copilot prompt for each finding when you are ready to implement.
3. Use the acceptance criteria to verify the fix is complete.
4. Keep this file updated as each item is closed.

## Findings and fixes

| ID | OWASP 2021 | Severity | Finding | Evidence | Production Fix Summary |
|---|---|---|---|---|---|
| F1 | A01 Broken Access Control / A05 Security Misconfiguration | High | Missing CSRF protection on cookie-authenticated state-changing routes | app/routes/admin_routes.py, app/routes/zone_routes.py, app/routes/hygiene_routes.py, app/routes/rule_review_routes.py, app/routes/map_routes.py, app/routes/device_review_routes.py, app/routes/api_routes.py | Add server-side CSRF protection for all POST/PUT/PATCH/DELETE routes and send token/header from frontend fetch calls and forms |
| F2 | A01 Broken Access Control / A05 Security Misconfiguration | High | Logout is a GET endpoint and can be CSRF-triggered | app/routes/auth_routes.py | Convert logout to POST only and protect with CSRF token |
| F3 | A02 Cryptographic Failures | High | Upstream TLS verification defaults are insecure (disabled) and warnings suppressed | app/config.py, app/fmg_client.py | Make certificate verification enabled by default, remove blanket warning suppression, and document trusted CA/cert workflow |
| F4 | A05 Security Misconfiguration | Medium | Raw exception messages are returned to clients | app/routes/api_routes.py, app/routes/hygiene_routes.py, app/routes/rule_review_routes.py, app/routes/device_review_routes.py, app/routes/zone_routes.py | Return generic client-safe errors, log internal details server-side with correlation IDs |
| F5 | A04 Insecure Design | Medium | File import path has no explicit upload size guard (CSV/XLSX) | app/routes/rule_review_routes.py | Enforce MAX_CONTENT_LENGTH, add file size/type validation, and fail fast on oversized uploads |
| F6 | A07 Identification and Authentication Failures | Medium | Password policy is minimal for local user creation | manage_users.py, app/auth.py | Enforce minimum length/complexity for local fallback users and reject weak passwords |
| F7 | A05 Security Misconfiguration | Medium | Missing common security headers | app/__init__.py, app/templates/base.html, app/templates/login.html | Add security headers in after_request middleware (CSP, HSTS in TLS, X-Frame-Options or frame-ancestors, X-Content-Type-Options, Referrer-Policy) |
| F8 | A07 Identification and Authentication Failures | Medium | users.json is currently tracked in git (bcrypt hashes still sensitive) | users.json | Remove tracked credentials file from git history going forward, keep runtime copy untracked, rotate credentials as needed |

## Recommended implementation order

1. F1 CSRF protection
2. F2 Logout POST + CSRF
3. F3 TLS verification defaults
4. F4 Safe error handling
5. F7 Security headers
6. F5 Upload limits
7. F6 Password policy
8. F8 Credential file hygiene

## Copilot implementation prompts

Use these prompts in sequence when moving to production.

### Prompt for F1: CSRF protection

Implement CSRF protection for this Flask app with minimal disruption.

Requirements:
- Use Flask-WTF CSRFProtect (or equivalent robust server-side CSRF middleware).
- Protect all state-changing endpoints (POST/PUT/PATCH/DELETE) including:
  - admin APIs
  - zone mutation APIs
  - refresh triggers
  - login/logout flow as applicable
- Ensure JSON fetch requests send CSRF token in a header.
- Add CSRF token injection strategy in templates so static JS can read/use it safely.
- Return consistent JSON errors for API CSRF failures and normal redirects/messages for HTML forms.
- Keep existing role-based decorators and behavior intact.

Deliverables:
- Updated backend initialization and route handling.
- Updated frontend fetch calls for state-changing requests.
- Brief note in README or production docs on CSRF behavior.

Acceptance checks:
- Same-site valid requests succeed.
- Cross-site forged requests fail with 400/403.
- No regressions for read-only GET APIs.

### Prompt for F2: Logout hardening

Harden logout endpoint.

Requirements:
- Change logout route from GET to POST only.
- Add CSRF protection to logout.
- Update UI links/buttons to submit POST safely.
- Preserve existing session clear and redirect behavior.

Acceptance checks:
- GET /logout returns 405 (or not found if redesigned).
- POST with valid CSRF logs user out.

### Prompt for F3: TLS verification defaults

Make upstream FortiManager TLS validation production-safe by default.

Requirements:
- Default FMG_VERIFY_SSL to true.
- Remove global suppression of urllib3 insecure request warnings.
- Keep an explicit opt-out for non-production troubleshooting only.
- Document how to trust internal CA/certificates.
- Ensure failure messages are actionable but do not leak secrets.

Acceptance checks:
- With invalid/untrusted cert, calls fail closed by default.
- With trusted cert chain, calls succeed.

### Prompt for F4: Safe error responses

Replace raw exception leakage with safe client responses.

Requirements:
- Do not return str(exc) to clients on 500 responses.
- Return generic message and correlation ID to client.
- Log full exception and correlation ID server-side.
- Keep existing status code semantics where possible.

Acceptance checks:
- API responses no longer expose stack/internal host details.
- Logs retain enough data for debugging.

### Prompt for F5: Upload limits

Harden file import endpoints against oversized uploads and parser abuse.

Requirements:
- Set MAX_CONTENT_LENGTH in Flask config.
- Validate extension and MIME type before parsing.
- Add clear error response for too-large payloads (413).
- Keep current CSV/XLSX feature behavior for normal files.

Acceptance checks:
- Oversized upload rejected quickly.
- Valid small CSV/XLSX continues to work.

### Prompt for F6: Password policy

Add production-safe password policy for local fallback accounts.

Requirements:
- Enforce minimum length and complexity in manage_users workflow and shared auth helper.
- Provide clear validation message.
- Keep bcrypt hashing and current role model unchanged.

Acceptance checks:
- Weak passwords rejected.
- Strong passwords accepted.

### Prompt for F7: Security headers

Add baseline security headers through Flask middleware.

Requirements:
- Add headers in an after_request hook:
  - Content-Security-Policy (start strict but compatible with current inline scripts, then iterate)
  - X-Content-Type-Options: nosniff
  - Referrer-Policy: strict-origin-when-cross-origin (or stricter)
  - X-Frame-Options: DENY (or CSP frame-ancestors equivalent)
  - Strict-Transport-Security in HTTPS deployments
- Do not break current pages and JS behavior.

Acceptance checks:
- Headers present on HTML and API responses.
- App pages still function correctly.

### Prompt for F8: Credentials file hygiene

Fix tracked local credential storage for production posture.

Requirements:
- Ensure users.json is not tracked in git going forward.
- Keep a safe template/example file if needed.
- Update docs for first-run bootstrap user creation.
- Provide migration note for existing deployments.

Acceptance checks:
- git ls-files does not include users.json in future commits.
- App still boots and can create users in runtime environment.

## Production verification checklist

- CSRF enforced on every state-changing endpoint.
- Logout uses POST + CSRF.
- FMG TLS verification defaults to enabled.
- No raw exception text returned to clients.
- Upload size limits enforced and tested.
- Local password policy enforced.
- Security headers present on responses.
- No credential-bearing runtime files are tracked in git.

## Notes for dev vs prod

Current dev behavior can remain flexible, but production profile should be fail-closed.
If dual-mode behavior is needed, gate weaker behavior behind explicit environment flags and keep secure defaults for production.