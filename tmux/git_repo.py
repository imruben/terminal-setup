#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Repo pane of the `git` tab · follows the repo highlighted in Repos
#
#  Status    branch and upstream (↑ to push · ↓ to pull), what git is in the
#            middle of, remote and its page, who you commit as and which config
#            file says so (includeIf), last commit, last fetch, then every change:
#            conflicts · staged · not staged · untracked
#  Diff      everything not committed yet (staged and not), with delta when installed
#  Log       the history of this branch (and of its upstream: what a pull brings)
#  Branches  local branches by last commit, with ahead / behind / gone, then remote ones
#  Stash     what is stashed
# ═══════════════════════════════════════════════════════════════

import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gitsrc
from gitsrc import ago, git, git_out, tilde
from tui import BLUE, BOLD, DIM, GREEN, RED, RESET, SUB, TEXT, YELLOW, ellipsis, pad
from viewer import Viewer, run

DELTA = shutil.which("delta")
MAX_LINES = 4000
KIND = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "T": "type changed",
        "U": "unmerged"}
CONFLICT = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


def k(label):
    return f"  {DIM}{label:<11}{RESET}"


def head_exists(repo):
    res = git(repo, "rev-parse", "--verify", "--quiet", "HEAD")
    return bool(res and res.returncode == 0)


