# What the panes read from other programs: container logs, docker, git remotes, ssh commands
# and config, sizes · parsers with no side effects, checked against real-looking lines.
import unittest

from helpers import plain
import disksrc
import docker
import gitsrc
import logfmt
import pkgsrc
import sshsrc


def log(line, stamp=None):
    lvl, pretty = logfmt.parse(line, stamp)
    return lvl, plain(pretty)


class Logs(unittest.TestCase):
    def test_json(self):
        self.assertEqual(log('{"level":"error","msg":"boom","k":1}'), ("error", "ERR  boom k=1"))
        self.assertEqual(log('{"level":50,"msg":"pino"}'), ("error", "ERR  pino"))       # pino's numbers
        self.assertEqual(log('{"log":{"level":"warn"},"message":"ecs"}')[0], "warning")

    def test_caddy_access(self):
        line = ('{"level":"info","logger":"http.log.access.log0","request":{"method":"GET","uri":"/x"},'
                '"status":404,"duration":0.012}')
        self.assertEqual(log(line), ("info", "INFO http GET /x → 404 · 12 ms"))

    def test_redis_postgres_symfony(self):
        self.assertEqual(log("1:M 04 Nov 2026 10:00:00.123 * Ready to accept connections"),
                         ("info", "INFO 10:00:00 Ready to accept connections"))
        self.assertEqual(log("2026-11-04 10:00:00.123 UTC [42] user@db ERROR:  relation missing"),
                         ("error", "ERR  10:00:00 relation missing"))
        self.assertEqual(log("[2026-11-04T10:00:00+00:00] app.WARNING: careful"),
                         ("warning", "WARN 10:00:00 app careful"))

    def test_logfmt(self):
        self.assertEqual(log('time=2026-11-04T10:00:00Z level=warn msg="slow query" ms=200'),
                         ("warning", "WARN 10:00:00 slow query ms=200"))

    def test_plain_with_level_word(self):
        self.assertEqual(log("2026-11-04 10:00:00 ERROR something broke")[0], "error")
        self.assertEqual(log("nothing special here"), (None, "     nothing special here"))

    def test_docker_stamp_wins(self):
        self.assertEqual(log("hello", stamp="2026-11-04T08:30:00.123456789Z")[1], "     08:30:00 hello")

    def test_mark_keeps_text(self):
        line = "\x1b[31mHello World\x1b[0m"
        marked = logfmt.mark(line, ["world"])
        self.assertEqual(plain(marked), "Hello World")
        self.assertNotEqual(marked, line)
        self.assertEqual(logfmt.mark(line, []), line)

    def test_no_catastrophic_backtracking(self):
        logfmt.parse("[1]" + "a@" * 5000)                # took over a minute with an older pattern


class Docker(unittest.TestCase):
    def test_short_state(self):
        self.assertEqual(docker.short_state("running", "Up 3 hours (healthy)"), "up 3h ✓")
        self.assertEqual(docker.short_state("exited", "Exited (137) 32 hours ago"), "exited 137 32h")
        self.assertEqual(docker.short_state("exited", "Exited (0) 2 days ago"), "exited 2d")
        self.assertEqual(docker.short_state("running", "Up About a minute"), "up 1m")
        self.assertEqual(docker.short_state("running", "Up 5 seconds (health: starting)"), "up 5s …")

    def test_host_ports(self):
        self.assertEqual(docker.host_ports("0.0.0.0:40525->1025/tcp, [::]:40525->1025/tcp, 6379/tcp"), [40525])
        self.assertEqual(docker.host_ports("0.0.0.0:8000-8002->8000-8002/tcp"), [8000, 8001, 8002])
        self.assertEqual(docker.host_ports("10.0.0.5:80->80/tcp, 0.0.0.0:53->53/udp", web=True), [])
        self.assertEqual(docker.host_ports(None), [])

    def test_sizes(self):
        self.assertEqual(docker.mem_bytes("1.5GiB"), 1.5 * 1024 ** 3)
        self.assertEqual(docker.mem_bytes("8kB"), 8000)
        self.assertIsNone(docker.mem_bytes("--"))
        self.assertEqual(docker.human(1536), "2K")
        self.assertEqual(docker.human(5 * 1024 ** 3), "5.0G")

    def test_stats_refresh(self):
        block = (b'\x1b[K{"Name":"web","CPUPerc":"1.50%","MemUsage":"10MiB / 1GiB"}\n'
                 b'{"Name":"x","CPUPerc":"--","MemUsage":"-- / --"}\n')      # a container stopping
        self.assertEqual(docker.Stats.parse(block), {"web": (1.5, 10 * 1024 ** 2, 1024 ** 3)})

    def test_stats_frames(self):
        stream = b'\x1b[2J\x1b[H{"Name":"a","CPUPerc":"1%","MemUsage":"1B / 2B"}\n\x1b[2J\x1b[H{"Na'
        parts = docker.STATS_FRAME.split(stream)
        whole = [p for p in parts[:-1] if p.strip()]
        self.assertEqual(docker.Stats.parse(whole[-1]), {"a": (1.0, 1, 2)})
        self.assertEqual(parts[-1], b'{"Na')                 # still arriving


