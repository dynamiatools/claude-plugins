"""Offline tests: a local server imitates Foojay, nodejs.org, Apache, Gradle, go.dev, rust-lang.org and Google's Android repository."""
import hashlib
import http.server
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = str(ROOT / "bin" / "toolchain")
sys.path.insert(0, str(ROOT / "lib"))
import toolchain as tc  # noqa: E402

SYSTEM, ARCH = tc.platform_ids()
NODE_OS, NODE_CPU = ("linux" if SYSTEM == "linux" else "darwin"), ("x64" if ARCH == "x64" else "arm64")
GO_OS, GO_CPU = ("linux" if SYSTEM == "linux" else "darwin"), ("amd64" if ARCH == "x64" else "arm64")
ANDROID_HOST = "linux" if SYSTEM == "linux" else "macosx"


def targz(files, mode="w:gz"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as t:
        for name, (content, perm) in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(content), perm
            t.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, (content, perm) in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o100000 | perm) << 16
            z.writestr(info, content)
    return buf.getvalue()


def sha(data, algo="sha256"):
    return hashlib.new(algo, data).hexdigest()


class Fake:
    """Routes by path (the query is ignored). `bad_sum` and `evil` change what the JDK download looks like."""

    def __init__(self, bad_sum=False, evil=False):
        self.routes = {}
        handler = self._handler()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.build(bad_sum, evil)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self):
        routes = self.routes

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?")[0]
                body = routes.get(path)
                if body is None and path.endswith("/rustup-init.sha256"):
                    body = routes["/rustup-init.sha256"]
                if body is None and path.endswith("/rustup-init"):
                    body = routes["/rustup-init"]
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body if isinstance(body, bytes) else body.encode())

            def log_message(self, *a):
                pass
        return H

    def build(self, bad_sum, evil):
        r, b = self.routes, self.base
        # JDK through Foojay
        files = {"jdk-21.0.1/bin/java": (b"#!/bin/sh\necho java\n", 0o755), "jdk-21.0.1/release": (b'JAVA_VERSION="21.0.1"\n', 0o644)}
        if evil:
            files["../evil.txt"] = (b"x", 0o644)
        jdk = targz(files)
        r["/dl/jdk.tar.gz"] = jdk
        r["/foojay/packages"] = json.dumps({"result": [{"java_version": "21.0.1+12", "major_version": 21, "filename": "fake.tar.gz", "size": 1 << 20,
                                                        "term_of_support": "lts", "links": {"pkg_info_uri": f"{b}/foojay/ids/abc"}}]})
        r["/foojay/ids/abc"] = json.dumps({"result": [{"direct_download_uri": f"{b}/dl/jdk.tar.gz", "checksum": "0" * 64 if bad_sum else sha(jdk),
                                                       "checksum_type": "sha256"}]})
        r["/foojay/major_versions"] = json.dumps({"result": [{"major_version": 21, "term_of_support": "LTS"}, {"major_version": 25, "term_of_support": "LTS"}]})
        r["/foojay/distributions"] = json.dumps({"result": [{"api_parameter": "temurin", "name": "Temurin", "maintained": True}]})
        # Node
        node_dir = f"node-v22.1.0-{NODE_OS}-{NODE_CPU}"
        node = targz({f"{node_dir}/bin/node": (b"#!/bin/sh\necho v22.1.0\n", 0o755), f"{node_dir}/bin/npm": (b"#!/bin/sh\necho 10.0.0\n", 0o755)}, "w:xz")
        r["/node/index.json"] = json.dumps([{"version": "v23.0.0-rc.1", "lts": False, "npm": "11"}, {"version": "v22.1.0", "lts": "Jod", "npm": "10.0.0"},
                                            {"version": "v20.5.0", "lts": "Iron", "npm": "9"}])
        r["/node/v22.1.0/SHASUMS256.txt"] = f"{sha(node)}  {node_dir}.tar.xz\n"
        r[f"/node/v22.1.0/{node_dir}.tar.xz"] = node
        # Maven
        mvn = targz({"apache-maven-3.9.9/bin/mvn": (b"#!/bin/sh\necho Apache Maven 3.9.9\n", 0o755)})
        r["/maven/maven-metadata.xml"] = "<versions><version>3.9.8</version><version>3.9.9</version><version>4.0.0-rc-7</version></versions>"
        r["/maven/dist/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.tar.gz"] = mvn
        r["/maven/dist/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.tar.gz.sha512"] = sha(mvn, "sha512") + "\n"
        # Gradle
        gz = zipped({"gradle-8.10.2/bin/gradle": (b"#!/bin/sh\necho Gradle 8.10.2\n", 0o755)})
        r["/gradle/versions/all"] = json.dumps([{"version": "9.0-rc-1", "rcFor": "9.0", "snapshot": False, "nightly": False, "milestoneFor": "", "broken": False},
                                                {"version": "8.10.2", "snapshot": False, "nightly": False, "rcFor": "", "milestoneFor": "", "broken": False,
                                                 "downloadUrl": f"{b}/gradle/distributions/gradle-8.10.2-bin.zip",
                                                 "checksumUrl": f"{b}/gradle/distributions/gradle-8.10.2-bin.zip.sha256"}])
        r["/gradle/distributions/gradle-8.10.2-bin.zip"] = gz
        r["/gradle/distributions/gradle-8.10.2-bin.zip.sha256"] = sha(gz)
        # Go
        go = targz({"go/bin/go": (b"#!/bin/sh\necho go1.23.4\n", 0o755)})
        fn = f"go1.23.4.{GO_OS}-{GO_CPU}.tar.gz"
        r["/go/dl/"] = json.dumps([{"version": "go1.24rc1", "stable": False, "files": []},
                                   {"version": "go1.23.4", "stable": True, "files": [{"filename": fn, "os": GO_OS, "arch": GO_CPU, "kind": "archive",
                                                                                      "sha256": sha(go), "size": len(go)}]}])
        r[f"/go/dl/{fn}"] = go
        # Rust: a fake rustup-init that creates cargo where CARGO_HOME says
        init = b'#!/bin/sh\nmkdir -p "$CARGO_HOME/bin" "$RUSTUP_HOME"\nprintf "#!/bin/sh\\necho cargo fake\\n" > "$CARGO_HOME/bin/cargo"\nchmod +x "$CARGO_HOME/bin/cargo"\n'
        r["/rustup-init"] = init
        r["/rustup-init.sha256"] = f"{sha(init)} *./rustup-init\n"
        # Android
        cmd = zipped({"cmdline-tools/bin/sdkmanager": (b"#!/bin/sh\necho 23.0\n", 0o755), "cmdline-tools/lib/x.jar": (b"j", 0o644)})
        r["/android/commandlinetools-fake_latest.zip"] = cmd
        archs = "" if SYSTEM == "linux" else f"<host-arch>{ARCH}</host-arch>"
        r["/android/repository2-3.xml"] = (
            '<remotePackage path="cmdline-tools;latest"><revision><major>23</major><minor>0</minor></revision><archives><archive><complete>'
            f'<size>1</size><checksum type="sha1">{sha(cmd, "sha1")}</checksum><url>commandlinetools-fake_latest.zip</url></complete>'
            f'<host-os>{ANDROID_HOST}</host-os>{archs}</archive></archives></remotePackage>')

    def env(self, home, **extra):
        b = self.base
        return {**os.environ, "HOME": str(home), "TOOLCHAIN_FOOJAY_URL": f"{b}/foojay", "TOOLCHAIN_NODE_URL": f"{b}/node",
                "TOOLCHAIN_MAVEN_META_URL": f"{b}/maven/maven-metadata.xml", "TOOLCHAIN_MAVEN_DIST_URL": f"{b}/maven/dist",
                "TOOLCHAIN_GRADLE_URL": f"{b}/gradle", "TOOLCHAIN_GO_URL": f"{b}/go", "TOOLCHAIN_RUSTUP_URL": b, "TOOLCHAIN_ANDROID_URL": f"{b}/android", **extra}

    def close(self):
        self.server.shutdown()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name).resolve() / "home"
        self.home.mkdir()
        self.addCleanup(self._tmp.cleanup)
        self.fake = Fake()
        self.addCleanup(self.fake.close)

    def tool(self, *args, cwd=None, env=None, fake=None):
        return subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, cwd=cwd or self.home,
                              env=(fake or self.fake).env(self.home, **(env or {})))

    def ok(self, *args, **kw):
        r = self.tool(*args, **kw)
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout!r} stderr={r.stderr!r}")
        return r.stdout


