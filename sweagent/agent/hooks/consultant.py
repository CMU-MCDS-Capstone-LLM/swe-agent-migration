"""
Interactive Consultant Hook (container-aware, clean)

- Uses env.execute_command to read files INSIDE the Docker container
- Supplies the consultant with real repo context:
  * Problem statement
  * Recent actions/observations
  * Contents of files the worker actually read (from tool observations)
  * Extra repo files sampled from disk (prioritizes config + .py, size-capped)
  * A shallow repo tree for orientation
- Injects concise, directional advice back to the worker
- Includes FORCE mode to trigger guidance early (for testing/demo)

NOTE: Keep hook-level flags (force_intervention, etc.) at the hook config level.
DO NOT put them inside the consultant_model config dict, or pydantic will error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Tuple, Union
import re

from sweagent.agent.hooks.abstract import AbstractAgentHook
from sweagent.agent.models import GenericAPIModelConfig, ModelConfig, get_model
from sweagent.tools.tools import ToolConfig
from sweagent.types import AgentInfo, StepOutput, TrajectoryStep
from sweagent.utils.log import get_logger

if TYPE_CHECKING:
    from sweagent.agent.agents import DefaultAgent


# ------------------------------
# Stuck Detector (simple & conservative)
# ------------------------------
class StuckDetector:
    def is_stuck(
        self, traj: List[TrajectoryStep], window: int = 8, force_trigger: bool = False
    ) -> Tuple[bool, str]:
        if len(traj) < 5 and not force_trigger:
            return (False, "Too early")

        # FORCE MODE: Ultra-aggressive for testing
        if force_trigger:
            if len(traj) >= 2:
                return (True, "FORCE TRIGGER: Testing consultant intervention")

        recent = traj[-window:]
        actions = [s.get("action", "") for s in recent]
        obs = [s.get("observation", "") for s in recent]

        err_cnt = sum(1 for o in obs if "error" in o.lower() or "failed" in o.lower())
        edit_cnt = sum(
            1
            for a in actions
            if any(t in a for t in ("edit_file", "str_replace", "write_file"))
        )
        read_cnt = sum(1 for a in actions if "read_file" in a)
        file_ops = [
            a
            for a in actions
            if any(
                t in a for t in ("read_file", "edit_file", "str_replace", "write_file")
            )
        ]

        # Thrash: many reads, no edits for a while
        if read_cnt >= 4 and edit_cnt == 0:
            return (True, "Reading many files without making progress")
        # Implementation phase: multiple errors after edits
        if edit_cnt > 0 and err_cnt >= 2:
            return (True, "Multiple errors after edit attempts")
        # No file ops in a while
        if len(file_ops) == 0:
            return (True, "No file operations in recent steps")

        # NEW: Check for repeated identical actions (stuck in loop)
        if len(actions) >= 3:
            # Look for 3+ consecutive identical actions (even if "successful")
            consecutive_identical = 0
            for i in range(len(actions) - 1):
                if actions[i] == actions[i + 1] and actions[i].strip():
                    consecutive_identical += 1
                else:
                    consecutive_identical = 0
                if consecutive_identical >= 2:  # 3+ consecutive identical actions
                    return (
                        True,
                        f"Repeated identical action {consecutive_identical + 1} times: '{actions[i][:50]}...'",
                    )

            # Look for same action repeated with slight variations
            if len(actions) >= 4:
                unique_actions = list(set(actions))
                if (
                    len(unique_actions) <= 2
                ):  # Only cycling between 1-2 different actions
                    return (
                        True,
                        f"Cycling between few actions: {unique_actions}",
                    )

        return (False, "")


# ------------------------------
# Interactive Consultant Hook
# ------------------------------
class InteractiveConsultantHook(AbstractAgentHook):
    """
    Container-aware consultant hook:
      - Resolves repo root *inside* the container
      - Reads files via env.execute_command
      - Builds compact, useful context for a stronger LLM consultant
    """

    def __init__(
        self,
        consultant_model_config: Union[dict[str, Any], ModelConfig],
        intervention_threshold: int = 6,
        max_interventions: int = 2,
        # context limits
        include_opened_limit: int = 6,
        include_extra_limit: int = 10,
        file_bytes_limit: int = 6000,
        # force/testing knobs
        force_intervention: bool = False,
        force_warmup_steps: int = 0,
        force_include_repo_samples: int = 8,
        # optional: a candidate working_dir string from config (validated in-container)
        working_dir: str | None = None,
    ):
        cfg = (
            GenericAPIModelConfig.model_validate(consultant_model_config)
            if isinstance(consultant_model_config, dict)
            else consultant_model_config
        )
        self.consultant_model = get_model(cfg, ToolConfig())

        # behavior
        self.intervention_threshold = intervention_threshold
        self.max_interventions = max_interventions

        # limits
        self.include_opened_limit = include_opened_limit
        self.include_extra_limit = include_extra_limit
        self.file_bytes_limit = file_bytes_limit

        # force/testing
        self.force_intervention = force_intervention
        self.force_warmup_steps = force_warmup_steps
        self.force_include_repo_samples = force_include_repo_samples

        # repo path (INSIDE container)
        self.repo_root: str | None = working_dir

        # state
        self.agent: DefaultAgent | None = None
        self.problem_statement: str = ""
        self.interventions_used = 0
        self.last_intervention_step = -10
        self.detector = StuckDetector()

        self.logger = get_logger("consultant", emoji="🧠")

    # ---- lifecycle ----
    def on_init(self, *, agent: DefaultAgent):
        self.agent = agent

    def on_setup_done(self):
        if not self.agent:
            return

        # Problem statement
        ps = getattr(self.agent, "_problem_statement", None)
        if ps:
            self.problem_statement = (
                ps.get_problem_statement()
                if hasattr(ps, "get_problem_statement")
                else str(ps)
            )

        # Resolve repo root INSIDE the container
        self.repo_root = self._resolve_repo_root(self.repo_root)
        if self.repo_root:
            self.logger.info(f"Consultant repo root (container): {self.repo_root}")
        else:
            self.logger.warning(
                "Consultant could not resolve a valid repo root in container; will operate with limited context."
            )

    def on_step_start(self):
        if not self.agent or self.interventions_used >= self.max_interventions:
            return

        cur_step = len(self.agent._trajectory or [])
        # Force mode for testing/demo
        if self.force_intervention and cur_step >= self.force_warmup_steps:
            self.logger.warning("🧠 CONSULTANT (TEST MODE): forcing intervention")
            guidance = self._get_guidance("TEST_MODE: forced intervention")
            if guidance:
                self._inject(guidance)
                self.interventions_used += 1
                self.last_intervention_step = cur_step
            return

        # Cooldown
        if cur_step - self.last_intervention_step < 3:
            return

        # Stuck?
        is_stuck, reason = self.detector.is_stuck(
            self.agent._trajectory, force_trigger=self.force_intervention
        )
        if not is_stuck or cur_step < self.intervention_threshold:
            return

        self.logger.info(
            f"Consultant intervention [{self.interventions_used + 1}/{self.max_interventions}]: {reason}"
        )
        guidance = self._get_guidance(reason)
        if guidance:
            self._inject(guidance)
            self.interventions_used += 1
            self.last_intervention_step = cur_step

    # ---- guidance ----
    def _get_guidance(self, reason: str) -> str | None:
        ctx = self._build_context(reason)
        self.logger.debug(f"Consultant context LLOOK HERE: {ctx}")
        system = (
            "You are a senior code-migration consultant. "
            "Give concise, strategic guidance (no full patches). "
            "Point to specific files/areas and 2–3 next actions."
        )
        # Extract most recent action/observation for emphasis
        recent_actions = ctx["recent_actions"]
        last_action_result = ""
        if recent_actions and "RESULT:" in recent_actions:
            lines = recent_actions.split("\n")
            for i in range(len(lines) - 1, -1, -1):
                if "RESULT:" in lines[i]:
                    last_action_result = lines[i]
                    break

        user = (
            f"**MOST RECENT FAILURE (FOCUS HERE)**:\n{last_action_result}\n\n"
            f"**Why consultant called**: {ctx['reason']}\n\n"
            f"**Recent action sequence**:\n{ctx['recent_actions']}\n\n"
            f"**Problem statement**:\n{ctx['problem']}\n\n"
            f"**Current file content (may be outdated)**:\n{ctx['opened_files_block']}\n\n"
            f"**Additional context**:\n{ctx['extra_files_block']}\n\n"
            "🎯 **CRITICAL**: Focus on the MOST RECENT FAILURE above, not old errors in file content.\n"
            "Provide: (1) Root cause of the current failure, (2) Why the recent action failed, (3) Specific corrected action to try."
        )
        try:
            resp = self.consultant_model.query(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
            return resp.get("message", "")
        except Exception as e:
            self.logger.error(f"Consultant model error: {e}")
            return None

    def _opened_file_from_step(self, action: str, observation: str) -> str | None:
        action = action or ""
        observation = observation or ""

        # 1) str_replace_editor view <path>
        m = re.search(r"\bstr_replace_editor\s+view\s+([^\s]+)", action)
        if m:
            return m.group(1)

        # 2) str_replace_editor open/show/read <path> (future-proof)
        m = re.search(r"\bstr_replace_editor\s+(open|show|read)\s+([^\s]+)", action)
        if m:
            return m.group(2)

        # 3) bash “cat -n” format present in the observation you showed:
        # "Here's the result of running `cat -n` on /path/to/file: ..."
        m = re.search(r"cat -n` on\s+(/[^:\n]+):", observation)
        if m:
            return m.group(1)

        # 4) Generic file-with-extension fallback (last resort)
        m = re.search(r"(/?[\w\-.\/]+\.(py|toml|cfg|ini|ya?ml|json|md|txt))", action)
        if m:
            return m.group(1)

        return None

    def _build_context(self, reason: str) -> Dict[str, str]:
        traj = self.agent._trajectory if self.agent else []
        recent = traj[-12:] if len(traj) > 12 else traj

        # recent actions summary
        lines: List[str] = []
        for i, st in enumerate(recent, start=len(traj) - len(recent) + 1):
            a = st.get("action", "")
            o = st.get("observation", "")
            if len(o) > 160:
                o = o[:160] + "..."
            lines.append(f"{i}. ACTION: {a}")
            if o:
                lines.append(f"   RESULT: {o}")
        recent_block = "\n".join(lines) if lines else "None"

        # files the worker actually opened (from observations)
        opened_map: Dict[str, str] = {}
        for st in recent:
            a = st.get("action", "") or ""
            o = st.get("observation", "") or ""
            fn = self._opened_file_from_step(a, o)
            if fn and o and not o.lower().startswith("error") and fn not in opened_map:
                opened_map[fn] = o

        # In FORCE mode (or when nothing opened yet), proactively pull repo samples
        if (self.force_intervention or not opened_map) and self.repo_root:
            if not opened_map:
                # Keyword-driven pass
                kws = self._keywords_from_text(
                    self.problem_statement + " " + "\n".join(lines)
                )
                sample_files = self._list_repo_files_prioritized(
                    self.repo_root, kws, self.force_include_repo_samples
                )
                for rel in sample_files:
                    body = self._read(rel)
                    if body:
                        opened_map[rel] = body
                        if len(opened_map) >= self.include_opened_limit:
                            break

        # build opened files block
        opened_block = ""
        for fn in list(opened_map.keys())[: self.include_opened_limit]:
            content = opened_map[fn]
            if len(content) > self.file_bytes_limit:
                content = content[: self.file_bytes_limit] + "\n... [truncated]"
            opened_block += f"\n--- {fn} ---\n{content}\n"
        if not opened_block:
            opened_block = "(none)"

        # extra relevant files (beyond those opened)
        extra_block = ""
        if self.repo_root:
            kws = self._keywords_from_text(
                self.problem_statement + " " + "\n".join(lines)
            )
            extras = self._list_repo_files_prioritized(
                self.repo_root, kws, self.include_extra_limit
            )
            for rel in extras:
                if rel in opened_map:
                    continue
                body = self._read(rel)
                if body:
                    if len(body) > self.file_bytes_limit:
                        body = body[: self.file_bytes_limit] + "\n... [truncated]"
                    extra_block += f"\n--- {rel} ---\n{body}\n"
        if not extra_block:
            extra_block = "(none)"

        # repo tree (shallow)
        tree = self._repo_tree(self.repo_root) if self.repo_root else "No repo"

        return {
            "problem": self.problem_statement or "(none)",
            "reason": reason,
            "recent_actions": recent_block,
            "repo_tree": tree,
            "opened_files_block": opened_block,
            "extra_files_block": extra_block,
        }

    # ---- container filesystem helpers ----
    def _resolve_repo_root(self, candidate: str | None) -> str | None:
        """
        Resolve a path that actually exists *inside* the container.
        Tries: provided candidate -> git root -> $ROOT -> /{repo_name} -> CWD
        """
        env = getattr(self.agent, "_env", None)
        if not env or not hasattr(env, "execute_command"):
            return None

        # 0) Provided candidate (from config)
        for cand in [candidate] if candidate else []:
            if self._dir_exists_in_container(cand):
                return cand

        # 1) git root
        res = env.execute_command(
            "sh -lc 'git rev-parse --show-toplevel 2>/dev/null || true'", check=False
        )
        git_root = (res.stdout or "").strip() if res and res.returncode == 0 else ""
        if git_root and self._dir_exists_in_container(git_root):
            return git_root

        # 2) $ROOT
        res = env.execute_command("sh -lc 'printf %s \"$ROOT\"'", check=False)
        root_env = (res.stdout or "").strip() if res and res.returncode == 0 else ""
        if root_env and self._dir_exists_in_container(root_env):
            return root_env

        # 3) /{repo_name} (SWE-Agent default)
        repo = getattr(env, "repo", None)
        repo_name = getattr(repo, "repo_name", None) if repo else None
        if repo_name:
            guess = f"/{repo_name}"
            if self._dir_exists_in_container(guess):
                return guess

        # 4) CWD
        res = env.execute_command("sh -lc 'pwd'", check=False)
        cwd = (res.stdout or "").strip() if res and res.returncode == 0 else ""
        if cwd and self._dir_exists_in_container(cwd):
            return cwd

        return None

    def _dir_exists_in_container(self, path: str) -> bool:
        env = getattr(self.agent, "_env", None)
        if not env or not hasattr(env, "execute_command") or not path:
            return False
        res = env.execute_command(
            f"sh -lc '[ -d {self._shq(path)} ] && echo OK || echo NO'", check=False
        )
        return bool(res and res.returncode == 0 and (res.stdout or "").strip() == "OK")

    def _repo_tree(self, root: str) -> str:
        """
        Shallow tree: list up to ~60 files within top two levels, repo-relative.
        Skips hidden dirs.
        """
        env = getattr(self.agent, "_env", None)
        if not env or not hasattr(env, "execute_command"):
            return "No repo directory available."

        cmd = (
            f"sh -lc 'cd {self._shq(root)} && "
            r"find . -path \"./.*\" -prune -o -type f -maxdepth 2 -print | sed \"s|^\./||\" | head -n 60'"
        )
        res = env.execute_command(cmd, check=False)
        out = (res.stdout or "").strip() if res and res.returncode == 0 else ""
        return out if out else "Repo appears empty."

    def _list_repo_files_prioritized(
        self, root: str, keywords: List[str], limit: int
    ) -> List[str]:
        """
        Return up to `limit` repo-relative files, prioritizing configs, then .py, then misc text,
        size-capped to self.file_bytes_limit to keep outputs readable.
        If keywords are provided, prefer names that contain any keyword.
        """
        if limit <= 0:
            return []

        # Passes in priority order (config → python → markdown/text → anything small)
        passes: List[Tuple[str, List[str]]] = [
            ("config", ["*.toml", "*.yaml", "*.yml", "*.json", "*.cfg", "*.ini"]),
            ("python", ["*.py"]),
            ("docs", ["*.md", "*.txt"]),
            ("small", ["*"]),
        ]

        collected: List[str] = []
        seen: set[str] = set()
        for pass_name, globs in passes:
            for pat in globs:
                if len(collected) >= limit:
                    break
                files = self._find_files_by_glob(
                    root, pat, size_cap_bytes=self.file_bytes_limit * 6, max_rows=200
                )
                # prefer keyword-containing names first
                if keywords:
                    files.sort(
                        key=lambda p: (
                            0 if any(k.lower() in p.lower() for k in keywords) else 1,
                            p,
                        )
                    )
                else:
                    files.sort()
                for rel in files:
                    if rel in seen:
                        continue
                    seen.add(rel)
                    collected.append(rel)
                    if len(collected) >= limit:
                        break
            if len(collected) >= limit:
                break
        return collected[:limit]

    def _find_files_by_glob(
        self, root: str, name_glob: str, size_cap_bytes: int, max_rows: int
    ) -> List[str]:
        """
        List repo-relative files matching `name_glob`, excluding hidden dirs, under size_cap_bytes.
        """
        env = getattr(self.agent, "_env", None)
        if not env or not hasattr(env, "execute_command"):
            return []

        # Use byte size cap (-size -{N}c). Exclude hidden dirs, return relative paths.
        cmd = (
            f"sh -lc 'cd {self._shq(root)} && "
            f'find . -path "./.*" -prune -o -type f -name {self._shq(name_glob)} -size -{int(size_cap_bytes)}c -print '
            '| sed "s|^\\./||" | head -n ' + str(int(max_rows)) + "'"
        )
        res = env.execute_command(cmd, check=False)
        if not res or res.returncode != 0 or not res.stdout:
            return []
        return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]

    def _read(self, relpath: str) -> str | None:
        """
        Read up to self.file_bytes_limit bytes from repo-relative path inside container.
        """
        env = getattr(self.agent, "_env", None)
        root = self.repo_root
        if not env or not hasattr(env, "execute_command") or not root:
            return None
        # Guard against path traversal: ensure relpath looks relative
        if relpath.startswith("/") or relpath.startswith(".."):
            return None
        cmd = (
            f"sh -lc 'cd {self._shq(root)} && "
            f"head -c {int(self.file_bytes_limit)} -- {self._shq(relpath)} 2>/dev/null'"
        )
        res = env.execute_command(cmd, check=False)
        if not res or res.returncode != 0:
            return None
        out = res.stdout or ""
        return out if out.strip() else None

    # ---- injection & small utils ----
    def _inject(self, guidance: str):
        if not self.agent:
            return
        msg = (
            "🧠 **Consultant Guidance**\n\n"
            f"{guidance}\n\n"
            "**IMPORTANT**: In your next THOUGHT section, please:\n"
            "1. Briefly summarize this consultant guidance\n"
            "2. Explain how you will apply it to avoid repeating the same mistake\n"
            "3. Then proceed with the corrected action\n\n"
            "_(This helps verify you're processing the guidance correctly.)_"
        )
        if hasattr(self.agent, "history") and isinstance(self.agent.history, list):
            # CRITICAL FIX: Include "agent" field so message isn't filtered out
            self.agent.history.append(
                {
                    "role": "user",
                    "content": msg,
                    "agent": self.agent.name,  # ← This ensures it passes the filter!
                }
            )
        self.logger.info("Consultant guidance injected.")

    def _extract_filename(self, action: str) -> str | None:
        # "read_file: path"
        if "read_file" in action and ":" in action:
            return action.split(":", 1)[1].strip()
        # generic file pattern
        m = re.search(
            r"([A-Za-z0-9_\-./]+?\.(py|toml|cfg|ini|yaml|yml|json|md|txt))", action
        )
        return m.group(1) if m else None

    def _keywords_from_text(self, text: str) -> List[str]:
        base = {
            "test",
            "config",
            "setup",
            "init",
            "api",
            "model",
            "utils",
            "migration",
            "compat",
            "deps",
            "convert",
        }
        words = re.findall(r"[A-Za-z]{4,}", text.lower())
        # Keep unique words; intersect with text is redundant; just union with base, cap count
        uniq = set(words)
        return sorted((uniq | base))[:12]

    def _shq(self, s: str) -> str:
        # shell-quote a string for single-quoted context
        return "'" + s.replace("'", "'\"'\"'") + "'"
