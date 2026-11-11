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
import shutil
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sshsrc
import tmuxlink
from background import Background, parallel
from sshsrc import ago, tilde
from table import Column, TableApp, run
from tui import DIM, GREEN, RED, SUB, TEXT, YELLOW

ICON = dict(connect="\U000F0318", popup="\U000F018D", test="\U000F0E1E", tunnel="\U000F0D3F", close="\U000F0156",
            key="\U000F0306", edit="\U000F03EB", add="\U000F0415", copy="\U000F018F", git="\U000F02A2")
PROBE_EVERY = 60         # a TCP connect: sshd logs it, fail2ban and PerSourcePenalties count it
ACCOUNT_EVERY = 3600
TEST_KEEP = 300          # a login test or account answer from the menu is shown this long
LINE_EDITORS = ("micro", "vim", "nvim", "vi", "nano", "emacs", "kak", "hx", "helix")   # take +LINE


def session_name(alias, others=()):
    """ssh-NAME (characters tmux does not take become -) · when another host (of ~/.ssh/config,
    or others: the history ones the pane shows) would get the same name (a.b and a-b: ssh-a-b),
    a short hash of the alias keeps them apart."""
    clean = re.sub(r"[^\w-]", "-", alias)
    if clean != alias and any(o != alias and re.sub(r"[^\w-]", "-", o) == clean
                              for o in [a for a, _ in sshsrc.concrete_hosts()] + list(others)):
        import hashlib
        clean += "-" + hashlib.sha1(alias.encode()).hexdigest()[:4]
    return "ssh-" + clean


