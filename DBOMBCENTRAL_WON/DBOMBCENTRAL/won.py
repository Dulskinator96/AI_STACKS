# won.py — DBOMB ASCENDENT WON  |  ACAS-Phase1-v1.1
# Specialist advisor agent operating under CENTCOM Cortex.
# Free. Local. No paid API required.

import os
from datetime import datetime
from rich.console import Console
from rich.rule import Rule
from rich.panel import Panel
from rich.table import Table
from rich import box

from core.brain import Brain
from core.memory import WONMemory
from core.researcher import Researcher
from core.obsidian import ObsidianWriter
from core.brief_engine import BriefEngine
from core.predictor import Predictor
from core.project_tracker import ProjectTracker
from core.centcom import CENTCOMCortex
from core.agent_registry import get_by_phase, summary as agent_summary
import yaml

console = Console()

IDENTITY = {
    "name":       "WON",
    "full":       "DBOMB ASCENDENT WON",
    "build":      "ACAS-Phase1-v1.1",
    "author":     "DBOMBCENTRAL",
    "department": "CORE",
    "tier":       "Specialist Agent",
    "reports_to": "CENTCOM Cortex",
}

BANNER = """
██╗    ██╗ ██████╗ ███╗   ██╗
██║    ██║██╔═══██╗████╗  ██║
██║ █╗ ██║██║   ██║██╔██╗ ██║
██║███╗██║██║   ██║██║╚██╗██║
╚███╔███╔╝╚██████╔╝██║ ╚████║
 ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═══╝
  DBOMB ASCENDENT — AGENT WON
  Reports to: CENTCOM CORTEX
"""

COMMANDS = {
    "<prompt>":        "Reason, analyze, or advise on any input",
    "brief <project>": "Generate a full structured brief → Obsidian",
    "research <query>":"Pull structured intel from public sources",
    "track":           "Show ACAS phase progress",
    "centcom":         "Full CENTCOM Cortex department + agent overview",
    "agents":          "Show agent registry — active and planned",
    "suggest":         "3 probability-weighted next-step vectors",
    "plan <project>":  "Build execution plan note in Obsidian",
    "memory [n]":      "Recall last n memory entries (default 10)",
    "search <query>":  "Full-text search across all WON memory",
    "projects":        "List all tracked projects and phases",
    "new project":     "Register a new project",
    "history":         "Show session command history",
    "status":          "Full WON + CENTCOM status dashboard",
    "vault":           "Open Obsidian vault location",
    "help":            "Show this list",
    "quit":            "Save all state and exit",
}


def load_config(path="configs/won_settings.yaml"):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing: {path}")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def startup_brief(memory, tracker, predictor):
    s = memory.session_summary()
    if s["total_entries"] == 0:
        console.print("[dim]  First boot — WON memory initialised.[/dim]")
        return
    console.print(Rule("[bold cyan]LAST SESSION INTEL[/bold cyan]"))
    console.print(f"  [dim]Entries:[/dim] [cyan]{s['total_entries']}[/cyan]  "
                  f"[dim]Sessions:[/dim] [cyan]{s['session_count']}[/cyan]  "
                  f"[dim]Top modes:[/dim] [cyan]{s['top_modes']}[/cyan]")
    if s.get("last_brief"):
        console.print(Panel(s["last_brief"], title="[magenta]Prior Brief[/magenta]", border_style="dim"))
    suggestions = predictor.suggest(memory, tracker, count=3)
    if suggestions:
        console.print(Rule("[bold yellow]FORWARD VECTORS[/bold yellow]"))
        for i, sv in enumerate(suggestions, 1):
            bar = "█" * int(sv["probability"] * 10) + "░" * (10 - int(sv["probability"] * 10))
            console.print(f"  [yellow]{i}.[/yellow] [bold]{sv['concept']}[/bold]  "
                          f"[green][{bar}][/green] [cyan]{sv['probability']:.0%}[/cyan]")
            console.print(f"     [dim]{sv['rationale']}[/dim]")
    console.print()


def print_status(memory, tracker, brain, obsidian):
    console.print(Rule("[bold cyan]WON STATUS — DBOMBCENTRAL[/bold cyan]"))
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 3))
    t.add_column("k", style="dim")
    t.add_column("v", style="cyan")
    t.add_row("Identity",     IDENTITY["full"])
    t.add_row("Build",        IDENTITY["build"])
    t.add_row("Department",   IDENTITY["department"])
    t.add_row("Reports to",   IDENTITY["reports_to"])
    t.add_row("Brain",        f"{brain.model}  ({'online' if brain.ping() else 'offline — template mode'})")
    t.add_row("Memory",       f"{memory.count()} entries  ·  {memory.session_count()} sessions")
    t.add_row("Projects",     str(tracker.count()))
    asumm = agent_summary()
    t.add_row("Agent registry", f"{asumm['total']} total  ·  {asumm['active']} active  ·  "
                                f"Ph2: {asumm['by_phase'][2]} planned")
    t.add_row("Vault",        obsidian.vault_path or "not configured")
    console.print(t)


