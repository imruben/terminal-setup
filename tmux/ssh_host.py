#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Host pane of the `ssh` tab · follows the host highlighted in Hosts
#
#  Info    how ssh really connects (ssh -G): address and what it resolves to,
#          user, port, keys (exists · passphrase · in the agent), proxy / jump,
#          forwards, whether known_hosts knows it, where it is defined, the
#          sessions and tunnels open now, when you last used it
#  Config  the blocks of ~/.ssh/config (and Included files) that apply to it,
#          in the order ssh reads them: the first value of each option wins
#  Recent  your ssh, scp, rsync, sftp… commands with this host, newest first
# ═══════════════════════════════════════════════════════════════

import datetime
import os
import shutil
import socket
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sshsrc
from sshsrc import ago, tilde
from tui import BLUE, BOLD, DIM, GREEN, RED, RESET, SUB, TEXT, YELLOW
from viewer import BackgroundViewer, run

BAT = shutil.which("bat") or shutil.which("batcat")
SHOWN = ("hostname", "user", "port", "identityfile", "identitiesonly", "proxyjump", "proxycommand", "forwardagent",
         "localforward", "remoteforward", "dynamicforward", "addkeystoagent", "controlmaster", "controlpath",
         "serveraliveinterval", "stricthostkeychecking", "requesttty", "remotecommand")


def k(label):
    return f"  {DIM}{label:<12}{RESET}"


