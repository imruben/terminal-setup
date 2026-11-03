# ═══════════════════════════════════════════════════════════════
#  What the git tab knows about your repos (tmux/git_repos.py, tmux/git_repo.py)
#
#  Where to look: ~/.tmux/git-roots, one folder per line, optionally followed by
#  how deep to look inside it (default 4):
#      ~/workspace
#      ~/clients 2
#  Without that file: ~/workspace, ~/projects, ~/code, ~/src, ~/dev, ~/repos and
#  ~/git, those that exist (else your home, 3 deep). The Repos pane edits the file.
#
#  A repo is a folder with .git in it; nothing inside a repo is looked into, nor
#  hidden folders (unless they are a repo themselves: ~/.dotfiles) or dependency
#  and build folders (node_modules, vendor, .venv, target…).
#  git runs with GIT_OPTIONAL_LOCKS=0: reading the status never takes the index
#  lock, so it never gets in the way of your own git commands.
# ═══════════════════════════════════════════════════════════════

import glob
import os
import re
import subprocess
import time
import urllib.parse

HOME = os.path.expanduser("~")
ROOTS_FILE = os.path.join(HOME, ".tmux", "git-roots")
DEFAULT_ROOTS = ["workspace", "projects", "code", "src", "dev", "repos", "git"]
DEFAULT_DEPTH = 4
SKIP = {"node_modules", "vendor", "venv", "__pycache__", "site-packages", "target", "dist", "build",
        "bower_components", "Pods", "DerivedData", "Library", "Applications", "snap", "go", "pkg"}
GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0",
           "GIT_PAGER": "cat", "PAGER": "cat"}


def tilde(p):
    return "~" + p[len(HOME):] if p == HOME or p.startswith(HOME + "/") else p


def expand(p):
    return os.path.abspath(os.path.expanduser(p.strip()))


# ─── where to look ───
def read_roots():
    """[(folder, depth)] and whether they come from ~/.tmux/git-roots (False: the defaults)."""
    try:
        with open(ROOTS_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        found = [os.path.join(HOME, d) for d in DEFAULT_ROOTS if os.path.isdir(os.path.join(HOME, d))]
        return ([(p, DEFAULT_DEPTH) for p in found] or [(HOME, 3)]), False
    roots = []
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        path, _, depth = line.rpartition(" ")
        if not (path and depth.isdigit()):        # no depth given (or a path with spaces)
            path, depth = line, str(DEFAULT_DEPTH)
        roots.append((expand(path), int(depth)))
    return roots, True


def write_roots(roots):
    os.makedirs(os.path.dirname(ROOTS_FILE), exist_ok=True)
    head = ("# Folders the git tab of the system monitor looks for repos in (tmux/gitsrc.py)\n"
            "# one per line, optionally followed by how deep to look (default 4)\n")
    body = "".join(f"{tilde(p)}{'' if d == DEFAULT_DEPTH else f' {d}'}\n" for p, d in roots)
    tmp = ROOTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(head + body)
    os.replace(tmp, ROOTS_FILE)


def ensure_roots_file():
    """The file, created from what is used now when there is none (to edit it by hand)."""
    roots, saved = read_roots()
    if not saved:
        write_roots(roots)
    return ROOTS_FILE


def add_root(path, depth=DEFAULT_DEPTH):
    """Add a folder · returns an error text, or '' when it was added."""
    path = expand(path)
    if not os.path.isdir(path):
        return f"{tilde(path)} is not a folder"
    roots, _ = read_roots()
    if any(p == path for p, _ in roots):
        return f"{tilde(path)} is already in the list"
    write_roots(roots + [(path, depth)])
    return ""


def remove_root(path):
    roots, _ = read_roots()
    write_roots([(p, d) for p, d in roots if p != path])


def find_repos(roots):
    """{repo path: root it was found under} · a root that is a repo itself counts too."""
    found = {}

    def walk(path, depth, root):
        if os.path.exists(os.path.join(path, ".git")):
            found.setdefault(path, root)
            return
        if depth <= 0:
            return
        try:
            entries = list(os.scandir(path))
        except OSError:
            return
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if e.name == ".git":
                continue
            if os.path.exists(os.path.join(e.path, ".git")):    # a repo, whatever its name
                found.setdefault(e.path, root)
            elif not (e.name in SKIP or e.name.startswith(".")):
                walk(e.path, depth - 1, root)

    for root, depth in roots:
        if os.path.isdir(root):
            walk(root, depth, root)
    return found


# ─── asking git ───
def git(repo, *args, timeout=15):
    try:
        res = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=GIT_ENV,
                             timeout=timeout, stdin=subprocess.DEVNULL, errors="replace")
        return res
    except (subprocess.TimeoutExpired, OSError):
        return None


