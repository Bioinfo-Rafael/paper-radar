# Discord reaction feedback (experimental, additive, shadow-only)

This extension collects 👍 / ❤️ / ❤️‍🔥 reactions that `TARGET_USER_ID` leaves
on existing Paper Radar Discord messages, records them as raw interest
evidence, forwards ❤️/❤️‍🔥 papers to `#saved-papers`/`#must-read`, and (as a
fully experimental, non-production shadow system) compares several semantic
interest models against that feedback. **It changes nothing about
`src/paper_radar`**: paper retrieval, scoring, ranking, selection,
deduplication, and Discord delivery for `/daily`/`/more`/`/tune` are
untouched. `src/paper_radar` never imports this directory.

## Why reactions are not "ratings"

A reaction records *user interest evidence*, not paper quality. The absence
of a reaction is **unknown/unlabeled**, never a negative label — nothing in
this extension treats an unreacted paper as disliked, and nothing here
feeds back into `score`/`rating`/`importance_score` on `Paper` objects.

| Reaction | Meaning | Raw feedback | Forwarded to |
|---|---|---|---|
| 👍 | weak interest | yes | — |
| ❤️ | medium interest | yes | `#saved-papers` |
| ❤️‍🔥 | strong interest | yes | `#must-read` |

Weights (👍 < ❤️ < ❤️‍🔥) live in [`reactions.yaml`](reactions.yaml) and can be
changed at any time without touching code.

## Architecture

No Discord Gateway connection is added. Two independent GitHub Actions
workflows poll the Discord REST API on a schedule:

- **`.github/workflows/feedback_collect.yml`** (every 30 minutes, plus
  `workflow_dispatch`): scans the three source channels for new/updated
  paper messages, confirms `TARGET_USER_ID` actually left one of the three
  target reactions (via the reaction-users endpoint, never trusting the
  reaction-count summary alone), records a raw feedback event, and forwards
  ❤️/❤️‍🔥 papers.
- **`.github/workflows/feedback_enrich.yml`** (every 6 hours, plus
  `workflow_dispatch` with a `force` input): batch-fetches abstracts for
  papers that had none locally available, then computes shadow interest
  predictions.

Both workflows only ever read this repository (`state/candidates.json`,
read-only) and read/write a **separate private repository**,
`Bioinfo-Rafael/paper-radar-feedback-state`, checked out with the
`FEEDBACK_STATE_TOKEN` secret. Neither workflow ever commits to
`Bioinfo-Rafael/paper-radar`, so there is no interaction with the
`paper-radar-state` concurrency group used by `daily.yml`/`more.yml`/
`tune.yml`; both feedback workflows instead share their own
`feedback-state-repo` concurrency group so they never race pushes to the
private repo against each other.

If `DISCORD_BOT_TOKEN` or `FEEDBACK_STATE_TOKEN` is not configured yet, both
workflows detect that in a guard step and exit successfully without doing
anything — this extension is designed to be safe to merge before the
private repository or secrets exist.

## Paper identification

Every Paper Radar paper message is an Embed with a `title` and `url`.
`extensions/feedback/identify.py` matches a reacted message against
`state/candidates.json` in this priority order (as specified):

1. exact `paper_url` match,
2. `canonical_id` match — synthesized from the embed URL the same way
   `Paper.compute_canonical_id` would (DOI/arXiv extracted from the URL,
   falling back to a normalized-title id), so it lines up with the real
   canonical id if the DOI/arXiv id is recoverable,
3. normalized-title fallback (`paper_radar.models.normalize_title`).

`state/candidates.json` only ever holds the *latest* day's qualifying
candidates per category (it is fully replaced on every daily run), so a
paper reacted to well after it was posted may no longer be present — that
paper is recorded with whatever identifiers can be parsed from its URL and
queued for abstract enrichment rather than treated as unmatched-and-dropped.

## Idempotency

A stable event id is derived from `sha256(guild_id:channel_id:message_id:
user_id:normalized_emoji)`. The raw `TARGET_USER_ID` value itself is not
duplicated onto every event record — this system's scope (a single target
user) is recorded once, as metadata, in the private state repo's
`meta.json`. Before doing anything with a reaction, the event id is checked
against `processed_events.json`; a reaction already processed is skipped
entirely, so a single ❤️ can never be copied into `#saved-papers` more than
once, no matter how many times the 30-minute poll observes it.

## Private feedback state (`Bioinfo-Rafael/paper-radar-feedback-state`)

All files are plain JSON/JSONL, chosen so they diff cleanly in git (no
SQLite binary committed on every run):

- `raw_events.jsonl` — **append-only** log of every recorded reaction event
  (event id, canonical id, title, paper URL, reaction, reaction-strength
  class, category, publication date, source channel/message id, jump URL,
  message timestamp, detection timestamp, original score/rating if known,
  abstract-enrichment status, and identifiers). Never rewritten, so a
  future, different interest algorithm can replay full history.
- `processed_events.json` — idempotency ledger (event id → recorded/
  forwarded-to).
