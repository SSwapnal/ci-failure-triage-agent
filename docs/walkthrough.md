# Walkthrough

A step-by-step tour for someone who has never seen this code, on macOS and starting from a
clean clone. It takes about 15 minutes. Every command and output excerpt below
was run and copied from a real session.

## 1. Prerequisites

| Tool | Needed for | Check with | Known good |
|---|---|---|---|
| Python 3.12+ | everything | `python3 --version` | `Python 3.12.9` |
| git | cloning | `git --version` | `git version 2.54.0 (Apple Git-157)` |
| Anthropic API key | real LLM mode only | `echo ${ANTHROPIC_API_KEY:+set}` | prints `set` |
| GitHub token | real issue filing only | `echo ${GITHUB_TOKEN:+set}` | prints `set` |

Mock mode needs neither key.

macOS ships an older `/usr/bin/python3` (3.9 on many machines). Check which one
you get:

```bash
python3 --version
which python3.12      # e.g. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
```

If `python3` is older than 3.12, install 3.12 from python.org or with `brew install python@3.12`,
and use `python3.12` in the commands below.

## 2. Setup

```bash
git clone <repo-url> ci-failure-triage-agent
cd ci-failure-triage-agent

python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"
```

This installs the package in editable mode, along with LangGraph, the Anthropic SDK,
junitparser, httpx, typer, pydantic, pytest and ruff (pinned versions are in
`pyproject.toml`). It also installs a `triage` command into `.venv/bin/`.

Check that it worked:

```bash
.venv/bin/triage --help
```

```
 Usage: triage [OPTIONS] COMMAND [ARGS]...

 Triage CI test failures: flaky tests, regressions, infra problems.
...
│ run    Run the triage pipeline and write the report.                         │
│ graph  Print the pipeline graph as Mermaid.                                  │
```

You can run `source .venv/bin/activate` so that plain `triage` and `pytest` work.
This guide uses `.venv/bin/...` paths so every command works in any shell.

## 3. Look at the input first

The tool reads a folder of CI runs. Open the sample data before running anything:

```bash
ls sample_data/runs
# r1001 r1002 ... r1009
cat sample_data/runs/r1004/run.json
find sample_data/runs/r1004 -type f
```

```json
{
  "run_id": "r1004",
  "pipeline": "orders-ci",
  "branch": "main",
  "trigger": "push",
  "timestamp": "2026-09-22T12:00:00+00:00",
  "commit": {
    "sha": "9c41e7a",
    "message": "pricing: move bulk discount thresholds to config",
    "author": "dev.patel"
  }
}
```

Each run has:

- `run.json` with the commit, branch and timestamp
- JUnit XML from a Java module (`orders-service/surefire-reports/TEST-*.xml`)
- JUnit XML from a pytest suite (`api-tests/pytest-report.xml`)
- `console.log`, the CI job log

`sample_data/README.md` lists what was planted in each run. It's worth reading
now so you know what the tool *should* find.

Useful things to look at:

```bash
cat sample_data/runs/r1006/console.log          # the infra incident: OOMKilled, "no such host"
grep -l "<failure\|<error" -r sample_data/runs/r1007
```

## 4. Run the triage in mock mode

```bash
.venv/bin/triage run --input sample_data --out reports/
```

Expected output:

```
classifier: mock
runs: 9  signatures: 6  needs review: 1
  96c4992c80  product_bug    0.85  1 test(s)
  a8252e02cf  test_code_bug  0.85  2 test(s)
  af8af61825  flaky_test     0.80  1 test(s)
  eacf7aa34b  environment    0.90  3 test(s)
  3f511f3805  environment    0.90  2 test(s)
  08f85f9f62  product_bug    0.55  1 test(s)  [review]
  issue 96c4992c80: dry-run reports/issues/96c4992c80.json
  issue a8252e02cf: dry-run reports/issues/a8252e02cf.json
report: reports/triage-report.md
```

What each line tells you:

- `classifier: mock`: no API key was found, so the deterministic mock classifier was used.
- 21 failing test results across 9 runs were grouped into **6 signatures** (6 root causes).
- One group scored below the 0.7 confidence threshold, so it was flagged `[review]` and will not be filed.
- Two groups are real bugs (a product bug and a test-code bug). Their GitHub issue payloads were
  written to disk but **not** sent, because dry-run is the default.

Files written:

```
reports/
  triage-report.md      full human-readable report
  triage.json           evidence + classification per group (machine-readable)
  bugs/<sig>.md         one bug-report draft per bug
  issues/<sig>.json     GitHub issue payload per bug (dry-run)
```

