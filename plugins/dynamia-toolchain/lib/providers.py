"""One provider per tool: where it lives, which versions exist, how to get one release and how to load it.

Every download comes from the tool's official site and is installed only when the checksum that site publishes matches.
Each site's base URL can be overridden with an environment variable, which is how the tests run offline.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import urllib.parse
from pathlib import Path

import toolchain as tc


def base_url(var: str, default: str) -> str:
    return os.environ.get(var, default).rstrip("/")


def vkey(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v.split("+")[0]))


def match(spec: str, versions: list[str]) -> str | None:
    """The highest version that is `spec` or starts with it (`3.9` -> 3.9.9, `22` -> 22.x.y); `latest` is the highest of all."""
    if spec == "latest":
        pool = versions
    else:
        pool = [v for v in versions if v == spec or v.startswith(spec + ".")]
    return max(pool, key=vkey) if pool else None


def need_spec(spec: str) -> str:
    if spec != "latest" and not re.match(r"^\d+(\.\d+)*$", spec):
        tc.die(f"invalid version '{spec}': use a number such as 3, 3.9 or 3.9.9, or 'latest'")
    return spec


class Provider:
    name = ""
    marker = ""            # a file inside the tool's home that proves it is there
    top = ""               # folder under the home folder (and under the repo, for --project); ignore entry for git
    usage = "VERSION"
    note = ""

    def base(self, where: str) -> Path:
        if where == "home":
            return Path.home() / self.top
        if where == "project":
            return (tc.repo_root() or Path.cwd()) / self.top
        return Path(os.path.expanduser(where)).resolve()

    def ignore_entry(self) -> str:
        return self.top.split("/")[0]

    def env(self, home: Path) -> tuple[dict[str, str], list[Path]]:
        return {}, [home / "bin"]

    def available(self, args: list[str]) -> list[str]:
        raise NotImplementedError

    def resolve(self, args: list[str]) -> dict:
        """{name, version, url, checksum, algo, filename, size}"""
        raise NotImplementedError

    def install(self, rel: dict, target: Path, tmp: Path) -> None:
        archive = tmp / rel["filename"]
        tc.download(rel["url"], archive, rel["checksum"], rel["algo"])
        tc.install_archive(archive, target, self.marker)


def _machine() -> tuple[str, str]:
    system, arch = tc.platform_ids()
    return system, arch


# ----------------------------------------------------------------------- jdk
class Jdk(Provider):
    name, marker, top = "jdk", "bin/java", ".jdks"
    usage = "DISTRO VERSION   (VERSION: 21, lts, or 21.0.5; DISTRO: temurin, corretto, zulu, ...)"
    note = "JAVA_HOME and PATH"

    @property
    def api(self) -> str:
        return base_url("TOOLCHAIN_FOOJAY_URL", "https://api.foojay.io/disco/v3.0")

    def env(self, home):
        return {"JAVA_HOME": str(home)}, [home / "bin"]

    def _packages(self, distro: str, version: str | None) -> list[dict]:
        system, arch = _machine()
        q = {"distribution": distro, "architecture": arch, "operating_system": system, "archive_type": "tar.gz", "package_type": "jdk",
             "directly_downloadable": "true", "release_status": "ga"}
        if system == "linux":
            q["lib_c_type"] = "musl" if tc.is_musl() else "glibc"
        if version is None:
            q["latest"] = "available"
        elif "." in version:
            q["version"] = version   # an exact version: without `latest`, Foojay returns that build, not the newest of its major
        else:
            q["version"], q["latest"] = version, "available"
        pkgs = tc.get_json(f"{self.api}/packages?" + "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in q.items())).get("result", [])
        if version and "." in version:
            pkgs = [p for p in pkgs if p["java_version"] == version or p["java_version"].startswith((version + "+", version + "."))]
        return pkgs

    def available(self, args):
        if not args:
            majors = tc.get_json(f"{self.api}/major_versions?ea=false&ga=true&maintained=true")["result"]
            distros = tc.get_json(f"{self.api}/distributions?include_versions=false")["result"]
            return ([f"{m['major_version']:<4} {m['term_of_support']}" for m in majors] + ["", "distributions:"]
                    + [f"  {d['api_parameter']:<20} {d['name']}" for d in sorted(distros, key=lambda d: d["api_parameter"]) if d.get("maintained", True)])
        distro = tc.valid_name("distribution", args[0])
        best: dict[int, dict] = {}
        for p in self._packages(distro, None):
            if p["major_version"] not in best or vkey(p["java_version"]) > vkey(best[p["major_version"]]["java_version"]):
                best[p["major_version"]] = p
        if not best:
            tc.die(f"{distro} has no JDK for this machine (see: toolchain jdk available)")
        return [f"{m:<4} {best[m]['java_version']:<16} {best[m].get('term_of_support', '')}" for m in sorted(best, reverse=True)]

    def resolve(self, args):
        if len(args) != 2:
            tc.die("usage: toolchain jdk install DISTRO VERSION")
        distro, version = tc.valid_name("distribution", args[0]), args[1]
        if version.lower() == "lts":
            lts = [m for m in tc.get_json(f"{self.api}/major_versions?ea=false&ga=true&maintained=true")["result"] if m["term_of_support"] == "LTS"]
            if not lts:
                tc.die("could not find the newest LTS")
            version = str(max(m["major_version"] for m in lts))
        if not re.match(r"^\d+(\.\d+)*$", version):
            tc.die(f"invalid version '{args[1]}': use a major (21), 'lts' or a full version (21.0.5)")
        pkgs = self._packages(distro, version)
        if not pkgs:
            tc.die(f"{distro} {args[1]} has no JDK for this machine: see 'toolchain jdk available {distro}'")
        pkg = max(pkgs, key=lambda p: vkey(p["java_version"]))
        info = tc.get_json(pkg["links"]["pkg_info_uri"])["result"][0]
        return {"name": tc.valid_name("name", f"{distro}-{pkg['java_version'].split('+')[0]}"), "version": pkg["java_version"],
                "url": info["direct_download_uri"], "checksum": info.get("checksum", ""), "algo": info.get("checksum_type") or "sha256",
                "filename": pkg["filename"], "size": pkg.get("size", 0)}


# ---------------------------------------------------------------------- node
class Node(Provider):
    name, marker, top = "node", "bin/node", ".toolchains/node"
    usage = "VERSION   (lts, latest, 22, or 22.11.0); npm and npx come with it"

    @property
    def dist(self) -> str:
        return base_url("TOOLCHAIN_NODE_URL", "https://nodejs.org/dist")

    def _index(self) -> list[dict]:
        return tc.get_json(f"{self.dist}/index.json")

    def available(self, args):
        out = []
        for e in self._index():
            if e["version"].count("-"):
                continue
            out.append(f"{e['version'].lstrip('v'):<12} npm {e.get('npm', '?'):<8} {('LTS ' + e['lts']) if e.get('lts') else ''}")
            if len(out) >= 20:
                break
        return out

    def resolve(self, args):
        if len(args) != 1:
            tc.die("usage: toolchain node install VERSION   (lts, latest, 22 or 22.11.0)")
        spec = args[0].lower().lstrip("v")
        entries = [e for e in self._index() if "-" not in e["version"]]
        if spec == "lts":
            entry = next((e for e in entries if e.get("lts")), None)
        else:
            version = match(need_spec(spec), [e["version"].lstrip("v") for e in entries])
            entry = next((e for e in entries if e["version"].lstrip("v") == version), None)
        if entry is None:
            tc.die(f"no Node.js release matches '{args[0]}' (see: toolchain node available)")
        v = entry["version"]
        system, arch = _machine()
        osn, cpu = ("linux" if system == "linux" else "darwin"), ("x64" if arch == "x64" else "arm64")
        filename = f"node-{v}-{osn}-{cpu}.tar.xz"
        sums = tc.get_text(f"{self.dist}/{v}/SHASUMS256.txt")
        checksum = next((ln.split()[0] for ln in sums.splitlines() if ln.strip().endswith(" " + filename) or ln.strip().endswith("  " + filename)), "")
        if not checksum:
            tc.die(f"{filename} is not in SHASUMS256.txt: this machine has no Node.js {v} build")
        return {"name": f"node-{v.lstrip('v')}", "version": v.lstrip("v"), "url": f"{self.dist}/{v}/{filename}", "checksum": checksum, "algo": "sha256",
                "filename": filename, "size": 0}


# --------------------------------------------------------------------- maven
class Maven(Provider):
    name, marker, top = "maven", "bin/mvn", ".toolchains/maven"
    usage = "VERSION   (latest, 3, 3.9 or 3.9.9)"

    def env(self, home):
        return {"MAVEN_HOME": str(home)}, [home / "bin"]

    def _versions(self) -> list[str]:
        xml = tc.get_text(base_url("TOOLCHAIN_MAVEN_META_URL", "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/maven-metadata.xml"))
        return [v for v in re.findall(r"<version>([^<]+)</version>", xml) if re.match(r"^\d+(\.\d+)*$", v)]   # releases only: no -rc, -alpha, -beta

    def available(self, args):
        by_minor: dict[str, str] = {}
        for v in self._versions():
            k = ".".join(v.split(".")[:2])
            if k not in by_minor or vkey(v) > vkey(by_minor[k]):
                by_minor[k] = v
        return [by_minor[k] for k in sorted(by_minor, key=vkey, reverse=True)[:12]]

    def resolve(self, args):
        if len(args) != 1:
            tc.die("usage: toolchain maven install VERSION")
        v = match(need_spec(args[0]), self._versions())
        if v is None:
            tc.die(f"no Maven release matches '{args[0]}' (see: toolchain maven available)")
        dist = base_url("TOOLCHAIN_MAVEN_DIST_URL", "https://archive.apache.org/dist/maven")
        fn = f"apache-maven-{v}-bin.tar.gz"
        url = f"{dist}/maven-{v.split('.')[0]}/{v}/binaries/{fn}"
        checksum = tc.get_text(url + ".sha512").split()[0]
        return {"name": f"maven-{v}", "version": v, "url": url, "checksum": checksum, "algo": "sha512", "filename": fn, "size": 0}


# -------------------------------------------------------------------- gradle
class Gradle(Provider):
    name, marker, top = "gradle", "bin/gradle", ".toolchains/gradle"
    usage = "VERSION   (latest, 8, 8.10 or 8.10.2)"

    def env(self, home):
        return {"GRADLE_HOME": str(home)}, [home / "bin"]

    def _releases(self) -> list[dict]:
        data = tc.get_json(base_url("TOOLCHAIN_GRADLE_URL", "https://services.gradle.org") + "/versions/all")
        return [x for x in data if not (x.get("snapshot") or x.get("nightly") or x.get("rcFor") or x.get("milestoneFor") or x.get("broken"))]

    def available(self, args):
        by_minor: dict[str, str] = {}
        for x in self._releases():
            v = x["version"]
            k = ".".join(v.split(".")[:2])
            if k not in by_minor or vkey(v) > vkey(by_minor[k]):
                by_minor[k] = v
        return [by_minor[k] for k in sorted(by_minor, key=vkey, reverse=True)[:12]]

    def resolve(self, args):
        if len(args) != 1:
            tc.die("usage: toolchain gradle install VERSION")
        rels = {x["version"]: x for x in self._releases()}
        v = match(need_spec(args[0]), list(rels))
        if v is None:
            tc.die(f"no Gradle release matches '{args[0]}' (see: toolchain gradle available)")
        x = rels[v]
        checksum = tc.get_text(x["checksumUrl"]).split()[0]
        return {"name": f"gradle-{v}", "version": v, "url": x["downloadUrl"], "checksum": checksum, "algo": "sha256",
                "filename": f"gradle-{v}-bin.zip", "size": 0}


# ------------------------------------------------------------------------ go
class Go(Provider):
    name, marker, top = "go", "bin/go", ".toolchains/go"
    usage = "VERSION   (latest, 1.23 or 1.23.4)"

    @property
    def site(self) -> str:
        return base_url("TOOLCHAIN_GO_URL", "https://go.dev")

    def env(self, home):
        return {"GOROOT": str(home)}, [home / "bin"]

    def _releases(self) -> list[dict]:
        return [x for x in tc.get_json(f"{self.site}/dl/?mode=json&include=all") if x.get("stable")]

    def available(self, args):
        by_minor: dict[str, str] = {}
        for x in self._releases():
            v = x["version"].removeprefix("go")
            k = ".".join(v.split(".")[:2])
            if k not in by_minor or vkey(v) > vkey(by_minor[k]):
                by_minor[k] = v
        return [by_minor[k] for k in sorted(by_minor, key=vkey, reverse=True)[:12]]

    def resolve(self, args):
        if len(args) != 1:
            tc.die("usage: toolchain go install VERSION")
        rels = {x["version"].removeprefix("go"): x for x in self._releases()}
        spec = need_spec(args[0])
        v = match(spec, list(rels))
        if v is None and re.match(r"^\d+\.\d+$", spec):
            v = match(spec + ".0", list(rels)) or (spec if spec in rels else None)   # Go names its first release 1.23, not 1.23.0
        if v is None:
            tc.die(f"no Go release matches '{args[0]}' (see: toolchain go available)")
        system, arch = _machine()
        goos, goarch = ("linux" if system == "linux" else "darwin"), ("amd64" if arch == "x64" else "arm64")
        f = next((f for f in rels[v]["files"] if f["os"] == goos and f["arch"] == goarch and f["kind"] == "archive"), None)
        if f is None:
            tc.die(f"Go {v} has no build for {goos}/{goarch}")
        return {"name": f"go-{v}", "version": v, "url": f"{self.site}/dl/{f['filename']}", "checksum": f["sha256"], "algo": "sha256",
                "filename": f["filename"], "size": f.get("size", 0)}


# ---------------------------------------------------------------------- rust
class Rust(Provider):
    name, marker, top = "rust", "cargo/bin/cargo", ".toolchains/rust"
    usage = "TOOLCHAIN   (stable, beta, nightly or 1.82.0): installs cargo and rustc through rustup into its own folder"

    def env(self, home):
        return {"CARGO_HOME": str(home / "cargo"), "RUSTUP_HOME": str(home / "rustup")}, [home / "cargo" / "bin"]

    def available(self, args):
        return ["stable", "beta", "nightly", "or a version such as 1.82.0"]

    def resolve(self, args):
        if len(args) != 1 or not re.match(r"^(stable|beta|nightly|\d+\.\d+(\.\d+)?)$", args[0]):
            tc.die("usage: toolchain rust install stable|beta|nightly|1.82.0")
        system, arch = _machine()
        triple = {("linux", "x64"): "x86_64-unknown-linux-gnu", ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
                  ("macos", "x64"): "x86_64-apple-darwin", ("macos", "aarch64"): "aarch64-apple-darwin"}[(system, arch)]
        if system == "linux" and tc.is_musl():
            triple = triple.replace("-gnu", "-musl")
        dist = base_url("TOOLCHAIN_RUSTUP_URL", "https://static.rust-lang.org/rustup/dist")
        checksum = tc.get_text(f"{dist}/{triple}/rustup-init.sha256").split()[0]
        return {"name": f"rust-{args[0]}", "version": args[0], "url": f"{dist}/{triple}/rustup-init", "checksum": checksum, "algo": "sha256",
                "filename": "rustup-init", "size": 0}

    def install(self, rel, target, tmp):
        init = tmp / "rustup-init"
        tc.download(rel["url"], init, rel["checksum"], rel["algo"])
        init.chmod(init.stat().st_mode | stat.S_IXUSR)
        target.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CARGO_HOME": str(target / "cargo"), "RUSTUP_HOME": str(target / "rustup")}
        # the checksum above is the one rust-lang.org publishes for this exact file; --no-modify-path keeps it out of the user's shell files
        r = subprocess.run([str(init), "-y", "--no-modify-path", "--profile", "minimal", "--default-toolchain", rel["version"]], env=env)
        if r.returncode != 0 or not (target / "cargo" / "bin" / "cargo").exists():
            import shutil
            shutil.rmtree(target, ignore_errors=True)
            tc.die("rustup-init failed: nothing was installed")


# ------------------------------------------------------------------- android
class Android(Provider):
    name, marker, top = "android", "cmdline-tools/latest/bin/sdkmanager", ".toolchains/android"
    usage = "[sdk]   (installs the SDK command-line tools; then use `toolchain android sdk PACKAGE...`)"
    note = "ANDROID_HOME, ANDROID_SDK_ROOT"

    def env(self, home):
        return ({"ANDROID_HOME": str(home), "ANDROID_SDK_ROOT": str(home)},
                [home / "cmdline-tools" / "latest" / "bin", home / "platform-tools"])

    def available(self, args):
        r = self._release()
        return [f"command-line tools build {r['build']} (revision {r['revision']}); then: toolchain android sdk 'platform-tools' 'platforms;android-35' 'build-tools;35.0.0'"]

    def _release(self) -> dict:
        repo = base_url("TOOLCHAIN_ANDROID_URL", "https://dl.google.com/android/repository")
        xml = tc.get_text(f"{repo}/repository2-3.xml")
        m = re.search(r'<remotePackage path="cmdline-tools;latest">(.*?)</remotePackage>', xml, re.S)
        if not m:
            tc.die("the Android repository has no cmdline-tools;latest entry")
        system, arch = _machine()
        host = "linux" if system == "linux" else "macosx"
        for a in re.findall(r"<archive>(.*?)</archive>", m.group(1), re.S):
            if f"<host-os>{host}</host-os>" not in a:
                continue
            ha = re.search(r"<host-arch>([^<]+)</host-arch>", a)
            if ha and ha.group(1) != arch:
                continue
            ck, url = re.search(r'<checksum type="(\w+)">([0-9a-f]+)</checksum>', a), re.search(r"<url>([^<]+)</url>", a)
            rev = re.search(r"<major>(\d+)</major>\s*<minor>(\d+)</minor>", m.group(1))
            if ck and url:
                return {"url": f"{repo}/{url.group(1)}", "algo": ck.group(1), "checksum": ck.group(2), "filename": url.group(1),
                        "build": (re.search(r"-(\d+)_latest", url.group(1)) or [None, "?"])[1], "revision": f"{rev.group(1)}.{rev.group(2)}" if rev else "?"}
        tc.die(f"no Android command-line tools for {host}/{arch}")

    def resolve(self, args):
        r = self._release()
        return {"name": "android-sdk", "version": r["build"], "url": r["url"], "checksum": r["checksum"], "algo": r["algo"],
                "filename": r["filename"], "size": 0}

    def install(self, rel, target, tmp):
        archive = tmp / rel["filename"]
        tc.download(rel["url"], archive, rel["checksum"], rel["algo"])   # the repository publishes sha1 only
        unpack = tmp / "unpack"
        tc.safe_extract(archive, unpack)
        src = unpack / "cmdline-tools"
        if not (src / "bin" / "sdkmanager").is_file():
            tc.die("the archive has no cmdline-tools/bin/sdkmanager: not a valid install")
        (target / "cmdline-tools").mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(str(src), str(target / "cmdline-tools" / "latest"))


PROVIDERS = {p.name: p for p in (Jdk(), Node(), Maven(), Gradle(), Go(), Rust(), Android())}
