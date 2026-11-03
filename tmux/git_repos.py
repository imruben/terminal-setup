#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Repos pane of the `git` tab (tmux/system.sh) · every repo under the folders
#  you choose (~/.tmux/git-roots, see tmux/gitsrc.py), live:
#  branch (and what git is in the middle of: rebasing, merging…), changes
#  (+ staged · ~ not staged · ? untracked · ! conflicts), ↑ to push · ↓ to pull,
#  stashes, last commit, last fetch, who you commit as, the remote.
#  The highlighted repo is shown in the Repo pane below.
#
#  Double-click: open it in a session of its own. Right-click: lazygit / tig
#  (when installed) · shell in a popup · fetch · pull (fast-forward only) ·
#  push (asks) · fetch every repo · open its page · copy path, branch, URL
#  · folders to look in: add one, edit the list.
#  Nothing here asks for a password: fetch / pull / push run without a terminal,
#  so a key that needs one says so instead of waiting.
# ═══════════════════════════════════════════════════════════════

import os
import shlex
import shutil
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gitsrc
import tmuxlink
from background import Background, parallel
from gitsrc import ago, tilde
from table import Column, TableApp, run
from tui import BLUE, DIM, GREEN, RED, SUB, TEXT, YELLOW

HERE = os.path.dirname(os.path.realpath(__file__))
ICON = dict(open="\U000F0770", ui="\U000F02A2", shell="\U000F018D", fetch="\U000F06B0", pull="\U000F01DA",
            push="\U000F0552", web="\U000F059F", copy="\U000F018F", folder="\U000F024B", add="\U000F0257",
            edit="\U000F03EB", remove="\U000F0A7A", scan="\U000F0450")
# fetch / pull / push: no terminal and no graphical password window either (WSLg, a desktop)
NET_ENV = {**gitsrc.GIT_ENV, "SSH_ASKPASS_REQUIRE": "never", "GIT_ASKPASS": "true"}


def changes_text(st):
    if st.get("error"):
        return "error"
    parts = []
    if st["conflicts"]:
        parts.append(f"!{st['conflicts']}")
    if st["staged"]:
        parts.append(f"+{st['staged']}")
    if st["modified"]:
        parts.append(f"~{st['modified']}")
    if st["untracked"]:
        parts.append(f"?{st['untracked']}")
    return " ".join(parts) or "✓"


def sync_text(st, has_remote):
    if st.get("error"):
        return ""
    if st.get("detached"):
        return "detached"
    if st.get("gone"):
        return "gone"                       # its upstream branch was deleted (merged on the remote?)
    if not st["upstream"]:
        return "…" if has_remote is None else "unpushed" if has_remote else "local"
    if not (st["ahead"] or st["behind"]):
        return "✓"
    return " ".join(t for t in (f"↑{st['ahead']}" if st["ahead"] else "", f"↓{st['behind']}" if st["behind"] else "") if t)


def last_line(out):
    """The line of git's output that says what went wrong (not 'and the repository exists.'),
    and what to do when it is a key or a password the pane cannot ask for."""
    lines = [l.strip() for l in (out or "").strip().splitlines() if l.strip()]
    why = next((l for l in lines if "Permission denied" in l or "Could not resolve" in l
                or "Connection timed out" in l or "Host key verification failed" in l), None)
    if not why:
        why = next((l.split(":", 1)[1].strip() for l in lines if l.startswith(("fatal:", "error:", "ERROR:"))),
                   lines[-1] if lines else "failed")
    text = " ".join(lines)
    if any(t in text for t in ("passphrase", "Permission denied", "terminal prompts disabled", "Authentication failed")):
        why += " · the key or password is asked in a terminal: run it there once (or ssh-add the key)"
    elif "Host key verification failed" in text:
        why += " · connect once with ssh in a terminal to trust the host"
    elif "[rejected]" in text or "fetch first" in text:
        why = "the remote has commits you do not: pull first"
    return why.replace("git@", "")


