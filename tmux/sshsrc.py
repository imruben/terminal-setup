# ═══════════════════════════════════════════════════════════════
#  What the ssh tab knows (tmux/ssh_hosts.py, tmux/ssh_host.py, tmux/ssh_keys.py)
#
#  Hosts   every Host of ~/.ssh/config (and the files it Includes) that names one
#          host, plus the ones you reached by hand (ssh user@1.2.3.4) from your
#          shell history. ssh -G says how ssh would really connect to each.
#  Keys    the key pairs in ~/.ssh, which ones the ssh-agent holds, which hosts use them
#  Live    the ssh processes running now (sessions and tunnels), from ps
#  Nothing here logs in by itself, except asking a git host (GitHub, GitLab…)
#  which account a key belongs to: that is what `ssh -T git@github.com` is for.
# ═══════════════════════════════════════════════════════════════

import fnmatch
import glob
import os
import re
import shlex
import socket
import subprocess
import time

HOME = os.path.expanduser("~")
SSH_DIR = os.path.join(HOME, ".ssh")
CONFIG = os.path.join(SSH_DIR, "config")
GIT_HOSTS = {"github.com": "GitHub", "gitlab.com": "GitLab", "bitbucket.org": "Bitbucket",
             "codeberg.org": "Codeberg", "ssh.dev.azure.com": "Azure DevOps", "gitea.com": "Gitea"}
HISTORY = [os.path.join(HOME, ".zsh_history"), os.path.join(HOME, ".bash_history")]
# ssh options that take a value (the destination is the first word that is neither)
ARG_OPTS = set("BbcDEeFIiJLlmOoPpQRSWw")
CLIENTS = ("ssh", "scp", "sftp", "rsync", "mosh", "sshfs")


def tilde(p):
    return "~" + p[len(HOME):] if p == HOME or p.startswith(HOME + "/") else p


def ssh_env():
    """The environment for ssh tools: the agent of this setup (~/.ssh/agent.sock, see
    zsh/platform/linux.zsh) when tmux started without SSH_AUTH_SOCK."""
    env = dict(os.environ)
    sock = env.get("SSH_AUTH_SOCK", "")
    if not (sock and os.path.exists(sock)) and os.path.exists(os.path.join(SSH_DIR, "agent.sock")):
        env["SSH_AUTH_SOCK"] = os.path.join(SSH_DIR, "agent.sock")
    return env


def run(argv, timeout=10, env=None):
    """(returncode, stdout, stderr) · never a terminal: nothing can ask for a password here."""
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                             env=env or ssh_env(), start_new_session=True, errors="replace")
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "no answer"
    except OSError as e:
        return 127, "", e.strerror or "cannot run"


# ─── ~/.ssh/config ───
def config_stamp():
    """Changes when ~/.ssh/config or a file it Includes changes."""
    blocks()
    return _blocks_cache[0]


_blocks_cache = [None, None]


def blocks():
    """Every Host / Match block, in the order ssh reads them: {kind, patterns, file, line,
    end, first (the first block of its file)} · Include followed (up to 4 deep)."""
    stamp = []
    out = []

    def read(path, depth):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
            stamp.append((path, os.path.getmtime(path)))
        except OSError:
            return
        cur = {"kind": "top", "patterns": [], "file": path, "line": 1, "end": 0, "first": True}
        out.append(cur)
        for n, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, value = _kv(line)
            key = key.lower()
            if key in ("host", "match"):
                cur["end"] = n - 1
                cur = {"kind": key, "patterns": value.split() if key == "host" else [value], "file": path,
                       "line": n, "end": len(lines), "first": False}
                out.append(cur)
            elif key == "include" and depth < 4:
                for pat in value.split():
                    pat = os.path.expanduser(pat)
                    pat = pat if os.path.isabs(pat) else os.path.join(SSH_DIR, pat)
                    for p in sorted(glob.glob(pat)):
                        read(p, depth + 1)
        cur["end"] = len(lines)

    if _blocks_cache[0] is not None and _blocks_cache[0] == _restat(_blocks_cache[0]):
        return _blocks_cache[1]
    read(CONFIG, 0)
    _blocks_cache[0], _blocks_cache[1] = tuple(stamp) or ((CONFIG, 0),), out
    return out