- `pending_abstracts.json` — queue of papers with no locally-known
  abstract, keyed by canonical id, holding every identifier recoverable
  (DOI/arXiv id/Semantic Scholar id/title/URL) plus retry bookkeeping.
- `enriched_abstracts.json` — cache of abstracts fetched via batch calls,
  keyed by canonical id (joined against `raw_events.jsonl` at read time,
  not written back into it, to keep the raw log append-only).
- `meta.json` — per-channel last-seen-message-id cursor, plus the
  single-target-user scope note.
- `shadow_predictions.jsonl` — **append-only** log of shadow model
  predictions (see below).

## Abstract enrichment

`collect.py` never calls an external paper API. If a matched paper already
has an abstract in `state/candidates.json`, that abstract is copied inline
onto the raw event (`abstract_enrichment_status: reused_local`). Otherwise
the paper is queued in `pending_abstracts.json`
(`abstract_enrichment_status: pending`, or `no_identifier` if no DOI/arXiv
id/Semantic Scholar id could be recovered at all).

`enrich.py` (a separate workflow) normally only runs its batch fetch once
the pending queue has at least 20 resolvable papers (`--force`/
`FEEDBACK_ENRICH_FORCE` bypasses this), reuses
`paper_radar.sources.semantic_scholar.SemanticScholarSource.fetch_batch`
(and the existing `S2_API_KEY` secret) grouped into chunks of at most 50
identifiers — never one external request per reaction. A failed or
rate-limited chunk leaves every paper in that chunk in the pending queue
for the next run; a papers-with-no-abstract-available result is likewise
kept pending rather than dropped. Nothing here can fail the collection
workflow, since they are different workflow files, and a failure inside
`enrich.py` itself is caught and logged rather than raised.

## Semantic interest inference (shadow only)

`extensions/feedback/shadow/` is a fully experimental, isolated model
registry. **Nothing here is wired into `src/paper_radar` scoring, ranking,
or selection; production ranking contribution is 0%.**

- `interfaces.py` — the `ChallengerModel` contract every entry implements
  (`is_available`, optional `fit(corpus)`, `embed(text)`, `similarity`).
- `lexical_tfidf.py` — a pure-Python TF-IDF/cosine baseline. Always
  available (no dependency), so this is the one challenger that always
  actually runs.
- `embedding_models.py` — `BAAI/bge-small-en-v1.5` and a SPECTER-family
  scientific-paper embedding challenger, both lazily imported from the
  optional `sentence-transformers` dependency (`pip install
  '.[feedback-embeddings]'`). Neither is installed by default, by
  `daily.yml`, or by the `dev` extra; `feedback_enrich.yml` only installs
  them for a given run if `workflow_dispatch` requests
  `install_embeddings: true`. If unavailable, `is_available()` is `False`
  and the model is skipped — never a hard failure.
- `aggregation.py` — profile-construction strategies, combinable rather
  than mutually exclusive: weighted centroid, per-reaction-type profiles,
  simple k-means clustering (dense vectors only), and an optional recency
  half-life applied to reaction weights before any of the above. Reaction
  strength weighting (👍 < ❤️ < ❤️‍🔥, from `reactions.yaml`) is always
  applied as the base input weight.
- `registry.py` — lists every challenger; no entry is hard-coded as "the"
  model.
- `predict.py` — joins enriched reactions with `state/candidates.json`
  candidates that already carry an abstract (never re-fetching an abstract
  just for shadow scoring), and, only once at least 20 reactions have a
  usable abstract, writes one row per (model × aggregation × candidate) to
  `shadow_predictions.jsonl` with `model_name`, `model_version`,
  `profile_version`, `aggregation_method`, `interest_score`, `computed_at`,
  and an `input_data_hash` for reproducibility. With fewer than 20 usable
  reactions it logs "insufficient feedback data" and writes nothing — this
  is a normal, successful exit, not an error.

No reaction-absent paper is ever treated as negative anywhere in this
pipeline; there is no "negative" label in this schema at all.

## Configuration

`extensions/feedback/config.py` hardcodes the concrete IDs for this
workspace as defaults (they are ordinary Discord snowflake IDs, not
secrets) and reads `DISCORD_BOT_TOKEN`/`FEEDBACK_STATE_TOKEN` only from the
environment. See the `feedback_collect.yml`/`feedback_enrich.yml` `env:`
blocks for the full list of environment variables, and `.env.example` for
local-run documentation.

## What this extension deliberately does not do

- Does not add a persistent Discord Gateway/bot process.
- Does not touch `daily.yml`/`more.yml`/`tune.yml`, their concurrency
  group, or their committed state files.
- Does not change the Discord paper embed format used for delivery.
- Does not call an external abstract API per-reaction, or at all during
  collection.
- Does not let a shadow model touch `Paper.score`/`Paper.rating`/
  `Paper.importance_score` or any selection/threshold logic.
- Does not require any of the above to be configured for
  `/daily`/`/more`/`/tune` to keep working exactly as before.