Open `reports/triage-report.md` (or the committed copy, `docs/sample-triage-report.md`).
Read the Summary table, then the "Needs human review" section, then one bug draft.
An issue payload starts like this:

```json
{
  "signature_id": "96c4992c80",
  "title": "OrderPricingTest.appliesBulkDiscountAboveThreshold: AssertionFailedError: expected: <90.00> but was: <100.00>",
  "body": "**Category:** product_bug | **Confidence:** 0.85 | **Suggested owner:** orders/pricing\n**Suspected commit:** `9c41e7a` pricing: mo...
```

Print the pipeline graph:

```bash
.venv/bin/triage graph
```

This prints Mermaid text. Paste it into any Mermaid viewer, or compare it with the diagram in the README.

## 5. Follow one run through the code

The pipeline is a LangGraph `StateGraph`. Each node reads from a shared state dict and adds
one key to it. Read the files in this order:

| Stage | File | What to look at |
|---|---|---|
| Wiring | `src/ci_triage/graph.py` | `build_graph()` registers seven nodes and the edges between them. Two edges are conditional: the graph skips classification when there are no failures, and skips issue filing when there are no bug drafts. |
| Ingest | `src/ci_triage/ingest.py` | `load_runs()` finds every `run.json` and sorts runs by timestamp. `parse_junit_xml()` uses junitparser for both Surefire and pytest XML. pytest puts the exception type into the message, so `_to_result()` splits it back out. |
| History / flakiness | `src/ci_triage/flakiness.py` | `history_for()` computes, per test, the fail rate and the **same-commit flip rate** (share of rerun commits where the outcome changed). It also computes the trailing failure streak, which gives the first failing and last passing commit. `is_flaky()` holds the rule. |
| Signatures | `src/ci_triage/signatures.py` | `_NORMALIZERS` is the list of regexes that replace UUIDs, timestamps, IPs, hex and numbers. `extract_frames()` keeps only in-app stack frames. `signature_for()` combines type, message and frames into a 10-char id. |
| Clustering + evidence | `src/ci_triage/clustering.py` | `cluster_failures()` groups failures by signature. `build_evidence()` builds the `ClusterEvidence` bundle the classifier sees: infra keywords (from both the test output and the job log), setup-phase flag, suspect commits, log excerpt. |
| Classification | `src/ci_triage/llm.py` | `SYSTEM_PROMPT` defines the four categories. `AnthropicClassifier` calls Claude with `messages.parse(output_format=Classification)`. `MockClassifier` follows the same rules in plain Python. `get_classifier()` picks one based on environment variables. |
| Routing | `graph.py`, `route()` | Sets `needs_review=True` when confidence is below the threshold. |
| Report | `src/ci_triage/report.py` | `render_report()` builds the markdown, and `render_bug_draft()` builds each bug report, including repro commands (`mvn -Dtest=...` / `pytest "..."`). |
| Issues | `src/ci_triage/issues.py` | `file_issues()` returns straight away in dry-run. Otherwise it searches for an open issue with the same `triage-signature` marker before it creates a new one. |
| CLI | `src/ci_triage/cli.py` | Parses options, invokes the graph, writes the output files. |
| Data types | `src/ci_triage/models.py` | All pydantic models. `Classification` is the LLM's output schema. |

To poke at intermediate state in a Python shell:

```bash
.venv/bin/python
```

```python
from ci_triage.ingest import load_runs
from ci_triage.flakiness import analyze_history
runs = load_runs("sample_data")
h = analyze_history(runs)
h["tests.api.test_checkout::test_checkout_completes_within_sla"].flipped_commits
# ['3f2a9c1', 'e7a1b52']
```

## 6. Run the tests and linters

```bash
.venv/bin/pytest
```

```
........................................................................ [100%]
73 passed in 4.25s
```

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

```
All checks passed!
26 files already formatted
```

What the tests cover (in `tests/`):

| File | Covers |
|---|---|
| `test_ingest.py` | Surefire and pytest XML parsing, outcomes, exception-type splitting |
| `test_signatures.py` | normalization cases, frame extraction, grouping behaviour, frame depth |
| `test_flakiness.py` | flip-rate math, streaks, first failing commit, flaky rules |
| `test_clustering.py` | evidence for each planted scenario in the sample data |
| `test_llm.py` | mock classifier per scenario; Anthropic classifier with a fake client (success, refusal, API error); provider selection |
| `test_graph.py` | end-to-end graph run, threshold routing, the "no failures" path |
| `test_report.py` | report sections, bug drafts, repro commands |
| `test_issues.py` | dry-run, create, skip-if-exists, HTTP error, with `httpx.MockTransport` (no network) |
| `test_cli.py` | the CLI writes all the expected files |

