#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
#  Container pane of the `docker` tab · follows the highlighted container
#
#  Details     image & architecture, state, health, restarts, ports, networks,
#              mounts, command, compose project / service / folder / files
#  Dockerfile  where it is (from `docker compose config`: build context +
#              dockerfile, same .env files as the project) and its contents
#  Compose     the compose file(s) of the project (the override is marked)
#  Merged      this service as docker compose runs it: every compose file merged
#              (override applied) and ${VARS} filled in; secrets are hidden
#  Files are coloured with bat when it is installed.
# ═══════════════════════════════════════════════════════════════

import datetime
import json
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from tui import BLUE, BOLD, DIM, GREEN, RED, RESET, SUB, TEXT, YELLOW
from viewer import BackgroundViewer, run

HOME = os.path.expanduser("~")
BAT = shutil.which("bat") or shutil.which("batcat")


def tilde(p):
    return "~" + p[len(HOME):] if p == HOME or p.startswith(HOME + "/") else p


def docker(*args, cwd=None, timeout=15):
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def when(stamp):
    """Docker's UTC time ('2026-10-29T09:12:33.123456789Z') → '2026-10-29 11:12 · 3h ago' in local time.
    None for docker's 'never' (0001-01-01)."""
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:\d\d)?", stamp or "")
    if not m or m[1].startswith("0001"):
        return None
    t = datetime.datetime.fromisoformat(m[1] + ("+00:00" if m[2] in (None, "Z") else m[2])).astimezone()
    secs = max(0, int((datetime.datetime.now(t.tzinfo) - t).total_seconds()))
    if secs < 60:
        ago = "just now"
    else:
        ago = next(f"{secs // n}{u} ago" for n, u in ((86400 * 365, "y"), (86400 * 30, "mo"), (86400, "d"),
                                                     (3600, "h"), (60, "m")) if secs >= n)
    return f"{t:%Y-%m-%d %H:%M} · {ago}"


SECRET_KEY = re.compile(r"PASS|PWD|_PW\b|^PW\b|SECRET|TOKEN|KEY|PRIVATE|CREDENTIAL|DSN|AUTH|JWT|SALT|COOKIE", re.I)
URL_PASSWORD = re.compile(r"(\w+://[^:/@\s]*:)(\S+)(@[^@\s]*)")           # the last @ is the host's
REDIS_PASSWORD = re.compile(r"(redis-cli\b[^;|&]*?\s-a\s+)(\S+)")      # inside a CMD-SHELL string
# a password given to a client on its command line: mysql -psecret · mongosh -p s3cret ·
# redis-server --requirepass x · curl -u user:pw · --password=x
INLINE = [re.compile(r"(\b(?:mysql|mysqladmin|mysqldump|mariadb)\b[^;|&]*?\s-p)(\S+)"),
          re.compile(r"(\b(?:mongo|mongosh|mongodump|mongorestore)\b[^;|&]*?\s(?:-p|--password)[ =])(\S+)"),
          re.compile(r"(--(?!no-)[\w-]*(?:requirepass|masterauth|password|pass|token|secret)[ =])(\S+)", re.I),
          re.compile(r"(\bcurl\b[^;|&]*?\s(?:-u|--user)\s+[^:\s]+:)(\S+)"),
          re.compile(r"(\b[\w.]*(?:password|passwd|pwd|secret|token|api_?key|apikey|auth|credential|private_?key)"
                     r"[\w.]*=)([^\s&;'\",\]]+)", re.I)]


def hide_inline(text):
    """Secrets inside a command line or a value (REDIS_ARGS=--requirepass x, JAVA_OPTS=-D…password=x)."""
    text = URL_PASSWORD.sub(r"\1••••\3", text)
    text = REDIS_PASSWORD.sub(r"\1••••", text)
    for rx in INLINE:
        text = rx.sub(lambda m: m[1] + "••••", text)
    return text


def hide(key, value):
    """Secrets stay out of the screen: values of secret-looking keys, and passwords in URLs."""
    if isinstance(value, str):
        if SECRET_KEY.search(str(key)) and value:
            return "•••• (hidden)"
        return hide_inline(value)
    return value


