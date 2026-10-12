# QA Daily Agent

A beginner-friendly LLM QA agent project. It analyzes a bug description and produces:
- bug title
- priority
- risk
- QA test cases
- confidence
- human-review decision

This project is intentionally simple so you can learn LLM concepts before studying a larger LangGraph agent.

## 1. Setup

Requires Python 3.12+.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## 2. Configure Claude

Copy `.env.example` to `.env` and put your Anthropic API key in it.

```bash
cp .env.example .env
```

Then edit `.env`.

The application reads:
- `ANTHROPIC_API_KEY`
- `LLM_MODEL`

## 3. Run

```bash
.venv/bin/qa-agent --help
.venv/bin/qa-agent analyze "When I enter an invalid password, the login page keeps spinning and never shows an error."
```

Or use the included sample:

```bash
.venv/bin/qa-agent analyze-file sample_data/bug.txt
```

## 4. Run tests

```bash
.venv/bin/pytest
```

## Architecture

```text
CLI
 ↓
agent.py
 ↓
llm.py
 ↓
Structured QAAnalysis
 ↓
confidence check
 ↓
READY or HUMAN_REVIEW
```

## Concepts practiced

LLM, prompts, system prompt, user prompt, API, structured output, Pydantic, confidence, hallucination prevention, deterministic logic, and human-in-the-loop.
