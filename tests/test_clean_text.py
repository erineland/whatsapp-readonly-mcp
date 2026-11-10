"""Tests for the terminal-safety cleaning in whatsapp_mcp.py.

Importing the server installs an import guard that blocks modules such as
`subprocess`, so the server is only ever loaded inside child processes: each
unit case runs in a fresh interpreter, and the end-to-end test talks to the
server over stdio.

Run:  python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import unittest

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "whatsapp_mcp.py")

# Loads the server in a child process, applies one function to JSON input, prints JSON output.
CHILD = r"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("whatsapp_mcp", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cases = json.loads(sys.stdin.read())
out = []
for kind, arg in cases:
    if kind == "clean_text":
        out.append(mod.clean_text(arg))
    else:
        result, error = arg
        mod._clean_reply(result, error)
        out.append([result, error])
sys.stdout.write(json.dumps(out))
"""

ENGLAND = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"

CASES = [
    ("a\x1b[31mred\x1b[0m", "a␛[31mred␛[0m"),
    ("x\x1b]52;c;cHduZWQ=\x07", "x␛]52;c;cHduZWQ=␇"),
    ("line1\r\nline2\rX", "line1\nline2␍X"),
    ("tab\tand\nnewline", "tab\tand\nnewline"),
    ("\x9b31m\x85", "�31m�"),
    ("del\x7f nul\x00", "del␡ nul␀"),
    ("‮evil‬ ⁦iso⁩", "evil iso"),
    ("\U0001F469‍\U0001F4BB", "\U0001F469‍\U0001F4BB"),
    (ENGLAND, ENGLAND),
    ("می‌خواهم", "می‌خواهم"),
]


def run_child(cases):
    p = subprocess.run([sys.executable, "-c", CHILD, SERVER], input=json.dumps(cases),
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)


class CleanTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = run_child([["clean_text", i] for i, _ in CASES])

    def test_cases(self):
        for (inp, expected), got in zip(CASES, self.results):
            with self.subTest(input=repr(inp)):
                self.assertEqual(got, expected)


class CleanReplyTest(unittest.TestCase):
    def test_result_and_error_cleaned(self):
        result = {"content": [{"type": "text", "text": "\x1b[2Jhi"}]}
        error = {"code": -32602, "message": "Unknown tool: \x1b]0;t\x07"}
        [[result, error]] = run_child([["clean_reply", [result, error]]])
        self.assertEqual(result["content"][0]["text"], "␛[2Jhi")
        self.assertNotIn("\x1b", error["message"])
        self.assertNotIn("\x07", error["message"])
        self.assertEqual(error["code"], -32602)


class EndToEndTest(unittest.TestCase):
    def test_unknown_tool_name_is_cleaned(self):
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "x\u001b]0;pwned\u0007", "arguments": {}}},
        ]
        stdin = "".join(json.dumps(r) + "\n" for r in reqs)
        p = subprocess.run([sys.executable, SERVER], input=stdin, capture_output=True,
                           text=True, timeout=30)
        replies = {}
        for line in p.stdout.splitlines():
            msg = json.loads(line)
            replies[msg["id"]] = msg
        self.assertIn(2, replies, p.stdout + p.stderr)
        decoded = json.dumps(replies[2], ensure_ascii=False)
        self.assertNotIn("\x1b", decoded)
        self.assertNotIn("\x07", decoded)
        self.assertIn("␛", decoded)


if __name__ == "__main__":
    unittest.main()
