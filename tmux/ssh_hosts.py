#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Hosts pane of the `ssh` tab (tmux/system.sh) · the hosts of ~/.ssh/config
#  (and the ones you reached by hand, from your shell history), live:
#  user, address, whether it answers (and how fast), the account a git host
#  (GitHub, GitLab…) sees for your key, the key used, ssh sessions and tunnels
#  open now, when you last used it. The highlighted host is shown in Host.
#
#  Double-click: connect, in a session of its own (ssh-NAME).
#  Right-click: connect in a popup · test the login / ask the git host who you are
#  · open a tunnel (localhost:PORT → the host) · close one · install your key on
#  it (ssh-copy-id) · edit ~/.ssh/config · add a host · copy `ssh NAME` or the address.
#  Nothing logs in by itself: only the git hosts are asked (once an hour) which
#  account your key is, which is what `ssh -T git@github.com` is for.
# ═══════════════════════════════════════════════════════════════

import os
import re
import shlex
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sshsrc
import tmuxlink
from background import Background
from sshsrc import ago, tilde
from table import Column, TableApp, run
from tui import DIM, GREEN, RED, SUB, TEXT, YELLOW

ICON = dict(connect="\U000F0318", popup="\U000F018D", test="\U000F0E1E", tunnel="\U000F0D3F", close="\U000F0156",
            key="\U000F0306", edit="\U000F03EB", add="\U000F0415", copy="\U000F018F", git="\U000F02A2")
PROBE_EVERY = 30
ACCOUNT_EVERY = 3600


def session_name(alias):
    return "ssh-" + re.sub(r"[^\w-]", "-", alias)