class Host(BackgroundViewer):
    icon = "\U000F08C0"
    title = "Host"
    option = "@ssh-selected"
    tabs = ["Info", "Config", "Recent"]
    interval = 0.3
    refresh_every = 5
    empty = "highlight a host in the Hosts pane"

    def compute(self, dest, tab, width):              # in a thread (BackgroundViewer): DNS, ssh -G, ps…
        if tab == "Config":
            return self.config(dest, width)
        if tab == "Recent":
            return self.recent(dest)
        return self.info(dest)

    # ─── Info ───
    def info(self, dest):
        c = sshsrc.resolve(dest, self.extra(dest))
        if not c:
            why = sshsrc.ERRORS.get(dest, "is ssh installed?")
            return [f"  {RED}ssh -G {dest} failed: {why}",
                    f"  {DIM}a typo in ~/.ssh/config? Hosts → right-click → Edit ~/.ssh/config"]
        lines = [k("Connect") + f"{TEXT}{BOLD}ssh {dest}{RESET}"]
        host, port = c.get("hostname", dest), c.get("port", "22")
        addr = ""
        if any(ch.isalpha() for ch in host.replace(":", "")):      # a name, not an IP: what it points to
            try:
                addr = socket.getaddrinfo(host, None)[0][4][0]
            except (socket.gaierror, OSError, IndexError, ValueError):
                addr = f"{RED}does not resolve"
        lines.append(k("Address") + f"{TEXT}{host}{DIM}" + (f"  → {addr}" if addr else "") + (f"  port {port}" if port != "22" else ""))
        lines.append(k("User") + f"{TEXT}{c.get('user', '?')}")
        service = sshsrc.git_service(c)
        if service:
            lines.append(k("Service") + f"{TEXT}{service}{DIM} · git over ssh, no shell: Hosts → right-click asks which account your key is")
        held, problem = sshsrc.agent_keys()
        by_path = {key["path"]: key for key in sshsrc.keys()}
        shown = 0
        for p in sshsrc.key_files(c):              # %h %r… expanded, only the ones that exist
            key = by_path.get(p) or sshsrc.key_entry(p)
            if key:
                state = (f"{GREEN}in the agent" if key["fingerprint"] in held else
                         f"{YELLOW}passphrase, not in the agent" if key["encrypted"] else f"{DIM}no passphrase")
                lines.append(k("Key" if shown == 0 else "") + f"{TEXT}{tilde(p)}{DIM}  {key['type']} · {state}")
            else:
                lines.append(k("Key" if shown == 0 else "") + f"{TEXT}{tilde(p)}")
            shown += 1
        if not shown:
            lines.append(k("Key") + f"{YELLOW}no key file: it logs in with a password (or the agent's keys)")
        if c.get("identitiesonly") == "yes":
            lines.append(k("") + f"{DIM}IdentitiesOnly: only these keys are offered")
        for opt, label in (("proxyjump", "Jump via"), ("proxycommand", "Proxy")):
            if c.get(opt, "none") != "none":
                lines.append(k(label) + f"{TEXT}{c[opt]}")
        for opt, label in (("localforward", "Forward"), ("remoteforward", "Reverse"), ("dynamicforward", "SOCKS")):
            for n, v in enumerate(c.get(opt, [])):
                lines.append(k(label if n == 0 else "") + f"{TEXT}{v}")
        if c.get("forwardagent") == "yes":
            lines.append(k("Agent") + f"{YELLOW}forwarded: the server can use your keys while you are connected")
        if not service:
            known = sshsrc.known_host(c)
            lines.append(k("Known host") + (f"{GREEN}yes{DIM}  {known} key in known_hosts" if known else
                                            f"{YELLOW}no{DIM}  the first connection asks you to trust its key"))
        lines.append("")
        block = next((b for a, b in sshsrc.concrete_hosts() if a == dest), None)
        lines.append(k("Defined in") + (f"{SUB}{tilde(block['file'])}:{block['line']}" if block else
                                        f"{YELLOW}not in ~/.ssh/config{DIM} (from your history) · Hosts → Add a host…"))
        live = sshsrc.live()
        procs = list({p[0]: p for p in live.get(dest, []) + (live.get(host, []) if host != dest else [])}.values())
        if procs:
            for n, (pid, kind, args, fwd) in enumerate(procs):
                lines.append(k("Open now" if n == 0 else "") + f"{GREEN}{kind}{DIM}  pid {pid} · {args[:120]}")
        else:
            lines.append(k("Open now") + f"{DIM}nothing")
        uses = [h for h in sshsrc.history() if self.about(h, dest, host)]
        last = max((h[0] for h in uses if h[0]), default=None)
        lines.append(k("Used") + (f"{TEXT}{len(uses)} time{'s' if len(uses) != 1 else ''}{DIM}" + (f" · last {ago(last)} ago" if last else "")
                                  if uses else f"{DIM}never from this shell's history"))
        if problem:
            lines += ["", f"  {YELLOW}{problem}: keys with a passphrase are asked every time"]
        return lines

    @staticmethod
    def extra(dest):
        """A host from your history: the options of its last command (-p 2222…)."""
        last = None
        for h in sshsrc.history():
            if h[3] == dest:
                last = h[4]
        return sshsrc.conn_args(last) if last and dest not in [a for a, _ in sshsrc.concrete_hosts()] else []

    @staticmethod
    def about(h, dest, host):
        d = sshsrc.host_of(h[3])
        return h[3] == dest or d == dest or d == host

    # ─── Config ───
    def config(self, dest, width):
        out = []
        for b in sshsrc.applying(dest):
            text = sshsrc.block_text(b)
            if not text:
                continue
            what = (f"Included inside {sshsrc.within_text(b)}" if b["kind"] == "top" and b.get("within") else
                    "before any Host line (applies to every host)" if b["kind"] == "top" else
                    "Match: applies when ssh decides it does" if b["kind"] == "match" else
                    f"Host {' '.join(b['patterns'])}")
            if b["kind"] != "top" and b.get("within"):
                what += f" · inside {sshsrc.within_text(b)}"
            out += [f"  {BOLD}{BLUE}{tilde(b['file'])}:{b['line']}{RESET}  {DIM}{what}", ""]
            out += self.colour("\n".join(text), b["line"], width)
            out.append("")
        if not out:
            return [f"  {DIM}No block of ~/.ssh/config applies to {dest}: ssh uses its defaults."]
        return [f"  {DIM}ssh reads these in order: for each option, the first value it finds wins", ""] + out

    def colour(self, text, first, width):
        if BAT:
            try:
                res = subprocess.run([BAT, "--color=always", "--style=plain", "--paging=never", "--language=ssh_config",
                                      f"--terminal-width={max(20, width - 10)}"], input=text, capture_output=True,
                                     text=True, timeout=10)
                if res.returncode == 0:
                    return [f"  {DIM}{n:4}{RESET}  {line}" for n, line in enumerate(res.stdout.splitlines(), first)]
            except (subprocess.TimeoutExpired, OSError):
                pass
        return [f"  {DIM}{n:4}{RESET}  {TEXT}{line}" for n, line in enumerate(text.splitlines(), first)]

    # ─── Recent ───
    def recent(self, dest):
        c = sshsrc.resolve(dest, self.extra(dest))
        host = c.get("hostname", dest)
        uses = [h for h in sshsrc.history() if self.about(h, dest, host)]
        if not uses:
            return [f"  {DIM}No ssh, scp, rsync… command with {dest} in your shell history."]
        lines = [f"  {DIM}{len(uses)} commands · newest first", ""]
        for when, cmd, prog, d, _ in reversed(uses[-300:]):
            stamp = datetime.datetime.fromtimestamp(when).strftime("%Y-%m-%d %H:%M") if when else "                "
            safe = "".join("?" if ord(ch) < 32 or ord(ch) == 127 else ch for ch in cmd)
            lines.append(f"  {DIM}{stamp}{RESET}  {TEXT}{safe}")
        return lines


if __name__ == "__main__":
    run(Host)
