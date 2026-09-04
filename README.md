# Paper Radar

Paper Radar is a personal research monitor whose scheduled retrieval and ranking are LLM-free. Every run gathers a deliberately broad candidate pool, normalizes metadata, applies deterministic and explainable rules, and sends only high-scoring papers to three Discord channels. Groq is called only when a user invokes `/tune`; abstracts and generated summaries are never posted.

## 1. What this bot does

- **Bioinfo:** prioritizes computational method development for scRNA-seq, dynamics, GRNs, perturbation, generative models, multi-omics, spatial methods, and single-cell foundation models. Retrieves from bioRxiv, Crossref (preprints and general works), PubMed, Europe PMC, Semantic Scholar, and OpenAlex.
- **ML Algorithms:** prioritizes actionable changes to model design, training, formulation, understanding, diagnosis, or evaluation. Broad arXiv retrieval is supplemented by an independent `stat.ML` query in Fresh and Backfill lanes, then deduplicated by paper identity. Also retrieves from PMLR (ICML/AISTATS/UAI proceedings), OpenReview, NeurIPS Proceedings, Crossref works, Semantic Scholar, and OpenAlex.
- **AI Frontier:** no longer depends on Semantic Scholar as its backbone. Retrieves from arXiv (`cs.RO`/`cs.AI`/`cs.LG`/`cs.CV`/`cs.CL`), Hugging Face Daily Papers, OpenReview, PMLR (CoRL), NeurIPS Proceedings, CVF Open Access (CVPR/ICCV), ACL Anthology (ACL/EMNLP), RSS Proceedings, Crossref works, Semantic Scholar, and OpenAlex, for Physical AI, VLA, world models, agents, self-improvement, and AI scientists.
- Selects up to five unsent papers at or above the category's `more_min_score`, preferring Fresh and filling shortages from Backfill and top-journal Archive lanes.
- Keeps `matched_criteria`, `penalties`, and every numeric score component for inspection with `--debug-scores`.
- Does not use OpenAI, Anthropic, Gemini, or any other LLM API.

## 2. Architecture

```text
many independent sources, fetched in parallel per lane
(bioRxiv · Crossref · PubMed · Europe PMC · arXiv · OpenReview · PMLR ·
 NeurIPS Proceedings · CVF · ACL Anthology · RSS Proceedings ·
 Hugging Face · OpenAlex · Semantic Scholar)
                         │
        each source is isolated: a 429/timeout/failure in one
           never stops or degrades acquisition from the rest
                         │
             normalize → deduplicate → score
                         │
        Fresh → Backfill → top-journal Archive fill
                         │
              presentation grouping
                         │
                Discord webhooks + state
```

