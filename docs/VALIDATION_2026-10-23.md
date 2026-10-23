# Validation report — 2026-10-23

Scope: the branch pipeline (dev → mirror trigger), the deploy-visibility fix
(`.gcloudignore`), and Copilot roadmap **B3 (query rewriting)** including the
validation-driven fixes that followed the first review. Everything below was
re-verified in this pass, not assumed.

## 1. Branch pipeline (push `dev` → mirror, merge `main` → public)

| check | result |
|---|---|
| Trigger `stf-staging-dev-deploy` exists, branch `^dev$`, `_SERVICE_NAME=stf-staging` | ✓ |
| Every `dev` push auto-built + deployed (a3c6b09, cbd22f5, 1ef278f — all SUCCESS) | ✓ |
| Mirror config preserved across trigger deploys: private IAM (owner-only invoker), `STF_API_DOCS=1`, 10 Secret Manager mounts, 1 GiB / 1 CPU | ✓ |
| Anonymous request → 403; authed `/health` + `/openapi.json` (26 paths) | ✓ |
| Public `stf-live` untouched by dev pushes (separate trigger, runs main's image) | ✓ |

Known cosmetic issue: the trigger's `_TRIGGER_ID` label points at a deleted first
import; it only feeds revision labels. `triggers import` updates by name but ignores
`build.substitutions` changes, so it was not fixable that way; left as-is, documented
in `kimi-code/SESSION_LOG.md`.

## 2. `.gcloudignore` (staging-deploy blocker)

Root cause of the earlier silent staging failures: gcloud source upload falls back to
`.gitignore`, which excludes `requirements-api.txt` (the Dockerfile `COPY`s it).
Fixed with a root `.gcloudignore`; gotcha documented: unanchored `docs/*` also matched
`web/src/dashboard/docs/` — patterns are now root-anchored. Verified by downloading the
uploaded source zip and inspecting its contents.

## 3. B3 query rewriting — what the validation found and what changed

First-pass validation against the **real corpus** (920 passages) found the spell-fixer
overcorrecting ordinary words, because the corpus vocabulary excludes stopwords and
inflections:

| input | first-pass output | problem |
|---|---|---|
| `what baking temprature does the ovne use` | `chat baking temprature does the oven use` | "what" → "chat" (stopword not in vocab) |
| `why dose the belt warn` | `why done the belt warn` | typo of stopword "does" corrected to "done" |
| `temprature`, `craine` | unchanged | insertion-type typos missed (token itself never checked against the delete index) |

Fixes shipped in `1ef278f`:

1. **Stopword guard** — tokens in `grounding.STOP_WORDS` are never corrected.
2. **Stem guard** — a token whose stemmed form is in the vocab is an inflection, not
   a typo (the search-time stemmer handles it); also fixes "computed" → "computer".
3. **Digit guard** — identifiers like `24v` are left alone.
4. **Function-word preference** — a near-miss of a stopword (`dose`) resolves to that
   stopword (`does`), not to an unrelated vocab word (`done`).
5. **Insertion-typo lookup** — the unmodified token is checked against the delete index,
   catching missing-letter typos (`temprature` → `temperature`).

Re-validation on the real corpus (all cases):

| input | output |
|---|---|
| what baking temprature does the ovne use | what baking **temperature** does the **oven** use ✓ |
| how is the karbon footprint computed | how is the **carbon** footprint computed ✓ (computed kept) |
| why dose the belt warn | why **does** the belt warn ✓ |
| how many cokies per hour | how many **cookie** per hour ✓ |
| what is the 24v motor | unchanged ✓ |
| high-bay craine / spoken anwsers | unchanged (accepted: short-word insertion + transposition edge cases; the vector side and margin rule cover them — `craine` still retrieved the warehouse doc in testing) |

## 4. Regression gates

| gate | result |
|---|---|
| Full backend suite (`pytest --ignore=tests/perf`) | exit 0 |
| `ruff check packages services tests` | clean |
| Retrieval golden set (16 pairs) | hit@8 0.875, MRR 0.642 — within noise of the recorded baseline (0.875 / 0.644); CI floors pass |
| New rewrite tests (12, incl. 3 regression tests from this validation) | pass |
| Deployed mirror, typo'd question end-to-end | "why dose the ovne belt warn?" → correct belt-wear maintenance passage (`docs/maintenance/README.md`) |

## 5. Residual risks / follow-ups

- `craine`-class typos (short word + inserted letter, correct form short) are not
  lexically fixed; acceptable because hybrid retrieval still surfaces the right doc.
  A word-frequency prior (dismiss ultra-rare words when a common neighbour exists) is a
  possible later refinement.
- Typo-recovery is not yet represented in the golden eval set (B2 harness); the
  `docs/VALIDATION_2026-10-23.md` table above is the current regression reference.