class Hosts(TableApp):
    icon = "\U000F08C0"
    master = True
    title = "Hosts"
    noun = "hosts"
    interval = 1.0
    reload_every = 3
    sort_key = "order"
    search_keys = ("alias", "user", "address", "state", "account", "key")
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
        self.tests = {}               # dest → (result, problem, when): logins tested from the menu
        self.extra = {}               # dest from your history → the options of its last command (-p, -i…)
        super().__init__(screen)

    # ─── reading ───
    def resolve_all(self, dests, extra=None):
        extra = extra or {}
        found = parallel(lambda d: sshsrc.resolve(d, extra.get(d, ())), dests)
        return {d: c or {} for d, c in zip(dests, found)}

    def probe_all(self, targets):
        """targets: {dest: (host, port)} → {dest: (ms, problem)}."""
        items = list(targets.items())
        found = parallel(lambda t: sshsrc.probe(*t[1]), items)
        return {d: r or (None, "unknown name") for (d, _), r in zip(items, found)}

    def accounts(self, dests):
        return {d: r or ("", "failed") for d, r in zip(dests, parallel(sshsrc.git_account, dests))}

    def args(self, r):
        """The options to reach a host: none for the hosts of ~/.ssh/config, those of its last
        command for one from your history (ssh -p 2222 root@1.2.3.4 → -p 2222)."""
        return sshsrc.conn_args(self.extra.get(r["alias"])) if r["history"] else []

    def aliases(self):
        return [r["alias"] for r in self.all or []]

    def ssh_cmd(self, r):
        return " ".join(["ssh", *map(shlex.quote, self.args(r)), shlex.quote(r["alias"])])

    def fetch(self):
        stamp = sshsrc.config_stamp()
        hosts = sshsrc.concrete_hosts()
        aliases = [a for a, _ in hosts]
        # in the background: when zsh rewrites the history file (100k lines) reading it again takes
        # a quarter of a second, which would freeze the pane (unchanged it is a cached answer)
        hist = self.bg.get(("history",), sshsrc.history, 3) or []
        # what history reached by hand: user@address of a configured host counts as that host
        cfgs = self.bg.get_for(("reading",), (stamp, tuple(aliases)), lambda: self.resolve_all(aliases), 300) or {}
        by_address = {}
        for a in aliases:
            c = cfgs.get(a) or {}
            if c.get("hostname"):
                by_address.setdefault(c["hostname"], a)
        used, extra = {}, {}
        for when, cmd, prog, dest, parsed in hist:
            host = sshsrc.host_of(dest)
            alias = host if host in aliases else by_address.get(host)
            if not alias:
                if prog != "ssh" or host in sshsrc.GIT_HOSTS:
                    continue
                alias = dest
                extra[dest] = True
                self.extra[dest] = parsed             # the last command's options win
            n, last = used.get(alias, (0, None))
            used[alias] = (n + 1, when if when and (last is None or when > last) else last)
        extra_list = sorted(extra)
        opts = {d: tuple(sshsrc.conn_args(self.extra.get(d))) for d in extra_list}
        extra_cfgs = self.bg.get_for(("reading", "history"), (stamp, tuple(sorted(opts.items()))),
                                     lambda: self.resolve_all(extra_list, opts), 300) or {}
        cfgs = {**cfgs, **extra_cfgs}
        # ps and ssh-add in the background: a slow agent (Windows' bridge on WSL, 1Password…) or a
        # busy machine must not freeze the pane (both are asked every 3 s on screen)
        live = self.bg.get(("live",), sshsrc.live, 3) or {}
        # who answers (every 30 s) · which account the git hosts see for your key (every hour)
        targets = {}
        for d in aliases + extra_list:
            c = cfgs.get(d) or {}
            if c.get("hostname") and not (c.get("proxyjump", "none") != "none" or c.get("proxycommand", "none") != "none"):
                targets[d] = (c["hostname"], c.get("port", "22"))
        # a new host is asked at once; hosts that went away do not make the others asked early
        now_t = frozenset(targets.items())
        seen = self.bg.inputs.get(("checking",), frozenset())
        probes = self.bg.get_for(("checking",), seen | now_t, lambda: self.probe_all(targets), PROBE_EVERY,
                                 again=not now_t <= seen) or {}
        # a key with a passphrase that the agent does not hold cannot be used without a terminal
        agent = self.bg.get(("agent",), sshsrc.agent_keys, 3)
        held = agent[0] if isinstance(agent, tuple) else {}
        by_path = {k["path"]: k for k in sshsrc.keys()}

        def locked(c):
            if c.get("usekeychain") == "yes":           # macOS: the passphrase is in the Keychain
                return False
            ks = [by_path.get(p) or sshsrc.key_entry(p) for p in sshsrc.key_files(c)]
            return bool(ks) and all(k and k["encrypted"] and k["fingerprint"] not in held for k in ks)
        for d in [d for d, t in list(self.tests.items()) if time.time() - t[2] > TEST_KEEP]:
            self.tests.pop(d, None)                     # an old answer is not today's
        def asks_you(c):
            """A security key (touch it) or another agent (1Password, Bitwarden: approve it) would
            ask for you even in BatchMode: such hosts are only asked from the menu."""
            ks = [by_path.get(p) or sshsrc.key_entry(p) for p in sshsrc.key_files(c)]
            agent = os.path.expanduser(c.get("identityagent", "none"))
            default = ("none", "", "SSH_AUTH_SOCK", "$SSH_AUTH_SOCK", sshsrc.ssh_env().get("SSH_AUTH_SOCK", ""),
                       os.path.join(sshsrc.SSH_DIR, "agent.sock"))
            return any(k and k["type"].endswith("-SK") for k in ks) or agent not in default
        gits = [a for a in aliases if sshsrc.git_service(cfgs.get(a) or {}) and not locked(cfgs.get(a) or {})
                and not asks_you(cfgs.get(a) or {})]
        accounts = (self.bg.get_for(("asking",), tuple(gits), lambda: self.accounts(gits), ACCOUNT_EVERY) or {}) if gits else {}
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
            here = list({p[0]: p for p in here}.values())     # one process counted once
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
                         "error": sshsrc.ERRORS.get(dest, ""),
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
        bad = next((r["error"] for r in self.all if r["error"] and not r["history"]), "")
        if bad:
            return f"{RED}~/.ssh/config: {bad}"
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
        if r["error"]:
            return f"{RED}ssh -G {r['alias']}: {r['error']}"
        if not c:
            return f"{DIM}reading what ssh would do…"
        user = f"{c.get('user')}@" if c.get("user") else ""
        key = (f" · key {tilde(r['keys'][0])}" if r["keys"] else f" · {YELLOW}no key file: password login")
        if r["locked"]:
            key += f"{YELLOW} (passphrase, not in the agent: Keys → Add to the agent){DIM}"
        via = f" · via {r['jump']}" if r["jump"] else ""
        used = f" · last used {r['used']} ago" if r["used_t"] else (" · never used from this shell" if not r["uses"] else "")
        hist = f"{DIM} · {YELLOW}not in ~/.ssh/config (from your history){DIM}" if r["history"] else ""
        why = f" · {RED}{r['problem']}{DIM}" if r["problem"] and r["ms"] is None else ""
        return f"{TEXT}{self.ssh_cmd(r)}{DIM} → {user}{r['address']}{via}{why}{key}{used}{hist}"

    def menu_title(self, r):
        return r["alias"]

    def selected(self, r):
        tmuxlink.publish("@ssh-selected", r["alias"] if r else "")

    # ─── menu ───
    def menu_items(self, r):
        git = bool(r["service"])
        items = []
        if not git:
            items += [(f"{ICON['connect']}  Connect (session {session_name(r['alias'], self.aliases())})", "o", lambda: self.connect(r)),
                      (f"{ICON['popup']}  Connect in a popup", "p", lambda: self.popup(
                          f"ssh {r['alias']} · exit closes", f"{self.ssh_cmd(r)}; [ $? -eq 255 ] && "
                          f"{{ printf '\\n  ssh could not connect · press Enter'; read -r _; }}", "95%", "90%", env=self.env())),
                      (f"{ICON['test']}  Test the login (no password asked)", "l", lambda: self.test(r)),
                      (f"{ICON['tunnel']}  Open a tunnel…", "n", lambda: self.ask_tunnel(r))]
            for pid, kind, args, fwd in r["live"]:
                if kind == "tunnel":
                    what = " ".join(f.split(" ", 1)[1] for f in fwd) or f"pid {pid}"
                    items.append((f"{ICON['close']}  Close the tunnel {what}", "",
                                  lambda pid=pid, args=args: self.close_tunnel(r, pid, args)))
            items.append((f"{ICON['key']}  Install your key on it (ssh-copy-id)…", "k", lambda: self.copy_id(r)))
        else:
            items += [(f"{ICON['git']}  Which {r['service']} account is this key?", "w", lambda: self.ask_account(r)),
                      (f"{ICON['popup']}  ssh -T in a popup", "p",
                       lambda: self.popup(f"ssh -T git@{r['alias']}", f"ssh -T git@{shlex.quote(r['alias'])}; printf '\\npress Enter'; read",
                                          "70%", "40%", env=self.env()))]
        block = None if r["history"] else next((b for a, b in sshsrc.concrete_hosts() if a == r["alias"]), None)
        items += [("", "", None),
                  (f"{ICON['edit']}  Edit " + (f"{tilde(block['file'])}:{block['line']}" if block else "~/.ssh/config"), "e",
                   lambda: self.edit(block)),
                  (f"{ICON['add']}  Add a host…", "a", self.ask_add),
                  ("", "", None),
                  (f"{ICON['copy']}  Copy: {self.ssh_cmd(r)}", "c", lambda: self.copy(self.ssh_cmd(r))),
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
        name = session_name(r["alias"], self.aliases())
        if subprocess.run(["tmux", "has-session", "-t", f"={name}"], capture_output=True).returncode:
            cmd = (f"{self.ssh_cmd(r)}; [ $? -eq 255 ] && {{ printf '\\n  ssh could not connect · press Enter to close'; read -r _; }}")
            env = [a for k, v in self.env().items() for a in ("-e", f"{k}={v}")]
            subprocess.run(["tmux", "new-session", "-d", "-s", name, *env, "-c", os.path.expanduser("~"), cmd],
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
        self.run_bg(r, "testing", lambda: sshsrc.test_login_args(self.args(r), r["alias"]), done)

    def ask_account(self, r):
        def done(result):
            account, problem = result
            problem = self.explain(r, problem)
            self.tests[r["alias"]] = (account, "key locked" if problem.startswith("key locked") else problem, time.time())
            gits = [k for k in list(self.bg.data) if k and k[0] == "asking"]
            for k in gits:                               # the hourly answer is out of date now
                self.bg.forget(k)
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
                *self.args(r), "-L", f"{local}:localhost:{remote}", r["alias"]]
        own = r["cfg"].get("localforward", [])

        def done(result):
            rc, out, err = result
            if rc == 0:
                self.bg.forget(("live",))                # the new tunnel shows at once
                self.flash(f"localhost:{local} → {r['alias']}:{remote} · right-click → Close the tunnel to stop it")
            else:
                busy = "Address already in use" in err or "cannot listen" in err
                why = ("the port is in use here" + (f" (the host's config also forwards {', '.join(own)})" if own else "")
                       if busy else self.explain(r, sshsrc.login_problem(err)))
                self.flash(f"tunnel to {r['alias']}: {why}", ok=False)
        self.run_bg(r, "opening tunnel", lambda: sshsrc.run(argv, timeout=20), done)

    def close_tunnel(self, r, pid, args):
        """Only if that pid is still the same tunnel (a pid is reused once its process ends)."""
        still = any(p[0] == pid and p[2] == args for ps in sshsrc.live().values() for p in ps)
        if not still:
            self.flash("that tunnel is not open any more")
            self.reload()
            return
        try:
            os.kill(pid, 15)
            self.flash(f"tunnel to {r['alias']} closed")
        except OSError as e:
            self.flash(f"could not close it: {e.strerror}", ok=False)
        self.bg.forget(("live",))
        self.reload()

    def copy_id(self, r):
        pubs = [k + ".pub" for k in r["keys"] if os.path.exists(k + ".pub")]
        pub = pubs[0] if pubs else os.path.expanduser("~/.ssh/id_ed25519.pub")
        if not os.path.exists(pub):
            self.flash("no public key to install: create one in the Keys pane", ok=False)
            return
        # ssh-copy-id knows -p -o -F (and one -i): a history host's other options go as -o
        opts = []
        parsed = (self.extra.get(r["alias"]) or {}).get("opts", {}) if r["history"] else {}
        for v in parsed.get("p", []):
            opts += ["-p", v]
        for v in parsed.get("F", []):
            opts += ["-F", v]
        for v in parsed.get("o", []):
            opts += ["-o", v]
        for v in parsed.get("l", []):
            opts += ["-o", f"User={v}"]
        for v in parsed.get("J", []):
            opts += ["-o", f"ProxyJump={v}"]
        self.popup(f"ssh-copy-id · {tilde(pub)} → {r['alias']}",
                   f"printf '  installs {shlex.quote(tilde(pub))}\\n\\n'; ssh-copy-id -i {shlex.quote(pub)} "
                   f"{' '.join(map(shlex.quote, opts))} {shlex.quote(r['alias'])}; printf '\\npress Enter'; read -r _",
                   "80%", "50%", env=self.env())

    def edit(self, block):
        path = block["file"] if block else sshsrc.CONFIG
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            with open(path, "a"):
                pass
            os.chmod(path, 0o600)
        editor = next((e for e in (os.environ.get("VISUAL"), os.environ.get("EDITOR"), "micro", "nano", "vi")
                       if e and shutil.which(e.split()[0])), "vi")
        takes_line = os.path.basename(editor.split()[0]) in LINE_EDITORS
        line = f"+{block['line']} " if block and takes_line else ""
        self.popup(f"{tilde(path)} · save and close to apply", f"{editor} {line}{shlex.quote(path)}", "80%", "70%")

    def ask_add(self):
        def add(text):
            m = re.fullmatch(r"([\w.\-]+)\s+(?:([\w.\-]+)@)?(\S+)", text.strip())
            if not m:
                if text:
                    self.flash("write: NAME user@address[:port]  (e.g. web root@203.0.113.7:2222, [2001:db8::1]:22)", ok=False)
                return
            name, user, where = m.groups()
            port = ""
            v6 = re.fullmatch(r"\[([0-9a-fA-F:.%\w]+)\](?::(\d+))?", where)
            if v6:                                  # [2001:db8::1]:2222
                address, port = v6[1], v6[2] or ""
            elif where.count(":") == 1:             # host:port
                address, port = where.split(":")
                if not port.isdigit():
                    self.flash(f"{port} is not a port", ok=False)
                    return
            else:                                   # a name, an IPv4, or a bare IPv6 (no port)
                address = where
            if name in [a for a, _ in sshsrc.concrete_hosts()]:
                self.flash(f"{name} is already in ~/.ssh/config", ok=False)
                return
            block = [f"Host {name}", f"    HostName {address}"] + ([f"    User {user}"] if user else []) + \
                    ([f"    Port {port}"] if port and port != "22" else [])
            try:
                add_block(block)
            except OSError as e:
                self.flash(f"could not write ~/.ssh/config: {e.strerror}", ok=False)
                return
            check = sshsrc.resolve(name)
            if user and check.get("user") != user or (port and port != "22" and check.get("port") != port):
                self.flash(f"added {name}, but an earlier block wins for some options: Edit ~/.ssh/config", ok=False)
            else:
                self.flash(f"added {name} to ~/.ssh/config")
            self.reload()
        self.ask_text("New host · NAME user@address[:port]:", "", add)

    def env(self):
        """The agent this pane sees (popups and sessions start with tmux's environment)."""
        sock = sshsrc.ssh_env().get("SSH_AUTH_SOCK")
        return {"SSH_AUTH_SOCK": sock} if sock else {}

    def copy(self, text):
        tmuxlink.copy(text)
        self.flash(f"copied: {text}")


def add_block(lines):
    """Put a Host block in ~/.ssh/config before the first block that applies to many hosts
    (Host *, Host *.corp, Match): ssh takes the first value it finds, so after them it would
    lose its User, Port… · a new file is made with mode 600."""
    path = sshsrc.CONFIG
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read().splitlines()
    except FileNotFoundError:
        old = []
    at = len(old)
    for n, line in enumerate(old):
        key, value = sshsrc._kv(line.strip()) if line.strip() and not line.strip().startswith("#") else ("", "")
        if key.lower() == "match" or (key.lower() == "host" and any(c in w for w in sshsrc.words(value) for c in "*?!")):
            at = n
            while at > 0 and old[at - 1].strip().startswith("#"):    # its comment stays with it
                at -= 1
            break
    new = old[:at] + ([""] if at and old[at - 1].strip() else []) + lines + ([""] if at < len(old) else []) + old[at:]
    target = os.path.realpath(path)             # through a link (dotfiles): the real file changes
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(new).rstrip("\n") + "\n")
    os.chmod(tmp, (os.stat(target).st_mode & 0o777) if os.path.exists(target) else 0o600)
    os.replace(tmp, target)


if __name__ == "__main__":
    run(Hosts)
