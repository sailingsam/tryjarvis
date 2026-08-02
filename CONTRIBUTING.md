# Contributing

Mantrin is a personal chief of staff you talk to. Before writing code, skim
[docs/foundation](docs/foundation/) — especially [the philosophy](docs/foundation/2_philosophy.md).
It's short, and most review feedback here is one of its principles restated.

## Setup

```bash
git clone https://github.com/sailingsam/tryjarvis.git && cd tryjarvis
python3 -m venv .venv
./.venv/bin/pip install -e ".[all]"   # core + voice + both local providers
export ANTHROPIC_API_KEY=...          # the brain runs on Claude

./.venv/bin/mantrin setup             # pick ears/voice; local defaults are free
./.venv/bin/mantrin                   # say "hey jarvis"
```

Useful while developing:

```bash
./.venv/bin/mantrin daemon --timings  # foreground, with per-stage timings
./.venv/bin/mantrin --text            # keyboard in, text out
./.venv/bin/mantrin memory            # what it knows, and why
```

## The rules that matter

- **The Human PA Test.** Before shipping any behaviour, ask: would a sharp
  human assistant do it this way? A person never reads a 14-digit id aloud,
  never mistakes "no, I said yes" for a refusal, never asks twice for
  permission already given.
- **Rules first, AI second.** Deterministic code for what code can decide;
  a model only where language genuinely needs understanding.
- **Everything rented is replaceable.** LLM, STT, TTS, embeddings all sit
  behind interfaces. A new voice provider is one class with one method plus a
  line in `providers/voice_registry.py`. What's ours is the memory and the
  understanding built on it.
- **Design lives in docstrings.** Each module's docstring says why it exists
  and what it refuses to do. Update it when your change makes it wrong —
  a fix ships twice, code and docs.

## Sending changes

- Small PRs, one behaviour each. For anything large, open an issue first —
  the big roadmap features are usually already in motion.
- Say how you verified it. There is no formal test suite yet; for voice
  changes paste the session transcript or `--timings` line that shows the
  behaviour. Transcripts are this repo's bug reports.
- Match the surrounding code. Comments say *why*, not *what*.
- Reference issues (`fixes #5`) so they close on merge.

Good starting points are labelled
[good first issue](https://github.com/sailingsam/tryjarvis/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## License and the CLA

Mantrin is licensed [FSL-1.1-ALv2](LICENSE.md) — free to use, modify and
self-host; not to resell. Each release converts to Apache 2.0 two years on.

That conversion, and the paid cloud that funds this work, both need one
thing from contributors: a one-time [CLA](CLA.md). You keep ownership of
your code; you grant the right to ship it under the Project's licenses. On
your first PR a bot will ask — signing is replying with one sentence, once,
and it covers everything after.