def hide_args(args):
    """A command line with its secrets hidden: --password=x, --requirepass x, TOKEN=x, URLs,
    and redis-cli's -a x (the usual compose healthcheck)."""
    out, hide_next, redis = [], False, False
    for a in args:
        a = str(a)
        redis = redis or "redis-cli" in a
        if hide_next and not a.startswith("-"):
            out.append("••••")
        elif "=" in a and SECRET_KEY.search(a.split("=", 1)[0].lstrip("-")):
            out.append(a.split("=", 1)[0] + "=••••")
        else:
            out.append(hide_inline(a))                   # sh -c "redis-server --requirepass x"…
        hide_next = (a.startswith("-") and "=" not in a and bool(SECRET_KEY.search(a))) or (redis and a == "-a")
    # a client and its password in separate arguments (mysqladmin ping -psecret · curl -u a:b):
    # the whole line, seen at once, says which is which · the list keeps its shape
    if any(" " in a for a in out):
        return [hide_inline(a) for a in out]
    joined = " ".join(out)
    masked = hide_inline(joined).split(" ")
    return masked if len(masked) == len(out) else out


def to_yaml(obj, indent=0, key=""):
    """Small YAML writer for `docker compose config` output (dicts, lists, scalars)."""
    pad = "  " * indent
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out += to_yaml(v, indent + 1, k)
            else:
                out.append(f"{pad}{k}: {scalar(hide(k, v))}")
    elif isinstance(obj, list):
        if all(not isinstance(v, (dict, list)) for v in obj):
            obj = hide_args(obj)                         # command / entrypoint / healthcheck
        for v in obj:
            if isinstance(v, (dict, list)) and v:
                inner = to_yaml(v, indent + 1, key)
                out.append(f"{pad}- {inner[0].strip()}")
                out += inner[1:]
            else:
                out.append(f"{pad}- {scalar(hide(key, v))}")
    return out


def scalar(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return "{}" if isinstance(v, dict) else "[]"
    text = str(v)
    return json.dumps(text, ensure_ascii=False) if (not text or re.search(r"[:#{}\[\],&*!|>'\"%@`]|^\s|\s$", text)) else text


def show_text(text, language, width):
    if BAT:
        res = subprocess.run([BAT, "--color=always", "--style=numbers", "--paging=never", f"--language={language}",
                              f"--terminal-width={max(20, width - 4)}"], input=text, capture_output=True, text=True,
                             timeout=10)
        if res.returncode == 0:
            return res.stdout.splitlines()
    return [f"{DIM}{n:4}{RESET} {line}" for n, line in enumerate(text.splitlines(), 1)]


SECRET_LINE = re.compile(r"^(\s*(?:-\s*)?(?:(?:ENV|ARG)\s+)?[\"']?([\w.\-]+)[\"']?\s*[:=]\s*)(\S.*?)\s*$")


PAIR = re.compile(r"(\b([\w.\-]+)=)(\"[^\"]*\"|'[^']*'|[^\s,\]\"']+)")


def mask_secrets(text):
    """A file as text with the values of secret-looking keys hidden: PASSWORD: x, - TOKEN=x,
    ENV A=1 API_KEY=x, ARG SECRET x, ["API_KEY=x"], and the lines of a block (KEY: | …)
    (${VARS} stay: they are not secrets themselves)."""
    out, block = [], None          # block: indent of a secret key whose value is the lines below
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip())
        if block is not None:
            if line.strip() and indent <= block:
                block = None
            else:
                out.append((" " * indent + "•••• (hidden)") if line.strip() else line)
                continue
        arr = re.search(r"\[.*\]", line)                # exec form: ["redis-cli", "-a", "pw", "ping"]
        if arr:
            try:
                items = json.loads(arr[0])
            except ValueError:
                items = None
            if isinstance(items, list) and items and all(isinstance(a, str) for a in items):
                masked = hide_args(items)
                if masked != items:
                    line = line[:arr.start()] + json.dumps(masked, ensure_ascii=False) + line[arr.end():]
        m = SECRET_LINE.match(line)
        if m and SECRET_KEY.search(m[2]) and re.fullmatch(r"[|>][-+0-9]*", m[3]):
            out.append(m[1] + m[3])                       # PRIVATE_KEY: | → the next lines are the key
            block = indent
            continue
        if m and SECRET_KEY.search(m[2]) and not m[3].startswith("${") and m[3] not in ("''", '""'):
            line = m[1] + "•••• (hidden)"
        else:
            env = re.match(r"^(\s*(?:ENV|ARG)\s+)([\w.\-]+)(\s+)(\S.*)$", line)    # ENV KEY value
            if env and SECRET_KEY.search(env[2]) and "=" not in env[2]:
                line = env[1] + env[2] + env[3] + "•••• (hidden)"
            else:                                         # KEY=value pairs anywhere on the line
                line = PAIR.sub(lambda p: p[1] + "••••" if SECRET_KEY.search(p[2]) and not p[3].startswith("${")
                                else p[0], hide_inline(line))
        out.append(line)
    return "\n".join(out)


