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
import sys
import re
import subprocess
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))     # also when run as a command
import tmuxlink  # noqa: E402  (run_group: timeouts end the whole process group)

HOME = os.path.expanduser("~")
ROOTS_FILE = os.path.join(HOME, ".tmux", "git-roots")
DEFAULT_ROOTS = ["workspace", "projects", "code", "src", "dev", "repos", "git"]
DEFAULT_DEPTH = 4
SKIP = {"node_modules", "vendor", "venv", "__pycache__", "site-packages", "target", "dist", "build",
        "bower_components", "Pods", "DerivedData", "Library", "Applications", "snap", "go", "pkg"}
# no terminal, no password window (ssh's askpass, Git Credential Manager on WSL), no lazy
# fetch of a partial clone, never the index lock
GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0",
           "GIT_PAGER": "cat", "PAGER": "cat", "SSH_ASKPASS_REQUIRE": "never", "GCM_INTERACTIVE": "never",
           "GIT_NO_LAZY_FETCH": "1"}
MACOS = os.uname().sysname == "Darwin"
# the macOS folders that ask for permission when read: never looked into when walking home
PRIVATE = {"Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music"}


def tilde(p):
    return "~" + p[len(HOME):] if p == HOME or p.startswith(HOME + "/") else p


def expand(p):
    return os.path.abspath(os.path.expanduser(p.strip()))


# ─── where to look ───
COMMENT = re.compile(r"(^|\s)#.*$")          # a # at the start or after a space: a folder can be called a#b
DEPTH = re.compile(r"^(.*\S)\s+(\d{1,2})$")


def parse_root(line):
    """'~/clients 2' → (path, 2) · '~/Projects 2024' (an existing folder) stays that folder · None: no folder."""
    line = COMMENT.sub("", line).strip()
    if not line:
        return None
    if os.path.isdir(expand(line)):
        return expand(line), DEFAULT_DEPTH
    m = DEPTH.match(line)
    return (expand(m[1]), int(m[2])) if m else (expand(line), DEFAULT_DEPTH)


def read_roots():
    """[(folder, depth)] and whether they come from ~/.tmux/git-roots (False: the defaults)."""
    try:
        with open(ROOTS_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        found = [os.path.join(HOME, d) for d in DEFAULT_ROOTS if os.path.isdir(os.path.join(HOME, d))]
        return ([(p, DEFAULT_DEPTH) for p in found] or [(HOME, 3)]), False
    return [r for r in map(parse_root, lines) if r], True


def root_line(path, depth):
    """How a folder is written: the depth only when it is not the default, or when the
    folder's own name ends in digits (it would be read as a depth)."""
    p = tilde(path)
    return f"{p} {depth}" if depth != DEFAULT_DEPTH or DEPTH.match(p) else p


def write_lines(lines):
    """Write the file (through a link: a dotfiles repo keeps its file) atomically."""
    target = os.path.realpath(ROOTS_FILE)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("".join(l + "\n" for l in lines))
    os.replace(tmp, target)


HEADER = ["# Folders the git tab of the system monitor looks for repos in (tmux/gitsrc.py)",
          "# one per line, optionally followed by how deep to look (default 4)"]


def ensure_roots_file():
    """The file, created from what is used now when there is none (to edit it by hand)."""
    roots, saved = read_roots()
    if not saved:
        write_lines(HEADER + [root_line(p, d) for p, d in roots])
    return ROOTS_FILE


def add_root(path, depth=DEFAULT_DEPTH):
    """Add a folder (your comments and lines stay as they are) · an error text, or ''."""
    path = expand(path)
    if not os.path.isdir(path):
        return f"{tilde(path)} is not a folder"
    roots, _ = read_roots()
    if any(p == path for p, _ in roots):
        return f"{tilde(path)} is already in the list"
    ensure_roots_file()
    with open(ROOTS_FILE, encoding="utf-8") as f:
        lines = f.read().splitlines()
    write_lines(lines + [root_line(path, depth)])
    return ""


def remove_root(path):
    """Take a folder's line(s) out; the other lines and comments stay."""
    ensure_roots_file()
    with open(ROOTS_FILE, encoding="utf-8") as f:
        lines = f.read().splitlines()
    write_lines([l for l in lines if (parse_root(l) or ("",))[0] != path])


def find_repos(roots, saved=True):
    """{repo path: root it was found under} · a root that is a repo itself counts too.
    Links are followed (~/workspace/proj → /mnt/d/proj), each real folder once. Without a
    list of your own (saved=False), home's private folders (Documents…) are left alone."""
    found, seen = {}, set()

    def real(p):
        try:
            return os.path.realpath(p)
        except OSError:
            return p

    def add(path, root):
        r = real(path)
        if r not in seen:
            seen.add(r)
            found.setdefault(path, root)

    def walk(path, depth, root):
        r = real(path)
        if os.path.exists(os.path.join(path, ".git")):
            add(path, root)
            return
        if depth <= 0 or ("dir:" + r) in seen:
            return
        seen.add("dir:" + r)
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.is_symlink())    # real folders first
        except OSError:
            return
        for e in entries:
            try:
                if not e.is_dir():                       # follows links: a loop stops at seen
                    continue
            except OSError:
                continue
            if e.name == ".git":
                continue
            if os.path.exists(os.path.join(e.path, ".git")):    # a repo, whatever its name
                add(e.path, root)
            elif not (e.name in SKIP or e.name.startswith(".")
                      or (MACOS and path == HOME and e.name in PRIVATE)):
                if e.is_symlink() and any(real(e.path) == r or real(e.path).startswith(r + "/")
                                          for r in other_roots if r != root):
                    continue                     # a link into another root: that root lists those repos
                walk(e.path, depth - 1, root)

    other_roots = [real(r) for r, _ in roots]
    for root, depth in roots:
        if os.path.isdir(root):
            walk(root, depth, root)
    return found


