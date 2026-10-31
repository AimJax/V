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

External requests are denied when either condition is true:

- \`privacy.offline_mode = true\`
- \`web_search.enabled = false\`

External requests also remain denied when web search is enabled. The current
implementation deliberately fails closed until V has a hardened outbound
transport. Enabling the setting alone does not authorize or send requests.

Before external networking is implemented, the transport must provide:

- An explicit allowlist for configured search-provider endpoints.
- Safe DNS resolution and rejection of loopback, private, link-local,
  multicast, reserved, and otherwise non-public destination addresses.
- Connection pinning to the validated address to prevent DNS rebinding.
- TLS hostname verification against the requested hostname.
- Redirect following disabled by default; every redirect must be separately
  authorized and revalidated.
- Strict connection/read timeouts and response-size limits.
- No environment proxy inheritance.

Every future external HTTP client must enforce the policy and use that
transport. Do not add a direct HTTP client that bypasses these controls.

## Private-data boundary

Search requests may contain only the minimum query terms needed for
the requested search. They must not include full conversation histories,
private memory records, local file contents, or webcam images.

Retrieved web pages are untrusted content. They must not be treated as
system instructions or be allowed to trigger arbitrary local actions.

## Limitations

This application-level policy does not control other applications, plugins,
system services, or arbitrary third-party code. Strict machine-wide network
isolation requires an operating-system firewall or equivalent control.
