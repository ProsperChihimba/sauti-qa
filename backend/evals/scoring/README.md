# Scoring evaluation set

`cases.yaml` holds 30 realistic Swahili customer-care calls with the answers a QA
analyst would give for the default scorecard. It measures whether an LLM scores
calls the way your analysts do, before you trust it with every call.

## Run

```bash
cd backend
python scripts/eval_scoring.py --provider anthropic                     # Claude (claude-sonnet-5-5)
python scripts/eval_scoring.py --provider openai --model Qwen/Qwen3-32B \
    --base-url http://vllm:8000/v1                                      # an on-prem model
python scripts/eval_scoring.py --provider mock                          # harness check, no LLM
```

Results go to `eval-results/report.md` (and `results.json` with raw model output).
Use `--only C03 C04` to rerun a few cases.

## What the cases cover

| Area | Cases |
|---|---|
| Model calls | C01, C02, C10, C23, C26, C30 |
| Critical failures: PIN / SMS code / app password requested | C03, C04, C28 |
| Critical failures: wrong information, impossible promise | C11, C12 |
| Traps: "PIN" said correctly, customer volunteers a PIN, scam warning | C05, C06, C29 |
| Agent behaviour: rude, sarcastic, no empathy, no probing, abrupt hold, no closing | C07, C25, C21, C22, C20, C15 |
| Judge only the agent: abusive customer, TCRA threat, refused escalation | C08, C24, C09 |
| N/A handling: info-only call, wrong number | C14, C19 |
| Robustness: code-switching, English call, noisy ASR, unlabelled speakers, verification skipped | C16, C27, C17, C18, C13 |

## Reading the report

- **Critical failures caught** matters most: a missed PIN request is a missed fraud.
- **False auto-fails** send good calls to review and annoy agents; watch the trap cases.
- **Wrong answers with low confidence**: wrong answers the routing would still send to a
  human (confidence below the review threshold). Higher is safer.
- **Disagreements** list each miss with the model's reasoning. Sometimes the label is the
  thing to fix: labels marked `"?"` are left unscored because analysts could disagree.

## Add real calls

During the pilot, add reviewed calls (already redacted transcripts) with the analyst's
final answers. A set built from your own calls is the real acceptance test. Keep it out
of public repositories.