# ─── asking git ───
def git(repo, *args, timeout=15):
    try:
        # core.fsmonitor is a command in the repo's own config: a repo you only unpacked would run it
        res = tmuxlink.run_group(["git", "-c", "core.fsmonitor=false", "-C", repo, *args], timeout, env=GIT_ENV,
                                 stdin=subprocess.DEVNULL, errors="replace")
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


def common_dir(gdir):
    """The main repo's .git folder of a worktree (its own .git folder otherwise)."""
    try:
        with open(os.path.join(gdir, "commondir"), encoding="utf-8") as f:
            d = f.read().strip()
        return d if os.path.isabs(d) else os.path.normpath(os.path.join(gdir, d))
    except OSError:
        return gdir


def in_progress(gdir):
    """What git is in the middle of ('rebasing', 'merging'…) or ''."""
    for name, what in (("rebase-merge", "rebasing"), ("rebase-apply", "rebasing"), ("MERGE_HEAD", "merging"),
                       ("CHERRY_PICK_HEAD", "cherry-picking"), ("REVERT_HEAD", "reverting"),
                       ("BISECT_LOG", "bisecting")):
        if os.path.exists(os.path.join(gdir, name)):
            return what
    return ""


_LAST = {}                  # repo → (HEAD's commit id, its time · subject · author)
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
        # the cause, not the hint after it (dubious ownership ends with the safe.directory command)
        lines = res.stderr.strip().splitlines() if res else []
        err = next((l for l in lines if l.startswith(("fatal:", "error:"))), lines[-1] if lines else "git did not answer") \
            if res else "git did not answer in 15 s"
        return {"error": err}
    st = {"branch": "", "oid": "", "upstream": "", "ahead": 0, "behind": 0, "stash": 0,
          "staged": 0, "modified": 0, "untracked": 0, "conflicts": 0, "error": "", "gone": False}
    has_ab = False
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
                st["ahead"], st["behind"], has_ab = int(m[1]), int(m[2]), True
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
    # an upstream git names but that is not there any more (merged and deleted on the remote)
    st["initial"] = st["oid"] == "(initial)"
    st["gone"] = bool(st["upstream"]) and not has_ab and not st["initial"]   # (an empty clone is not gone)
    if not _STASH_OK[0]:                       # git < 2.35: count the stash reflog
        out = git_out(repo, "rev-list", "--walk-reflogs", "--count", "refs/stash").strip()
        st["stash"] = int(out) if out.isdigit() else 0
    gdir = git_dir(repo)
    st["doing"] = in_progress(gdir)
    # a worktree's FETCH_HEAD is its own; fetches from the main repo land in the common one
    stamps = []
    for d in (gdir, common_dir(gdir)):
        try:
            stamps.append(os.path.getmtime(os.path.join(d, "FETCH_HEAD")))
        except OSError:
            pass
    st["fetched"] = max(stamps) if stamps else None
    # the last commit's time, subject and author: asked only when HEAD's commit changed (status
    # gave its id): every repo is looked at every few seconds, and this was half the git calls
    hit = _LAST.get(repo)
    if hit and hit[0] == st["oid"] and st["oid"]:
        last = hit[1]
    else:
        last = git_out(repo, "log", "-1", "--no-show-signature", "--format=%ct%x1f%s%x1f%an", "--").strip().split("\x1f")
        if len(_LAST) > 500:
            _LAST.clear()
        _LAST[repo] = (st["oid"], last)
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
            m = re.match(r"^\s*([^\s=#][^\s=]*)\s*(?:=\s*|\s+)(.*)$", line)     # Key value · Key=value
            if not m:
                continue
            key, value = m[1].lower(), re.sub(r"(^|\s)#.*$", "", m[2]).strip().strip('"')
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
    """(host, 'owner/repo', web page or '') of a remote URL · ssh aliases resolved · never raises."""
    try:
        return _parse_remote(url, aliases)
    except ValueError:                           # a bad port, a broken [IPv6]…
        return "", safe_url(url), ""


def safe_url(url):
    """The URL without user:password@ (tokens stay off the screen and the clipboard)."""
    return re.sub(r"^(\w[\w+.-]*://)[^/@]*@", r"\1", (url or "").strip())


def _parse_remote(url, aliases=None):
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
