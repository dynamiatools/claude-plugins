import importlib.machinery
import importlib.util
import os

BIN = os.path.join(os.path.dirname(__file__), "..", "bin")


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), os.path.join(BIN, name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod
