# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest (main) | Yes |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, report them via **GitHub's private vulnerability reporting**:
1. Go to the [Security tab](../../security/advisories/new) of this repository
2. Click "Report a vulnerability"
3. Fill in the details

You can expect a response within **48 hours** and a fix or mitigation within **7 days** for critical issues.

## Scope

The following are in scope:
- SQL injection or data exposure via API endpoints
- Authentication/authorization bypasses (`RAGAS_API_KEY` handling)
- Secrets or credentials leaked in responses or logs
- Dependency vulnerabilities with a known exploit

## Out of Scope

- Denial of service via large payloads (no rate limiting SLA)
- Issues requiring physical access to the server