Run one file, or one test by name:

```bash
.venv/bin/pytest tests/test_flakiness.py -v
.venv/bin/pytest -k same_commit_flip_rate -v
```

The project's own CI (`.github/workflows/ci.yml`) runs these, then runs the demo and
`diff`s it against `docs/sample-triage-report.md`. If a behaviour change alters the report,
CI fails until the sample report is regenerated and committed:

```bash
.venv/bin/triage run --input sample_data --out reports/ && cp reports/triage-report.md docs/sample-triage-report.md
```

## 7. Try some options

```bash
# Stricter review threshold: more items go to human review
.venv/bin/triage run -i sample_data -o /tmp/r --threshold 0.9
# runs: 9  signatures: 6  needs review: 4

# Two stack frames per signature instead of one: the three DB tests stop grouping together
.venv/bin/triage run -i sample_data -o /tmp/r --frame-depth 2
# runs: 9  signatures: 8  needs review: 1
```

## 8. Switch to the real LLM

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # never commit this; put it in your shell, not a file in the repo
.venv/bin/triage run --input sample_data --out reports/
```

When the key is set, the provider defaults to `anthropic` and the first output line becomes
`classifier: anthropic:claude-sonnet-5-5`. Optional settings:

```bash
export LLM_MODEL=claude-opus-5-5     # use a different model
export LLM_PROVIDER=mock             # force mock mode even with a key set
.venv/bin/triage run -i sample_data -o reports --provider anthropic --model claude-sonnet-5-5
```

The real model writes its own rationales and confidences, so the numbers will differ
from the mock output above. If an API call fails, or the model declines, that group gets
confidence 0.0 and appears under "Needs human review". The run does not crash.

Filing real GitHub issues (to a scratch repo first):

```bash
export GITHUB_TOKEN=ghp_...           # token with issues:write on the target repo
.venv/bin/triage run -i sample_data -o reports --no-dry-run --repo your-user/scratch-repo
```

Run it twice. The second time, each issue should report `exists` instead of `created`. This behaviour
is covered by `tests/test_issues.py` against a mocked GitHub API. It has not been run against
real GitHub from this repo.

## 9. Troubleshooting

These are problems that came up, or were reproduced, while building and testing this project.

**`ERROR: Package 'ci-failure-triage-agent' requires a different Python: 3.9.6 not in '>=3.12'`**
The venv was created with the macOS system Python. Delete it and recreate it with 3.12:
`rm -rf .venv && python3.12 -m venv .venv`.

**`zsh: command not found: triage`**
The venv isn't activated. Use `.venv/bin/triage` or run `source .venv/bin/activate`.

**`Invalid value for --provider: LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY (or use LLM_PROVIDER=mock)`**
You asked for the real LLM (`--provider anthropic` or `LLM_PROVIDER=anthropic`) without a key in
the environment. Export the key in the same shell, or drop the option to use mock mode.
Before this check existed, the same situation crashed deep inside the SDK with
`TypeError: Could not resolve authentication method`.

**`Invalid value for '--input' / '-i': Directory 'nope' does not exist.`**
The path is relative to where you run the command. Run from the repo root, or pass an absolute path.

**`FileNotFoundError: no */run.json found under ...`**
The input folder must contain `runs/<run_id>/run.json` (or `<run_id>/run.json` directly).
JUnit XML without a `run.json` is not picked up, because the tool needs the commit and timestamp.

**CI fails on "Committed sample report is up to date"**
You changed behaviour that affects the report. Regenerate `docs/sample-triage-report.md`
(command in step 6) and commit it together with the code change.

**pytest warns `cannot collect test class 'TestResult' because it has a __init__ constructor`**
pytest tries to collect any class whose name starts with `Test`. The models `TestResult` and
`TestHistory` set `__test__ = False` to prevent this. Keep that line if you add a similar model.

**ruff reports `E501 Line too long` in `scripts/generate_sample_data.py`**
The long lines are stack-trace string literals. E501 is disabled in `pyproject.toml` and
`ruff format` handles line length for code instead. If you re-enable E501, expect these hits.

**Regenerating the sample data changed nothing**
That's expected. `scripts/generate_sample_data.py` is seeded and deterministic. Change the scenario
constants at the top of the script (for example `FLAKY_RUNS`) to change the data.
