# ADR 0009 · The first call checks the versions

**Status:** accepted, 2026-10-10.

**Context.** Three things update separately: the server process, the layer file it loaded, and the skill uploaded to the client. On 10. Oct 2026 all three drifted in one afternoon: the layer moved to a new version while Claude Desktop kept running the server it had started earlier, and the uploaded skill predated two changes. Nothing reported it; the agent simply answered with what it had ("I can only see the current definition, not what changed"), which is the expensive way to find out.

**Decision.** `whoami`, the skill's first call, carries a `health` block. The skill states its own version in its text and passes it (`whoami(skill_version=...)`); `metrics.yaml` names the version it expects (`skill_expected`). The server records what it loaded at start (the layer version and the timestamps of `metrics.yaml`, `server.py`, `prices.yaml`) and compares them with the files on disk. Each check returns a status and, when it is not current, the one-line fix: re-upload the skill, or restart the client.

**Consequences.** A stale install is reported in the first call of a conversation, and the skill tells the user before answering. A client with no skill at all is reported as `undeclared`, because the server cannot tell an old upload from none. Releasing a skill change now means bumping `skill_expected` with it. Checked in `tests/smoke.py` (five cases).