class Hosts(TableApp):
    icon = "\U000F08C0"
    master = True
    title = "Hosts"
    noun = "hosts"
    interval = 1.0
    reload_every = 3
    sort_key = "order"
    columns = [Column("alias", "HOST", 20, min=10),
               Column("user", "USER", 10, optional=True),
               Column("address", "ADDRESS", min=10),
               Column("state", "STATE", 11, sort="state_sort", min=6),
               Column("account", "ACCOUNT", 18, optional=True),
               Column("key", "KEY", 20, optional=True),
               Column("open_txt", "OPEN", 4, "r", sort="open", desc=True, optional=True),
               Column("used", "USED", 5, "r", sort="used_t", desc=True, optional=True)]

    def __init__(self, screen):
        self.bg = Background(self.wake, fallback=dict)
        self.pool = ThreadPoolExecutor(max_workers=8)
        self.tests = {}               # dest → (result, problem, when): logins tested from the menu
        super().__init__(screen)

    # ─── reading ───
    def resolve_all(self, dests):
        return dict(zip(dests, self.pool.map(sshsrc.resolve, dests)))

    def probe_all(self, targets):
        """targets: {dest: (host, port)} → {dest: (ms, problem)}."""
        items = list(targets.items())
        return dict(zip([d for d, _ in items], self.pool.map(lambda t: sshsrc.probe(*t[1]), items)))

    def accounts(self, dests):
        return dict(zip(dests, self.pool.map(sshsrc.git_account, dests)))

    def fetch(self):
        stamp = sshsrc.config_stamp()
        hosts = sshsrc.concrete_hosts()
        aliases = [a for a, _ in hosts]
        hist = sshsrc.history()
        # what history reached by hand: user@address of a configured host counts as that host
        cfgs = self.bg.get(("reading", stamp, tuple(aliases)), lambda: self.resolve_all(aliases), 300) or {}
        by_address = {}
        for a in aliases:
            c = cfgs.get(a) or {}
            if c.get("hostname"):
                by_address.setdefault(c["hostname"], a)
        used, extra = {}, {}
        for when, cmd, prog, dest in hist:
            host = sshsrc.host_of(dest)
            alias = host if host in aliases else by_address.get(host)
            if not alias:
                if prog != "ssh" or host in sshsrc.GIT_HOSTS:
                    continue
                alias = dest
                extra[dest] = True
            n, last = used.get(alias, (0, None))
            used[alias] = (n + 1, when if when and (last is None or when > last) else last)
        extra_list = sorted(extra)
        extra_cfgs = self.bg.get(("reading", "history", tuple(extra_list)), lambda: self.resolve_all(extra_list), 300) or {}
        cfgs = {**cfgs, **extra_cfgs}
        live = sshsrc.live()
        # who answers (every 30 s) · which account the git hosts see for your key (every hour)
        targets = {}
        for d in aliases + extra_list:
            c = cfgs.get(d) or {}
            if c.get("hostname") and not (c.get("proxyjump", "none") != "none" or c.get("proxycommand", "none") != "none"):
                targets[d] = (c["hostname"], c.get("port", "22"))
        probes = self.bg.get(("checking", tuple(sorted(targets.items()))), lambda: self.probe_all(targets), PROBE_EVERY) or {}
        # a key with a passphrase that the agent does not hold cannot be used without a terminal
        held, _ = sshsrc.agent_keys()
        by_path = {k["path"]: k for k in sshsrc.keys()}

        def locked(c):
            ks = [by_path.get(p) for p in sshsrc.key_files(c)]
            return bool(ks) and all(k and k["encrypted"] and k["fingerprint"] not in held for k in ks)
        gits = [a for a in aliases if sshsrc.git_service(cfgs.get(a) or {}) and not locked(cfgs.get(a) or {})]
        accounts = (self.bg.get(("asking", tuple(gits)), lambda: self.accounts(gits), ACCOUNT_EVERY) or {}) if gits else {}
        rows = []
        for n, dest in enumerate(aliases + extra_list):
            c = cfgs.get(dest) or {}
            from_history = dest in extra
            hostname, port = c.get("hostname", sshsrc.host_of(dest)), c.get("port", "22")
            jump = c.get("proxyjump", "none")
            jump = jump if jump != "none" else ("proxy" if c.get("proxycommand", "none") != "none" else "")
            keys = sshsrc.key_files(c)
            service = sshsrc.git_service(c)
            here = live.get(dest, []) + (live.get(hostname, []) if hostname != dest else [])
            if from_history:
                here = live.get(sshsrc.host_of(dest), [])
            ms, problem = probes.get(dest, (None, ""))
            if jump:
                state, state_sort = f"via {jump}", 2
            elif dest not in probes:
                state, state_sort = "…", 3
            elif ms is not None:
                state, state_sort = f"● {ms}ms", 0
            else:
                state, state_sort = f"✗ {problem}", 1
            account, acc_problem = "", ""
            if service:
                account, acc_problem = accounts.get(dest, ("", "")) if accounts else ("", "")
            if dest in self.tests:
                account, acc_problem = self.tests[dest][:2]
            is_locked = locked(c)
            if is_locked and not account:
                acc_problem = "key locked"
            count, last = used.get(dest, (0, None))
            rows.append({"id": dest, "alias": dest, "cfg": c, "user": c.get("user", ""), "hostname": hostname,
                         "port": port, "address": hostname + (f":{port}" if port != "22" else ""), "jump": jump,
                         "state": state, "state_sort": state_sort, "ms": ms, "problem": problem,
                         "service": service, "account": account or ("\U000F033E key locked" if acc_problem == "key locked" else
                                                       f"✗ {acc_problem}" if acc_problem else ""),
                         "account_ok": bool(account), "locked": is_locked,
                         "key": os.path.basename(keys[0]) if keys else "",
                         "keys": keys, "live": here, "open": len(here), "open_txt": str(len(here)) if here else "",
                         "used_t": last, "used": ago(last) if last else ("" if not count else "yes"), "uses": count,
                         "history": from_history, "order": (from_history, n)})
        return rows

    # ─── look ───
    def summary(self):
        if "reading" in self.bg.loading() and not self.all:
            return f"{YELLOW}reading ~/.ssh/config…"
        up = sum(1 for r in self.all if r["ms"] is not None)
        down = sum(1 for r in self.all if r["state"].startswith("✗"))
        sessions = sum(1 for r in self.all for p in r["live"] if p[1] != "tunnel")
        tunnels = sum(1 for r in self.all for p in r["live"] if p[1] == "tunnel")
        parts = [f"{GREEN}{up} answer"] if up else []
        if down:
            parts.append(f"{RED}{down} do not")
        if sessions:
            parts.append(f"{TEXT}{sessions} session{'s' if sessions != 1 else ''} open")
        if tunnels:
            parts.append(f"{TEXT}{tunnels} tunnel{'s' if tunnels != 1 else ''}")
        busy = sorted(self.bg.loading() - {"reading"})
        if busy:
            parts.append(f"{YELLOW}{' · '.join(busy)}…")
        return f"{DIM} · ".join(parts)

    def row_colour(self, r):
        if r["history"]:
            return DIM
        if r["locked"] and not r["account_ok"]:
            return YELLOW
        if r["state"].startswith("✗") or r["account"].startswith("✗"):
            return RED
        return TEXT if r["live"] else SUB

    def detail(self, r):
        c = r["cfg"]
        if not c:
            return f"{DIM}reading what ssh would do…"
        user = f"{c.get('user')}@" if c.get("user") else ""
        key = (f" · key {tilde(r['keys'][0])}" if r["keys"] else f" · {YELLOW}no key file: password login")
        if r["locked"]:
            key += f"{YELLOW} (passphrase, not in the agent: Keys → Add to the agent){DIM}"
        via = f" · via {r['jump']}" if r["jump"] else ""
        used = f" · last used {r['used']} ago" if r["used_t"] else (" · never used from this shell" if not r["uses"] else "")
        hist = f"{DIM} · {YELLOW}not in ~/.ssh/config (from your history){DIM}" if r["history"] else ""
        return f"{TEXT}ssh {r['alias']}{DIM} → {user}{r['address']}{via}{key}{used}{hist}"

    def menu_title(self, r):
        return r["alias"]

    def selected(self, r):
        tmuxlink.put("@ssh-selected", r["alias"] if r else "")

    # ─── menu ───
    def menu_items(self, r):
        git = bool(r["service"])
        items = []
        if not git:
            items += [(f"{ICON['connect']}  Connect (session {session_name(r['alias'])})", "o", lambda: self.connect(r)),
                      (f"{ICON['popup']}  Connect in a popup", "p", lambda: self.popup(f"ssh {r['alias']} · exit closes",
                                                                                     "ssh " + shlex.quote(r["alias"]), "95%", "90%")),
                      (f"{ICON['test']}  Test the login (no password asked)", "l", lambda: self.test(r)),
                      (f"{ICON['tunnel']}  Open a tunnel…", "n", lambda: self.ask_tunnel(r))]
            for pid, kind, args in r["live"]:
                if kind == "tunnel":
                    fwd = " ".join(re.findall(r"-[LRD]\s*(\S+)", args)) or f"pid {pid}"
                    items.append((f"{ICON['close']}  Close the tunnel {fwd}", "", lambda pid=pid: self.close_tunnel(r, pid)))
            items.append((f"{ICON['key']}  Install your key on it (ssh-copy-id)…", "k", lambda: self.copy_id(r)))
        else:
            items += [(f"{ICON['git']}  Which {r['service']} account is this key?", "w", lambda: self.ask_account(r)),
                      (f"{ICON['popup']}  ssh -T in a popup", "p",
                       lambda: self.popup(f"ssh -T git@{r['alias']}", f"ssh -T git@{shlex.quote(r['alias'])}; printf '\\npress Enter'; read",
                                          "70%", "40%"))]
        block = next((b for a, b in sshsrc.concrete_hosts() if a == r["alias"]), None)
        items += [("", "", None),
                  (f"{ICON['edit']}  Edit ~/.ssh/config" + (f" (line {block['line']})" if block else ""), "e",
                   lambda: self.edit(block)),
                  (f"{ICON['add']}  Add a host…", "a", self.ask_add),
                  ("", "", None),
                  (f"{ICON['copy']}  Copy: ssh {r['alias']}", "c", lambda: self.copy(f"ssh {r['alias']}")),
                  (f"{ICON['copy']}  Copy the address", "d", lambda: self.copy(r["address"]))]
        return items

    def empty_menu_items(self):
        return [(f"{ICON['add']}  Add a host…", "a", self.ask_add),
                (f"{ICON['edit']}  Edit ~/.ssh/config", "e", lambda: self.edit(None))]

    def on_double(self, r, col, x):
        if r["service"]:
            self.ask_account(r)
        else:
            self.connect(r)

    # ─── actions ───
    def connect(self, r):
        """A session of its own, named after the host: connecting again goes back to it.
        When ssh itself fails (255: no answer, key refused…) the pane waits so you can read why."""
        name = session_name(r["alias"])
        dest = shlex.quote(r["alias"])
        if subprocess.run(["tmux", "has-session", "-t", f"={name}"], capture_output=True).returncode:
            cmd = (f"ssh {dest}; [ $? -eq 255 ] && {{ printf '\\n  ssh could not connect · press Enter to close'; read -r _; }}")
            subprocess.run(["tmux", "new-session", "-d", "-s", name, "-c", os.path.expanduser("~"), cmd],
                           capture_output=True)
            subprocess.run(["tmux", "set", "-t", f"{name}:", "@description", f"ssh {r['alias']} · {r['address']}"],
                           capture_output=True)
        subprocess.run(["tmux", "switch-client", "-t", f"={name}"], capture_output=True)

    def run_bg(self, r, doing, fn, done):
        self.busy[r["id"]] = doing

        def work():
            try:
                result = fn()
            finally:
                self.busy.pop(r["id"], None)
            done(result)
            self.wake()
        threading.Thread(target=work, daemon=True).start()

    def explain(self, r, problem):
        """'key not accepted' for a key that was never offered: it is locked, not refused."""
        if problem == "key not accepted" and r["locked"]:
            return "key locked: it has a passphrase and the agent does not hold it (Keys → Add to the agent)"
        return problem

    def test(self, r):
        def done(result):
            ok, problem = result
            problem = self.explain(r, problem)
            self.tests[r["alias"]] = (ok, "key locked" if problem.startswith("key locked") else problem, time.time())
            self.flash(f"{r['alias']}: the login works with your key" if ok else f"{r['alias']}: {problem}", ok=bool(ok))
        self.run_bg(r, "testing", lambda: sshsrc.test_login(r["alias"]), done)

    def ask_account(self, r):
        def done(result):
            account, problem = result
            problem = self.explain(r, problem)
            self.tests[r["alias"]] = (account, "key locked" if problem.startswith("key locked") else problem, time.time())
            self.flash(f"{r['alias']}: {r['service']} sees this key as {account}" if account
                       else f"{r['alias']}: {problem}", ok=bool(account))
        self.run_bg(r, "asking", lambda: sshsrc.git_account(r["alias"]), done)

    def ask_tunnel(self, r):
        def start(text):
            m = re.fullmatch(r"(\d{1,5})(?::(\d{1,5}))?", text.strip())
            if not m:
                if text:
                    self.flash("a port (5432) or local:remote (8080:80)", ok=False)
                return
            local, remote = m[1], m[2] or m[1]
            self.open_tunnel(r, local, remote)
        self.ask_text(f"Tunnel to {r['alias']} · port, or local:remote:", "", start)

    def open_tunnel(self, r, local, remote):
        """ssh -f -N in the background: it detaches once the tunnel works, so a failure (port in
        use, key refused, a key that needs its passphrase) comes back as a message."""
        argv = ["ssh", "-f", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "-L", f"{local}:localhost:{remote}", r["alias"]]

        def done(result):
            rc, out, err = result
            if rc == 0:
                self.flash(f"localhost:{local} → {r['alias']}:{remote} · right-click → Close the tunnel to stop it")
            else:
                why = "the port is in use here" if "Address already in use" in err or "cannot listen" in err \
                    else sshsrc.login_problem(err)
                self.flash(f"tunnel to {r['alias']}: {why}", ok=False)
        self.run_bg(r, "opening tunnel", lambda: sshsrc.run(argv, timeout=20), done)

    def close_tunnel(self, r, pid):
        try:
            os.kill(pid, 15)
            self.flash(f"tunnel to {r['alias']} closed")
        except OSError as e:
            self.flash(f"could not close it: {e.strerror}", ok=False)
        self.reload()

    def copy_id(self, r):
        pubs = [k + ".pub" for k in r["keys"] if os.path.exists(k + ".pub")]
        pub = pubs[0] if pubs else os.path.expanduser("~/.ssh/id_ed25519.pub")
        if not os.path.exists(pub):
            self.flash("no public key to install: create one in the Keys pane", ok=False)
            return
        self.popup(f"ssh-copy-id · {r['alias']}",
                   f"ssh-copy-id -i {shlex.quote(pub)} {shlex.quote(r['alias'])}; printf '\\npress Enter'; read -r _",
                   "80%", "50%")

    def edit(self, block):
        path = block["file"] if block else sshsrc.CONFIG
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            with open(path, "a"):
                pass
            os.chmod(path, 0o600)
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "micro"
        line = f"+{block['line']} " if block else ""
        self.popup(f"{tilde(path)} · save and close to apply", f"{editor} {line}{shlex.quote(path)}", "80%", "70%")

    def ask_add(self):
        def add(text):
            m = re.fullmatch(r"([\w.\-]+)\s+(?:([\w.\-]+)@)?([\w.\-:\[\]]+?)(?::(\d+))?", text.strip())
            if not m:
                if text:
                    self.flash("write: NAME user@address[:port]  (e.g. web root@203.0.113.7:2222)", ok=False)
                return
            name, user, address, port = m.groups()
            if name in [a for a, _ in sshsrc.concrete_hosts()]:
                self.flash(f"{name} is already in ~/.ssh/config", ok=False)
                return
            block = f"\nHost {name}\n    HostName {address}\n" + (f"    User {user}\n" if user else "") + \
                    (f"    Port {port}\n" if port and port != "22" else "")
            path = sshsrc.CONFIG
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            new = not os.path.exists(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(block.lstrip("\n") if new else block)
            if new:
                os.chmod(path, 0o600)
            self.flash(f"added {name} to ~/.ssh/config")
            self.bg.forget()
            self.reload()
        self.ask_text("New host · NAME user@address[:port]:", "", add)

    def copy(self, text):
        tmuxlink.copy(text)
        self.flash(f"copied: {text}")


if __name__ == "__main__":
    run(Hosts)
