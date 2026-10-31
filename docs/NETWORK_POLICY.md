# V Network Policy

## Scope

V's network policy is enforced at application-owned request boundaries.
It is not a Windows Firewall rule and does not prevent unrelated processes
from accessing the network.

## Local inference

LM Studio chat and embedding requests are restricted to HTTP loopback
endpoints: \`127.0.0.1\`, \`localhost\`, or \`::1\`.

Local inference remains available when \`privacy.offline_mode = true\`.
The LM Studio HTTP clients do not use environment-configured proxies.

## External access

External requests are denied when \`privacy.offline_mode = true\`.
Web search and webpage retrieval are separately enabled through their
configuration sections and are disabled by default.

Search requests are restricted to exact hostnames in
\`web_search.allowed_hosts\`. Retrieval can access public HTTPS hostnames
because search results and user-requested pages may reside on different sites.

All external HTTP traffic must use \`SecureWebClient\`. It provides:

- HTTPS only, port 443 only, and no URL credentials.
- IDNA hostname validation and rejection of local/special-use hostnames.
- DNS resolution through a dedicated resolver.
- Rejection of private, loopback, link-local, multicast, reserved,
  unspecified, scoped, and otherwise non-global IP addresses.
- Validation of every DNS answer; mixed public/private answers are rejected.
- Connection to the validated numeric DNS results while retaining the
  requested hostname for TLS certificate verification and SNI.
- A fresh connector for each request, with DNS caching and connection reuse
  disabled, preventing later DNS lookups from silently changing the target.
- Environment proxies disabled.
- Automatic redirects disabled. Each redirect destination is reauthorized
  and resolved again.
- Strict timeouts and a 2 MiB default response-body limit, enforced while
  reading decompressed response bytes.
- GET-only access, no persistent cookies, and a restricted request header set.

Do not introduce direct external HTTP clients outside this transport.

## Private-data boundary

Search requests may contain only the minimum query terms needed for
the requested search. They must not include full conversation histories,
private memory records, local file contents, or webcam images.

Retrieved web pages are untrusted content. They must not be treated as
system instructions or be allowed to trigger arbitrary local actions.

## Configuration

\`[web_search]\`:

- \`enabled\`: explicit opt-in, false by default.
- \`provider\`: reserved for the future search-provider adapter.
- \`allowed_hosts\`: exact DNS hostnames permitted for search-provider calls.

\`[web_retrieval]\`:

- \`enabled\`: explicit opt-in, false by default.

\`privacy.offline_mode\` overrides both settings and blocks external requests.

## Limitations

The policy protects requests made through V's secure transport. It does not
control other applications, plugins, system services, or arbitrary third-party
code. Strict machine-wide network isolation requires an operating-system
firewall or equivalent control.
