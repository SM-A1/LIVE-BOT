"""Isolated user-script runner. Stdlib only; launched as a separate, resource-limited process.

Reads {"code": str, "ctx": dict} from stdin and prints one JSON result line. The script never receives the bot
token or network access by design: it can only *request* actions (reply, reply_buttons) which the parent validates
and performs. This is defence-in-depth (AST allow-listing + restricted builtins + OS rlimits), NOT a hard
security boundary: see README before enabling the feature for untrusted users.
"""
import ast
import json
import sys
import types

import builtins as _b
import base64, collections, datetime, decimal, functools, hashlib, itertools, math, random, re, statistics
import textwrap, time, unicodedata
import json as _json_mod

MAX_ACTIONS, MAX_TEXT, MAX_CODE = 5, 4096, 20_000

MODULES = {m.__name__: m for m in (
    base64, collections, datetime, decimal, functools, hashlib, itertools, math, random, re, statistics,
    textwrap, time, unicodedata, _json_mod)}
FACADES = {}
for _name, _mod in MODULES.items():
    FACADES[_name] = types.SimpleNamespace(**{
        k: v for k, v in vars(_mod).items() if not k.startswith("_") and not isinstance(v, types.ModuleType)})

BLOCKED_NAMES = {"eval", "exec", "compile", "open", "getattr", "setattr", "delattr", "globals", "locals", "vars",
                 "dir", "input", "breakpoint", "exit", "quit", "help", "memoryview", "__import__"}
BLOCKED_ATTRS = {"format", "format_map", "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "cr_await",
                 "ag_frame", "ag_code", "tb_frame", "tb_next", "f_back", "f_globals", "f_locals", "f_builtins",
                 "f_code", "func_globals", "mro", "sys", "modules", "os", "system", "popen", "codecs", "open",
                 "importlib", "subprocess", "builtins"}
ASYNC_NODES = (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)
SAFE_BUILTINS = ("abs all any ascii bin bool bytes callable chr classmethod dict divmod enumerate filter float "
                 "frozenset hash hex int isinstance issubclass iter len list map max min next object oct ord pow "
                 "property range repr reversed round set slice sorted staticmethod str sum super tuple type zip "
                 "Exception ValueError TypeError KeyError IndexError ZeroDivisionError ArithmeticError "
                 "StopIteration AttributeError RuntimeError NotImplementedError OverflowError LookupError "
                 "True False None").split()


class ScriptError(Exception):
    pass


def validate(tree: ast.AST) -> None:
    for n in ast.walk(tree):
        if isinstance(n, ASYNC_NODES):
            raise ScriptError("async code is not allowed")
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name not in MODULES:
                    raise ScriptError(f"import of '{a.name}' is not allowed")
        elif isinstance(n, ast.ImportFrom):
            if n.level or (n.module or "") not in MODULES:
                raise ScriptError(f"import of '{n.module}' is not allowed")
        elif isinstance(n, ast.Attribute):
            if n.attr.startswith("_") or n.attr in BLOCKED_ATTRS:
                raise ScriptError(f"access to attribute '{n.attr}' is not allowed")
        elif isinstance(n, ast.Name):
            if n.id in BLOCKED_NAMES or n.id.startswith("__"):
                raise ScriptError(f"use of '{n.id}' is not allowed")


class Ctx:
    def __init__(self, data: dict):
        self.text = str(data.get("text", ""))
        self.args = str(data.get("args", ""))
        self.user = dict(data.get("user", {}))
        self.chat = dict(data.get("chat", {}))
        self.bot = dict(data.get("bot", {}))
        self.is_admin = bool(data.get("is_admin", False))
        self._actions = []

    def _add(self, a):
        if len(self._actions) >= MAX_ACTIONS:
            raise ScriptError("too many replies (max 5)")
        self._actions.append(a)

    def reply(self, text):
        self._add({"op": "reply", "text": str(text)[:MAX_TEXT]})

    def reply_buttons(self, text, rows):
        clean = [[(str(l)[:40], str(u)[:500]) for l, u in row] for row in rows][:8]
        self._add({"op": "reply_buttons", "text": str(text)[:MAX_TEXT], "rows": clean})


def main() -> None:
    out_stream = sys.stdout
    printed = []

    def safe_print(*args, **_):
        if sum(map(len, printed)) < 2000:
            printed.append(" ".join(map(str, args)))

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name not in FACADES or level:
            raise ImportError(f"import of '{name}' is not allowed")
        return FACADES[name]

    try:
        req = json.loads(sys.stdin.read(300_000))
        code = req["code"]
        if len(code) > MAX_CODE:
            raise ScriptError("script is too long")
        tree = ast.parse(code, "<script>")
        validate(tree)
        ctx = Ctx(req["ctx"])
        builtins_ns = {k: getattr(_b, k) for k in SAFE_BUILTINS}
        builtins_ns.update({"print": safe_print, "__import__": safe_import, "__build_class__": _b.__build_class__})
        ns = {"__builtins__": builtins_ns, "__name__": "script", "ctx": ctx, "bot": ctx,
              "message": {"text": ctx.text}, "user": ctx.user, "chat": ctx.chat}
        exec(compile(tree, "<script>", "exec"), ns)
        result = {"ok": True, "actions": ctx._actions, "out": "\n".join(printed)[:2000]}
    except ScriptError as e:
        result = {"ok": False, "error": str(e)[:300]}
    except SyntaxError as e:
        result = {"ok": False, "error": f"SyntaxError on line {e.lineno}: {e.msg}"}
    except BaseException as e:  # noqa: BLE001 - everything must be reported, never crash silently
        line = ""
        tb = e.__traceback__
        while tb:
            if tb.tb_frame.f_code.co_filename == "<script>":
                line = f" (line {tb.tb_lineno})"
            tb = tb.tb_next
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"[:250] + line}
    out_stream.write(json.dumps(result))
    out_stream.flush()


if __name__ == "__main__":
    main()