def _restat(stamp):
    return tuple((p, os.path.getmtime(p) if os.path.exists(p) else 0) for p, _ in stamp)


def _kv(line):
    """'Key value', 'Key=value' or 'Key = value' → (key, value without quotes / comment)."""
    m = re.match(r"(\S+?)(?:\s*=\s*|\s+)(.*)$", line)
    if not m:
        return line, ""
    value = m[2].strip()
    if value.startswith('"') and value.endswith('"') and len(value) > 1:
        value = value[1:-1]
    return m[1], value


def block_text(b):
    try:
        with open(b["file"], encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    chunk = lines[b["line"] - 1:b["end"]]
    while chunk and not chunk[-1].strip():
        chunk.pop()
    return chunk


def concrete_hosts():
    """[(alias, block)] of the Host lines that name a host (no * ? or !), first one wins."""
    seen, out = set(), []
    for b in blocks():
        if b["kind"] != "host":
            continue
        for p in b["patterns"]:
            if not any(c in p for c in "*?!") and p not in seen:
                seen.add(p)
                out.append((p, b))
    return out


def matches(patterns, name):
    """ssh's rule: one pattern matches and no negated (!) one does."""
    hit = False
    for p in patterns:
        if p.startswith("!"):
            if fnmatch.fnmatchcase(name, p[1:]):
                return False
        elif fnmatch.fnmatchcase(name, p):
            hit = True
    return hit


def applying(alias):
    """The blocks that apply to alias, in order (Match blocks: maybe, ssh decides)."""
    host = alias.rsplit("@", 1)[-1]
    out = []
    for b in blocks():
        if b["kind"] == "top" and b["end"] >= b["line"] and any(l.strip() and not l.strip().startswith("#")
                                                                  for l in block_text(b)):
            out.append(b)
        elif b["kind"] == "host" and matches(b["patterns"], host):
            out.append(b)
        elif b["kind"] == "match":
            out.append(b)
    return out


MULTI = {"identityfile", "localforward", "remoteforward", "dynamicforward", "certificatefile", "sendenv", "setenv"}


def resolve(dest):
    """How ssh would connect to dest (`ssh -G`): {option: value} (lists for repeatable ones)."""
    rc, out, _ = run(["ssh", "-G", dest], timeout=5)
    if rc:
        return {}
    cfg = {}
    for line in out.splitlines():
        key, _, value = line.partition(" ")
        if key in MULTI:
            cfg.setdefault(key, []).append(value)
        else:
            cfg[key] = value
    return cfg


def key_files(cfg):
    """The identity files of a resolved host that exist, as full paths."""
    out = []
    for p in cfg.get("identityfile", []):
        p = os.path.expanduser(p)
        if os.path.exists(p) and p not in out:
            out.append(p)
    return out


def git_service(cfg):
    return GIT_HOSTS.get(cfg.get("hostname", "").lower(), "")


# ─── history and what runs now ───
def parse_command(cmd):
    """'ssh -p 2222 root@1.2.3.4 uptime' → ('ssh', 'root@1.2.3.4') · None when it is not an
    ssh-family command with a destination."""
    try:
        words = shlex.split(cmd, comments=True)
    except ValueError:
        words = cmd.split()
    while words and (words[0] in ("sudo", "exec", "command", "time", "nohup") or "=" in words[0]):
        words = words[1:]
    if not words:
        return None
    prog = os.path.basename(words[0])
    if prog not in CLIENTS:
        return None
    if prog == "ssh":
        i = 1
        while i < len(words):
            w = words[i]
            if w == "--":
                i += 1
                break
            if w.startswith("-") and len(w) > 1:
                letter = w[-1]
                if letter in ARG_OPTS and len(w) == 2:      # the value is the next word
                    i += 2
                    continue
                i += 1
                continue
            break
        if i >= len(words):
            return None
        dest = words[i]
        if dest.startswith("ssh://"):
            dest = dest[6:].split("/", 1)[0].rsplit(":", 1)[0]
        return prog, dest
    # scp / rsync / sftp / sshfs / mosh: the first word with host: (or the last word)
    for w in words[1:]:
        if w.startswith("-"):
            continue
        m = re.match(r"^(?:[\w.\-]+@)?[\w.\-]+(?=:)", w)
        if m and not w.startswith("/"):
            return prog, m[0]
    if prog in ("sftp", "mosh") and len(words) > 1 and not words[-1].startswith("-"):
        return prog, words[-1]
    return None


_hist_cache = [None, None]


def history():
    """[(time or None, command, prog, destination)] of the ssh-family commands in your
    shell history, oldest first (zsh's extended history has the times)."""
    stamp = tuple((p, os.path.getmtime(p)) for p in HISTORY if os.path.exists(p))
    if _hist_cache[0] == stamp:
        return _hist_cache[1]
    out = []
    for path in HISTORY:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        text = data.decode("utf-8", "replace")
        for line in text.splitlines():
            when = None
            m = re.match(r"^: (\d+):\d+;(.*)$", line)
            if m:
                when, line = int(m[1]), m[2]
            if not any(c in line for c in CLIENTS) or len(line) > 500:
                continue
            hit = parse_command(line)
            if hit:
                out.append((when, line, hit[0], hit[1]))
    _hist_cache[0], _hist_cache[1] = stamp, out
    return out


def host_of(dest):
    return dest.rsplit("@", 1)[-1]


def live():
    """{destination host: [(pid, kind, command)]} of the ssh processes running now
    (kind: 'session', 'tunnel' or 'command') · git's own ssh calls are left out."""
    rc, out, _ = run(["ps", "-axo", "pid=,args="], timeout=5)
    found = {}
    for line in out.splitlines():
        pid, _, args = line.strip().partition(" ")
        args = args.strip()
        if not pid.isdigit() or not re.match(r"^(\S*/)?ssh(\s|$)", args):
            continue
        if "git-upload-pack" in args or "git-receive-pack" in args or " -G " in f" {args} " or " -O " in f" {args} ":
            continue
        hit = parse_command(args)
        if not hit:
            continue
        words = args.split()
        tunnel = "-N" in words or any(w in ("-L", "-R", "-D") or w.startswith(("-L", "-R", "-D")) for w in words[1:])
        try:
            rest = args.split(hit[1], 1)[1].strip()
        except IndexError:
            rest = ""
        kind = "tunnel" if tunnel else ("command" if rest else "session")
        found.setdefault(host_of(hit[1]), []).append((int(pid), kind, args))
    return found


# ─── reaching a host ───
def probe(host, port, timeout=3.0):
    """(milliseconds, '') when something answers on host:port · (None, why) otherwise."""
    start = time.monotonic()
    try:
        with socket.create_connection((host, int(port or 22)), timeout=timeout):
            return int((time.monotonic() - start) * 1000), ""
    except socket.gaierror:
        return None, "unknown name"
    except socket.timeout:
        return None, "no answer"
    except ConnectionRefusedError:
        return None, "refused"
    except OSError as e:
        return None, (e.strerror or "unreachable").lower()


ACCOUNT = [re.compile(r"Hi ([\w.\-]+)!"), re.compile(r"Welcome to GitLab, @([\w.\-]+)!"),
           re.compile(r"logged in as ([\w.\-]+)"), re.compile(r"Hi there, ([\w.\-]+)!"),
           re.compile(r"Hi ([\w.\-]+), You've successfully authenticated")]


def login_problem(err):
    """ssh's error → a short explanation."""
    e = err.lower()
    if "permission denied" in e:
        return "key not accepted"
    if "host key verification failed" in e:
        return "unknown host key: connect once in a terminal"
    if "remote host identification has changed" in e:
        return "HOST KEY CHANGED: check before trusting it"
    if "could not resolve" in e:
        return "unknown name"
    if "timed out" in e or "no answer" in e:
        return "no answer"
    if "refused" in e:
        return "refused"
    if "passphrase" in e or "agent" in e:
        return "the key needs its passphrase: add it to the agent"
    lines = [l for l in err.strip().splitlines() if l.strip()]
    return lines[-1][:60] if lines else "failed"


def git_account(dest):
    """(account name, '') of the key a git host sees for dest · ('', why) when it says no."""
    rc, out, err = run(["ssh", "-T", "-l", "git", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", dest], timeout=15)
    text = out + err
    for rx in ACCOUNT:
        m = rx.search(text)
        if m:
            return m[1], ""
    return "", login_problem(text)


def test_login(dest):
    """('', '') when a login works without a password · ('', why) otherwise."""
    rc, out, err = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-T", dest, "true"], timeout=15)
    return ("login ok", "") if rc == 0 else ("", login_problem(err))


def known_host(cfg):
    """The key type known_hosts has for this host ('ED25519'…) or ''."""
    name = cfg.get("hostkeyalias") or cfg.get("hostname", "")
    port = cfg.get("port", "22")
    if not name:
        return ""
    target = name if port == "22" else f"[{name}]:{port}"
    files = [os.path.expanduser(f) for f in cfg.get("userknownhostsfile", "~/.ssh/known_hosts").split()]
    for f in files:
        if not os.path.exists(f):
            continue
        rc, out, _ = run(["ssh-keygen", "-F", target, "-f", f], timeout=5)
        for line in out.splitlines():
            if line and not line.startswith("#"):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1].replace("ssh-", "").replace("ecdsa-sha2-", "ecdsa-").upper()
    return ""


# ─── keys ───
_keys_cache = [None, None]


def keys():
    """[{path, pub, type, bits, fingerprint, comment, encrypted}] of the key pairs in ~/.ssh
    (read again only when a file there changes)."""
    out, seen = [], set()
    try:
        names = sorted(os.listdir(SSH_DIR))
        stamp = tuple((n, os.path.getmtime(os.path.join(SSH_DIR, n))) for n in names)
    except OSError:
        return []
    if _keys_cache[0] == stamp:
        return _keys_cache[1]
    for name in names:
        path = os.path.join(SSH_DIR, name)
        if name.endswith(".pub") or not os.path.isfile(path) or name in ("config", "known_hosts", "authorized_keys"):
            continue
        try:
            with open(path, "rb") as f:
                head = f.read(4096)
        except OSError:
            continue
        if b"PRIVATE KEY-----" not in head[:80]:
            continue
        pub = path + ".pub" if os.path.exists(path + ".pub") else ""
        rc, text, _ = run(["ssh-keygen", "-lf", pub or path], timeout=5)
        m = re.match(r"(\d+) (\S+) (.*) \((\w+)\)$", text.strip())
        bits, fp, comment, kind = (m.groups() if m else ("", "", "", "?"))
        encrypted = is_encrypted(head)
        seen.add(path)
        out.append({"path": path, "name": name, "pub": pub, "type": kind, "bits": bits, "fingerprint": fp,
                    "comment": comment, "encrypted": encrypted})
    _keys_cache[0], _keys_cache[1] = stamp, out
    return out


def is_encrypted(head):
    """Does the private key need a passphrase? Old PEM keys say so in a header; OpenSSH's
    own format names its cipher inside the base64 body ('none' = no passphrase)."""
    if b"ENCRYPTED" in head:
        return True
    if b"BEGIN OPENSSH PRIVATE KEY" not in head:
        return False
    import base64
    body = b"".join(l.strip() for l in head.splitlines()[1:] if l.strip() and not l.startswith(b"-----"))
    try:
        raw = base64.b64decode(body[:200] + b"=" * (-len(body[:200]) % 4))
    except ValueError:
        return False
    magic = b"openssh-key-v1\0"
    if not raw.startswith(magic):
        return False
    n = int.from_bytes(raw[len(magic):len(magic) + 4], "big")
    return raw[len(magic) + 4:len(magic) + 4 + n] != b"none"


def agent_keys():
    """({fingerprint: (type, comment)} of the keys the agent holds, problem or '')."""
    rc, out, err = run(["ssh-add", "-l"], timeout=5)
    if rc == 2 or "could not open" in err.lower() or "error connecting" in err.lower():
        return {}, "no ssh-agent running"
    held = {}
    for line in out.splitlines():
        m = re.match(r"(\d+) (\S+) (.*) \((\w+)\)$", line.strip())
        if m:
            held[m[2]] = (m[4], m[3])
    return held, ""


# ─── ages ───
def ago(stamp, now=None):
    if stamp is None:
        return ""
    secs = max(0, int((now or time.time()) - stamp))
    for n, unit in ((86400 * 365, "y"), (86400 * 30, "mo"), (86400 * 7, "w"), (86400, "d"), (3600, "h"), (60, "m")):
        if secs >= n:
            return f"{secs // n}{unit}"
    return "now"
