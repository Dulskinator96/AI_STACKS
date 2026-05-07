# core/brief_engine.py — WON structured brief + plan generator
from datetime import datetime

_DATE = lambda: datetime.utcnow().strftime("%Y-%m-%d")
_TS   = lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


class BriefEngine:
    def __init__(self, brain, research, obsidian, memory):
        self._brain    = brain
        self._research = research
        self._obsidian = obsidian
        self._memory   = memory

    # ── Full project brief ─────────────────────────────────────────────────

    def generate(self, project: str, tracker) -> dict:
        proj_data = tracker.get(project) or {"name": project, "phase": "1", "description": ""}
        phase     = proj_data.get("phase", "1")

        # Pull relevant memory
        mem_entries = self._memory.search(project, limit=6)
        mem_block   = "\n".join(e.get("content","")[:200] for e in mem_entries) or "No prior memory."

        # Pull public intel
        research_results = self._research.pull(f"{project} AI development 2024", max_results=3)
        research_block   = "\n".join(f"- {r['title']}: {r['summary'][:120]}" for r in research_results)

        # Brain synthesis
        brain_prompt = (
            f"Project: {project}\nPhase: {phase}\n"
            f"Description: {proj_data.get('description','')}\n\n"
            f"Prior memory context:\n{mem_block}\n\n"
            f"Public source intel:\n{research_block}\n\n"
            "Generate a structured brief with:\n"
            "1. What It Is / What It Does (2-3 sentences)\n"
            "2. What Has Been Done (bullet points)\n"
            "3. Three pinpointed forward concepts with probability rationale\n"
            "Be precise. No filler. Dense and actionable."
        )
        synthesis = self._brain.reason(brain_prompt, context=self._memory.recall_context(4))

        # Build display version
        display = (
            f"PROJECT: {project.upper()}\n"
            f"Phase {phase}  ·  {_TS()}\n"
            f"{'─'*50}\n"
            f"{synthesis}"
        )

        # Build markdown for Obsidian
        sources_md = "\n".join(f"- [{r['title']}]({r['url']})" for r in research_results if r.get('url'))
        markdown = f"""---
created: {_DATE()}
project: {project}
phase: {phase}
type: brief
agent: WON — DBOMB ASCENDENT
---

# Brief — {project}
*Generated: {_TS()}*

{synthesis}

## Public Sources Referenced
{sources_md or '_No sources retrieved._'}

## Memory Entries Referenced
{len(mem_entries)} prior entries searched.

---
*Brief by WON — DBOMB ASCENDENT*
"""
        # Write research note too
        if research_results:
            self._obsidian.write_research(project, research_results)

        return {"display": display, "markdown": markdown}

    # ── Project plan ──────────────────────────────────────────────────────

    def generate_plan(self, project: str, tracker, predictor, memory) -> str:
        proj_data   = tracker.get(project) or {"name": project, "phase": "1", "description": ""}
        phase       = int(proj_data.get("phase", 1))
        suggestions = predictor.suggest(memory, tracker, count=3)

        brain_prompt = (
            f"Build a detailed execution plan for: {project}\n"
            f"Current ACAS Phase: {phase}\n"
            f"Description: {proj_data.get('description','')}\n\n"
            "Include: immediate actions (this week), short-term milestones (30 days), "
            "phase completion criteria, dependencies, and risks.\n"
            "Format as structured actionable steps. Be precise."
        )
        plan_body = self._brain.reason(brain_prompt, context=memory.recall_context(4))

        vectors_md = ""
        for i, s in enumerate(suggestions, 1):
            vectors_md += f"{i}. **{s['concept']}** — {s['probability']:.0%}\n   {s['rationale']}\n\n"

        return f"""---
created: {_DATE()}
project: {project}
phase: {phase}
type: plan
agent: WON — DBOMB ASCENDENT
---

# Plan — {project}
*Generated: {_TS()}*

## Execution Plan
{plan_body}

## Forward Vectors (Probability-Weighted)
{vectors_md}

## Phase Progress
- Current Phase: {phase}
- Next Phase: {phase + 1 if phase < 4 else 'Deployment'}

---
*Plan by WON — DBOMB ASCENDENT*
"""
