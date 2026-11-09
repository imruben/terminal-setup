#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Keys pane of the `ssh` tab · the key pairs in ~/.ssh: type, whether they have a
#  passphrase, whether the ssh-agent holds them now (a key with a passphrase only
#  works in the background, tunnels or git fetch, once the agent has it), which
#  hosts of ~/.ssh/config use them, their comment and fingerprint.
#  Keys the agent holds that are not in ~/.ssh show too (agent only).
#
#  Right-click: copy the public key (to paste in GitHub, a server…) · add to /
#  remove from the agent (the passphrase is asked in a popup) · copy the
#  fingerprint · create a new key · add every key to the agent.
# ═══════════════════════════════════════════════════════════════

import os
import re
import shlex
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sshsrc
import tmuxlink
from background import Background
from sshsrc import tilde
from table import Column, TableApp, run
from tui import DIM, GREEN, SUB, TEXT, YELLOW

ICON = dict(copy="\U000F018F", add="\U000F0415", remove="\U000F0374", new="\U000F0306", all="\U000F0306")


class Keys(TableApp):
    icon = "\U000F0306"
    title = "Keys"
    noun = "keys"
    interval = 3.0
    sort_key = "name"
    search_keys = ("name", "type", "comment", "used_by")
    columns = [Column("name", "KEY", 24, min=12),
               Column("pass", "PASS", 4),
               Column("type", "TYPE", 7, optional=True),
               Column("agent_txt", "AGENT", 6, sort="agent", desc=True),
               Column("used_by", "USED BY", min=8),
               Column("comment", "COMMENT", 24, optional=True)]

    def __init__(self, screen):
        self.bg = Background(self.wake, fallback=dict)
        self.problem = ""
        super().__init__(screen)

    def users(self):
        """{key path: [hosts]} from what ssh -G says for every host of ~/.ssh/config."""
        out = {}
        for alias, _ in sshsrc.concrete_hosts():
            for k in sshsrc.key_files(sshsrc.resolve(alias)):
                out.setdefault(k, []).append(alias)
        return out

    def fetch(self):
        # ssh-add -l in the background: a slow agent (Windows' bridge on WSL…) must not freeze the pane
        agent = self.bg.get(("agent",), sshsrc.agent_keys, 3)
        loaded, self.problem = agent if isinstance(agent, tuple) else ({}, "")
        users = self.bg.get_for(("reading",), sshsrc.config_stamp(), self.users, 300) or {}
        found = list(sshsrc.keys())
        have = {k["path"] for k in found}
        for path in sorted(users):                   # keys the config uses from other folders (~/keys/prod…)
            if path not in have:
                k = sshsrc.key_entry(path)
                if k:
                    found.append(k)
        rows = []
        for k in found:
            rows.append({"id": k["path"], "name": k["name"], "path": k["path"], "pub": k["pub"], "type": k["type"],
                         "fp": k["fingerprint"], "comment": k["comment"], "encrypted": k["encrypted"],
                         "pass": "yes" if k["encrypted"] else "no", "agent": k["fingerprint"] in loaded,
                         "agent_txt": "✓" if k["fingerprint"] in loaded else "",
                         "used_by": ", ".join(users.get(k["path"], [])), "agent_only": False})
        mine = {k["fingerprint"] for k in found}
        for fp, (kind, comment) in loaded.items():
            if fp not in mine:
                rows.append({"id": fp, "name": "(agent only)", "path": "", "pub": "", "type": kind, "fp": fp,
                             "comment": comment, "encrypted": False, "pass": "", "agent": True, "agent_txt": "✓",
                             "used_by": "", "agent_only": True})
        return rows

    # ─── look ───
    def summary(self):
        n = sum(1 for r in self.all if r["agent"])
        locked = sum(1 for r in self.all if r["encrypted"] and not r["agent"])
        parts = [f"{TEXT}{n} in the agent"]
        if locked:
            parts.append(f"{YELLOW}{locked} locked")
        return f"{DIM} · ".join(parts)

    def row_colour(self, r):
        if r["agent"]:
            return GREEN
        return YELLOW if r["encrypted"] and r["used_by"] else SUB

    def detail(self, r):
        if r["agent_only"]:
            return f"{TEXT}{r['comment']}{DIM} · {r['fp']} · held by the agent, not a file in ~/.ssh (forwarded, or added from elsewhere)"
        state = ("in the agent: ssh, git and tunnels use it without asking" if r["agent"] else
                 "has a passphrase and is not in the agent: background ssh (tunnels, git fetch) cannot use it"
                 if r["encrypted"] else "no passphrase: works without the agent")
        return f"{TEXT}{tilde(r['path'])}{DIM} · {r['type']} · {state} · {r['fp']}"

    def footer(self, y):
        r = self.current()
        if self.problem and not (self.ask or self.prompt or self.msg):
            return f" {YELLOW}{self.problem} (SSH_AUTH_SOCK){DIM} · " + (self.detail(r) if r else "")
        return super().footer(y)

    def env(self):
        """The agent this pane sees (a popup starts with tmux's environment, maybe another one)."""
        sock = sshsrc.ssh_env().get("SSH_AUTH_SOCK")
        return {"SSH_AUTH_SOCK": sock} if sock else {}

    def menu_title(self, r):
        return r["name"]

    # ─── menu ───
    def menu_items(self, r):
        if r["agent_only"]:
            return [(f"{ICON['copy']}  Copy the fingerprint", "f", lambda: self.copy(r["fp"], "the fingerprint"))]
        return [(f"{ICON['copy']}  Copy the public key", "c", (lambda: self.copy_pub(r)) if r["pub"] else None),
                (f"{ICON['add']}  Add to the agent" + ("…" if r["encrypted"] else ""), "a",
                 (lambda: self.add(r)) if not r["agent"] and not self.problem else None),
                (f"{ICON['remove']}  Remove from the agent", "r", (lambda: self.remove(r)) if r["agent"] else None),
                (f"{ICON['copy']}  Copy the fingerprint", "f", lambda: self.copy(r["fp"], "the fingerprint")),
                ("", "", None)] + self.empty_menu_items()

    def empty_menu_items(self):
        locked = [r for r in self.all if not r["agent"] and not r["agent_only"]]
        return [(f"{ICON['new']}  Create a new key…", "n", self.ask_new),
                (f"{ICON['all']}  Add every key to the agent ({len(locked)})…", "A",
                 (lambda: self.add_all(locked)) if locked and not self.problem else None)]

    def on_double(self, r, col, x):
        if r["pub"]:
            self.copy_pub(r)
        else:
            super().on_double(r, col, x)

    # ─── actions ───
    def copy_pub(self, r):
        try:
            with open(r["pub"], encoding="utf-8") as f:
                text = f.read().strip()
        except OSError as e:
            self.flash(f"cannot read {tilde(r['pub'])}: {e.strerror}", ok=False)
            return
        tmuxlink.copy(text)
        self.flash(f"copied the public key {os.path.basename(r['pub'])}: paste it in GitHub, a server's authorized_keys…")

    def add(self, r):
        if r["encrypted"]:           # the passphrase is typed in the popup
            self.popup(f"ssh-add · {r['name']}", f"ssh-add {shlex.quote(r['path'])} || {{ printf '\\npress Enter'; read -r _; }}",
                       "70%", "30%", env=self.env())
            return
        rc, out, err = sshsrc.run(["ssh-add", r["path"]], timeout=10)      # no passphrase: no popup needed
        self.flash(f"{r['name']} is in the agent" if rc == 0 else f"ssh-add: {(err or out).strip()[:80]}", ok=rc == 0)
        self.bg.forget(("agent",))
        self.reload()

    def add_all(self, rows):
        paths = " ".join(shlex.quote(r["path"]) for r in rows)
        self.popup("ssh-add · every key", f"ssh-add {paths}; printf '\\npress Enter'; read -r _", "70%", "40%", env=self.env())

    def remove(self, r):
        target = r["pub"] or r["path"]
        rc, out, err = sshsrc.run(["ssh-add", "-d", target], timeout=10)
        self.flash(f"{r['name']} is out of the agent" if rc == 0 else f"ssh-add -d: {(err or out).strip()[:80]}", ok=rc == 0)
        self.bg.forget(("agent",))
        self.reload()

    def ask_new(self):
        def create(text):
            name = re.sub(r"[^\w.\-]", "", text.strip())
            if not name:
                return
            path = os.path.join(sshsrc.SSH_DIR, f"id_ed25519_{name}")
            if os.path.exists(path):
                self.flash(f"{tilde(path)} exists already", ok=False)
                return
            self.popup(f"new key · {tilde(path)}",
                       f"mkdir -p -m 700 {shlex.quote(sshsrc.SSH_DIR)} && "
                       f"ssh-keygen -t ed25519 -f {shlex.quote(path)} -C {shlex.quote(name)} && "
                       f"printf '\\n  Public key (right-click it in Keys → Copy the public key):\\n\\n' && cat {shlex.quote(path)}.pub; "
                       f"printf '\\npress Enter'; read -r _", "80%", "60%")
        self.ask_text("New ed25519 key · a name (work, github, the server…):", "", create)

    def copy(self, text, what):
        tmuxlink.copy(text)
        self.flash(f"copied {what}")


if __name__ == "__main__":
    run(Keys)
