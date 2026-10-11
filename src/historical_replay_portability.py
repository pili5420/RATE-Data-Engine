"""Opt-in isolated historical source/Git resolver; no historical function patches."""
import builtins
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace

KIND = "RATE_HISTORICAL_REPLAY_PORTABILITY_V1"
REPOSITORY = "https://github.com/pili5420/RATE-Data-Engine.git"
READ_COMMANDS = {"rev-parse", "merge-base", "show", "rev-list", "cat-file", "status", "ls-tree", "ls-files", "for-each-ref"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def read(body):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "PORTABILITY_DUPLICATE_JSON_KEY")
            value[key] = item
        return value
    def invalid(value):
        raise ValueError("PORTABILITY_NONFINITE_METADATA")
    return json.loads(body, object_pairs_hook=pairs, parse_constant=invalid)


def pinned(ref):
    body = Path(ref["path"]).read_bytes()
    require(sha(body) == ref["sha256"], "PORTABILITY_EVIDENCE_HASH_MISMATCH")
    if "bytes" in ref:
        require(len(body) == ref["bytes"], "PORTABILITY_EVIDENCE_SIZE_MISMATCH")
    return body


def relative(name):
    require(isinstance(name, str) and "\\" not in name and ":" not in name, "PORTABILITY_PATH_TRAVERSAL")
    path = PurePosixPath(name)
    require(bool(name) and not path.is_absolute() and name == path.as_posix() and all(p not in {".", "..", ""} for p in path.parts), "PORTABILITY_PATH_TRAVERSAL")
    return path