def git_out(repo, *args, timeout=15):
    res = git(repo, *args, timeout=timeout)
    return res.stdout if res and res.returncode == 0 else ""


def git_dir(repo):
    """The repo's .git folder (a worktree or submodule has a .git file pointing to it)."""
    dot = os.path.join(repo, ".git")
    if os.path.isfile(dot):
        try:
            with open(dot, encoding="utf-8") as f:
                line = f.read().strip()
            if line.startswith("gitdir:"):
                d = line[7:].strip()
                return d if os.path.isabs(d) else os.path.normpath(os.path.join(repo, d))
        except OSError:
            pass
    return dot


def in_progress(gdir):
    """What git is in the middle of ('rebasing', 'merging'…) or ''."""
    for name, what in (("rebase-merge", "rebasing"), ("rebase-apply", "rebasing"), ("MERGE_HEAD", "merging"),
                       ("CHERRY_PICK_HEAD", "cherry-picking"), ("REVERT_HEAD", "reverting"),
                       ("BISECT_LOG", "bisecting")):
        if os.path.exists(os.path.join(gdir, name)):
            return what
    return ""


_STASH_OK = [True]          # git < 2.35 has no --show-stash: asked without it from then on


def status(repo):
    """The repo as one dict: branch, upstream, ahead / behind, changes, stash, last commit,
    what git is in the middle of, last fetch · None when git cannot read it."""
    args = ["status", "--porcelain=v2", "--branch"] + (["--show-stash"] if _STASH_OK[0] else [])
    res = git(repo, *args)
    if res and res.returncode and "show-stash" in res.stderr:
        _STASH_OK[0] = False
        res = git(repo, "status", "--porcelain=v2", "--branch")
    if not res or res.returncode:
        err = (res.stderr.strip().splitlines() or ["git did not answer"])[-1] if res else "git did not answer in 15 s"
        return {"error": err}
    st = {"branch": "", "oid": "", "upstream": "", "ahead": 0, "behind": 0, "stash": 0,
          "staged": 0, "modified": 0, "untracked": 0, "conflicts": 0, "error": ""}
    for line in res.stdout.splitlines():
        if line.startswith("# branch.head "):
            st["branch"] = line[14:]
        elif line.startswith("# branch.oid "):
            st["oid"] = line[13:]
        elif line.startswith("# branch.upstream "):
            st["upstream"] = line[18:]
        elif line.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", line)
            if m:
                st["ahead"], st["behind"] = int(m[1]), int(m[2])
        elif line.startswith("# stash "):
            st["stash"] = int(line[8:]) if line[8:].isdigit() else 0
        elif line[:2] in ("1 ", "2 "):
            xy = line[2:4]
            st["staged"] += xy[0] != "."
            st["modified"] += xy[1] != "."
        elif line.startswith("u "):
            st["conflicts"] += 1
        elif line.startswith("? "):
            st["untracked"] += 1
    if st["branch"] == "(detached)":
        st["branch"] = ""
        st["detached"] = st["oid"][:8]
    gdir = git_dir(repo)
    st["doing"] = in_progress(gdir)
    try:
        st["fetched"] = os.path.getmtime(os.path.join(gdir, "FETCH_HEAD"))
    except OSError:
        st["fetched"] = None
    last = git_out(repo, "log", "-1", "--format=%ct%x1f%s%x1f%an").strip().split("\x1f")
    st["last"] = int(last[0]) if last and last[0].isdigit() else None
    st["subject"] = last[1][:200] if len(last) > 1 else ""      # a message with no blank line is all subject
    st["author"] = last[2] if len(last) > 2 else ""
    return st