class Repo(Viewer):
    icon = "\U000F02A2"
    title = "Repo"
    option = "@git-selected"
    tabs = ["Status", "Diff", "Log", "Branches", "Stash"]
    interval = 0.3
    refresh_every = 4
    empty = "highlight a repo in the Repos pane"

    def title_row(self, with_title, key_w, short):
        """The repo's folder name on the title row, not its whole path."""
        key, self.key = self.key, (os.path.basename(self.key) if self.key else self.key)
        try:
            return super().title_row(with_title, key_w, short)
        finally:
            self.key = key

    def load(self, repo, tab, width):
        if not os.path.isdir(repo):
            return [f"  {YELLOW}{tilde(repo)} is gone"]
        if tab == "Diff":
            return self.diff(repo, width)
        if tab == "Log":
            return self.log(repo)
        if tab == "Branches":
            return self.branches(repo)
        if tab == "Stash":
            return self.stash(repo)
        return self.overview(repo)

    # ─── Status ───
    def overview(self, repo):
        st = gitsrc.status(repo)
        if st.get("error"):
            return [f"  {RED}{st['error']}"]
        s = gitsrc.settings(repo)
        s["host"], s["path"], s["web"] = gitsrc.parse_remote(s["url"], gitsrc.ssh_aliases())
        lines = [k("Folder") + f"{TEXT}{tilde(repo)}"]
        if st.get("detached"):
            branch = f"{YELLOW}detached at {st['detached']}{DIM} · not on any branch"
        else:
            branch = f"{TEXT}{BOLD}{st['branch']}{RESET}"
            if st["upstream"]:
                branch += f"{DIM} → {st['upstream']}  "
                sync = []
                if st["ahead"]:
                    sync.append(f"{BLUE}↑{st['ahead']} to push")
                if st["behind"]:
                    sync.append(f"{BLUE}↓{st['behind']} to pull")
                branch += f"{DIM} · ".join(sync) if sync else f"{GREEN}up to date"
                if not st["fetched"] and s["remotes"]:
                    branch += f"{DIM} (as of the last fetch: never)"
            elif s["remotes"]:
                branch += f"{DIM} · not on {s['remote']} yet (push publishes it)"
            else:
                branch += f"{DIM} · no remote: only on this machine"
        lines.append(k("Branch") + branch)
        if st["doing"]:
            lines.append(k("State") + f"{RED}{BOLD}{st['doing']}{RESET}{RED} · finish it or --abort in a terminal")
        for n, (name, url) in enumerate(sorted(s["remotes"].items(), key=lambda kv: kv[0] != s["remote"])):
            web = gitsrc.parse_remote(url, gitsrc.ssh_aliases())[2]
            lines.append(k("Remote" if n == 0 else "") + f"{TEXT}{name}{DIM}  {url}" + (f"  {BLUE}{web}" if web else ""))
        who = f"{TEXT}{s['name'] or '?'} <{s['email']}>" if s["email"] else f"{RED}no user.email set: commits fail"
        lines.append(k("Commits as") + who + (f"{DIM}  from {tilde(s['email_from'])}" if s["email_from"] else ""))
        if st["last"]:
            sha = git_out(repo, "rev-parse", "--short", "HEAD").strip()
            lines.append(k("Last") + f"{YELLOW}{sha}{RESET} {TEXT}{st['subject']}{DIM} · {gitsrc.ago_text(st['last'])} · {st['author']}")
        else:
            lines.append(k("Last") + f"{DIM}no commits yet")
        if s["remotes"]:
            lines.append(k("Fetched") + (f"{DIM}{gitsrc.ago_text(st['fetched'])}" if st["fetched"] else f"{DIM}never"))
        if st["stash"]:
            lines.append(k("Stash") + f"{TEXT}{st['stash']}{DIM} (Stash tab)")
        lines.append("")
        return lines + self.changes(repo)

    def changes(self, repo):
        out = git_out(repo, "status", "--porcelain=v1", "--untracked-files=normal")
        groups = {"conflicts": [], "staged": [], "changed": [], "untracked": []}
        for line in out.splitlines():
            xy, path = line[:2], line[3:]
            if xy == "??":
                groups["untracked"].append(f"  {DIM}  {path}")
            elif xy in CONFLICT:
                groups["conflicts"].append(f"  {RED}  {path}")
            else:
                if xy[0] not in " ?!":
                    groups["staged"].append(f"  {GREEN}  {KIND.get(xy[0], xy[0]):<10}{RESET} {TEXT}{path}")
                if xy[1] not in " ?!":
                    groups["changed"].append(f"  {YELLOW}  {KIND.get(xy[1], xy[1]):<10}{RESET} {TEXT}{path}")
        if not any(groups.values()):
            return [f"  {GREEN}Nothing to commit: the working tree is clean"]
        lines = []
        for key, title, colour in (("conflicts", "Conflicts", RED), ("staged", "Staged (in the next commit)", GREEN),
                                   ("changed", "Not staged", YELLOW), ("untracked", "Untracked", SUB)):
            items = groups[key]
            if items:
                lines.append(f"  {colour}{BOLD}{title}{RESET}{DIM}  {len(items)}")
                lines += items[:500] + ([f"  {DIM}  … and {len(items) - 500} more"] if len(items) > 500 else [])
                lines.append("")
        return lines

    # ─── Diff ───
    def diff(self, repo, width):
        base = ["HEAD"] if head_exists(repo) else ["--cached"]
        stat = git_out(repo, "-c", "color.ui=always", "diff", *base, f"--stat={max(40, width - 4)}").rstrip("\n")
        if not stat:
            untracked = sum(1 for l in git_out(repo, "status", "--porcelain=v1").splitlines() if l.startswith("??"))
            return [f"  {GREEN}No changes to tracked files"] + \
                   ([f"  {DIM}{untracked} untracked (not in a diff until you git add them: Status tab)"] if untracked else [])
        lines = [f"  {line}" for line in stat.splitlines()] + [""]
        raw = git(repo, "diff", *base, timeout=30)
        text = raw.stdout if raw and raw.returncode == 0 else ""
        if DELTA and text:
            try:
                res = subprocess.run([DELTA, "--paging=never", f"--width={max(40, width - 3)}"], input=text,
                                     capture_output=True, text=True, timeout=30, errors="replace")
                body = res.stdout.splitlines() if res.returncode == 0 else []
            except (subprocess.TimeoutExpired, OSError):
                body = []
        else:
            body = []
        if not body:
            body = git_out(repo, "-c", "color.ui=always", "diff", *base, timeout=30).splitlines()
        if len(body) > MAX_LINES:
            body = body[:MAX_LINES] + [f"{YELLOW}… {len(body) - MAX_LINES} more lines: see the whole diff in a terminal"]
        return lines + body

    # ─── Log ───
    def log(self, repo):
        if not head_exists(repo):
            return [f"  {DIM}no commits yet"]
        revs = ["HEAD"]
        if git_out(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}").strip():
            revs.append("@{upstream}")
        out = git_out(repo, "log", "--graph", "--color=always", "--date=relative", "-n", "200",
                      "--format=%C(yellow)%h%C(reset) %s %C(dim)· %ad · %an%C(reset)%C(auto)%d", *revs, timeout=30)
        return [f" {line}" for line in out.splitlines()] or [f"  {DIM}no commits yet"]

    # ─── Branches ───
    def branches(self, repo):
        fmt = "%(HEAD)%1f%(refname:short)%1f%(upstream:short)%1f%(upstream:track)%1f%(committerdate:unix)%1f%(subject)"
        local = git_out(repo, "for-each-ref", "--sort=-committerdate", f"--format={fmt}", "refs/heads").splitlines()
        if not local:
            return [f"  {DIM}no branches yet (no commits)"]
        rows = [l.split("\x1f") for l in local]
        w = min(32, max(len(r[1]) for r in rows))
        lines = [f"  {BOLD}{BLUE}Local{RESET}{DIM}  {len(rows)}", ""]
        for head, name, up, track, when, subject in (r + [""] * (6 - len(r)) for r in rows):
            mark = f"{GREEN}●" if head == "*" else " "
            track = track.strip("[]")
            tr = (f"{RED}upstream gone" if track == "gone" else
                  f"{BLUE}{track.replace('ahead ', '↑').replace('behind ', '↓')}" if track else
                  f"{DIM}{'in sync' if up else 'local'}")
            age = ago(int(when)) if when.isdigit() else ""
            lines.append(f"  {mark} {TEXT if head == '*' else SUB}{pad(ellipsis(name, w), w)}{RESET} {pad(tr, 20)}{RESET} "
                         f"{DIM}{age:>4} {RESET}{SUB}{subject}")
        # (origin/HEAD only points to the default branch: left out)
        remote = git_out(repo, "for-each-ref", "--sort=-committerdate", "--count=41",
                         "--format=%(symref)%1f%(refname:short)%1f%(committerdate:unix)%1f%(subject)",
                         "refs/remotes").splitlines()
        remote = [r.split("\x1f")[1:] for r in remote if r.count("\x1f") >= 3 and not r.split("\x1f")[0]][:40]
        if remote:
            w = min(40, max(len(r[0]) for r in remote))
            lines += ["", f"  {BOLD}{BLUE}Remote{RESET}{DIM}  newest 40 · as of the last fetch", ""]
            for name, when, subject in (r + [""] * (3 - len(r)) for r in remote):
                age = ago(int(when)) if when.isdigit() else ""
                lines.append(f"    {SUB}{pad(ellipsis(name, w), w)}{RESET} {DIM}{age:>4} {RESET}{SUB}{subject}")
        return lines

    # ─── Stash ───
    def stash(self, repo):
        out = git_out(repo, "stash", "list", "--format=%gd%x1f%cr%x1f%gs").splitlines()
        if not out:
            return [f"  {DIM}nothing stashed"]
        lines = [f"  {DIM}{len(out)} stashed · git stash pop brings back the newest", ""]
        for line in out:
            ref, when, what = (line.split("\x1f") + ["", ""])[:3]
            lines.append(f"  {YELLOW}{ref:<11}{RESET} {TEXT}{what}{DIM} · {when}")
        return lines


if __name__ == "__main__":
    run(Repo)
