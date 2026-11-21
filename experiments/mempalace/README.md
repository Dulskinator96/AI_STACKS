# MemPalace — real-model Tomb 1 recall gate

Upstream foundation: [MemPalace/mempalace](https://github.com/MemPalace/mempalace), version 3.12.0. This branch tests the pyramid/tomb concept without changing upstream source.

## Scope

Two **real, distinct** local LLMs interact in Tomb 1 under the same instructions. Their actual messages are stored in the real MemPalace index. Model B subsequently generates a new message assigned to Tomb 2. The Tomb 1 history is preserved, then Model A is called afresh to answer a factual question using retrieved memory.

- Model A: `qwen2.5:0.5b`.
- Model B: `smollm2:135m`.
- Local LLM engine: Ollama.
- Memory engine: real MemPalace `mine`, scoped `search`, and `export`.
- Storage: disposable temporary palace, with no user data and no cloud model API.
- GitHub Actions: workflow installs both real models, calls them, and uploads evidence.

## What is tested

1. B produces an actual message containing a randomized historical identifier.
2. A actually reads B's message and repeats that identifier.
3. MemPalace stores both model responses and retrieves their shared history.
4. B is reassigned to Tomb 2 and generates new post-move memory.
5. A fresh A inference, with no memory, is used as a baseline.
6. A separate fresh A inference reads only the **scoped** Tomb 1 MemPalace retrieval and answers about B's historical identifier.
7. Export is checked for both exact original memory identifiers.
8. Test returns PASS only if A recalls the identifier with memory, but not without it.

This proves retrieval-augmented historical recall if it passes. It does **not** prove internal weight learning, physical model-process migration, consciousness, or unauthorized cross-tomb knowledge. Wings are organizational search scopes, not security boundaries.

## How to view real execution

Select the branch `experiment/mempalace-tomb-memory-v1` in GitHub Actions, view **MemPalace real LLM tomb experiment**, and open its uploaded `mempalace-real-llm-evidence` JSON. A committed workflow file alone is not a run.

## Local equivalent

```bash
python -m pip install mempalace==3.12.0
ollama serve
ollama pull qwen2.5:0.5b
ollama pull smollm2:135m
python experiments/mempalace/tomb_relocation.py --report mempalace-result.json
```

## Qualification

Do not promote until there is a completed green GitHub Actions run and examined evidence. Single-run success is only feasibility; reliability requires repeated fresh runs and documented failure modes.

## Execution trigger

The live-model GitHub Actions gate is requested for execution. A workflow `push` event on this experimental branch is used to trigger the configured test; successful completion must be established separately from the commit.

## Stage 2: Genuine model collaboration using associated knowledge

Runner: `knowledge_collaboration.py`. Calls two Ollama LLMs and the actual upstream MemPalace CLI. The models each hold only one fact: A knows PROJECT -> BRIDGE, and B knows BRIDGE -> TARGET. Each fact and each live model acknowledgment is indexed in its own MemPalace wing.

The evaluation requires BOTH single-model attempts to fail at retrieving the full answer, then performs an explicit, auditable handoff: A reads its indexed memory and selects BRIDGE; B looks up its own memory for the corresponding TARGET; A uses B's answer to produce the final TARGET. The exact output must match. It reports each original model response, stage correctness, latency and SHA-256 of governing instructions.

A successful test would demonstrate retrieval-assisted collaboration between the two genuine LLMs. It does **not** demonstrate spontaneous knowledge transfer, the models updating their weights, or a shared consciousness. One trial establishes feasibility, not an 80% reliability estimate. Further repetitions and varied tasks are required before promotion.

```bash
python experiments/mempalace/knowledge_collaboration.py \
  --model-a qwen2.5:0.5b --model-b smollm2:135m \
  --report mempalace-collaboration.json
```

GitHub Actions runs the collaboration gate separately from the historical-recall stage and retains separate evidence.