class Repos(TableApp):
    icon = "\U000F02A2"
    master = True
    title = "Repos"
    noun = "repos"
    interval = 1.0
    reload_every = 3
    sort_key = "repo"
    search_keys = ("repo", "branch_txt", "changes", "sync", "email", "remote", "doing")
    columns = [Column("repo", "REPO", 28, min=14),
               Column("branch_txt", "BRANCH", 18, min=8),
               Column("changes", "CHANGES", 11, sort="dirty", desc=True, min=7),
               Column("sync", "SYNC", 9, sort="unsync", desc=True, min=6),
               Column("stash_txt", "STASH", 5, "r", sort="stash", desc=True, optional=True),
               Column("last", "LAST", 5, "r", sort="last_t", desc=True),
               Column("fetched", "FETCHED", 7, "r", sort="fetched_t", desc=True, optional=True),
               Column("email", "COMMITS AS", 24, optional=True),
               Column("remote", "REMOTE", optional=True)]

    def __init__(self, screen):
        self.bg = Background(self.wake, fallback=dict)
        self.net_slots = threading.Semaphore(4)    # at most 4 fetch / pull / push at a time (sshd MaxStartups)
        self.root_filter = "all"
        self.repos = {}
        self.roots_seen = None
        self.fetch_failed = {}        # repo → when its last fetch failed (git touches FETCH_HEAD anyway)
        super().__init__(screen)

    # ─── reading ───
    def roots_stamp(self):
        try:
            return os.path.getmtime(gitsrc.ROOTS_FILE)
        except OSError:
            return None

    def scan(self):
        roots, saved = gitsrc.read_roots()
        return gitsrc.find_repos(roots, saved)

    def statuses(self, repos):
        paths = list(repos)
        return {p: st for p, st in zip(paths, parallel(gitsrc.status, paths)) if st is not None}

    def settings_all(self, repos):
        paths = list(repos)
        aliases = gitsrc.ssh_aliases()

        def one(path):
            s = gitsrc.settings(path)
            s["host"], s["path"], s["web"] = gitsrc.parse_remote(s["url"], aliases)
            return s
        return {p: s for p, s in zip(paths, parallel(one, paths)) if s is not None}

    def fetch(self):
        stamp = self.roots_stamp()
        if stamp != self.roots_seen:              # the list of folders changed: look again now
            self.roots_seen = stamp
            self.bg.forget(("scanning",))
        repos = self.bg.get(("scanning",), self.scan, 60) or {}
        if repos.keys() != self.repos.keys():      # repos came or went: read them all at once
            self.bg.forget(("status",))
            self.bg.forget(("settings",))
        self.repos = repos
        if not repos:
            return []
        # every 3 s with a few repos; more of them are read less often (100 repos: every 13 s).
        # Until an answer arrives the last one stays (rows do not flicker or lose the selection)
        statuses = self.bg.get(("status",), lambda: self.statuses(repos), 3 + len(repos) / 10) or {}
        sets = self.bg.get(("settings",), lambda: self.settings_all(repos), 30) or {}
        rows = []
        for path, root in repos.items():
            st, s = statuses.get(path), sets.get(path)
            known = s is not None                  # settings read (None: not yet, say nothing about them)
            s = s or {}
            rel = os.path.relpath(path, root) if path != root else os.path.basename(path)
            row = {"id": path, "repo": rel, "root": root, "path": path, "web": s.get("web", ""),
                   "url": gitsrc.safe_url(s.get("url", "")), "remote_name": s.get("remote", ""),
                   "email": s.get("email", ""), "email_from": s.get("email_from", ""), "known": known,
                   "has_remote": bool(s.get("remotes")) if known else None,
                   "remote": (s.get("path", "") + (f"  {s['host']}" if s.get("host") and s["host"] != "github.com" else ""))
                   if s else "", "st": st}
            if not st:
                row.update(branch="", branch_txt="…", changes="", sync="", dirty=0, unsync=0, stash=0,
                           stash_txt="", last="", last_t=None, fetched="", fetched_t=None, doing="", error="")
            else:
                dirty = st.get("conflicts", 0) * 1000 + st.get("staged", 0) + st.get("modified", 0) + st.get("untracked", 0)
                branch = st.get("branch") or ""                    # "" when detached (no branch to push)
                shown = branch or (f"@{st['detached']}" if st.get("detached") else "")
                row.update(branch=branch, error=st.get("error", ""), doing=st.get("doing", ""),
                           branch_txt=(f"{shown} · {st['doing']}" if st.get("doing") else shown) if not st.get("error") else "",
                           changes=changes_text(st), sync=sync_text(st, row["has_remote"]), dirty=dirty,
                           unsync=(st.get("ahead", 0) + st.get("behind", 0)) if st.get("upstream") else 0,
                           stash=st.get("stash", 0), stash_txt=str(st["stash"]) if st.get("stash") else "",
                           last=ago(st.get("last")), last_t=st.get("last"),
                           fetched="" if st.get("error") else ago(st.get("fetched")) if st.get("fetched")
                           else ("never" if row["has_remote"] else ""),
                           fetched_t=st.get("fetched"))
                if path in self.fetch_failed and (st.get("fetched") or 0) <= self.fetch_failed[path] + 5:
                    row["fetched"] = "failed"
            rows.append(row)
        return rows

    # ─── look ───
    def keep(self, r):
        return self.root_filter == "all" or r["root"] == self.root_filter

    def chips(self):
        roots = sorted({r["root"] for r in self.all})
        if len(roots) < 2:
            return []
        counts = {}
        for r in self.all:
            counts[r["root"]] = counts.get(r["root"], 0) + 1
        names = {root: os.path.basename(root) or root for root in roots}
        twice = {n for n in names.values() if list(names.values()).count(n) > 1}
        for root in roots:                            # two roots with one name: their parents tell them apart
            if names[root] in twice:
                names[root] = f"{os.path.basename(os.path.dirname(root))}/{os.path.basename(root)}"
        return [("all", "all", self.root_filter == "all")] + \
               [(root, f"{names[root]} {counts[root]}", self.root_filter == root) for root in roots]

    def on_chip(self, name):
        self.root_filter = name
        self.query_changed()
        self.apply()

    def summary(self):
        if "scanning" in self.bg.loading() and not self.all:
            return f"{YELLOW}looking for repos…"
        rows = [r for r in self.all if r["st"]]
        parts = []
        n = sum(1 for r in rows if r["dirty"])
        if n:
            parts.append(f"{YELLOW}{n} with changes")
        n = sum(1 for r in rows if r["st"].get("ahead"))
        if n:
            parts.append(f"{BLUE}{n} to push")
        n = sum(1 for r in rows if r["st"].get("behind"))
        if n:
            parts.append(f"{BLUE}{n} to pull")
        n = sum(1 for r in rows if r["doing"] or r["error"] or r["st"].get("conflicts") or r["st"].get("gone"))
        if n:
            parts.append(f"{RED}{n} need a look")
        busy = len(self.busy)
        if busy:
            parts.append(f"{YELLOW}{busy} busy")
        return f"{DIM} · ".join(parts) if parts else f"{GREEN}all clean"

    def row_colour(self, r):
        if r["error"] or r["doing"] or (r["st"] or {}).get("conflicts"):
            return RED
        if (r["st"] or {}).get("gone"):
            return YELLOW
        if r["dirty"]:
            return YELLOW
        if r["unsync"] or r["sync"] == "unpushed":
            return BLUE
        return SUB if r["st"] else DIM

    def detail(self, r):
        st = r["st"]
        if not st:
            return f"{DIM}{tilde(r['path'])} · reading…"
        if st.get("error"):
            return f"{RED}{st['error']}"
        up = (f" → {st['upstream']} {YELLOW}(gone from the remote: publish it again or delete the branch){DIM}"
              if st.get("gone") else f" → {st['upstream']}" if st.get("upstream")
              else "" if r["has_remote"] is None else " · not pushed yet" if r["has_remote"] else " · no remote")
        last = f" · {DIM}{gitsrc.ago_text(st['last'])}: {TEXT}{st['subject']}" if st.get("last") else " · no commits yet"
        who = (f"{DIM} · as {r['email']}" if r["email"] else "" if not r["known"]
               else f" · {YELLOW}no user.email set{DIM}")
        return f"{TEXT}{tilde(r['path'])}{DIM} · {r['branch']}{up}{last}{who}"

    def footer(self, y):
        if not self.all and self.loaded and not (self.ask or self.prompt or self.msg) and "scanning" not in self.bg.loading():
            roots, _ = gitsrc.read_roots()
            where = ", ".join(tilde(p) for p, _ in roots) or "nowhere"
            return f" {YELLOW}no repos in {where} · right-click → Add a folder to look in…"
        return super().footer(y)

    def menu_title(self, r):
        return r["repo"]

    # ─── talking to the Repo pane ───
    def selected(self, r):
        tmuxlink.put("@git-selected", r["path"] if r else "")

    # ─── menu ───
    def menu_items(self, r):
        st = r["st"] or {}
        items = [(f"{ICON['open']}  Open in a session ({os.path.basename(r['path'])})", "o", lambda: self.open_session(r))]
        if shutil.which("lazygit"):
            items.append((f"{ICON['ui']}  lazygit", "g", lambda: self.popup(f"lazygit · {r['repo']}",
                                                                           "lazygit -p " + shlex.quote(r["path"]), "95%", "90%")))
        if shutil.which("tig"):
            items.append((f"{ICON['ui']}  tig", "i", lambda: self.popup(f"tig · {r['repo']}",
                                                                       f"cd {shlex.quote(r['path'])} && tig", "95%", "90%")))
        items.append((f"{ICON['shell']}  Shell here (popup)", "s", lambda: self.shell(r)))
        ahead, behind = st.get("ahead", 0), st.get("behind", 0)
        tracked = st.get("upstream") and not st.get("gone")
        free = r["id"] not in self.busy                  # one git at a time on a repo
        can_push = free and r["has_remote"] and r["branch"] and not st.get("initial") and (ahead or not tracked)
        items += [("", "", None),
                  (f"{ICON['fetch']}  Fetch", "f", (lambda: self.fetch_one(r)) if r["has_remote"] and free else None),
                  (f"{ICON['pull']}  Pull{f' {behind}' if behind else ''} (fast-forward only)", "p",
                   (lambda: self.pull(r)) if tracked and free and r["branch"] and not st.get("doing") else None),
                  (f"{ICON['push']}  Push{f' {ahead}' if ahead else ''}…" if tracked else f"{ICON['push']}  Publish the branch…",
                   "P", (lambda: self.ask_push(r)) if can_push else None),
                  (f"{ICON['fetch']}  Fetch every repo", "F", self.fetch_all),
                  ("", "", None)]
        if r["web"]:
            items.append((f"{ICON['web']}  Open {r['web'].split('://', 1)[1]}", "w", lambda: self.browse(r["web"])))
        items += [(f"{ICON['copy']}  Copy the path", "c", lambda: self.copy(r["path"])),
                  (f"{ICON['copy']}  Copy the branch", "b", (lambda: self.copy(r["branch"])) if r["branch"] else None),
                  (f"{ICON['copy']}  Copy the remote URL", "u", (lambda: self.copy(r["url"])) if r["url"] else None),
                  ("", "", None)]
        return items + self.roots_items(r)

    def empty_menu_items(self):
        return [(f"{ICON['fetch']}  Fetch every repo", "F", self.fetch_all if self.all else None),
                (f"{ICON['scan']}  Look for repos again", "r", self.rescan),
                ("", "", None)] + self.roots_items(None)

    def roots_items(self, r):
        items = [(f"{ICON['add']}  Add a folder to look in…", "a", self.ask_root),
                 (f"{ICON['edit']}  Edit the folders to look in…", "e", self.edit_roots)]
        if r:
            items.append((f"{ICON['remove']}  Stop looking in {tilde(r['root'])}…", "x", lambda: self.ask_drop_root(r)))
        return items

    def on_double(self, r, col, x):
        self.open_session(r)

    # ─── actions ───
    def open_session(self, r):
        """A session named after the repo; when that name is taken by another folder: parent-repo."""
        name = tmuxlink.session_for(r["path"])
        subprocess.Popen([os.path.join(HERE, "terminal.zsh"), "open", name, r["path"]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.flash(f"session {name} in {tilde(r['path'])}")

    def shell(self, r):
        sh = os.environ.get("SHELL") or "zsh"
        self.popup(f"shell · {r['repo']} · exit closes", f"cd {shlex.quote(r['path'])} && exec {shlex.quote(sh)}", "90%", "80%")

    def net(self, r, doing, steps, done):
        """git with the network, in the background and with no terminal: ssh cannot ask for
        a passphrase in the middle of the pane (it fails and says so instead). steps: one
        git command (a list) or several, run in turn until one fails. 4 at a time at most."""
        self.busy[r["id"]] = doing
        steps = steps if steps and isinstance(steps[0], list) else [steps]

        def work():
            ok, out = True, ""
            try:
                with self.net_slots:
                    for args in steps:
                        res = subprocess.run(["git", "-C", r["path"], *args], capture_output=True, text=True,
                                             env=NET_ENV, timeout=120, stdin=subprocess.DEVNULL,
                                             start_new_session=True, errors="replace")
                        ok, out = res.returncode == 0, (out + "\n" + res.stdout + res.stderr).strip()
                        if not ok:
                            break
            except subprocess.TimeoutExpired:
                ok, out = False, "no answer after 2 min"
            except OSError as e:
                ok, out = False, e.strerror
            finally:
                self.busy.pop(r["id"], None)
            self.bg.forget(("status",))
            done(ok, out)
            self.wake()
        threading.Thread(target=work, daemon=True).start()

    def fetched(self, r, ok):
        if ok:
            self.fetch_failed.pop(r["path"], None)
        else:
            self.fetch_failed[r["path"]] = time.time()

    def fetch_one(self, r):
        def done(ok, out):
            self.fetched(r, ok)
            self.flash(f"{r['repo']}: fetched" if ok else f"{r['repo']}: {last_line(out)}", ok)
        self.net(r, "fetching", ["fetch", "--prune", "--quiet"], done)

    def fetch_all(self):
        rows = [r for r in self.all if r["has_remote"] and r["id"] not in self.busy]
        if not rows:
            self.flash("no repo with a remote to fetch", ok=False)
            return
        left, failed = [len(rows)], []
        lock = threading.Lock()

        def one(r):
            def done(ok, out):
                self.fetched(r, ok)
                with lock:
                    left[0] -= 1
                    if not ok:
                        failed.append(r["repo"])
                    if left[0] == 0:
                        self.flash(f"fetched {len(rows)} repos" + (f" · failed: {', '.join(failed)}" if failed else ""),
                                   ok=not failed)
            self.net(r, "fetching", ["fetch", "--prune", "--quiet"], done)
        self.flash(f"fetching {len(rows)} repos…")        # before: a quick finish must not be overwritten
        for r in rows:
            one(r)

    def pull(self, r):
        def done(ok, out):
            if ok:
                self.flash(f"{r['repo']}: " + ("up to date" if "Already up to date" in out or "Already up-to-date" in out
                                               else "pulled"))
            elif "would be overwritten" in out:
                files = [l.strip() for l in out.splitlines() if l.startswith(("\t", "    ")) and l.strip()]
                self.flash(f"{r['repo']}: the pull changes files you changed too ({', '.join(files[:3]) or '?'}"
                           f"{'…' if len(files) > 3 else ''}): commit or stash them first", ok=False)
            elif "Not possible to fast-forward" in out or "diverg" in out or "not possible" in out.lower():
                self.flash(f"{r['repo']}: your branch and the remote both have new commits · merge or rebase in a terminal",
                           ok=False)
            else:
                self.flash(f"{r['repo']}: {last_line(out)}", ok=False)
        self.net(r, "pulling", [["fetch", "--quiet"],
                                ["-c", "merge.autoStash=false", "merge", "--ff-only", "--no-edit", "@{upstream}"]], done)

    def ask_push(self, r):
        st = r["st"] or {}
        what = (f"Push {st['ahead']} commit{'s' if st['ahead'] != 1 else ''} of {r['branch']} to {st['upstream']}?"
                if st.get("upstream") and not st.get("gone") else f"Publish {r['branch']} to {r['remote_name'] or 'the remote'}?")
        self.confirm(what, lambda: self.push(r), r)

    def push(self, r):
        """Exactly what the question said: this branch to its upstream (not what push.default,
        pushRemote or matching would pick), or publish it to the remote."""
        st = r["st"] or {}
        remote = gitsrc.git_out(r["path"], "config", f"branch.{r['branch']}.remote").strip()
        merge = gitsrc.git_out(r["path"], "config", f"branch.{r['branch']}.merge").strip()
        src = f"refs/heads/{r['branch']}"              # the branch the question named, not what is checked out now
        if st.get("upstream") and not st.get("gone") and remote and merge.startswith("refs/heads/"):
            args = ["push", remote, f"{src}:{merge}"]
        else:
            args = ["push", "-u", r["remote_name"] or "origin", f"{src}:{src}"]
        self.net(r, "pushing", args,
                 lambda ok, out: self.flash(f"{r['repo']}: pushed" if ok else f"{r['repo']}: {last_line(out)}", ok))

    def rescan(self):
        self.bg.forget()                           # the rows stay until the new answers come
        self.flash("looking for repos again…")
        self.reload()

    def ask_root(self):
        def save(text):
            if not text:
                return
            parsed = gitsrc.parse_root(text)           # "~/clients 2": how deep, like the file ("~/Projects 2024": a folder)
            if not parsed:
                return
            path, depth = parsed
            err = gitsrc.add_root(path, depth)
            if err:
                self.flash(err, ok=False)
            else:
                deep = f" ({depth} deep)" if depth != gitsrc.DEFAULT_DEPTH else ""
                self.flash(f"looking for repos in {path}{deep} too")
                self.reload()
        self.ask_text("Folder to look for repos in (and how deep, default 4):", "~/", save)

    def edit_roots(self):
        path = gitsrc.ensure_roots_file()
        editor = editor_cmd()
        self.popup("folders the git tab looks in · save and close to apply",
                   f"{editor} {shlex.quote(path)}", "70%", "50%")

    def ask_drop_root(self, r):
        self.confirm(f"Stop looking for repos in {tilde(r['root'])}? (the repos stay where they are)",
                     lambda: self.drop_root(r["root"]), r)

    def drop_root(self, root):
        roots, _ = gitsrc.read_roots()
        if not any(p == root for p, _ in roots):
            self.flash(f"{tilde(root)} is not in the list", ok=False)
            return
        gitsrc.remove_root(root)
        self.root_filter = "all"
        self.flash(f"not looking in {tilde(root)} any more")
        self.reload()

    def browse(self, url):
        if tmuxlink.open_url(url):
            self.flash(f"opening {url}")
        else:
            self.flash(f"could not start {tmuxlink.BROWSER}", ok=False)

    def copy(self, text):
        tmuxlink.copy(text)
        self.flash(f"copied: {text}")


def editor_cmd():
    """Your editor ($VISUAL / $EDITOR), else the first of micro, nano, vi that is installed."""
    for e in (os.environ.get("VISUAL"), os.environ.get("EDITOR"), "micro", "nano", "vi"):
        if e and shutil.which(e.split()[0]):
            return e
    return "vi"


if __name__ == "__main__":
    run(Repos)
