import importlib.machinery
import importlib.util
import json
import os
import socket
import subprocess
import sys
import unittest

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
        self.assertEqual(cs.load_config("/nonexistent/x.json"), {"servers": {}})
        bad = os.path.join(HERE, "bad.json")
        with open(bad, "w") as f:
            f.write("{nope")
        try:
            self.assertRaises(cs.ChainError, cs.load_config, bad)
        finally:
            os.remove(bad)


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
        self.assertIn("No servers configured", cs.Chain({"servers": {}}).describe())

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
