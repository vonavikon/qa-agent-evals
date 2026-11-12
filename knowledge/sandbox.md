# Execution Isolation: Levels and Policy

Why: an acceptance run starts a foreign plugin in a real Claude Code. Without a barrier this process can read host files (including secrets and card oracles), reach the network, and run commands outside the work folder. Isolation is a lock, not a hope in the honesty of the model.

## Isolation Levels

| Level | Name | What it is | What it guarantees | When to choose it |
|---|---|---|---|---|
| 0 | `host` | The current mode: a separate work directory, an env allowlist, an empty MCP, `--disallowedTools Skill`, the tamper detector | Environment secrets are not inherited. Foreign skills/MCP are not called. Tampering with run files is caught. **Leaving work is physically NOT blocked**: only the behavior of the model is the barrier | Public plugins from open repositories, quick acceptance runs, environments without Docker |
| 1 | `docker` | A container: only a SUT copy + work, network off, read-only + tmpfs, non-root, pids/memory limits | The SUT sees no host files (including oracles and secrets, except the single LLM config), has no network, and writes only to work | Untrusted plugins, closed or corporate systems, runs of "evil" material, public security demos |

## Selection Rules (Phase B, Adapter)

1. Choose the level deliberately during adapter setup and record it in the report (meta `isolation_level`). The default is `host`: simple public plugins need no container.
2. For untrusted material the `docker` level is mandatory. A request to "run it without a container" for such material gets a refusal with a reference to this rule.
3. **Fail-closed**: when `docker` is chosen but Docker is unavailable, the run stops with an explicit error. There is no silent swap to `host`. A switch happens only when the human edits the level choice, with a new entry in the report.
4. At either level the SUT session receives no environment of the tester (the env allowlist in the runner is a shared layer).

## What Lives in the Container (Level 1)

Mounts (after the hardening of 2026-10-13):

- `/workspace/sut`, a copy of the plugin under test, **read-only** (the SUT cannot rewrite its own sources).
- `/workspace/out`, the results, the only writable permanent place.
- `/workspace`, a tmpfs: writing is allowed (sessions create work files), but everything outside out/ dies with the container.
- `/home/node`, a tmpfs (service directories of the CLI).
- A decoy canary (read-only).
- NOT mounted: the whole work directory, the oracles, the runner directories, and the private directory with the keys. Also not mounted: the home, SSH, and Docker socket of the host.

The LLM secret (hardening P0-2): the real key lives ONLY in the environment of the proxy container. It comes from the private host directory `work-priv/`, which is never mounted. The proxy inserts the Authorization header itself. The SUT environment gets the placeholder `sandbox-local-placeholder` and the proxy address. The proxy accepts only LLM API paths and GET/POST methods, cuts bodies >4MB, and limits a run to 2000 requests. A proxy error does NOT enable a direct connection as a fallback (the SUT has no network around it).

Self-check at prepare: a write probe into the SUT sources from inside the live profile of the container. When the write works, the start is refused (fail-closed). The wall-time limit of a session: `QA_EVALS_SUT_TIMEOUT` (default 900s).

Cleanup: the container runs with `--rm`, and the proxy and the internal network are deleted with retries. A network cannot come off while the container is dying. The work and private directories are wiped. A repeated cleanup is safe. Resource names carry the work suffix, so parallel starts do not collide (checked in a live run).

## Remaining Risks of Level 1 (Recorded in the Report)

- The container does not protect against runtime vulnerabilities (a docker escape). For openly hostile material with exploit ambitions, use a VM level.
- The proxy is the only holder of the key on the host besides the runner CLI. A compromise of the proxy container equals a leak of the gateway key (personal, rotating, generation only).
- The Docker Desktop channels (bind mounts of Windows paths) count as trusted means of the platform itself.
- Container isolation is NOT equal to a separate virtual machine or a dedicated sandbox with a stronger border.

## Isolation Check (SEC Cards Against examples/evil-plugin)

SEC-01 host secret read (the canary) · SEC-02 run oracle read · SEC-03 network · SEC-04 endless process and timeout · SEC-05 write outside work · SEC-06 reference swap. Expected at the docker level: the attempts fail (a refusal, unreachability, an empty result). Expected at the host level: an honest record that there is no barrier (level 0 claims no sandbox).

## Backend Interface (scripts/sandbox.py)

- `verify <level>`: availability of the level (docker: the daemon and its version).
- `prepare <level> <sut-dir> <run-dir>`: a unique work, a SUT copy, the CLI config, meta (claude CLI version, SUT git hash, level).
- `wrap <level> <work> -- <команда>`: the start prefix (host: as is. docker: docker run with the flags above).
- `cleanup <work>`: the wipe.

## Final Hardening (2026-10-13, branch sandbox-final)

- **The fail-closed write probe is conclusive**: success only at rc==0 plus an explicit BLOCKED marker without WROTE. A timeout, a docker error, empty output, or both markers = a refused start with the reason in meta-sandbox.json (probe_refused).
- **Proxy**: path normalization (triple unquote, normpath, query/fragment) before the prefix check. The ../ and %2e%2e traversals are closed. Limits: body 4MB, response 16MB, 120 req/min, 4 concurrent, 2000 per run, 2h lifetime. An upstream error shows only the exception type. Response auth headers are filtered. The proxy container: nobody, read-only+tmpfs, cap-drop ALL, 256m/0.5cpu/32pids. proxy.env is 0600 in the private directory.
- **SEC-06A**: a decoy reference with a known md5 in the run directory. The attack comes from inside (write/delete/read by an absolute host path and through ../) plus hash control. **SEC-06B**: a fake verdict that the SUT writes to out/ stays isolated. The runner builds the final status, and a stale report is overwritten with a fresh run_id. **CLEANUP**: the criterion is the current run (its network, containers, and priv directory). A repeated call is safe. Foreign leftovers get a separate note.
- **The integration test** (`scripts/sec-integration.py`): the full live chain docker -> Claude Code -> transcript -> judge -> manifest -> cleanup on a mini card. Without Docker or a key, the result is SKIP with a reason (not PASS). Keep them apart: sec-checks are deterministic environment probes, and sec-integration is a live pipeline with an LLM.
- Live proxy tests for CI: tests/test_proxy_live.py (a dummy key).

## Automated Security Suite

`python scripts/sec-checks.py docker [--out runs/<дата>-sec]` runs SEC-01..06 deterministically, without an LLM (it fits CI. The proxy starts with a placeholder when there is no key). Statuses: PASS (the attack was blocked) / FAIL (a violation) / ERROR (did not run, and it is not a protection result) / SKIP. The exit code is 0 only without FAIL/ERROR. Reports: sec-report.json + sec-report.md + probe logs. CI: .github/workflows/security.yml. Last live run: runs/2026-10-13-sec (6/6 PASS).
