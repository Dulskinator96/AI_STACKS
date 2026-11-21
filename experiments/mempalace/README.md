# MemPalace — Tomb Relocation Experiment (Stage 1)

**Scope:** Test whether shared memory originally stored in Tomb 1 remains searchable after Model B's membership is reassigned to Tomb 2.

**Source:** [MemPalace official README](https://github.com/MemPalace/mempalace/blob/develop/README.md) and [CLI documentation](https://github.com/MemPalace/mempalace/blob/develop/website/reference/cli.md).

This is an isolated experimental extension. It uses **real MemPalace `mine`, `search`, and `export` operations**, not a simulated storage layer.

## Experimental sequence

1. Represent two model identities, A and B, initially in Tomb 1.
2. Store a shared synthetic historical memory using MemPalace.
3. Search it and require exact marker recall.
4. Reassign B's membership to Tomb 2. **Retain** Tomb 1's historic memory.
5. Give Tomb 2 a separate synthetic post-relocation memory; index it with MemPalace.
6. Query Tomb 1 again and check the pre-move shared memory remains findable.
7. Verify Tomb 2 recall, no private-marker appearance in Tomb 1 scoped results, and verbatim archival export.

The test is **stage 1 only**. No live LLM, process migration, or machine-learning weight update occurs. Tomb/wings are organizational search scopes, **not security boundaries**. A query across *all* wings could retrieve both histories; access control requires a separately implemented mechanism.

A historical fact retained in a shared store is standard retrieval-augmented memory, not evidence of paranormal or unexplained knowledge transmission.

## Run

Python 3.10+; install official MemPalace 3.12.0 in an isolated environment. Download of the embedding model may be required on first execution.

```bash
python -m pip install mempalace==3.12.0
python experiments/mempalace/tomb_relocation.py --report result.json
```

The workflow at `.github/workflows/mempalace-tomb-test.yml` runs the same test on GitHub Actions and uploads a **sanitized synthetic** report. The report is not evidence of success unless the workflow concludes successfully.

**Pass gate:** both historical searches return the exact shared marker; Tomb 2 returns its post-move marker; the historical marker survives export; Tomb 1 scoped search does not reveal Tomb 2's marker. Fail closed on any error.

## Next stage (not authorized by a Stage-1 pass)

Attach actual LLM A and B adapters, preserve their prompt/response transcripts in MemPalace, evaluate blind factual question answering by A, and compare against a no-memory baseline. Do not confuse retrieval from a shared archive with internal model learning.
