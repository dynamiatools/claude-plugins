import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(__file__)
SERVER = os.path.join(HERE, "..", "bin", "chain-server")
FAKE = os.path.join(HERE, "fake_mcp.py")
loader = importlib.machinery.SourceFileLoader("chain_server", SERVER)
spec = importlib.util.spec_from_loader("chain_server", loader)
cs = importlib.util.module_from_spec(spec)
loader.exec_module(cs)


def make_chain(**extra):
    cfg = {"servers": {"fake": {"command": sys.executable, "args": [FAKE]}}, **extra}
    return cs.Chain(cfg)


class PureTest(unittest.TestCase):
    def test_unwrap(self):
        self.assertEqual(cs.unwrap({"structuredContent": {"a": 1}, "content": []}), (True, {"a": 1}))
        self.assertEqual(cs.unwrap({"content": [{"type": "text", "text": '{"a": 2}'}]}), (True, {"a": 2}))
        self.assertEqual(cs.unwrap({"content": [{"type": "text", "text": "plain"}]}), (True, "plain"))
        self.assertEqual(cs.unwrap({"isError": True, "content": [{"type": "text", "text": "bad"}]}), (False, "bad"))

    def test_allowed(self):
        ro = {"name": "x", "annotations": {"readOnlyHint": True}}
        rw = {"name": "y"}
        self.assertTrue(cs.allowed({}, ro))
        self.assertFalse(cs.allowed({}, rw))
        self.assertTrue(cs.allowed({"allow": ["y"]}, rw))
        self.assertTrue(cs.allowed({"allow": ["*"]}, rw))

    def test_load_config(self):
        with isolated_home() as (home, cwd):
            self.assertEqual(cs.load_config("/nonexistent/x.json"), {"servers": {}, "skipped": []})
            bad = os.path.join(home, "bad.json")
            with open(bad, "w") as f:
                f.write("{nope")
            self.assertRaises(cs.ChainError, cs.load_config, bad)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


