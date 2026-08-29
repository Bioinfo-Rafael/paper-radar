# Paper Radar

Paper Radar is a personal research monitor whose scheduled retrieval and ranking are LLM-free. Every run gathers a deliberately broad candidate pool, normalizes metadata, applies deterministic and explainable rules, and sends only high-scoring papers to three Discord channels. Groq is called only when a user invokes `/tune`; abstracts and generated summaries are never posted.

## 1. What this bot does

- **Bioinfo:** prioritizes computational method development for scRNA-seq, dynamics, GRNs, perturbation, generative models, multi-omics, spatial methods, and single-cell foundation models.
- **ML Algorithms:** prioritizes actionable changes to model design, training, formulation, understanding, diagnosis, or evaluation.
- **AI Frontier:** starts from the current ISO week's Hugging Face Daily Papers Trending Top 50 and tracks Physical AI, VLA, world models, agents, self-improvement, and AI scientists.
- Selects up to five unsent papers at or above the category's `more_min_score`, preferring Fresh and filling shortages from Backfill and top-journal Archive lanes.
- Keeps `matched_criteria`, `penalties`, and every numeric score component for inspection with `--debug-scores`.
- Does not use OpenAI, Anthropic, Gemini, or any other LLM API.

## 2. Architecture

```text
bioRxiv / Crossref / PubMed / arXiv / Semantic Scholar / Hugging Face
                         │
                  high-recall union
                         │
             normalize → deduplicate → score
                         │
        Fresh → Backfill → top-journal Archive fill
                         │
              presentation grouping
                         │
                Discord webhooks + state
```

Candidate generation and ranking are separate. Semantic Scholar recommendations add candidates and at most a small score bonus; they are never a hard filter. Daily and `/more` search all applicable retrieval lanes, use the same rule-based scorer, exclude already-sent papers, and return up to five results. `/more` increases source limits to explore more candidates. The `src/paper_radar` core never imports `extensions`, so deleting experimental extensions cannot break daily or `/more`.

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

