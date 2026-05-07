# core/obsidian.py — WON Obsidian vault integration
"""
Writes structured markdown notes directly into the Obsidian vault.
No plugin required — Obsidian reads any markdown file in the vault folder.
"""
import os
import requests
import json
from datetime import datetime

_TS = lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
_DATE = lambda: datetime.utcnow().strftime("%Y-%m-%d")


class ObsidianWriter:
    def __init__(self, vault_path: str = "", api_key: str = "", vault_id: str = "5a003f3531e82371"):
        self.vault_path = vault_path or os.path.expanduser("~/Documents/WON-Vault")
        self.api_key = api_key or os.environ.get("OBSIDIAN_API_KEY", "")
        self.vault_id = vault_id
        # Use host.docker.internal to reach Obsidian on the host machine from the container
        self.api_url = os.environ.get("OBSIDIAN_API_URL", "https://host.docker.internal:27124")
        self._ensure_structure()

    def get_obsidian_url(self, rel_path: str) -> str:
        """Generate an obsidian:// URI for a note."""
        import urllib.parse
        clean_path = rel_path.replace("\\", "/")
        encoded_path = urllib.parse.quote(clean_path)
        return f"obsidian://open?vault={self.vault_id}&file={encoded_path}"

    def organize_vault(self):
        """Automatically organize the vault into logical hierarchies."""
        print("[Obsidian] Running vault organization routine...")
        # Placeholder for more complex organization logic
        self._ensure_structure()
        return True

    def apply_theme_settings(self, theme_config: dict):
        """Update Obsidian appearance settings via API if possible."""
        if not self.api_key:
            return False
        # The Local REST API might not support theme changes directly,
        # but we can write to .obsidian/appearance.json if we have FS access.
        try:
            app_json = os.path.join(self.vault_path, ".obsidian", "appearance.json")
            if os.path.exists(os.path.dirname(app_json)):
                with open(app_json, "w", encoding="utf-8") as f:
                    json.dump(theme_config, f, indent=2)
                print(f"[Obsidian] Theme configuration updated: {theme_config.get('theme')}")
                return True
        except Exception as e:
            print(f"[Obsidian] Failed to apply theme: {e}")
        return False

    def _ensure_structure(self):
        """Ensure directories exist for filesystem fallback."""
        if not os.path.exists(self.vault_path):
            try:
                os.makedirs(self.vault_path, exist_ok=True)
            except Exception:
                pass
        for sub in ["Briefs", "Plans", "Projects", "Research", "Memory", "Sessions"]:
            path = os.path.join(self.vault_path, sub)
            if not os.path.exists(path):
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception:
                    pass

    def _write(self, rel_path: str, content: str):
        """Write note via Obsidian API, fallback to filesystem."""
        success = False
        
        # 1. Attempt API write if key is available
        if self.api_key:
            try:
                # Obsidian Local REST API uses HTTPS on 27124 by default with a self-signed cert
                url = f"{self.api_url}/vault/{rel_path}"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "text/markdown"
                }
                # verify=False because of self-signed certs common in local dev
                resp = requests.put(url, data=content.encode("utf-8"), headers=headers, verify=False, timeout=5)
                if resp.status_code in (200, 201, 204):
                    print(f"[Obsidian] API write success: {rel_path}")
                    success = True
                else:
                    print(f"[Obsidian] API write failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                print(f"[Obsidian] API error: {e}")

        # 2. Fallback to direct filesystem write
        if not success:
            try:
                full = os.path.join(self.vault_path, rel_path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"[Obsidian] Filesystem write success: {full}")
            except Exception as e:
                print(f"[Obsidian] Filesystem write error: {e}")

    # ── Project stub ───────────────────────────────────────────────────────

    def write_project_stub(self, name: str, phase: str, description: str):
        md = f"""---
created: {_DATE()}
agent: WON — DBOMB ASCENDENT
type: project
phase: {phase}
status: active
---

# {name}

## What It Is / What It Does
{description}

## ACAS Phase Alignment
- **Current Phase:** {phase}
- **Phase Target:** See [[WON Dashboard]]

## Progress Log
| Date | Action | Notes |
|------|--------|-------|
| {_DATE()} | Project registered | Initial stub created by WON |

## Notes


---
*Documented by WON — {_TS()}*
"""
        self._write(f"Projects/{name}.md", md)

    # ── Brief ──────────────────────────────────────────────────────────────

    def write_brief(self, project: str, markdown: str):
        date_str = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
        self._write(f"Briefs/{project}_{date_str}.md", markdown)

    # ── Plan ───────────────────────────────────────────────────────────────

    def write_plan(self, project: str, markdown: str):
        self._write(f"Plans/{project}.md", markdown)

    # ── Research note ──────────────────────────────────────────────────────

    def write_research(self, query: str, results: list[dict]):
        date_str = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
        lines = [
            f"---\ncreated: {_DATE()}\ntype: research\nquery: \"{query}\"\nagent: WON\n---\n",
            f"# Research: {query}\n*{_TS()}*\n",
        ]
        for i, r in enumerate(results, 1):
            lines.append(f"\n## Source {i}: {r['title']}\n")
            lines.append(f"**URL:** {r['url']}\n\n{r['summary']}\n")
        lines.append(f"\n---\n*Researched by WON — {_TS()}*")
        self._write(f"Research/{query[:40]}_{date_str}.md", "\n".join(lines))

    # ── Session summary ────────────────────────────────────────────────────

    def write_session_summary(self, session_id: str, brief: str, suggestions: list[dict]):
        lines = [
            f"---\ncreated: {_DATE()}\ntype: session\nsession_id: {session_id}\nagent: WON\n---\n",
            f"# Session Summary — {session_id}\n*{_TS()}*\n\n",
            f"## Brief\n{brief}\n\n",
            "## Forward Vectors\n",
        ]
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. **{s['concept']}** ({s['probability']:.0%})\n   {s['rationale']}\n")
        lines.append(f"\n---\n*Logged by WON — {_TS()}*")
        self._write(f"Sessions/{session_id}.md", "\n".join(lines))

    # ── Dashboard (overwrite on each run) ─────────────────────────────────

    def update_dashboard(self, stats: dict, projects: list, suggestions: list):
        lines = [
            f"---\ncreated: {_DATE()}\ntype: dashboard\nagent: WON\n---\n",
            "# WON Dashboard — DBOMB ASCENDENT\n",
            f"*Last updated: {_TS()}*\n\n",
            f"## Memory\n- Entries: {stats.get('total_entries',0)}\n- Sessions: {stats.get('session_count',0)}\n\n",
            "## Active Projects\n",
        ]
        for p in projects:
            lines.append(f"- [[Projects/{p['name']}|{p['name']}]] — Phase {p['phase']} — {p['status']}\n")
        lines.append("\n## Next Vectors\n")
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. **{s['concept']}** — {s['probability']:.0%}\n")
        lines.append(f"\n---\n*WON — DBOMB ASCENDENT — {_TS()}*")
        self._write("WON Dashboard.md", "\n".join(lines))
