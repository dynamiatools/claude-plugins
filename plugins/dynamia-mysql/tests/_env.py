import json
import os
import stat
import sys
import tempfile
import importlib.machinery
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin")


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), os.path.join(BIN, name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Home:
    """A throwaway DYNAMIA_MYSQL_HOME with a profile that uses the fake client."""

    def __init__(self, responses=None, secrets="PROD_PW=s3cr3t-pw!\nREPL_PW=repl'pw\\x\n", mode=0o600):
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        self.log = os.path.join(d, "log.jsonl")
        self.resp = os.path.join(d, "resp.json")
        with open(self.resp, "w") as fh:
            json.dump(responses or {}, fh)
        fake = os.path.join(HERE, "fake_client.py")
        with open(os.path.join(d, "profiles.toml"), "w") as fh:
            fh.write('[profiles.src]\nhost="10.0.0.1"\nuser="dba"\nsecret="PROD_PW"\nclient="%s"\n'
            '[profiles.rep]\nhost="10.0.0.2"\nuser="dba"\nsecret="PROD_PW"\nclient="%s"\n' % (fake, fake))
        sp = os.path.join(d, "secrets.env")
        with open(sp, "w") as fh:
            fh.write(secrets)
        os.chmod(sp, mode)
        os.environ.update(DYNAMIA_MYSQL_HOME=d, FAKE_LOG=self.log, FAKE_RESP=self.resp)
        os.environ.pop("FAKE_FAIL", None)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [json.loads(l) for l in fh]

    def close(self):
        self.dir.cleanup()
