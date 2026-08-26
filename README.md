# Paper Radar

Paper Radar is a personal, LLM-free research monitor. Every run gathers a deliberately broad candidate pool, normalizes metadata, applies deterministic and explainable rules, and sends only high-scoring papers to three Discord channels. It never posts abstracts or generated summaries.

## 1. What this bot does

- **Bioinfo:** prioritizes computational method development for scRNA-seq, dynamics, GRNs, perturbation, generative models, multi-omics, spatial methods, and single-cell foundation models.
- **ML Algorithms:** prioritizes actionable changes to model design, training, formulation, understanding, diagnosis, or evaluation.
- **AI Frontier:** starts from the current ISO week's Hugging Face Daily Papers Trending Top 50 and tracks Physical AI, VLA, world models, agents, self-improvement, and AI scientists.
- Keeps `matched_criteria`, `penalties`, and every numeric score component for inspection with `--debug-scores`.
- Does not use OpenAI, Anthropic, Gemini, or any other LLM API.

## 2. Architecture

```text
bioRxiv / PubMed / arXiv / Semantic Scholar / Hugging Face
                         │
                  high-recall union
                         │
             normalize → deduplicate → score
                         │
             daily cutoff or same-rank /more
                         │
                Discord webhooks + state
```

Candidate generation and ranking are separate. Semantic Scholar recommendations add candidates and at most a small score bonus; they are never a hard filter. The `src/paper_radar` core never imports `extensions`, so deleting experimental extensions cannot break daily or `/more`.

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

In each Discord channel, open **Edit Channel → Integrations → Webhooks**, create a webhook, and copy its URL into the corresponding local variable or GitHub Actions secret. A run sends one compact header, then one Embed per paper containing only rating, linked title, year, venue, matched criteria, and paper URL.

Example:

```text
★★★★★ Must Read
A New Formulation for RNA Velocity
2026 · Nature Methods
Matched: single-cell · rna-velocity · dynamics · formulation · top-venue
Paper
```

## 8. GitHub Actions schedule

`.github/workflows/daily.yml` runs at `15 23 * * *` (08:15 JST the following day) and supports `workflow_dispatch`. Change the UTC cron line to change the schedule. The workflow commits only `state/sent.json` and the compact qualified-candidate cache, and a state commit cannot retrigger the workflow.

## 9. How to edit Bioinfo criteria

Edit `config/bioinfo.yaml`. Keyword families are separated into domain, method, formulation, application-only, low-priority, and review signals. Spatial and foundation-model venue requirements are independent. Bioinfo's intended order is formulation > relevance >> venue.

Default weighted score:

```text
domain relevance + method-development + formulation/conceptual
+ small venue prior + recency + capped seed bonus
- application/low-priority/subdomain penalties
```

Title matches receive more weight than abstract-only matches. Venue never rescues a weak application-only paper.

## 10. How to edit ML criteria

Edit `config/ml_algorithms.yaml`. The principal components are domain relevance, actionable method signal, conceptual/formulation signal, venue prior, recency, and the capped seed bonus. Task applications, benchmark-only work, incremental gains, systems work, and disconnected theory receive independent penalties. NeurIPS/ICML/ICLR get only a modest prior.

## 11. How to edit AI Frontier criteria

Edit `config/ai_frontier.yaml`. HF Trending rank is the dominant component, followed by core/secondary topic relevance, exclusions, recency/legendary handling, then citations. Secondary topics default to Top 15. Ordinary papers older than two years are rejected; very highly cited Top-5 resurfacing papers may take the legendary path.

## 12. How to edit thresholds

Each category YAML contains `thresholds.must_read`, `thresholds.strong`, and `thresholds.more_min_score`. Defaults are:

| Category | Must Read | Strong | `/more` minimum |
|---|---:|---:|---:|
| Bioinfo | 9.0 | 6.2 | 4.8 |
| ML | 8.5 | 5.8 | 4.5 |
| Frontier | 8.0 | 5.7 | 4.4 |

Daily sends every Must Read plus at most three Strong papers. Must Read is never artificially capped.

## 13. How to add positive/negative seeds

Edit `config/seeds.yaml`. A seed may supply a `paper_id` directly or only a title. Missing Semantic Scholar IDs are resolved and cached locally in ignored `config/seeds.resolved.yaml`. Bioinfo starts with scDiffusion, RegVelo, and CellFlow. ML may remain empty. Negative seed slots are reserved for future feedback and do not affect v1 until explicit rules are added.

## 14. `/more` setup

`python -m paper_radar.cli more` reuses the scored candidate cache from daily; it has no second ranker. It filters hard exclusions and sent papers, then returns the next five above `more_min_score`. `.github/workflows/more.yml` exposes the same operation through `workflow_dispatch`.

## 15. Cloudflare Worker deployment

The optional bridge is isolated in `extensions/discord_more`.

1. Copy `wrangler.toml.example` to `wrangler.toml` and set `GITHUB_OWNER`/`GITHUB_REPO`.
2. Run `npx wrangler secret put DISCORD_PUBLIC_KEY` using the Discord application's public key.
3. Create a fine-grained GitHub token limited to this repository with **Actions: write**, then run `npx wrangler secret put GITHUB_TOKEN`.
4. Optionally set `GITHUB_REF` as a Worker variable (defaults to `main`).
5. Run `npx wrangler deploy` and use the deployed HTTPS URL as the Discord Interactions Endpoint URL.

The Worker verifies Discord's Ed25519 signature, parses `/more`, and dispatches GitHub Actions. It contains no selection logic.

## 16. Discord Slash Command registration

Register `extensions/discord_more/register-command.json` with Discord's application-command API (replace IDs and token):

```bash
curl -X POST \
  -H "Authorization: Bot $DISCORD_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  --data @extensions/discord_more/register-command.json \
  "https://discord.com/api/v10/applications/$DISCORD_APPLICATION_ID/commands"
```

This creates `/more category:<bioinfo|ml|frontier>`. The GitHub token and Discord bot token are additional only when enabling the slash-command bridge; daily needs neither.

## 17. Experimental extensions

`extensions/more_like_this` and `extensions/feedback` are disabled placeholders. They are deliberately not imported by daily or `/more` and can be deleted safely.

## 18. Troubleshooting

- **429 / timeouts:** retries use exponential backoff. Add `S2_API_KEY`; transient failure of one source is logged while the other sources continue.
- **No Discord post:** verify the category-specific webhook environment variable. A zero-result live run still sends the daily header.
- **Too many/few papers:** first inspect `--debug-scores`, then tune weights and thresholds in YAML.
- **Repeated paper:** inspect `state/sent.json`. Identity priority is DOI → arXiv → bioRxiv DOI → Semantic Scholar ID → normalized title. A formal journal publication after a sent bioRxiv preprint is intentionally allowed once.
- **`/more` refetches:** run daily live once so `state/candidates.json` exists.
- **Tests:** run `pytest`; all scoring tests are deterministic and use no network.

External APIs used: official bioRxiv details/publication mapping endpoints, NCBI PubMed E-utilities, arXiv Atom API, Semantic Scholar Academic Graph and Recommendations APIs, and `huggingface_hub.HfApi.list_daily_papers`.