Set `S2_API_KEY` to improve Semantic Scholar limits. Public endpoints are used when it is absent. `NCBI_EMAIL` and `NCBI_API_KEY` are also optional and identify/rate-limit PubMed E-utilities requests politely.

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
+ separate freshness bonus
- application/low-priority/subdomain penalties
```

Title matches receive more weight than abstract-only matches. Venue never rescues a weak application-only paper.

## 10. How to edit ML criteria

Edit `config/ml_algorithms.yaml`. The principal components are domain relevance, actionable method signal, conceptual/formulation signal, venue prior, recency, and the capped seed bonus. Task applications, benchmark-only work, incremental gains, systems work, and disconnected theory receive independent penalties. NeurIPS/ICML/ICLR get only a modest prior.

## 11. How to edit AI Frontier criteria

Edit `config/ai_frontier.yaml`. HF Trending rank is the dominant component, followed by core/secondary topic relevance, exclusions, recency/legendary handling, then citations. Secondary topics default to Top 15. Ordinary papers older than two years are rejected; very highly cited Top-5 resurfacing papers may take the legendary path.

## 12. How to edit thresholds

Each category YAML contains `thresholds.must_read`, `thresholds.strong`, and `thresholds.more_min_score`. Ratings use scientific importance only; recency is a small ranking bonus and a separate Discord freshness label. Defaults are:

Retrieval lane boundaries and the five-paper target are configured in `config/common.yaml` under `search.lanes`. Daily uses 1× source limits and `/more` uses 3× source limits; changing acquisition breadth does not duplicate or alter scoring rules.

| Category | Must Read | Strong | Candidate / `/more` minimum |
|---|---:|---:|---:|
| Bioinfo | 7.5 | 5.4 | 4.0 |
| ML | 7.5 | 5.2 | 3.8 |
| Frontier | 7.2 | 5.0 | 3.8 |

Papers at or above Must Read and Strong thresholds receive those ratings. Papers from `more_min_score` up to the Strong threshold receive `★★★☆☆ Candidate`. Daily sends up to five qualifying unsent papers.

## 13. How to add positive/negative seeds

Edit `config/seeds.yaml`. A seed may supply a `paper_id` directly or only a title. Missing Semantic Scholar IDs are resolved and cached locally in ignored `config/seeds.resolved.yaml`. Bioinfo starts with scDiffusion, RegVelo, and CellFlow. ML may remain empty. Negative seed slots are reserved for future feedback and do not affect v1 until explicit rules are added.

## 14. `/daily` and `/more` setup

Both commands perform fresh network acquisition; neither uses `state/candidates.json` as its candidate source. Fresh covers 0–30 days, Backfill covers 31–365 days, and top-journal Archive covers 366–730 days by default, with a hard configurable maximum of 1095 days. Fresh is selected first, then shortages are filled from Backfill and Archive without lowering the quality threshold. Explore mode (`/more`) uses 3× source limits while reusing the exact daily scorer, thresholds, hard exclusions, and `state/sent.json` deduplication. `.github/workflows/more.yml` exposes the same operation through `workflow_dispatch`.

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

This creates `/daily` and `/more` without category options. The fine-grained GitHub token needs only repository **Actions: write**; the Discord bot token is used only to register commands and is not stored in the Worker.

## 17. `/tune` preference learning

`/tune feedback:<natural language>` interprets preference feedback with one Groq structured-output call, validates a finite action set, and updates deterministic scoring overlays. It does not ask an LLM to rank the daily paper pool or write executable code.

Validated rules are stored in `config/tuning.yaml`. Each successful interpretation appends its timestamp, original message, before/after rules, summary, warnings, and applied actions to `state/tuning_history.json`. The dedicated `tune.yml` workflow commits both files, so later scheduled and `/more` runs load the same rules. Daily, More, and Tune share the `paper-radar-state` concurrency group.

Supported tuning operations cover positive/negative concepts, concept weights, method/formulation/phenomenon/benchmark/application signals, journal priority, freshness bonus/window, top-journal archive duration, Fresh/Backfill result ratio, channel routing, notification thresholds, and paper-type preferences. Values are bounded and unknown operations are rejected. Feedback and paper abstracts are treated as untrusted text; tuning cannot change secrets, paths, commands, Python code, environment variables, or workflows.

Set `GROQ_API_KEY` as a GitHub Actions repository secret. It is used only by `tune.yml`; it is not required by the Cloudflare Worker and must not be placed in YAML or source files. The production model is `openai/gpt-oss-20b` with strict JSON Schema output.

The command resolves references from the recent candidate cache by URL or distinctive title terms. For arXiv, bioRxiv, DOI, and Semantic Scholar URLs not found in the cache, it reuses Semantic Scholar metadata retrieval before the Groq call. Explicitly stated reasons take precedence over inferred paper characteristics in the tuning prompt.

## 18. Experimental extensions

`extensions/more_like_this` and `extensions/feedback` are disabled placeholders. They are deliberately not imported by daily or `/more` and can be deleted safely.

## 19. Troubleshooting

- **429 / timeouts:** retries use exponential backoff. Add `S2_API_KEY`; transient failure of one source is logged while the other sources continue.
- **No Discord post:** verify the category-specific webhook environment variable. A zero-result live run still sends the daily header.
- **Too many/few papers:** first inspect `--debug-scores`, then tune weights and thresholds in YAML.
- **Repeated paper:** inspect `state/sent.json`. Identity priority is DOI → arXiv → bioRxiv DOI → Semantic Scholar ID → normalized title. A formal journal publication after a sent bioRxiv preprint is intentionally allowed once.
- **`/more` is slower than daily:** explore mode intentionally searches the same three lanes with larger source limits. It does not depend on the daily candidate cache.
- **`/tune` fails safely:** inspect the Tune Paper Radar workflow log. Groq/API/schema failures leave `config/tuning.yaml` unchanged and post a short failure notice when Discord is available.
- **Tests:** run `pytest`; all scoring tests are deterministic and use no network.

External APIs used: official bioRxiv details/publication mapping endpoints, Crossref Works, NCBI PubMed E-utilities, arXiv Atom API, Semantic Scholar Academic Graph and Recommendations APIs, and `huggingface_hub.HfApi.list_daily_papers`.