class isolated_home:
    """A temp HOME and project dir, so tests never read the real MCP configs."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home, self.cwd = os.path.join(self.tmp.name, "home"), os.path.join(self.tmp.name, "proj")
        os.makedirs(self.home)
        os.makedirs(self.cwd)
        self.patches = [mock.patch.dict(os.environ, {"HOME": self.home}), mock.patch("os.getcwd", return_value=self.cwd)]
        for p in self.patches:
            p.start()
        return self.home, self.cwd

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class ImportTest(unittest.TestCase):
    def test_claude_code_user_and_project_scope(self):
        with isolated_home() as (home, cwd):
            write_json(os.path.join(home, ".claude.json"), {
                "mcpServers": {"a": {"type": "stdio", "command": "ca", "args": ["x"]}, "b": {"command": "cb"}},
                "projects": {cwd: {"mcpServers": {"b": {"command": "cb-local"}}}}})
            servers, skipped = cs.discover(["claude"], home, cwd)
            self.assertEqual(servers["a"], {"command": "ca", "args": ["x"], "env": {}})
            self.assertEqual(servers["b"]["command"], "cb-local")
            self.assertEqual(skipped, [])

    def test_other_formats_and_precedence(self):
        with isolated_home() as (home, cwd):
            write_json(os.path.join(home, ".cursor/mcp.json"), {"mcpServers": {"x": {"command": "cursor"}}})
            write_json(os.path.join(cwd, ".vscode/mcp.json"), {"servers": {"y": {"command": "vscode"}}})
            write_json(os.path.join(cwd, ".mcp.json"), {"mcpServers": {"x": {"command": "project"}}})
            write_json(os.path.join(home, ".config/Claude/claude_desktop_config.json"),
                       {"mcpServers": {"z": {"command": "desktop"}}})
            servers, _ = cs.discover(cs.SOURCES, home, cwd)
            self.assertEqual({n: s["command"] for n, s in servers.items()},
                             {"x": "project", "y": "vscode", "z": "desktop"})

    def test_skips_remote_self_and_excluded_and_expands(self):
        with isolated_home() as (home, cwd):
            write_json(os.path.join(cwd, ".mcp.json"), {"mcpServers": {
                "remote": {"type": "http", "url": "https://x"},
                "tool-chain": {"command": "python3", "args": ["/p/bin/chain-server"]},
                "renamed": {"command": "python3", "args": ["/p/bin/chain-server"]},
                "skipme": {"command": "s"},
                "ok": {"command": "${CHAIN_T_CMD:-fallback}", "args": ["${CHAIN_T_ARG}"], "env": {"K": "${CHAIN_T_ARG}"}}}})
            with mock.patch.dict(os.environ, {"CHAIN_T_ARG": "v"}):
                servers, skipped = cs.discover(["project"], home, cwd, exclude=["skipme"])
            self.assertEqual(servers, {"ok": {"command": "fallback", "args": ["v"], "env": {"K": "v"}}})
            self.assertEqual(skipped, ["remote"])

    def test_configured_server_wins_and_import_can_be_off(self):
        with isolated_home() as (home, cwd):
            write_json(os.path.join(cwd, ".mcp.json"), {"mcpServers": {"s": {"command": "imported"}}})
            cfg_path = os.path.join(home, "c.json")
            write_json(cfg_path, {"servers": {"s": {"command": "mine"}}})
            self.assertEqual(cs.load_config(cfg_path)["servers"]["s"]["command"], "mine")
            write_json(cfg_path, {"import": False})
            self.assertEqual(cs.load_config(cfg_path)["servers"], {})
            write_json(cfg_path, {"import": ["nope"]})
            self.assertRaises(cs.ChainError, cs.load_config, cfg_path)


class ChainTest(unittest.TestCase):
    def tearDown(self):
        if hasattr(self, "chain"):
            self.chain.close()

    def run_code(self, code, **extra):
        self.chain = make_chain(**extra)
        return self.chain.run(code)

    def test_describe_hides_write_tools(self):
        self.chain = make_chain()
        out = self.chain.describe()
        self.assertIn("fake.add(a: number, b: number) -- Add two numbers.", out)
        self.assertIn("fake.echo_text(text: string)", out)
        self.assertNotIn("fake.delete(", out)
        self.assertIn("not callable", out)

    def test_describe_without_config(self):
        self.assertIn("No servers found", cs.Chain({"servers": {}}).describe())

    def test_chained_calls_only_print_the_end(self):
        text, err = self.run_code(
            "a = tools.fake.add(a=1, b=2)['sum']\n"
            "b = tools.fake.add(a=a, b=10)['sum']\n"
            "print(tools.fake.echo_text(text=f'total {b}'))")
        self.assertFalse(err)
        self.assertTrue(text.startswith("total 13"), text)

    def test_item_access_for_odd_names(self):
        text, err = self.run_code("print(tools['fake']['echo_text'](text='hi'))")
        self.assertFalse(err)
        self.assertTrue(text.startswith("hi"), text)

    def test_only_servers_named_in_the_script_are_started(self):
        self.chain = cs.Chain({"servers": {
            "fake": {"command": sys.executable, "args": [FAKE]},
            "other": {"command": sys.executable, "args": [FAKE]}}})
        text, err = self.chain.run("print(tools.fake.add(a=1, b=1)['sum'])")
        self.assertFalse(err)
        self.assertIsNone(self.chain.upstreams["other"].proc)

    def test_a_broken_server_does_not_hide_the_others(self):
        self.chain = cs.Chain({"servers": {
            "fake": {"command": sys.executable, "args": [FAKE]},
            "broken": {"command": "/nonexistent/server"}}})
        out = self.chain.describe()
        self.assertIn("fake.add(", out)
        self.assertIn("## broken: unavailable", out)

    def test_write_tool_is_blocked_by_default(self):
        text, err = self.run_code("tools.fake.delete(id='1')")
        self.assertTrue(err)
        self.assertIn("no tool 'delete'", text)

    def test_allow_list_opens_a_write_tool(self):
        self.chain = cs.Chain({"servers": {"fake": {"command": sys.executable, "args": [FAKE], "allow": ["delete"]}}})
        text, err = self.chain.run("print(tools.fake.delete(id='7'))")
        self.assertFalse(err)
        self.assertIn("{'deleted': '7'}", text)

    def test_tool_error_raises_toolerror(self):
        text, err = self.run_code("try:\n    tools.fake.boom()\nexcept ToolError as e:\n    print('caught', e)")
        self.assertFalse(err)
        self.assertTrue(text.startswith("caught it broke"), text)

    def test_script_error_is_reported(self):
        text, err = self.run_code("1/0")
        self.assertTrue(err)
        self.assertIn("ZeroDivisionError", text)
        self.assertIn("exit code 1", text)

    def test_timeout_kills_the_script(self):
        text, err = self.run_code("while True: pass", timeout=1)
        self.assertTrue(err)
        self.assertIn("killed after 1s timeout", text)

    def test_output_is_truncated(self):
        text, err = self.run_code("print('x' * 100000)")
        self.assertIn("output truncated", text)
        self.assertLess(len(text), cs.MAX_OUT + 200)

    def test_child_does_not_see_the_environment(self):
        os.environ["CHAIN_TEST_SECRET"] = "s3cret"
        try:
            text, _ = self.run_code("import os; print(os.environ.get('CHAIN_TEST_SECRET'))")
        finally:
            del os.environ["CHAIN_TEST_SECRET"]
        self.assertTrue(text.startswith("None"), text)

    def test_require_sandbox_refuses_without_isolation(self):
        original = cs.net_isolation
        cs.net_isolation = lambda: False
        try:
            text, err = self.run_code("print(1)", require_sandbox=True)
        finally:
            cs.net_isolation = original
        self.assertTrue(err)
        self.assertIn("refusing to run", text)

    @unittest.skipUnless(cs.net_isolation(), "unprivileged user namespaces are not available")
    def test_network_is_blocked_when_isolated(self):
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            text, _ = self.run_code(
                "import socket\n"
                f"try:\n    socket.create_connection(('127.0.0.1', {port}), 2)\n    print('connected')\n"
                "except OSError:\n    print('blocked')")
        self.assertTrue(text.startswith("blocked"), text)


class ProtocolTest(unittest.TestCase):
    def test_stdio_round_trip(self):
        env = {**os.environ, "MCP_TOOL_CHAIN_CONFIG": os.path.join(HERE, "nonexistent.json")}
        proc = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, env=env)

        def ask(msg):
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())

        try:
            init = ask({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
            self.assertEqual(init["result"]["serverInfo"]["name"], "tool-chain")
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            listing = ask({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            self.assertEqual([t["name"] for t in listing["result"]["tools"]], ["describe", "run"])
            call = ask({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "run", "arguments": {"code": "print(6 * 7)"}}})
            self.assertTrue(call["result"]["content"][0]["text"].startswith("42"))
            self.assertIn("error", ask({"jsonrpc": "2.0", "id": 4, "method": "nope"}))
        finally:
            proc.stdin.close()
            proc.wait(5)
            proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