class Git(unittest.TestCase):
    def test_remotes(self):
        self.assertEqual(gitsrc.parse_remote("git@github.com:me/repo.git"),
                         ("github.com", "me/repo", "https://github.com/me/repo"))
        self.assertEqual(gitsrc.parse_remote("https://user:tok@gitlab.example.com:8443/a/b.git"),
                         ("gitlab.example.com", "a/b", "https://gitlab.example.com:8443/a/b"))
        self.assertEqual(gitsrc.parse_remote("gh:me/r", {"gh": "github.com"}),
                         ("github.com", "me/r", "https://github.com/me/r"))
        self.assertEqual(gitsrc.parse_remote("ssh://git@example.org/srv/x.git"), ("example.org", "srv/x", ""))
        self.assertEqual(gitsrc.parse_remote("https://h:bad/x"), ("", "https://h:bad/x", ""))   # never raises
        self.assertEqual(gitsrc.parse_remote(""), ("", "", ""))

    def test_no_secrets_shown(self):
        self.assertEqual(gitsrc.safe_url("https://u:p@h/x"), "https://h/x")
        self.assertNotIn("tok", "".join(gitsrc.parse_remote("https://user:tok@github.com/a/b")))

    def test_ago(self):
        self.assertEqual(gitsrc.ago(0, now=3 * 3600 + 5), "3h")
        self.assertEqual(gitsrc.ago(100, now=110), "now")
        self.assertEqual(gitsrc.ago(None), "")


class Ssh(unittest.TestCase):
    def test_config_words(self):
        self.assertEqual(sshsrc.words('web "a b" # comment'), ["web", "a b"])
        self.assertEqual(sshsrc._kv("Port=22"), ("Port", "22"))
        self.assertEqual(sshsrc._kv("HostName  example.org"), ("HostName", "example.org"))

    def test_host_patterns(self):
        self.assertFalse(sshsrc.matches(["*.prod", "!db.prod"], "db.prod"))
        self.assertTrue(sshsrc.matches(["*.prod", "!db.prod"], "web.prod"))
        self.assertFalse(sshsrc.matches(["!x"], "y"))       # only negated: no match

    def test_commands(self):
        cases = {
            "ssh -NL 5432:localhost:5432 db": ("ssh", "db"),
            "sudo -u x ssh -p 2222 root@1.2.3.4 uptime": ("ssh", "root@1.2.3.4"),
            "scp -P 22 f.txt me@h:/tmp": ("scp", "me@h"),
            "ssh ssh://u@[::1]:2200": ("ssh", "u@::1"),
            "rsync -a x host:/y": ("rsync", "host"),
            "ssh -o ProxyJump=j web -t ls": ("ssh", "web"),
            "env A=1 ssh web": ("ssh", "web"),
            "ssh $h": None,
            "echo ssh": None,
            "ssh": None,
            "ssh 'unbalanced": None,
        }
        for cmd, want in cases.items():
            self.assertEqual(sshsrc.parse_command(cmd), want, cmd)

    def test_forwards(self):
        hit = sshsrc.parse_ssh("ssh -fNL 8080:localhost:80 -p 2222 web")
        self.assertEqual(hit["fwd"], ["-L 8080:localhost:80"])
        self.assertEqual(hit["flags"], {"f", "N"})
        self.assertEqual(hit["opts"]["p"], ["2222"])

    def test_history(self):
        self.assertEqual(sshsrc.unmetafy(b"a\x83\xa3b"), b"a\x83b")
        entries, waiting = sshsrc._parse_history(b": 1730000000:0;ssh web\n#1730000001\nssh db\nls\n", False)
        self.assertEqual([(e[0], e[3]) for e in entries], [(1730000000, "web"), (1730000001, "db")])
        self.assertIsNone(waiting)
        _, waiting = sshsrc._parse_history(b"#1730000002\n", False)
        self.assertEqual(waiting, 1730000002)                # its command comes in the next piece


class Sizes(unittest.TestCase):
    def test_units(self):
        self.assertEqual(disksrc.unit_bytes("7.815GB", decimal=True), 7815000000)
        self.assertEqual(disksrc.unit_bytes("64M"), 64 * 1024 ** 2)
        self.assertIsNone(disksrc.unit_bytes("x"))
        self.assertEqual(disksrc.human(None), "")
        self.assertEqual(disksrc.human(2048), "2K")
        self.assertEqual(pkgsrc.human(3 * 1024 ** 2), "3.0M")

    def test_short_paths(self):
        self.assertEqual(disksrc.short("/a/very/long/path/to/some/where", 15), "…/to/some/where")
        self.assertEqual(disksrc.short("/tmp", 15), "/tmp")
        self.assertLessEqual(len(disksrc.short("/" + "x" * 80, 20)), 20)

    def test_package_ids(self):
        self.assertEqual(pkgsrc.split_id("snap:hello"), ("snap", "hello"))
        self.assertEqual(pkgsrc.split_id("vim"), ("apt", "vim"))
        self.assertEqual(pkgsrc.split_id("weird:x"), ("apt", "weird:x"))

    def test_memo(self):
        calls = []

        def fn():
            calls.append(1)
            return [{"a": 1}]
        self.assertEqual(pkgsrc.memo("t", (1,), fn), [{"a": 1}])
        rows = pkgsrc.memo("t", (1,), fn)
        rows[0]["a"] = 2                                     # a copy: the kept rows stay the same
        self.assertEqual(pkgsrc.memo("t", (1,), fn), [{"a": 1}])
        self.assertEqual(len(calls), 1)
        pkgsrc.memo("t", (2,), fn)                           # what it reads changed
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