class TestJdk(Base):
    def test_install_in_home_then_list_env_run_and_remove(self):
        out = self.ok("jdk", "install", "temurin", "21")
        self.assertIn("installed temurin-21.0.1", out)
        java = self.home / ".jdks" / "temurin-21.0.1" / "bin" / "java"
        self.assertTrue(java.is_file() and os.access(java, os.X_OK))
        self.assertIn("temurin-21.0.1", self.ok("jdk", "list"))
        env = self.ok("jdk", "env", "temurin-21")   # a unique prefix is enough
        self.assertIn(f"export JAVA_HOME={self.home}/.jdks/temurin-21.0.1", env)
        self.assertIn("/bin:\"$PATH\"", env)
        self.assertEqual(self.ok("jdk", "run", "temurin-21.0.1", "--", "sh", "-c", "echo $JAVA_HOME").strip(), str(self.home / ".jdks" / "temurin-21.0.1"))
        self.assertIn("unset JAVA_HOME", self.ok("jdk", "env", "--unload", "temurin-21.0.1"))
        r = self.tool("jdk", "remove", "temurin-21.0.1")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(java.exists(), "nothing is deleted without --yes")
        self.ok("jdk", "remove", "temurin-21.0.1", "--yes")
        self.assertFalse((self.home / ".jdks" / "temurin-21.0.1").exists())

    def test_lts_resolves_to_the_newest_lts_and_a_second_install_does_nothing(self):
        self.ok("jdk", "install", "temurin", "lts")
        self.assertIn("already installed", self.ok("jdk", "install", "temurin", "lts"))

    def test_project_install_goes_in_the_repo_and_is_git_ignored_once(self):
        repo = self.home / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / ".gitignore").write_text("node_modules/")
        out = self.ok("jdk", "install", "temurin", "21", "--project", cwd=repo)
        self.assertTrue((repo / ".jdks" / "temurin-21.0.1" / "bin" / "java").is_file())
        self.assertIn("added .jdks/", out)
        self.ok("jdk", "install", "temurin", "21", "--project", "--force", cwd=repo)
        self.assertEqual((repo / ".gitignore").read_text().splitlines(), ["node_modules/", ".jdks/"])
        self.assertIn("project", self.ok("jdk", "list", cwd=repo))
        status = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=repo, capture_output=True, text=True).stdout
        self.assertNotIn(".jdks", status, "the installed JDK is invisible to git")

    def test_no_ignore_leaves_gitignore_alone(self):
        repo = self.home / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        self.ok("jdk", "install", "temurin", "21", "--project", "--no-ignore", cwd=repo)
        self.assertFalse((repo / ".gitignore").exists())

    def test_a_wrong_checksum_installs_nothing(self):
        bad = Fake(bad_sum=True)
        self.addCleanup(bad.close)
        r = self.tool("jdk", "install", "temurin", "21", fake=bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("checksum mismatch", r.stderr)
        self.assertEqual([p.name for p in (self.home / ".jdks").iterdir()] if (self.home / ".jdks").exists() else [], [])

    def test_an_archive_that_escapes_its_folder_is_refused(self):
        evil = Fake(evil=True)
        self.addCleanup(evil.close)
        r = self.tool("jdk", "install", "temurin", "21", fake=evil)
        self.assertEqual(r.returncode, 1)
        self.assertIn("unsafe path", r.stderr)
        self.assertFalse((self.home / ".jdks" / "evil.txt").exists() or (self.home / "evil.txt").exists())
        self.assertFalse((self.home / ".jdks" / "temurin-21.0.1").exists())

    def test_bad_names_and_plain_http_are_refused(self):
        self.assertEqual(self.tool("jdk", "install", "../x", "21").returncode, 1)
        self.assertEqual(self.tool("jdk", "remove", "../x", "--yes").returncode, 1)
        r = self.tool("node", "install", "lts", env={"TOOLCHAIN_NODE_URL": "http://example.com/dist"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing a download over http", r.stderr)

    def test_available_lists_majors_and_distributions(self):
        out = self.ok("jdk", "available")
        self.assertIn("21   LTS", out)
        self.assertIn("temurin", out)


class TestOtherTools(Base):
    def test_node_lts_and_a_major_come_with_npm(self):
        self.ok("node", "install", "lts")
        home = self.home / ".toolchains" / "node" / "node-22.1.0"
        self.assertTrue((home / "bin" / "npm").is_file())
        self.assertEqual(self.ok("node", "run", "node-22.1.0", "--", "node").strip(), "v22.1.0")
        self.assertIn("already installed", self.ok("node", "install", "22"))
        self.assertNotIn("rc", self.ok("node", "available"))

    def test_maven_latest_skips_release_candidates(self):
        self.ok("maven", "install", "latest")
        self.assertTrue((self.home / ".toolchains" / "maven" / "maven-3.9.9" / "bin" / "mvn").is_file())
        self.assertIn("export MAVEN_HOME=", self.ok("maven", "env", "maven-3.9.9"))

    def test_gradle_keeps_the_executable_bit_from_the_zip(self):
        self.ok("gradle", "install", "8")
        exe = self.home / ".toolchains" / "gradle" / "gradle-8.10.2" / "bin" / "gradle"
        self.assertTrue(os.access(exe, os.X_OK))
        self.assertIn("Gradle 8.10.2", self.ok("gradle", "run", "gradle-8.10.2", "--", "gradle"))

    def test_nested_run_combines_a_jdk_and_maven(self):
        self.ok("jdk", "install", "temurin", "21")
        self.ok("maven", "install", "latest")
        out = self.ok("jdk", "run", "temurin-21.0.1", "--", sys.executable, TOOL, "maven", "run", "maven-3.9.9", "--", "sh", "-c", "echo $JAVA_HOME $MAVEN_HOME; mvn")
        self.assertIn("temurin-21.0.1", out)
        self.assertIn("maven-3.9.9", out)
        self.assertIn("Apache Maven 3.9.9", out)

    def test_go_minor_resolves_to_the_newest_patch_and_sets_goroot(self):
        out = self.ok("go", "install", "1.23")
        self.assertIn("go 1.23.4", out)
        self.assertIn("export GOROOT=", self.ok("go", "env", "go-1.23.4"))

    def test_rust_runs_rustup_into_its_own_folder(self):
        self.ok("rust", "install", "stable")
        cargo = self.home / ".toolchains" / "rust" / "rust-stable" / "cargo" / "bin" / "cargo"
        self.assertTrue(cargo.is_file())
        env = self.ok("rust", "env", "rust-stable")
        self.assertIn("CARGO_HOME=", env)
        self.assertIn("RUSTUP_HOME=", env)
        self.assertEqual(self.tool("rust", "install", "../x").returncode, 1)

    def test_android_cmdline_tools_land_in_cmdline_tools_latest(self):
        self.ok("android", "install")
        sdk = self.home / ".toolchains" / "android" / "android-sdk"
        self.assertTrue(os.access(sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager", os.X_OK))
        env = self.ok("android", "env", "android-sdk")
        self.assertIn("ANDROID_HOME=", env)
        self.assertIn("ANDROID_SDK_ROOT=", env)

    def test_tools_lists_every_provider(self):
        out = self.ok("tools")
        for name in ("jdk", "node", "maven", "gradle", "go", "rust", "android"):
            self.assertIn(name, out)


class TestSkills(unittest.TestCase):
    def test_every_skill_has_front_matter_with_its_folder_name(self):
        for d in sorted((ROOT / "skills").iterdir()):
            text = (d / "SKILL.md").read_text()
            self.assertTrue(text.startswith("---\nname: " + d.name + "\ndescription: "), d.name)
            self.assertNotIn(": ", text.split("description: ", 1)[1].split("\n", 1)[0], d.name)   # an unquoted ": " breaks the front matter


if __name__ == "__main__":
    unittest.main()