def clean_env():
    value = {k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
    value.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_CONFIG_NOSYSTEM="1",
                 GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
    return value


def inside_repository(path):
    for parent in (Path(path), *Path(path).parents):
        marker = parent / ".git"
        if marker.is_file() or (marker / "HEAD").is_file():
            return True
    return False


def git(repo, *args):
    require(args and args[0] in READ_COMMANDS | {"archive", "remote"}, "PORTABILITY_GIT_WRITE_FORBIDDEN")
    if args[0] == "remote":
        require(args == ("remote", "get-url", "origin"), "PORTABILITY_GIT_WRITE_FORBIDDEN")
    return subprocess.check_output([shutil.which("git"), *args], cwd=repo, env=clean_env())


def commit(repo, ident):
    require(isinstance(ident, str) and re.fullmatch("[0-9a-f]{40}", ident), "PORTABILITY_WRONG_COMMIT")
    require(git(repo, "cat-file", "-t", ident).strip() == b"commit", "PORTABILITY_MISSING_COMMIT")
    return ident


def verify_binding(repo, binding):
    require(binding["artifact_kind"] == KIND and binding["fallback_allowed"] is False, "PORTABILITY_FALLBACK_FORBIDDEN")
    require(git(repo, "remote", "get-url", "origin").decode().strip() == REPOSITORY, "PORTABILITY_REPOSITORY_MISMATCH")
    producer = commit(repo, binding["producer_sha"])
    main = commit(repo, binding["current_main_sha"])
    consumer = commit(repo, binding["consumer_head_sha"])
    require(git(repo, "rev-parse", "origin/main").decode().strip() == main, "PORTABILITY_CURRENT_MAIN_MISMATCH")
    require(git(repo, "merge-base", producer, main).decode().strip() == producer, "PORTABILITY_PRODUCER_NOT_ANCESTOR")
    checkout = Path(binding["consumer_checkout"])
    require(git(checkout, "remote", "get-url", "origin").decode().strip() == REPOSITORY, "PORTABILITY_CONSUMER_REPOSITORY_MISMATCH")
    require(git(checkout, "rev-parse", "HEAD").decode().strip() == consumer, "PORTABILITY_CONSUMER_HEAD_MISMATCH")
    require(git(checkout, "merge-base", main, consumer).decode().strip() == main, "PORTABILITY_CONSUMER_BASE_MISMATCH")
    require(not git(checkout, "status", "--porcelain").strip(), "PORTABILITY_DIRTY_CONSUMER")
    require(sha(pinned(binding["accepted_reader"])) == binding["accepted_reader"]["sha256"], "PORTABILITY_READER_HASH")
    for ref in binding["evidence_pins"].values():
        pinned(ref)
    require(binding["producer_sha"] != binding["consumer_head_sha"], "PORTABILITY_IDENTITIES_COLLAPSED")
    return {"producer_sha": producer, "current_main_sha": main, "consumer_head_sha": consumer}


def reconstruct(repo, ident, destination):
    """Rebuild only immutable commit objects, never source files from a checkout."""
    commit(repo, ident)
    destination = Path(destination)
    require(not destination.exists(), "PORTABILITY_SANDBOX_MUST_BE_NEW")
    destination.mkdir(parents=True)
    entries = {}
    for line in git(repo, "ls-tree", "-rz", ident).split(b"\0"):
        if not line:
            continue
        meta, name = line.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        name = name.decode("utf-8")
        relative(name)
        require(kind == "blob" and mode in {"100644", "100755"}, "PORTABILITY_UNSAFE_SOURCE_ENTRY")
        entries[name] = blob
    archive = git(repo, "archive", "--format=tar", ident)
    pins = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream:
            if member.isdir():
                relative(member.name.rstrip("/"))
                continue
            name = member.name
            relative(name)
            require(member.isfile() and name in entries and name not in pins, "PORTABILITY_UNSAFE_SOURCE_ENTRY")
            body = stream.extractfile(member).read()
            blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            require(blob == entries[name], "PORTABILITY_SOURCE_BLOB_MISMATCH")
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(body)
            if os.name != "nt" and member.mode & 0o111:
                path.chmod(0o755)
            pins[name] = {"sha256": sha(body), "bytes":len(body), "git_blob":blob}
    require(set(pins) == set(entries), "PORTABILITY_SOURCE_ROW_LOSS")
    # This private repository is a replay view, never an authority or shared ref.
    subprocess.run([shutil.which("git"), "init", "-q", str(destination)], check=True, env=clean_env())
    objects = git(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip()
    info = destination / ".git/objects/info"
    info.mkdir(exist_ok=True)
    (info / "alternates").write_bytes((objects.replace("\\", "/") + "\n").encode("utf-8"))
    (destination / ".git/HEAD").write_bytes((ident + "\n").encode("ascii"))
    ref = destination / ".git/refs/remotes/origin/main"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes((ident + "\n").encode("ascii"))
    with (destination / ".git/config").open("a", encoding="utf-8") as output:
        output.write('\n[core]\n\tautocrlf = false\n[remote "origin"]\n\turl = ' + REPOSITORY + '\n')
    subprocess.run([shutil.which("git"), "read-tree", ident], cwd=destination, check=True, env=clean_env())
    require(not git(destination, "status", "--porcelain").strip(), "PORTABILITY_RECONSTRUCTION_DIRTY")
    return pins


class GitResolver:
    """Cwd-addressed private Git views; actual Git answers, never fabricated output."""
    def __init__(self, views):
        self.views = {str(Path(logical).resolve()): Path(physical).resolve() for logical,physical in views.items()}
        self.calls = []

    def run(self, command, **kwargs):
        require(isinstance(command, (list, tuple)) and command and command[0] == "git", "PORTABILITY_PROCESS_FORBIDDEN")
        require(len(command) > 1 and command[1] in READ_COMMANDS, "PORTABILITY_SHARED_REF_MUTATION_FORBIDDEN")
        require(not any(s in command for s in ("--ext-diff", "--textconv", "--exec")) and not kwargs.get("shell"), "PORTABILITY_PROCESS_FORBIDDEN")
        require(not ({"env", "executable", "input", "stdin"} & kwargs.keys()), "PORTABILITY_PROCESS_OVERRIDE_FORBIDDEN")
        logical = str(Path(kwargs.pop("cwd")).resolve())
        require(logical in self.views, "PORTABILITY_UNMAPPED_GIT_ROOT")
        physical = self.views[logical]
        self.calls.append({"logical_cwd":logical,"isolated_cwd":str(physical),"arguments":list(command[1:])})
        return subprocess.run([shutil.which("git"), *command[1:]], executable=shutil.which("git"), cwd=physical, env=clean_env(), **kwargs)

    def check_output(self, command, **kwargs):
        require("stdout" not in kwargs, "PORTABILITY_PROCESS_OVERRIDE_FORBIDDEN")
        result = self.run(command, stdout=subprocess.PIPE, check=True, **kwargs)
        return result.stdout

    def __getattr__(self, name):
        require(name in {"PIPE", "DEVNULL", "STDOUT", "CalledProcessError", "CompletedProcess", "TimeoutExpired"}, "PORTABILITY_PROCESS_FORBIDDEN")
        return getattr(subprocess, name)


class PinnedLoader(importlib.abc.Loader):
    def __init__(self, sandbox, logical, physical, expected):
        self.sandbox, self.logical, self.physical, self.expected = sandbox, Path(logical), Path(physical), expected

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        body = self.physical.read_bytes()
        require(sha(body) == self.expected, "PORTABILITY_SOURCE_BLOB_MISMATCH")
        module.__file__ = str(self.logical)
        if self.logical.name == "__init__.py":
            module.__path__ = [str(self.logical.parent)]
        imports = dict(vars(builtins))
        original_import = builtins.__import__
        def source_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and name == "subprocess":
                return self.sandbox.git
            if level == 0 and name == "importlib.util":
                return self.sandbox.importlib_util if fromlist else SimpleNamespace(util=self.sandbox.importlib_util)
            return original_import(name, globals, locals, fromlist, level)
        imports["__import__"] = source_import
        module.__dict__["__builtins__"] = imports
        self.sandbox.executed.append({"logical_path":str(self.logical), "reconstructed_path":str(self.physical), "sha256":sha(body)})
        exec(compile(body, str(self.logical), "exec"), module.__dict__)


class SourceSandbox(importlib.abc.MetaPathFinder):
    """Resolve imports from reconstructed bytes while preserving saved path identity."""
    def __init__(self, views, pins, primary):
        self.views = {Path(k).resolve():Path(v).resolve() for k,v in views.items()}
        self.pins = pins
        self.primary = Path(primary).resolve()
        self.executed = []
        self.git = GitResolver(views)
        self.importlib_util = SimpleNamespace(spec_from_file_location=self.spec_from_file_location,
                                             module_from_spec=importlib.util.module_from_spec)

    def spec_from_file_location(self, name, logical, **kwargs):
        logical = Path(logical).resolve()
        matches = [root for root in self.views if logical.is_relative_to(root)]
        require(len(matches) == 1, "PORTABILITY_UNMAPPED_SOURCE")
        root = matches[0]
        relative_name = logical.relative_to(root).as_posix()
        relative(relative_name)
        require(relative_name in self.pins[str(root)], "PORTABILITY_UNPINNED_SOURCE")
        physical = self.views[root] / relative_name
        pin = self.pins[str(root)][relative_name]
        loader = PinnedLoader(self, logical, physical, pin["sha256"])
        return importlib.util.spec_from_file_location(name, str(logical), loader=loader,
             submodule_search_locations=[str(logical.parent)] if logical.name == "__init__.py" else None)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in {"src", "scripts"}:
            return None
        name = fullname.replace(".", "/")
        for candidate in (name + "/__init__.py", name + ".py"):
            if candidate in self.pins[str(self.primary)]:
                return self.spec_from_file_location(fullname, self.primary / candidate)
        if any(key.startswith(name + "/") for key in self.pins[str(self.primary)]):
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = [str(self.primary / name)]
            return spec
        raise ImportError("PORTABILITY_UNPINNED_IMPORT:" + fullname)

    def reader(self, ref):
        body = pinned(ref)
        loader = PinnedLoader(self, ref["path"], ref["path"], sha(body))
        spec = importlib.util.spec_from_file_location("accepted_historical_reader", ref["path"], loader=loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module


class ReadOnlyRuntime:
    def __init__(self, output, sandboxes):
        self.output = Path(output).resolve()
        self.sandboxes = {str(Path(p).resolve()) for p in sandboxes}
        self.git_exe = str(Path(shutil.which("git")).resolve()).lower()

    def __call__(self, event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
            raise ValueError("PORTABILITY_NETWORK_FORBIDDEN")
        if event == "subprocess.Popen":
            executable, command, cwd, env = args
            require(str(Path(executable).resolve()).lower() == self.git_exe and str(Path(cwd).resolve()) in self.sandboxes,
                    "PORTABILITY_SHARED_PROCESS_FORBIDDEN")
            # The resolver already rejects every non-read-only Git command.
            if isinstance(command, str):
                match = re.match(r'^(?:"[^"]+"|\S+)\s+(\S+)(?:\s|$)', command)
                operation = match.group(1) if match else None
            else:
                operation = command[1] if len(command) > 1 else None
            require(operation in READ_COMMANDS, "PORTABILITY_GIT_WRITE_FORBIDDEN")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            mode, flags = args[1], args[2]
            writing = (isinstance(mode,str) and any(c in mode for c in "wax+")) or (flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            if writing:
                require(Path(os.fsdecode(args[0])).resolve() == self.output, "PORTABILITY_WRITE_FORBIDDEN")
        if event == "os.mkdir" and Path(args[0]).resolve() == self.output.parent and self.output.parent.is_dir():
            return
        if event in {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.link", "os.symlink", "os.chmod"}:
            raise ValueError("PORTABILITY_MUTATION_FORBIDDEN")


def equivalence(actual, expected):
    require(actual == expected, "PORTABILITY_HISTORICAL_OUTPUT_MISMATCH")
    return {"status":"PASS", "core_sha256":sha(canonical(actual)), "compared":"FULL_ACCEPTED_REPLAY_OBJECT_NOT_COUNTS_ONLY"}