def print_memory_entries(entries, title="Memory Recall"):
    console.print(Rule(f"[bold]{title}[/bold]"))
    if not entries:
        console.print("  [dim]Nothing found.[/dim]")
        return
    for e in entries:
        score   = f"{e['score']:.2f}" if e.get("score") else "—"
        content = e.get("content", "")
        preview = (content[:200] + "…") if len(content) > 200 else content
        console.print(f"  [dim]{e.get('timestamp','')[:19]}[/dim]  [cyan]{e.get('mode','')}[/cyan]  [green]{score}[/green]")
        console.print(f"  {preview}\n")


def run():
    os.makedirs("data", exist_ok=True)
    os.makedirs("configs", exist_ok=True)

    config    = load_config()
    memory    = WONMemory(path=config.get("memory_path", "data/won_memory.db"))
    brain     = Brain(model=config.get("ollama_model", "llama3.2"), timeout=config.get("timeout", 90))
    research  = Researcher()
    obsidian  = ObsidianWriter(vault_path=config.get("obsidian_vault", ""))
    tracker   = ProjectTracker(path=config.get("projects_path", "data/projects.json"))
    predictor = Predictor()
    brief_eng = BriefEngine(brain=brain, research=research, obsidian=obsidian, memory=memory)
    centcom   = CENTCOMCortex(tracker=tracker, memory=memory, predictor=predictor)

    session_id  = memory.open_session()
    session_log = []

    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print(f"  [dim]Build:[/dim]   {IDENTITY['build']}")
    console.print(f"  [dim]Brain:[/dim]   {brain.model}  ·  "
                  f"{'[green]Online[/green]' if brain.ping() else '[yellow]Offline — template mode[/yellow]'}")
    console.print(f"  [dim]Memory:[/dim]  {memory.count()} entries  ·  {tracker.count()} projects")
    console.print(f"  [dim]Vault:[/dim]   {obsidian.vault_path or '[red]Not set — update configs/won_settings.yaml[/red]'}")
    console.print()

    startup_brief(memory, tracker, predictor)
    console.print(Rule("[dim]Type [bold]help[/bold] for commands[/dim]"))

    try:
        while True:
            try:
                raw = console.input("[bold cyan]WON ›[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                raw = "quit"

            if not raw:
                continue

            cmd = raw.lower()
            session_log.append({"time": datetime.utcnow().isoformat(), "input": raw})

            if cmd in ("quit", "exit"):
                break

            elif cmd == "help":
                t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
                t.add_column("cmd",  style="cyan", no_wrap=True)
                t.add_column("desc", style="dim")
                for k, v in COMMANDS.items():
                    t.add_row(k, v)
                console.print(t)

            elif cmd == "status":
                print_status(memory, tracker, brain, obsidian)

            elif cmd == "centcom":
                centcom.print_full(console)

            elif cmd == "agents":
                t = Table(title="DBOMBCENTRAL Agent Registry", box=box.SIMPLE_HEAVY)
                t.add_column("Agent",       style="bold cyan")
                t.add_column("Tier",        style="dim",    justify="center")
                t.add_column("Phase",       style="yellow", justify="center")
                t.add_column("Status",      style="green")
                t.add_column("Dept",        style="dim")
                t.add_column("Capabilities", style="dim")
                for phase in [1, 2, 3, 4]:
                    for a in get_by_phase(phase):
                        sc = "green" if a.status == "active" else ("yellow" if a.status == "planned" else "dim")
                        t.add_row(a.name, a.role, str(a.phase),
                                  f"[{sc}]{a.status}[/{sc}]",
                                  a.department, ", ".join(a.capabilities[:3]))
                console.print(t)

            elif cmd == "track":
                tracker.print_phases(console)

            elif cmd == "projects":
                tracker.print_projects(console)

            elif cmd == "new project":
                name  = console.input("  [cyan]Project name:[/cyan] ").strip()
                phase = console.input("  [cyan]Current phase (1-4):[/cyan] ").strip()
                desc  = console.input("  [cyan]Description:[/cyan] ").strip()
                tracker.add_project(name, phase, desc)
                obsidian.write_project_stub(name, phase, desc)
                memory.store(f"Registered project: {name} (Phase {phase})", "project",
                             tags=["project", name.lower()])
                console.print(f"  [green]✓ {name} registered and noted in Obsidian.[/green]")

            elif cmd.startswith("memory"):
                parts = cmd.split()
                n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
                print_memory_entries(memory.recall(limit=n))

            elif cmd.startswith("search "):
                query = raw[7:].strip()
                print_memory_entries(memory.search(query, limit=8), title=f"Search: {query}")

            elif cmd.startswith("research "):
                query = raw[9:].strip()
                console.print(f"  [dim]Pulling intel:[/dim] [bold]{query}[/bold]")
                with console.status("[cyan]Researching…[/cyan]"):
                    results = research.pull(query, max_results=5)
                console.print(Rule("[bold]Research Intel[/bold]"))
                for r in results:
                    console.print(Panel(
                        f"[bold]{r['title']}[/bold]\n[dim]{r['url']}[/dim]\n\n{r['summary']}",
                        border_style="dim"))
                obsidian.write_research(query, results)
                memory.store("Research: " + query + "\n" + "\n".join(r["summary"] for r in results),
                             "research", tags=["research", query.split()[0]])
                console.print(f"  [green]✓ Research saved to Obsidian.[/green]")

            elif cmd == "suggest":
                suggestions = predictor.suggest(memory, tracker, count=3)
                console.print(Rule("[bold yellow]PROBABILITY-WEIGHTED VECTORS[/bold yellow]"))
                for i, sv in enumerate(suggestions, 1):
                    bar = "█" * int(sv["probability"] * 10) + "░" * (10 - int(sv["probability"] * 10))
                    console.print(Panel(
                        f"[bold]{sv['concept']}[/bold]\n[dim]{sv['rationale']}[/dim]\n"
                        f"[green][{bar}][/green]  [cyan]{sv['probability']:.0%}[/cyan]  ·  Phase {sv.get('phase','-')}",
                        title=f"[yellow]Vector {i}[/yellow]", border_style="yellow"))

            elif cmd.startswith("brief"):
                project = raw[5:].strip() or "DBOMBCENTRAL"
                console.print(f"  [dim]Generating brief:[/dim] [bold]{project}[/bold]")
                with console.status("[cyan]Building brief…[/cyan]"):
                    brief = brief_eng.generate(project, tracker)
                console.print(Panel(brief["display"],
                                    title=f"[magenta]BRIEF — {project.upper()}[/magenta]",
                                    border_style="magenta"))
                obsidian.write_brief(project, brief["markdown"])
                memory.store(brief["display"], "brief", tags=["brief", project.lower()])
                console.print(f"  [green]✓ Brief saved to Obsidian.[/green]")

            elif cmd.startswith("plan "):
                project = raw[5:].strip()
                with console.status("[cyan]Building plan…[/cyan]"):
                    plan_md = brief_eng.generate_plan(project, tracker, predictor, memory)
                obsidian.write_plan(project, plan_md)
                memory.store(f"Plan generated for {project}", "plan", tags=["plan", project.lower()])
                console.print(f"  [green]✓ Plan written to Obsidian: Plans/{project}.md[/green]")

            elif cmd == "history":
                for entry in session_log[-20:]:
                    console.print(f"  [dim]{entry['time'][:19]}[/dim]  {entry['input']}")

            elif cmd == "vault":
                vp = obsidian.vault_path
                if vp and os.path.exists(vp):
                    if os.name == "nt":
                        os.startfile(vp)
                    else:
                        console.print(f"  [cyan]{vp}[/cyan]")
                else:
                    console.print(f"  [red]Vault not found:[/red] {vp}")

            else:
                ctx = centcom.get_phase_context()
                with console.status("[cyan]Reasoning…[/cyan]"):
                    response = brain.reason(
                        prompt=f"[CENTCOM Context]\n{ctx}\n\n[Query]\n{raw}",
                        context=memory.recall_context(limit=5),
                        identity=IDENTITY,
                    )
                console.print(Panel(response, border_style="cyan"))
                memory.store(f"Q: {raw}\nA: {response}", "reasoning", tags=["reasoning"])

    finally:
        suggestions = predictor.suggest(memory, tracker, count=3)
        final_brief = (f"Session {session_id} closed. "
                       f"{memory.count()} total memory entries. "
                       f"{tracker.count()} projects tracked. "
                       f"ACAS Phase 1 active.")
        obsidian.write_session_summary(session_id, final_brief, suggestions)
        obsidian.update_dashboard(memory.session_summary(), tracker.all(), suggestions)
        memory.close_session(session_id, log=session_log, brief=final_brief)
        memory.save_snapshot()
        console.print(f"\n  [dim]WON offline. Dashboard updated. Session {session_id} closed.[/dim]\n")


if __name__ == "__main__":
    run()
