# ADR 0002 · Identity comes from the server's config until a real IdP is in front

**Status:** accepted, 2026-10-07

**Context.** A local stdio MCP server in Claude Desktop runs as the laptop user. There is no login, no token, no groups. A `set_role` tool would let any user escalate. The real design is a remote MCP connector behind OIDC with device trust, and warehouse policies keyed on the token's user.

**Decision.** The principal and role are read from environment variables set in the Desktop config; the demo runs one server entry per role. `whoami` reports the principal, the role and the sentence "role from server config; production: OIDC subject". No tool can change the role.

**Consequences.** The demo is honest about what it fakes. Row access (external sees its own practice) and grain gating (member grain needs analyst) are enforced in the server from the configured role, so the enforcement code is the same code that will read a token later. Tier 2 swaps the source of the principal, not the checks.

**Amended 2026-10-07, scope is explicit.** The first version read `PRACTICE_ID` only for the external role; an unset scope meant "all" for everyone else, so an admin or CSM entry with no scope saw every practice by omission. That is fail-open: absence of a grant behaved as a grant. Now `PRACTICE_ID` is one of a practice number (one practice, any role) or the literal `all` (a deliberate grant, written in the config), and an unset scope makes every data tool refuse with `scope policy: no practice scope configured`. `whoami` reports the scope and what it means. The Desktop entries for csm and admin carry `PRACTICE_ID: all` so the grant is visible in the config, which is the only place a grant should live until Tier 2 reads it from the token.