def settings(repo):
    """Slow-changing things: remotes, and who you commit as (with the file that says so,
    e.g. a ~/.gitconfig-work picked by includeIf)."""
    remotes = {}
    for line in git_out(repo, "config", "--get-regexp", r"^remote\..*\.url$").splitlines():
        key, _, url = line.partition(" ")
        remotes[key[len("remote."):-len(".url")]] = url
    who = {}
    for key in ("user.name", "user.email"):
        out = git_out(repo, "config", "--show-origin", "--get", key).rstrip("\n")
        origin, _, value = out.partition("\t")
        who[key] = (value, origin[5:] if origin.startswith("file:") else origin)
    remote = "origin" if "origin" in remotes else (sorted(remotes)[0] if remotes else "")
    return {"remotes": remotes, "remote": remote, "url": remotes.get(remote, ""),
            "name": who["user.name"][0], "email": who["user.email"][0], "email_from": who["user.email"][1]}


# ─── remotes: ssh aliases (Host github-work → github.com) and web pages ───
def ssh_aliases():
    """{alias: real host name} from ~/.ssh/config (Host / HostName pairs, Include too)."""
    out = {}

    def read(path, depth=0):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            return
        hosts = []
        for line in lines:
            parts = line.strip().split(None, 1)
            if len(parts) < 2 or parts[0].startswith("#"):
                continue
            key, value = parts[0].lower(), parts[1].split("#", 1)[0].strip().strip('"')
            if key == "host":
                hosts = [h for h in value.split() if not any(c in h for c in "*?!")]
            elif key == "match":
                hosts = []
            elif key == "hostname":
                for h in hosts:
                    out.setdefault(h, value)
            elif key == "include" and depth < 4:
                for pat in value.split():
                    pat = os.path.expanduser(pat)
                    pat = pat if os.path.isabs(pat) else os.path.join(HOME, ".ssh", pat)
                    for p in sorted(glob.glob(pat)):
                        read(p, depth + 1)
    read(os.path.join(HOME, ".ssh", "config"))
    return out


SCP_LIKE = re.compile(r"^(?:[^@/]+@)?([^:/]+):(.+)$")


def parse_remote(url, aliases=None):
    """(host, 'owner/repo', web page or '') of a remote URL · ssh aliases resolved."""
    url = (url or "").strip()
    if not url:
        return "", "", ""
    host, path = "", ""
    if "://" in url:
        u = urllib.parse.urlsplit(url)
        host, path = (u.hostname or ""), u.path
    else:
        m = SCP_LIKE.match(url)
        if m:
            host, path = m[1], m[2]
        else:
            return "", tilde(url), ""                 # a local path
    host = (aliases or {}).get(host, host)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    web = ""
    if url.startswith(("https://", "http://")) and path:      # the URL itself, without user:password@ or .git
        u = urllib.parse.urlsplit(url)
        netloc = (u.hostname or "") + (f":{u.port}" if u.port else "")
        web = f"{u.scheme}://{netloc}/{path}"
    elif host and path and is_forge(host):
        web = f"https://{host}/{path}"
    return host, path, web


FORGES = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "gitea.com", "sr.ht", "dev.azure.com")


def is_forge(host):
    """A host whose repos have a web page at https://HOST/OWNER/REPO."""
    host = host.lower()
    return host in FORGES or host.startswith(("gitlab.", "github.", "gitea.", "forgejo.", "bitbucket.", "git."))


# ─── ages ───
def ago_text(stamp):
    """'3h ago' · 'just now' (for sentences; ago() is for columns)."""
    a = ago(stamp)
    return "just now" if a == "now" else f"{a} ago" if a else ""


def ago(stamp, now=None):
    """Seconds since the epoch → '5m', '3h', '2d', '4mo', '1y' (None → '')."""
    if stamp is None:
        return ""
    secs = max(0, int((now or time.time()) - stamp))
    for n, unit in ((86400 * 365, "y"), (86400 * 30, "mo"), (86400 * 7, "w"), (86400, "d"), (3600, "h"), (60, "m")):
        if secs >= n:
            return f"{secs // n}{unit}"
    return "now"
