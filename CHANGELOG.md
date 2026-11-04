# Changelog

All notable changes to RepoHunter are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); pre-1.0 releases are date-based.

## [Unreleased]
### Added
- MCP `evaluate_repo` now returns `signals`: a keyword scan of release notes from the last 90 days
  and published security advisories from the last 180 days. A privacy or security incident (data
  leaving the machine without consent, exfiltration, leaked secrets, or a published advisory) caps
  a GO verdict at MAYBE and is reported with the release tag, date and a 200-character excerpt.
  Signals never raise a verdict. A failed fetch is reported as not checked, never as clean. Found
  on 2026-11-04 when claude-mem scored GO while its own v15.8.3 notes described uploading prompts
  without asking. Advisory-id mentions (CVE/GHSA) are informational only. Release text is untrusted
  and the untrusted-content note now covers it. Scanned text is capped at 20,000 characters and
  the patterns are bounded, so a hostile release body cannot cause regex backtracking (an earlier
  draft was quadratic; regression-tested).
- MCP `evaluate_repo` reports `resolved_name` when a repo was renamed or moved (case-only
  differences are ignored), keeping the requested name as the evidence endpoint, and `fork_of`
  for forks.
- MCP relevance now counts README keyword hits (4 points each, capped at 24, description hits stay
  at 12). `evaluate_repo` only; `find_repos` does not fetch READMEs.

### Changed
- Words that describe the asker rather than the domain ("user", "wanting", "solo", "consulting",
  and similar) are no longer relevance keywords.
- The evidence limit now reads "Code-level security vulnerabilities ... are not checked", since
  release notes and advisories are now scanned.

### Fixed
- MCP `find_repos`: spam and SEO repos with no query overlap in their own metadata could outrank
  relevant repos (a 150-star SQL dump beat the actual Wi-Fi design app for "wifi site survey
  design", measured 2026-10-31). Every candidate now must overlap the query in its
  name/description/topics, and results rank by the heuristic overall score, not raw star order
- MCP `find_repos` fallback picked the two *longest* query words, dropping short domain terms
  ("rf", "wifi", "wlan") and drifting off-topic or returning nothing ("wlan planner heatmap" ->
  "planner heatmap" -> zero results). It now prefers domain terms ("rf wifi", "wlan heatmap")
- MCP relevance (`evaluate_repo`, `find_repos`) had a free 20-point base and matched junk keywords
  ("maybe", "skip", "design"), so unrelated repos read as relevant. Relevance is now 12 x real
  keyword hits, with stop/generic words dropped and domain acronyms (rf, bom, poe, ...) kept
- Keyword matching: "Wi-Fi" now matches the keyword "wifi" (alnum-squash), while short acronyms
  like "rf" stay word-boundary-only and no longer match inside words like "performance"
- MCP search page size 8 -> 15 for recall before the overlap filter

### Added
- 7 regression tests in `test_repohunter_mcp.py`, one per failure mode above (118 tests total);
  evidence `formula_version` is now `repohunter-mcp-0.2`

- Soak-week hardening + full docs (see `SOAK_WEEK.md`)
- Landing-page guided walkthrough + larger hero logo
- Green **"compute saved ≈ energy ≈ CO₂ avoided"** estimate on adoptions _(planned)_
- Port the visual store (walkthrough + Map) fully into the standalone build

## [0.2.1] — 2026-10-04
### Fixed
- Claude Code plugin started its MCP server from an unpublished PyPI name, so it failed for
  every user and the name could have been squatted; it now starts from this tagged release (#26)
- Every documented install command is pinned to a release tag instead of the main branch
- `scan` says "repo not found" instead of guessing a rate limit (#23)
- `evaluate` without an LLM: verdict from the scores, not a hard-coded MAYBE, and no stale cache (#24)
- An unidentified license is never a GO in the MCP server and the badge service (#25)
- README and SECURITY.md name a human owner and describe the safety scan as unvalidated (#27)
### Added
- `scripts/verify_install.py`: tests every published install method in a sandbox (#26)

## [0.2.0] — 2026-09-22
### Added
- **License/resale-risk gate** — every dossier and `evaluate` now carries a license read
  (permissive / weak or strong copyleft / source-available), so a GPL or BUSL dependency doesn't
  quietly end up inside something you sell
- **Named project profiles** — `config.json` can define several projects; `--profile <name>` (or
  `REPOHUNTER_PROFILE`) switches between them, `repohunter profiles` lists what's configured. One
  install, several lenses.
- **Agent-config path walking** — `scan` now reads `.claude/`, `.agents/`, `skills/`, and similar
  nested agent-instruction directories, not just top-level files; a skill pack shipping 40 command
  files used to report "2 files scanned"
- **`repohunter-agent`** — authenticated, read-only A2A-style peer adapter exposing RepoHunter's
  skills to other agents
- **`repohunter-artifacts`** — artifact-level (not repo-level) evaluation: cost/blast-radius/safety
  of a skill, command, hook, or MCP server an agent actually loads
- Two discovery radars: YouTube channel polling, skillselion.com structured-data polling
- **Claude Code plugin** — this repo is its own marketplace (`/plugin install repohunter`); ships
  the MCP server and a new `repo-intake` skill (scan → triage → evaluate → fit-map) together
- **MCP evidence provenance** — every MCP skill result now carries a machine-readable block
  (endpoint, timestamp, derivation, limits) — see [`MCP-INSTALL.md`](MCP-INSTALL.md)
- Cloudflare Pages deploy is now codified (`wrangler.toml`, a deploy workflow, a post-deploy smoke
  check against the live site) instead of dashboard-only configuration
- Install via `uvx`/`uv tool install`/`pipx`, no clone required — see the Quickstart

### Fixed
- **Silent LLM failures** — a bad key, dead model ID, network failure, and rate limit used to all
  return `""` indistinguishably; failures are now logged with backend + reason. Added an optional
  app-level backend fallback (`llm.fallback` in `config.json`)
- **Concurrency-safe store I/O** — two `evaluate`/`plan`/`decide`/`ingest-video` runs at once could
  silently overwrite each other's store writes; now advisory-locked with atomic write-then-rename
- **Scan false positives** — API-documentation tables and policy/disclosure prose (e.g. a
  `SECURITY.md` describing an attack rather than instructing one) no longer trip the
  exfiltration-instruction detector; canonical AWS example keys no longer flag as leaked secrets
- A failed scan (GitHub rate limit, missing repo) used to report `"level": "clean"` — now honestly
  reports `"unknown"`

## [0.1.0] — 2026-07-26 — soft launch
### Added
- Public soft launch: repository + site at **repohunter.dev**
- **Integration dossier** per repo — relevance to your project, how to integrate, the enhancement,
  build-vs-integrate, rough cost (tokens/time/agents), does-it-run-on-your-hardware, kind classification,
  and a **GO / MAYBE / SKIP** verdict
- **All-inclusive ingest** — drop a repo, live GitHub search, YouTube "top repos" video ingest,
  and aggregate-list detection (awesome-lists treated as sources to mine)
- **Approve-first, two-gate integration planning** — concrete checksum-pinned plan → your approval
  (automated builder stage in progress); never a `curl | bash`
- **Pluggable LLM backend** — local Ollama by default (no API bill), OpenAI/OpenRouter via `config.json`
- **Store UI** — a sortable/filterable browser (best-fit / relevance / stars / maturity), dossier drawers,
  live GitHub search, and YouTube ingest. _(The guided walkthrough + Map view are tracked under Unreleased.)_
- Brand identity — dragonfly logo, brand guide, OG link-preview + social assets