_shown_files = {}       # (path, its mtime and size, language, width) → lines


def show_file(path, language, width):
    # bat wraps the file itself (to the pane width); viewer wrapping only adds an indent
    """A file as coloured lines (bat) or plain ones · kept while the file stays the same (the tab
    is asked again every few seconds: bat each time was 20-30 ms for the same lines)."""
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size, language, width)
    if key not in _shown_files:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = mask_secrets(f.read().expandtabs(4))      # secrets never reach the screen
        if len(_shown_files) > 32:
            _shown_files.clear()
        _shown_files[key] = show_text(text, language, width)
    return list(_shown_files[key])


class Details(BackgroundViewer):
    icon = "\U000F0868"
    title = "Container"
    option = "@docker-selected"
    tabs = ["Details", "Dockerfile", "Compose", "Merged"]
    interval = 1.0                # (the master wakes it when the selection changes: tmuxlink.publish)
    refresh_every = 5
    wrap_lines = True
    empty = "highlight a container in the Containers pane"

    def __init__(self, screen):
        self.compose_cache = {}
        super().__init__(screen)

    def inspect(self, name):
        res = docker("container", "inspect", name)        # not a network or volume of the same name
        try:
            return json.loads(res.stdout)[0] if res and res.returncode == 0 else None
        except (ValueError, IndexError):
            return None

    def compose_config(self, labels):
        """`docker compose config` of the container's project (all its files, its .env files), cached."""
        wd = labels.get("com.docker.compose.project.working_dir", "")
        files = [f for f in labels.get("com.docker.compose.project.config_files", "").split(",") if f]
        envs = [f for f in labels.get("com.docker.compose.project.environment_file", "").split(",") if f]
        if not (wd and files):
            return {}
        stamp = tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in files + envs)
        key = (wd, tuple(files), stamp)
        if key not in self.compose_cache:
            args = [a for f in files for a in ("-f", f)] + [a for e in envs if os.path.exists(e) for a in ("--env-file", e)]
            res = docker("compose", *args, "config", "--format", "json", cwd=wd if os.path.isdir(wd) else None)
            if res is None:
                return {}                  # no answer in time (Docker busy): not kept, asked again next time
            try:
                self.compose_cache[key] = json.loads(res.stdout) if res.returncode == 0 else {}
            except ValueError:
                self.compose_cache[key] = {}
        return self.compose_cache[key]

    def compose_build(self, labels):
        """(dockerfile path, target, image) of this container's service, from `docker compose config`."""
        wd = labels.get("com.docker.compose.project.working_dir", "")
        service = labels.get("com.docker.compose.service", "")
        if not service:
            return None
        svc = self.compose_config(labels).get("services", {}).get(service)
        if not svc:
            return None                    # docker compose config failed (e.g. a missing .env)
        build = svc.get("build")
        if not build:
            return (None, None, svc.get("image"))
        if build.get("dockerfile_inline"):
            return ("inline:" + build["dockerfile_inline"], build.get("target"), None)
        ctx = build.get("context", wd)
        if re.match(r"^(?:https?|git|ssh)://|^git@|\.git(?:#|$)", str(ctx)):
            return ("remote:" + str(ctx), build.get("target"), None)
        df = build.get("dockerfile", "Dockerfile")
        return (df if os.path.isabs(df) else os.path.join(ctx, df), build.get("target"), None)

    def compute(self, name, tab, width):                 # in a thread (BackgroundViewer)
        c = self.inspect(name)
        if not c:
            return [f"  {YELLOW}{name} is gone (removed, or Docker is not running)"]
        labels = c["Config"].get("Labels") or {}
        if tab == "Details":
            return self.details(c, labels)
        if tab == "Dockerfile":
            return self.dockerfile(c, labels, width)
        if tab == "Merged":
            return self.merged(labels, width)
        return self.compose(labels, width)

    def details(self, c, labels):
        st = c["State"]
        k = lambda label: f"  {DIM}{label:<11}{RESET}"
        lines = []
        image = c["Config"]["Image"]
        img = docker("image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", c["Image"])
        arch = img.stdout.strip() if img and img.returncode == 0 else "?"
        lines.append(k("Image") + f"{TEXT}{image}{DIM}  {arch}")
        state = st["Status"]
        colour = GREEN if state == "running" else DIM
        since = when(st["StartedAt"] if state in ("running", "paused", "restarting") else st["FinishedAt"])
        lines.append(k("State") + f"{colour}{state}{DIM}" + (f"  since {since}" if since else "") +
                     (f"  exit code {st['ExitCode']}" if state != "running" else ""))
        if st.get("Health"):
            h = st["Health"]
            hc = GREEN if h["Status"] == "healthy" else RED if h["Status"] == "unhealthy" else YELLOW
            lines.append(k("Health") + f"{hc}{h['Status']}{DIM}  failing streak {h.get('FailingStreak', 0)}")
            if h.get("Log"):
                last = (h["Log"][-1].get("Output") or "").strip().splitlines()
                if last:
                    lines.append(k("") + f"{DIM}last check: {last[0][:200]}")
        rc = c.get("RestartCount", 0)
        lines.append(k("Restarts") + (f"{RED}{rc}" if rc else f"{DIM}0") + f"{DIM}  policy {c['HostConfig']['RestartPolicy']['Name'] or 'no'}")
        lines.append(k("Created") + f"{DIM}{when(c['Created']) or '?'}")
        cmd = " ".join(hide_args((c["Config"].get("Entrypoint") or []) + (c["Config"].get("Cmd") or [])))
        if cmd:
            lines.append(k("Command") + f"{SUB}{cmd}")
        lines.append("")
        ports = c["NetworkSettings"].get("Ports") or {}
        shown = False
        for inside, binds in sorted(ports.items()):
            v4 = {b.get("HostPort") for b in binds or [] if b.get("HostIp") in ("0.0.0.0", "")}
            for b in binds or []:
                if b.get("HostIp") == "::" and b.get("HostPort") in v4:
                    continue                             # the same port, for IPv6: once is enough
                url = (f"  {BLUE}http://localhost:{b['HostPort']}" if inside.endswith("/tcp")
                       and b.get("HostIp", "") in ("", "0.0.0.0", "::", "127.0.0.1", "::1") else "")
                lines.append(k("Port" if not shown else "") + f"{TEXT}{b.get('HostIp') or '0.0.0.0'}:{b['HostPort']}"
                             f"{DIM} → {inside}{url}")
                shown = True
        if not shown:
            lines.append(k("Ports") + f"{DIM}none published")
        for n, (net, cfg) in enumerate((c["NetworkSettings"].get("Networks") or {}).items()):
            lines.append(k("Networks" if n == 0 else "") + f"{TEXT}{net}{DIM}  {cfg.get('IPAddress') or '-'}")
        for n, m in enumerate(c.get("Mounts") or []):
            src = m.get("Name") if m["Type"] == "volume" else tilde(m.get("Source", ""))
            lines.append(k("Mounts" if n == 0 else "") + f"{DIM}{m['Type']:<7}{SUB}{src}{DIM} → {m['Destination']}"
                         + ("" if m.get("RW", True) else "  (read-only)"))
        if labels.get("com.docker.compose.project"):
            lines.append("")
            lines.append(k("Compose") + f"{TEXT}{labels['com.docker.compose.project']}{DIM} / service "
                         f"{TEXT}{labels.get('com.docker.compose.service', '')}")
            wd = labels.get("com.docker.compose.project.working_dir", "")
            if wd:
                lines.append(k("Folder") + f"{SUB}{tilde(wd)}")
            for n, f in enumerate(labels.get("com.docker.compose.project.config_files", "").split(",")):
                if f:
                    lines.append(k("Files" if n == 0 else "") + f"{SUB}{tilde(f)}")
            built = self.compose_build(labels)
            if built and built[0] and built[0].startswith(("inline:", "remote:")):
                lines.append(k("Dockerfile") + f"{DIM}{'in the compose file' if built[0][0] == 'i' else built[0][7:]}")
            elif built and built[0]:
                ok = os.path.exists(built[0])
                lines.append(k("Dockerfile") + (f"{SUB}{tilde(built[0])}" if ok else f"{RED}{tilde(built[0])} (missing)")
                             + (f"{DIM}  target {built[1]}" if built[1] else ""))
            elif built:
                lines.append(k("Dockerfile") + f"{DIM}none · the service uses the image {built[2]}")
        return lines

    def dockerfile(self, c, labels, width):
        built = self.compose_build(labels)
        if not labels.get("com.docker.compose.project"):
            return [f"  {DIM}{c['Name'].lstrip('/')} was not started by docker compose,",
                    f"  {DIM}so there is no way to know which Dockerfile built {c['Config']['Image']}."]
        if not built or not built[0]:
            img = built[2] if built else c["Config"]["Image"]
            return [f"  {DIM}This service does not build anything: it runs the image {TEXT}{img}{DIM}."]
        path, target = built[0], built[1]
        if path.startswith("inline:"):
            return [f"  {BOLD}{BLUE}dockerfile_inline{RESET}{DIM}  · written in the compose file"
                    + (f" · build target {TEXT}{target}" if target else ""), ""] + \
                show_text(mask_secrets(path[7:]), "Dockerfile", width)
        if path.startswith("remote:"):
            return [f"  {DIM}It is built from a remote context: {TEXT}{path[7:]}{DIM}",
                    f"  {DIM}(the Dockerfile is in that repository, not on this machine)"]
        if not os.path.exists(path):
            return [f"  {RED}{tilde(path)} does not exist any more"]
        head = [f"  {BOLD}{BLUE}{tilde(path)}{RESET}" + (f"{DIM}  · build target {TEXT}{target}" if target else ""), ""]
        return head + show_file(path, "Dockerfile", width)

    def merged(self, labels, width):
        service = labels.get("com.docker.compose.service", "")
        files = [f for f in labels.get("com.docker.compose.project.config_files", "").split(",") if f]
        if not (service and files):
            return [f"  {DIM}Not started by docker compose: nothing to merge."]
        cfg = self.compose_config(labels).get("services", {}).get(service)
        if not cfg:
            return [f"  {YELLOW}docker compose config failed for this project (a missing .env?)"]
        names = " + ".join(os.path.basename(f) for f in files)
        head = [f"  {BOLD}{BLUE}service {service}{RESET}  {DIM}= {names}, merged in that order (later files win)",
                f"  {DIM}${{VARS}} filled in from the project's .env files · secrets hidden", ""]
        return head + show_text("\n".join(to_yaml({service: cfg})), "yaml", width)

    def compose(self, labels, width):
        files = [f for f in labels.get("com.docker.compose.project.config_files", "").split(",") if f]
        if not files:
            return [f"  {DIM}Not started by docker compose: no compose file."]
        out = []
        for n, f in enumerate(files):
            role = "base" if n == 0 else ("override" if "override" in os.path.basename(f) else "extra file")
            out += [f"  {BOLD}{BLUE}{tilde(f)}{RESET}  {DIM}· {role}" + (" (applied on top of the base)" if n else ""), ""]
            out += show_file(f, "yaml", width) if os.path.exists(f) else [f"  {RED}missing"]
            out.append("")
        return out


if __name__ == "__main__":
    run(Details)