Candidate generation and ranking are separate. No single source is load-bearing: every source is fetched independently (new sources fan out concurrently per lane; a source's failure is caught at both the adapter level and the orchestration level, and never blocks the others), then everything is normalized into one `Paper` schema, deduplicated, and scored together. Semantic Scholar is a supplemental source, used for recommendations, citation/influential-citation metadata, and as one of several search sources — it is never required for discovery, ranking, or delivery to keep working (see §5). OpenAlex is similarly optional/best-effort and requires no API key. Daily and `/more` search all applicable retrieval lanes, use the same rule-based scorer, exclude already-sent papers, and return up to five results. `/more` increases source limits to explore more candidates. The `src/paper_radar` core never imports `extensions`, so deleting experimental extensions cannot break daily or `/more`.

## 3. Local setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
set -a; source .env; set +a
```

## 4. Required GitHub Secrets

The daily workflow expects the already-configured secrets:

- `DISCORD_BIOINFO_WEBHOOK`
- `DISCORD_ML_WEBHOOK`
- `DISCORD_FRONTIER_WEBHOOK`

Webhook URLs are read only from the environment and are never logged or stored in YAML.

## 5. Optional Semantic Scholar API key

Set `S2_API_KEY` to improve Semantic Scholar limits. Public endpoints are used when it is absent. `NCBI_EMAIL` and `NCBI_API_KEY` are also optional and identify/rate-limit PubMed E-utilities requests politely. No key is configured or required for Europe PMC, OpenAlex, OpenReview, Crossref, PMLR, NeurIPS Proceedings, CVF Open Access, ACL Anthology, or RSS Proceedings — every newly added source works fully unauthenticated, and none of them gate any pipeline behavior on a missing key.

Semantic Scholar is intentionally not a required source. It contributes to Fresh/Backfill/Archive search alongside every other source, plus three supplemental roles that no other source replaces: resolving/expanding seed-paper recommendations, citation and influential-citation counts, and metadata enrichment for Hugging Face Daily Papers results. If Semantic Scholar is completely unreachable for an entire run, paper discovery, ranking, and Discord delivery all continue normally from the remaining sources — see §17.

## 6. Dry-run

```bash
python -m paper_radar.cli daily --category bioinfo --dry-run
python -m paper_radar.cli daily --category ml --dry-run
python -m paper_radar.cli daily --category frontier --dry-run
python -m paper_radar.cli daily --category all --dry-run
python -m paper_radar.cli more --category bioinfo --count 5 --dry-run
```

Add `--debug-scores` to print the full component breakdown. Dry-runs do not send Discord messages or modify deduplication state.

## 7. Discord webhook setup

In each Discord channel, open **Edit Channel → Integrations → Webhooks**, create a webhook, and copy its URL into the corresponding local variable or GitHub Actions secret. A run sends one radar header, then non-empty presentation group headers, followed by one compact Embed per paper. Each Embed contains a linked title, publication date (or year fallback) and venue, rating stars, and matched criteria. The abstract and redundant labels are not posted.

Example:

```text
🌟 Major Journals — 1 papers
A New Formulation for RNA Velocity  (linked title)
2026-08-21 · Nature Methods
⭐⭐⭐⭐⭐
single-cell · rna-velocity · dynamics · formulation · top-venue
```

## 8. GitHub Actions schedule

`.github/workflows/daily.yml` runs at 06:00, 09:00, 12:00, 15:00, and 18:00 JST using UTC cron expressions. It also supports category-aware `workflow_dispatch`; scheduled runs default to all categories. GitHub Actions scheduled workflows can be delayed during periods of high load, so these times are targets rather than strict execution guarantees. The workflow commits only `state/sent.json` and the compact qualified-candidate cache, and a state commit cannot retrigger the workflow.

## 9. How to edit Bioinfo criteria

Edit `config/bioinfo.yaml`. Keyword families are separated into domain, method, formulation, application-only, low-priority, and review signals. Spatial and foundation-model venue requirements are independent. Bioinfo's intended order is formulation > relevance >> venue.

Default ranking score:

```text
scientific importance (domain relevance + method-development + formulation/conceptual
+ scientific-value signals + small venue prior + capped seed bonus)
+ separate freshness/discovery/focus bonuses used only for ordering
- application/low-priority/subdomain penalties
```

Title matches receive more weight than abstract-only matches. Venue never rescues a weak application-only paper.

## 10. How to edit ML criteria

Edit `config/ml_algorithms.yaml`. The principal components are domain relevance, actionable method signal, conceptual/formulation signal, venue prior, recency, and the capped seed bonus. Task applications, benchmark-only work, incremental gains, systems work, and disconnected theory receive independent penalties. NeurIPS/ICML/ICLR get only a modest prior. Watch venues (Annals of Statistics, JRSS-B, Biometrika, configured under `ml.watch` in `config/venues.yaml`) never get a bare venue bonus by themselves — they only score a small `venue_watch` bonus when the paper already has a non-trivial domain- or method-relevance signal (learning, generative models, diffusion/flow matching, optimization, representation, generalization, and similar), so a pure-statistics paper with no ML connection is not pulled in by venue alone.

## 11. How to edit AI Frontier criteria

Edit `config/ai_frontier.yaml`. Core/secondary relevance, qualitative progress, venue, citations, and negative signals determine scientific importance and therefore the star rating. HF Trending is only a small discovery bonus in the selection score; it cannot raise the star rating. arXiv has no penalty. Frontier uses the same 30/365/730-day lanes, with top venues configured under `frontier` in `config/venues.yaml`; the hard age boundary is aligned with the tunable 1095-day archive maximum.

Age gating is intentionally stricter than the other two categories: a paper older than `ranking.trending_days` (default 75 days, ~2-3 months) is excluded unless it's from an `elite` venue (a small journal-only tier under `frontier` in `config/venues.yaml` — currently Nature/Nature Machine Intelligence/Science/Science Robotics/T-RO/IJRR, deliberately narrower than `top`, which also includes conferences like NeurIPS/CoRL/RSS) or has an HF Trending rank at or above `ranking.elite_hf_rank_max` (default 1, i.e. top-1%-of-the-day trending). An ordinary top/strong-venue paper is not, by itself, enough to survive past the trending window — only the elite tier or extreme trending rank is. Papers older than `ranking.old_after_days` (1095 days) fall back to the separate, harder-to-clear "legendary" path (very high citation counts), independent of venue.

## 12. How to edit thresholds

Each category YAML contains `thresholds.must_read`, `thresholds.strong`, and `thresholds.more_min_score`. Ratings use scientific importance only; recency is a small ranking bonus and a separate Discord freshness label. Defaults are:

Retrieval lane boundaries and the five-paper target are configured in `config/common.yaml` under `search.lanes`. Daily uses 1× source limits and `/more` uses 3× source limits; changing acquisition breadth does not duplicate or alter scoring rules.

| Category | Must Read | Strong | Candidate / `/more` minimum |
|---|---:|---:|---:|
| Bioinfo | 7.5 | 5.4 | 4.0 |
| ML | 7.5 | 5.2 | 3.8 |
| Frontier | 6.0 | 4.6 | 3.0 |

Papers at or above Must Read and Strong thresholds receive those ratings. Papers from `more_min_score` up to the Strong threshold receive `★★★☆☆ Candidate`. Daily sends up to five qualifying unsent papers.

## 13. How to add positive/negative seeds

Edit `config/seeds.yaml`. A seed may supply a `paper_id` directly or only a title. Missing Semantic Scholar IDs are resolved and cached locally in ignored `config/seeds.resolved.yaml`. Bioinfo starts with scDiffusion, RegVelo, and CellFlow. ML may remain empty. Negative seed slots are reserved for future feedback and do not affect v1 until explicit rules are added.

## 14. `/daily` and `/more` setup

Both commands perform fresh network acquisition; neither uses `state/candidates.json` as its candidate source. Fresh covers 0–30 days, Backfill covers 31–365 days, and top-journal Archive covers 366–730 days by default, with a hard configurable maximum of 1095 days. Selection is ordered by importance-led selection score, with Fresh normally capped at three of five slots so qualifying Backfill/Archive papers can compete; unused historical slots fall back to Fresh. Explore mode (`/more`) uses 3× source limits while reusing the exact daily scorer, thresholds, hard exclusions, and `state/sent.json` deduplication. `.github/workflows/more.yml` exposes the same operation through `workflow_dispatch`.

`/more focus:<phrase>` adds one-run Semantic Scholar/Crossref queries and a separate focus-ordering bonus. Known family names and aliases are normalized across case, hyphens, and punctuation; unknown phrases use best-effort query and token matching. Focus never changes scientific importance, star ratings, quality thresholds, persisted tuning, or deduplication state. An empty focus is identical to `/more` without the option, and no LLM is called.

Daily and `/more` share the `paper-radar-state` GitHub Actions concurrency group, preventing simultaneous state writers. Both Discord commands derive their category from the current Discord channel, so they use the same deduplication state without a category selector. The daily candidate cache remains available only for debugging, score inspection, and audit.

## 15. Cloudflare Worker deployment

The optional bridge is isolated in `extensions/discord_more`.

1. Copy `wrangler.toml.example` to `wrangler.toml` and set `GITHUB_OWNER`/`GITHUB_REPO`.
2. Run `npx wrangler secret put DISCORD_PUBLIC_KEY` using the Discord application's public key.
3. Create a fine-grained GitHub token limited to this repository with **Actions: write**, then run `npx wrangler secret put GITHUB_TOKEN`.
4. Set `CHANNEL_CATEGORY_MAP` to one JSON object mapping Discord channel IDs to `bioinfo`, `ml`, or `frontier`. This is the single source of truth shared by both commands.
5. Optionally set `GITHUB_REF` as a Worker variable (defaults to `main`).
6. Run `npx wrangler deploy` and use the deployed HTTPS URL as the Discord Interactions Endpoint URL.

The Worker verifies Discord's Ed25519 signature, maps the current channel to a category, parses `/daily` and `/more`, and dispatches the corresponding GitHub Actions workflow. It contains no selection logic.

## 16. Discord Slash Command registration

Bulk-register `extensions/discord_more/register-command.json` as guild commands (replace IDs and token):

```bash
curl -X PUT \
  -H "Authorization: Bot $DISCORD_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  --data @extensions/discord_more/register-command.json \
  "https://discord.com/api/v10/applications/$DISCORD_APPLICATION_ID/guilds/$DISCORD_GUILD_ID/commands"
```

This creates `/daily` and `/more` (with optional `focus`) without category options. The fine-grained GitHub token needs only repository **Actions: write**; the Discord bot token is used only to register commands and is not stored in the Worker.

## 17. `/tune` preference learning

`/tune feedback:<natural language>` interprets preference feedback with one Groq structured-output call, validates a finite action set, and updates deterministic scoring overlays. It does not ask an LLM to rank the daily paper pool or write executable code.

Validated rules are stored in `config/tuning.yaml`. Each successful interpretation appends its timestamp, original message, before/after rules, summary, warnings, and applied actions to `state/tuning_history.json`. The dedicated `tune.yml` workflow commits both files, so later scheduled and `/more` runs load the same rules. Daily, More, and Tune share the `paper-radar-state` concurrency group.

Supported tuning operations cover positive/negative concepts, concept weights, method/formulation/phenomenon/benchmark/application signals, journal priority, freshness bonus/window, top-journal archive duration, Fresh/Backfill result ratio, channel routing, notification thresholds, and paper-type preferences. Values are bounded and unknown operations are rejected. Feedback and paper abstracts are treated as untrusted text; tuning cannot change secrets, paths, commands, Python code, environment variables, or workflows.

Set `GROQ_API_KEY` as a GitHub Actions repository secret. It is used only by `tune.yml`; it is not required by the Cloudflare Worker and must not be placed in YAML or source files. The production model is `openai/gpt-oss-20b` with strict JSON Schema output.

The command resolves references from the recent candidate cache by URL or distinctive title terms. For arXiv, bioRxiv, DOI, and Semantic Scholar URLs not found in the cache, it reuses Semantic Scholar metadata retrieval before the Groq call. Explicitly stated reasons take precedence over inferred paper characteristics in the tuning prompt.

Each run prints a compact `Source health` summary in addition to per-source candidate counts. A source is marked degraded only when all of its final attempts fail (for example `rate_limit`, `timeout`, or `request_error`); a retry that eventually succeeds remains healthy. Multi-operation sources (currently Semantic Scholar: `.search` / `.enrichment` / `.recommendations`, PubMed: `.search` / `.fetch`, and Crossref: `.preprint` / `.works`) are tracked per operation, printed as separate `source.operation` entries, and rolled up into one status for the bare source name: healthy only if every operation succeeded, the shared failure reason if every operation failed, and `degraded` for any mix — including the same operation succeeding in one lane and failing in another within the same run. A success is never allowed to silently overwrite a failure. When a category has degraded sources **and** its post-dedup candidate pool falls below `search.warning_coverage_floor` (`config/common.yaml`, default 10), its Discord channel receives one compact `⚠️ Retrieval degraded: ...` message, naming the affected sources by their rollup status — never the per-operation sub-keys. A zero-result run alone does not trigger this warning, and neither does a degraded source when enough other sources still produced adequate coverage.

## 18. Retrieval resilience

Every source is fetched independently and its failure is isolated at two layers: each adapter (`src/paper_radar/sources/*.py`) catches its own network/parse errors internally and returns an empty list rather than raising, and `Pipeline._safe_call`/`Pipeline._run_parallel` (`src/paper_radar/pipeline.py`) provide a second, orchestration-level backstop so a bug that slips past an adapter's own handling still can't take other sources down with it. The broader batch of newer sources (Europe PMC, OpenAlex, OpenReview, Crossref works, PMLR, NeurIPS Proceedings, CVF Open Access, ACL Anthology, RSS Proceedings) is fanned out concurrently per lane via a thread pool; the original sources (bioRxiv, Crossref preprints, PubMed, arXiv, Semantic Scholar) stay sequential within a lane to keep their acquisition order deterministic. No single source is required: Semantic Scholar or any other one source going fully down for an entire run still leaves discovery, ranking, and delivery working from everything else (see §17 for how that shows up in Source health).

## 19. Experimental extensions

`extensions/more_like_this` and `extensions/feedback` are disabled placeholders. They are deliberately not imported by daily or `/more` and can be deleted safely.

## 20. Troubleshooting

- **429 / timeouts:** retries use exponential backoff. Add `S2_API_KEY` for Semantic Scholar; a transient failure of any one source is logged while every other source continues, and the run still completes.
- **No Discord post:** verify the category-specific webhook environment variable. A zero-result live run still sends the daily header.
- **Too many/few papers:** first inspect `--debug-scores`, then tune weights and thresholds in YAML.
- **Repeated paper:** inspect `state/sent.json`. Identity priority is DOI → arXiv → bioRxiv DOI → PubMed ID → OpenAlex ID → Semantic Scholar ID → normalized title, with a fuzzy title+author fallback pass for near-duplicates across sources that share none of those identifiers. A formal journal publication after a sent bioRxiv preprint is intentionally allowed once.
- **`/more` is slower than daily:** explore mode intentionally searches the same three lanes with larger source limits, across every source. It does not depend on the daily candidate cache.
- **`/tune` fails safely:** inspect the Tune Paper Radar workflow log. Groq/API/schema failures leave `config/tuning.yaml` unchanged and post a short failure notice when Discord is available.
- **A specific new source is quiet:** check `Source health` in the run log for that source's name; PMLR, NeurIPS Proceedings, CVF Open Access, and RSS Proceedings only cover the volumes/years/conferences listed under `proceedings` in `config/common.yaml`, so a missing recent one may just need adding there.
- **Tests:** run `pytest`; every test is deterministic and uses no network — `tests/conftest.py`'s `stub_broad_sources` stubs every source class other than Semantic Scholar for tests that exercise `Pipeline.acquire`/`_acquire_lane` without mocking each source individually.

External APIs used: official bioRxiv details/publication mapping endpoints, Crossref Works (preprints and general works search), NCBI PubMed E-utilities, Europe PMC REST API, arXiv Atom API, OpenAlex Works API, OpenReview API v2, PMLR volume pages, NeurIPS Proceedings, CVF Open Access, the ACL Anthology's canonical per-venue-year XML data, RSS (Robotics: Science and Systems) accepted-papers listing, Semantic Scholar Academic Graph and Recommendations APIs, and `huggingface_hub.HfApi.list_daily_papers`. CVF Open Access hosts CVPR and ICCV but not ECCV (ECCV proceedings live on a separate site, `ecva.net`, with a different page structure) — ECCV coverage for AI Frontier currently comes from arXiv, OpenAlex, and Crossref works instead of a dedicated CVF scrape.
