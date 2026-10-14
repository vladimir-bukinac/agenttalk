"""Prototype Python reader: one file at a time, never imports or runs it (design sections 4 and 5).

Pass 1 (`prescan`): decode, tokenise, count dialect markers, plan the Python 2 repairs.
Pass 2 (`read`): with the file's dialect decided, parse (ast / repaired ast / token outline) and
extract claims. Only identifiers, dotted names, line numbers and route patterns are kept.

SPIKE CODE - DO NOT MERGE.
"""
from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
import warnings
from dataclasses import dataclass, field

from .claims import AdapterIdentity, EdgeClaim, EntryPointClaim, FileClaims, ProblemClaim, UnitClaim

ADAPTER = AdapterIdentity("python-spike", 0, 0)
INTERPRETER = f"{sys.version_info[0]}.{sys.version_info[1]}"

DOTTED = re.compile(r"\A[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?::[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)?\Z")
PY2_KINDS = ("print_statement", "exec_statement", "ne_diamond", "backtick", "raise_comma", "long_suffix",
             "old_octal", "ur_prefix")
SETTINGS_SLOTS = ("INSTALLED_APPS", "MIDDLEWARE", "MIDDLEWARE_CLASSES", "ROOT_URLCONF", "WSGI_APPLICATION",
                  "AUTHENTICATION_BACKENDS", "TEMPLATE_CONTEXT_PROCESSORS")
DYNAMIC_IMPORT_FUNCS = {"import_module", "__import__", "import_string", "get_callable"}
URL_FUNCS = {"url", "path", "re_path"}
_START = {tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT}


def _quiet_parse(text: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(text)


# ----------------------------------------------------------------------------- pass 1

@dataclass
class Prescan:
    relative_path: str
    text: str | None = None
    problem: tuple[str, str] | None = None        # (reason_code, detail) when the file cannot be read
    tokens_ok: bool = False
    py2_markers: dict = field(default_factory=dict)
    py3_markers: dict = field(default_factory=dict)
    except_comma: int = 0
    tuple_parameter: int = 0
    edits: list = field(default_factory=list)       # (row, col, old_len, new_text, kind)
    absolute_import: bool = False
    parses_as_is: bool = False


def decode(raw: bytes) -> tuple[str | None, tuple[str, str] | None]:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    except SyntaxError as exc:
        return None, ("encoding_undecodable", f"unusable encoding declaration: {str(exc)[:80]}")
    try:
        return raw.decode(encoding), None
    except (UnicodeDecodeError, LookupError) as exc:
        return None, ("encoding_undecodable", f"does not decode as {encoding}: {type(exc).__name__}")


def _significant(tokens):
    return [t for t in tokens if t.type not in (tokenize.COMMENT, tokenize.NL)]


def _stmt_end(sig, i):
    """Index of the token that ends the simple statement starting at sig[i] (NEWLINE, ';', ENDMARKER)."""
    depth = 0
    for j in range(i + 1, len(sig)):
        t = sig[j]
        if t.type == tokenize.OP and t.string in "([{":
            depth += 1
        elif t.type == tokenize.OP and t.string in ")]}":
            depth -= 1
        elif depth == 0 and (t.type in (tokenize.NEWLINE, tokenize.ENDMARKER) or (t.type == tokenize.OP and t.string == ";")):
            return j
    return len(sig) - 1


def _comment_before(tokens, end_tok):
    """A trailing comment on the statement's last line: insert closers before it, not after."""
    for t in tokens:
        if t.type == tokenize.COMMENT and t.start[0] == end_tok.start[0] and t.start[1] < end_tok.start[1]:
            return t
    return None


def prescan(relative_path: str, raw: bytes) -> Prescan:
    pre = Prescan(relative_path)
    text, problem = decode(raw)
    if problem:
        pre.problem = problem
        return pre
    pre.text = text
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        pre.tokens_ok = True
    except (tokenize.TokenError, SyntaxError, IndentationError) as exc:
        pre.problem = ("unreadable", f"tokenize failed: {type(exc).__name__}")
        return pre
    sig = _significant(tokens)
    markers: dict[str, int] = {}
    edits = pre.edits

    def mark(kind):
        markers[kind] = markers.get(kind, 0) + 1

    def at_start(i):
        if i == 0:
            return True
        prev = sig[i - 1]
        if prev.type in _START or prev.type == tokenize.ENCODING:
            return True
        return prev.type == tokenize.OP and prev.string in (";", ":") and prev.end[0] == sig[i].start[0] and _depth_at(i) == 0

    depths = []
    d = 0
    for t in sig:
        depths.append(d)
        if t.type == tokenize.OP and t.string in "([{":
            d += 1
        elif t.type == tokenize.OP and t.string in ")]}":
            d -= 1

    def _depth_at(i):
        return depths[i]

    def close_at(end_index):
        end_tok = sig[end_index]
        comment = _comment_before(tokens, end_tok)
        where = comment.start if comment else end_tok.start
        return where

    backtick_open = False
    for i, t in enumerate(sig):
        nxt = sig[i + 1] if i + 1 < len(sig) else None
        if t.type == tokenize.NAME and t.string in ("print", "exec") and at_start(i) and nxt is not None \
                and not (nxt.type == tokenize.OP and nxt.string in ("(", "=", ".", ",", ")")) \
                and nxt.type not in (tokenize.NEWLINE, tokenize.ENDMARKER):
            kind = "print_statement" if t.string == "print" else "exec_statement"
            mark(kind)
            end = _stmt_end(sig, i)
            edits.append((t.end[0], t.end[1], 0, "(", kind))
            if t.string == "print" and nxt.type == tokenize.OP and nxt.string == ">>":
                edits.append((nxt.start[0], nxt.start[1], 2, "  ", kind))
            if t.string == "exec":
                for j in range(i + 1, end):
                    if depths[j] == depths[i] and sig[j].type == tokenize.NAME and sig[j].string == "in":
                        edits.append((sig[j].start[0], sig[j].start[1], 2, ",", kind))
                        break
            row, col = close_at(end)
            edits.append((row, col, 0, ")", kind))
        elif t.type == tokenize.OP and t.string == "<>":
            mark("ne_diamond")   # one token on Python 3.12+ (C tokenizer)
            edits.append((t.start[0], t.start[1], 2, "!=", "ne_diamond"))
        elif t.type == tokenize.OP and t.string == "<" and nxt is not None and nxt.type == tokenize.OP                 and nxt.string == ">" and nxt.start == t.end:
            mark("ne_diamond")   # two tokens on Python 3.10 and 3.11 (pure-Python tokenizer)
            edits.append((t.start[0], t.start[1], 2, "!=", "ne_diamond"))
        elif t.string == "`" and t.type in (tokenize.ERRORTOKEN, tokenize.OP):
            mark("backtick")
            edits.append((t.start[0], t.start[1], 1, ")" if backtick_open else "repr(", "backtick"))
            backtick_open = not backtick_open
        elif t.type == tokenize.NUMBER and re.fullmatch(r"\d+[lL]", t.string):
            mark("long_suffix")
            edits.append((t.end[0], t.end[1] - 1, 1, "", "long_suffix"))
        elif t.type == tokenize.NUMBER and nxt is not None and nxt.type == tokenize.NAME and nxt.string in ("L", "l") \
                and nxt.start == t.end:
            mark("long_suffix")
            edits.append((nxt.start[0], nxt.start[1], 1, "", "long_suffix"))
        elif t.type == tokenize.NUMBER and re.fullmatch(r"0\d+", t.string) and set(t.string) != {"0"}:
            mark("old_octal")
            edits.append((t.start[0], t.start[1] + 1, 0, "o", "old_octal"))
        elif t.type == tokenize.NUMBER and t.string == "0" and nxt is not None and nxt.type == tokenize.NUMBER \
                and nxt.start == t.end:
            mark("old_octal")
            edits.append((t.end[0], t.end[1], 0, "o", "old_octal"))
        elif t.type == tokenize.NAME and t.string.lower() == "ur" and nxt is not None and nxt.type == tokenize.STRING \
                and nxt.start == t.end:
            mark("ur_prefix")
            edits.append((t.start[0], t.start[1], 2, "r", "ur_prefix"))
        elif t.type == tokenize.NAME and t.string in ("except", "raise") and at_start(i):
            stop_colon = t.string == "except"
            comma = None
            has_as = False
            for j in range(i + 1, len(sig)):
                u = sig[j]
                if depths[j] == depths[i]:
                    if u.type == tokenize.OP and u.string == "," and comma is None:
                        comma = u
                    elif u.type == tokenize.NAME and u.string == "as":
                        has_as = True
                    if (stop_colon and u.type == tokenize.OP and u.string == ":") or u.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
                        break
            if comma is not None and not has_as:
                if stop_colon:
                    pre.except_comma += 1
                    edits.append((comma.start[0], comma.start[1], 1, " as", "except_comma"))
                else:
                    mark("raise_comma")
                    end = _stmt_end(sig, i)
                    edits.append((comma.start[0], comma.start[1], 1, "(", "raise_comma"))
                    row, col = close_at(end)
                    edits.append((row, col, 0, ")", "raise_comma"))
        elif t.type == tokenize.NAME and t.string == "lambda" and nxt is not None and nxt.type == tokenize.OP and nxt.string == "(":
            pre.tuple_parameter += 1
        elif t.type == tokenize.NAME and t.string == "def" and i + 3 < len(sig):
            depth = 0
            for j in range(i + 2, len(sig)):
                u = sig[j]
                if u.type == tokenize.OP and u.string == "(":
                    depth += 1
                    if depth == 2 and sig[j - 1].string in ("(", ","):
                        pre.tuple_parameter += 1
                        break
                elif u.type == tokenize.OP and u.string == ")":
                    depth -= 1
                    if depth == 0:
                        break
                elif u.type == tokenize.OP and u.string in ("=", ":") and depth == 1:
                    # a default value or an annotation: nested parentheses after it are not parameters
                    break
        if t.type == tokenize.NAME and t.string == "absolute_import" and i >= 3 and sig[i - 2].string == "import" \
                and sig[i - 3].string == "__future__":
            pre.absolute_import = True
    if pre.tuple_parameter:
        mark_tp = pre.tuple_parameter
        markers.setdefault("tuple_parameter", mark_tp)
    pre.py2_markers = {k: v for k, v in markers.items() if k in PY2_KINDS}
    try:
        tree = _quiet_parse(text)
        pre.parses_as_is = True
        pre.py3_markers = py3_markers(tree)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        pre.parses_as_is = False
    return pre


def py3_markers(tree) -> dict:
    found: dict[str, int] = {}

    def mark(kind):
        found[kind] = found.get(kind, 0) + 1

    for n in ast.walk(tree):
        if isinstance(n, ast.JoinedStr):
            mark("f_string")
        elif isinstance(n, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            mark("async")
        elif isinstance(n, ast.Nonlocal):
            mark("nonlocal")
        elif isinstance(n, ast.YieldFrom):
            mark("yield_from")
        elif isinstance(n, ast.AnnAssign):
            mark("annotation")
        elif isinstance(n, ast.NamedExpr):
            mark("walrus")
        elif hasattr(ast, "Match") and isinstance(n, ast.Match):
            mark("match")
        elif isinstance(n, (ast.FunctionDef, ast.Lambda)):
            a = n.args
            if a.kwonlyargs:
                mark("keyword_only_args")
            if a.posonlyargs:
                mark("positional_only_args")
            if isinstance(n, ast.FunctionDef) and (n.returns is not None or any(
                    x.annotation is not None for x in a.args + a.kwonlyargs + a.posonlyargs)):
                mark("annotation")
    return found


def apply_edits(text: str, edits) -> str:
    """Line-preserving rewrite: edits never add or remove a newline."""
    lines = text.splitlines(keepends=True)
    for row, col, old_len, new, _kind in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        line = lines[row - 1]
        lines[row - 1] = line[:col] + new + line[col + old_len:]
    out = "".join(lines)
    assert out.count("\n") == text.count("\n")
    return out


# ----------------------------------------------------------------------------- pass 2

@dataclass
class FileContext:
    relative_path: str
    module: str | None          # dotted module name from the import roots
    is_package: bool
    dialect: str                # "python2" | "python3"
    dialect_rule: str
    classification: str


def classify(relative_path: str) -> str:
    parts = relative_path.split("/")
    name = parts[-1]
    if name in ("tests.py", "conftest.py") or name.startswith("test_") or name.endswith(("_tests.py", "_test.py")):
        return "test"
    if any(p in ("tests", "test") for p in parts[:-1]):
        return "test"
    return "production"


def read(pre: Prescan, ctx: FileContext) -> FileClaims:
    problems: list[ProblemClaim] = []
    extras: dict = {"dialect": ctx.dialect, "dialect_rule": ctx.dialect_rule, "interpreter": INTERPRETER,
                    "absolute_import": pre.absolute_import, "py2_markers": pre.py2_markers,
                    "py3_markers": pre.py3_markers, "except_comma": pre.except_comma}
    if pre.problem:
        problems.append(ProblemClaim(*pre.problem))
        return FileClaims(ADAPTER, "python", ctx.relative_path, ctx.module, "unreadable", problems=problems, extras=extras)
    text = pre.text
    tree = None
    reader = None
    if ctx.dialect == "python2":
        edits = list(pre.edits)
        if pre.tuple_parameter:
            problems.append(ProblemClaim("python2_no_repair", "tuple parameter"))
        elif edits:
            try:
                tree = _quiet_parse(apply_edits(text, edits))
                reader = "python-ast-repaired"
                kinds = sorted({e[4] for e in edits})
                problems.append(ProblemClaim("python2_repaired", ",".join(kinds)))
            except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
                problems.append(ProblemClaim("python2_repair_failed", f"{type(exc).__name__}: {str(exc)[:60]}"))
        else:
            try:
                tree = _quiet_parse(text)
                reader = "python-ast"
            except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
                problems.append(ProblemClaim("parse_failed", f"{type(exc).__name__}: {str(exc)[:60]}"))
        if ctx.dialect_rule == "no_markers_default" and pre.except_comma:
            problems.append(ProblemClaim("dialect_assumed", "except X, e: read as Python 2"))
    else:
        try:
            tree = _quiet_parse(text)
            reader = "python-ast"
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            problems.append(ProblemClaim("parse_failed", f"{type(exc).__name__}: {str(exc)[:60]}"))
    if tree is None:
        return _token_outline(pre, ctx, problems, extras)
    return Extractor(ctx, tree, problems, extras, reader).claims()


def _token_outline(pre: Prescan, ctx: FileContext, problems, extras) -> FileClaims:
    """python-tokens: imports, class and function names with nesting, line numbers."""
    tokens = _significant(list(tokenize.generate_tokens(io.StringIO(pre.text).readline)))
    units, edges = [], []
    functions = {}
    stack: list[tuple[int, str]] = []   # (indent depth, class name)
    indent = 0
    file_anchor = f"{ctx.relative_path}#file"
    phase = "test" if ctx.classification == "test" else "runtime"
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == tokenize.INDENT:
            indent += 1
        elif t.type == tokenize.DEDENT:
            indent -= 1
            while stack and stack[-1][0] >= indent:
                stack.pop()
        elif t.type == tokenize.NAME and t.string in ("import", "from") and (i == 0 or tokens[i - 1].type in _START):
            j = _stmt_end(tokens, i)
            words = [u.string for u in tokens[i:j]]
            if words[0] == "import":
                for part in " ".join(words[1:]).split(","):
                    name = part.split(" as ")[0].replace(" ", "")
                    if name:
                        edges.append(EdgeClaim(file_anchor, "import", name, "py_import", "extracted", t.start[0], phase))
            elif "import" in words:
                k = words.index("import")
                mod = "".join(words[1:k])
                for part in " ".join(w for w in words[k + 1:] if w not in "()").split(","):
                    name = part.split(" as ")[0].strip()
                    if name:
                        edges.append(EdgeClaim(file_anchor, "import", f"{mod}|{name}", "py_from_import", "extracted",
                                               t.start[0], phase))
            i = j
            continue
        elif t.type == tokenize.NAME and t.string in ("class", "def") and i + 1 < len(tokens) \
                and tokens[i + 1].type == tokenize.NAME:
            name = tokens[i + 1].string
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if t.string == "class" and (not stack or len(stack) == indent) and ctx.module:
                qual = ".".join([ctx.module, *[s[1] for s in stack], name])
                units.append(UnitClaim(ctx.relative_path, qual, name, t.start[0], ctx.classification))
                stack.append((indent, name))
            elif t.string == "def" and indent == 0:
                functions[name] = t.start[0]
        i += 1
    extras["functions"] = functions
    problems.append(ProblemClaim("partial_read", "token outline only"))
    return FileClaims(ADAPTER, "python", ctx.relative_path, ctx.module, "python-tokens", units, edges, [], problems, extras)


def _dotted(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else None
    return None


def _func_name(call: ast.Call) -> str | None:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _str(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class Extractor:
    def __init__(self, ctx: FileContext, tree, problems, extras, reader):
        self.ctx, self.tree, self.problems, self.extras, self.reader = ctx, tree, problems, extras, reader
        self.units, self.edges, self.entry_points = [], [], []
        self.alias: dict[str, str] = {}
        self.consumed: set[int] = set()
        self.anchor = f"{ctx.relative_path}#file"
        self.phase = "test" if ctx.classification == "test" else "runtime"
        self.module_classes: set[str] = set()

    def claims(self) -> FileClaims:
        self._imports()
        self._classes()
        self._functions_and_main()
        self._settings()
        self._urls()
        self._dynamic_and_shapes()
        self._string_refs()
        if self.ctx.relative_path.split("/")[-3:-1] == ["management", "commands"] \
                and not self.ctx.relative_path.endswith("__init__.py") and "Command" in self.module_classes:
            name = self.ctx.relative_path.rsplit("/", 1)[-1][:-3]
            self.entry_points.append(EntryPointClaim(f"{self.ctx.module}.Command", "cli_command", name,
                                                     None, "extracted"))
        if self.ctx.relative_path.endswith("__main__.py"):
            self.entry_points.append(EntryPointClaim(self.ctx.module or self.anchor, "cli_main", "__main__",
                                                     1, "extracted"))
        return FileClaims(ADAPTER, "python", self.ctx.relative_path, self.ctx.module, self.reader, self.units,
                          self.edges, self.entry_points, self.problems, self.extras)

    # imports anywhere in the file; the alias table uses every import (spike simplification)
    def _imports(self):
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.edges.append(EdgeClaim(self.anchor, "import", a.name, "py_import", "extracted", n.lineno, self.phase))
                    if a.asname:
                        self.alias[a.asname] = a.name
                    else:
                        self.alias.setdefault(a.name.split(".")[0], a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                mod = "." * (n.level or 0) + (n.module or "")
                for a in n.names:
                    self.edges.append(EdgeClaim(self.anchor, "import", f"{mod}|{a.name}", "py_from_import",
                                                "extracted", n.lineno, self.phase))
                    if a.name != "*":
                        self.alias[a.asname or a.name] = f"{mod}|{a.name}"

    def _qualify(self, dotted: str | None) -> tuple[str | None, str]:
        """A name used in this file -> (target, target_kind) for the resolver."""
        if not dotted:
            return None, "py_expression"
        head, _, rest = dotted.partition(".")
        if head in self.alias:
            base = self.alias[head]
            return (f"{base}.{rest}" if rest else base), "py_via_import"
        if head in self.module_classes or head in self.extras.get("functions", {}):
            return f"{self.ctx.module}.{dotted}", "py_local"
        return dotted, "py_builtin_or_unknown"

    def _classes(self):
        functions = {}
        for n in self.tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[n.name] = n.lineno
        self.extras["functions"] = functions

        def visit(body, prefix):
            for n in body:
                if isinstance(n, ast.ClassDef):
                    if not prefix:
                        self.module_classes.add(n.name)
                    visit(n.body, prefix + [n.name])
        visit(self.tree.body, [])
        local = 0

        def walk(body, prefix, in_function):
            nonlocal local
            for n in body:
                if isinstance(n, ast.ClassDef):
                    if in_function:
                        local += 1
                        continue
                    qual = ".".join([self.ctx.module or self.anchor, *prefix, n.name])
                    self.units.append(UnitClaim(self.ctx.relative_path, qual, n.name, n.lineno, self.ctx.classification))
                    for b in n.bases:
                        target, kind = self._qualify(_dotted(b))
                        if target is None:
                            self.problems.append(ProblemClaim("base_not_static", f"class {n.name}", qual))
                            continue
                        self.edges.append(EdgeClaim(qual, "inherit", target, kind, "extracted", n.lineno, self.phase))
                    if any(isinstance(m, ast.FunctionDef) and m.name == "ready" for m in n.body) and any(
                            (_dotted(b) or "").endswith("AppConfig") for b in n.bases):
                        self.problems.append(ProblemClaim("unsupported_entry_point_shape", "appconfig_ready", qual))
                    walk(n.body, prefix + [n.name], in_function)
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    walk(n.body, prefix, True)
                elif isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While)) or type(n).__name__ == "TryStar":
                    for attr in ("body", "orelse", "finalbody", "handlers"):
                        sub = getattr(n, attr, None) or []
                        for s in sub:
                            if isinstance(s, ast.ExceptHandler):
                                walk(s.body, prefix, in_function)
                        walk([s for s in sub if not isinstance(s, ast.ExceptHandler)], prefix, in_function)
        walk(self.tree.body, [], False)
        self.extras["local_classes_skipped"] = local

    def _functions_and_main(self):
        for n in self.tree.body:
            if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and _dotted(n.test.left) == "__name__" \
                    and any(_str(c) == "__main__" for c in n.test.comparators):
                self.entry_points.append(EntryPointClaim(self.ctx.module or self.anchor, "cli_main", "__main__",
                                                         n.lineno, "extracted"))

    def _literal_names(self, node, known) -> list[str] | None:
        s = _str(node)
        if s is not None:
            self.consumed.add(id(node))
            return [s]
        if isinstance(node, (ast.List, ast.Tuple)):
            out = []
            for e in node.elts:
                part = self._literal_names(e, known)
                if part is None:
                    return None
                out += part
            return out
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self._literal_names(node.left, known), self._literal_names(node.right, known)
            return None if left is None or right is None else left + right
        if isinstance(node, ast.Name) and node.id in known:
            return list(known[node.id])
        return None

    def _settings(self):
        rel = self.ctx.relative_path
        name = rel.rsplit("/", 1)[-1]
        is_settings = name.startswith("settings") or "/settings/" in f"/{rel}" or any(
            isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "INSTALLED_APPS" for t in n.targets)
            for n in self.tree.body)
        for n in ast.walk(self.tree):  # DJANGO_SETTINGS_MODULE literal anywhere
            if isinstance(n, ast.Call) and len(n.args) >= 2 and _str(n.args[0]) == "DJANGO_SETTINGS_MODULE" \
                    and _str(n.args[1]):
                self.consumed.add(id(n.args[1]))
                self.extras.setdefault("settings_module_refs", []).append(_str(n.args[1]))
        if not is_settings:
            return
        self.extras["is_settings"] = True
        known: dict[str, list[str]] = {}
        for n in self.tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                slot, value, aug = n.targets[0].id, n.value, False
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and isinstance(n.op, ast.Add):
                slot, value, aug = n.target.id, n.value, True
            else:
                continue
            if slot not in SETTINGS_SLOTS:
                continue
            names = self._literal_names(value, known)
            if names is None:
                self.problems.append(ProblemClaim("settings_value_not_static", slot))
                continue
            known[slot] = (known.get(slot, []) + names) if aug else names
            for v in names:
                if not DOTTED.match(v) and "." not in v:
                    if slot == "INSTALLED_APPS" and re.fullmatch(r"[A-Za-z_]\w*", v):
                        pass  # a top-level app package name
                    else:
                        continue
                self.edges.append(EdgeClaim(self.anchor, "configuration", v, f"py_settings:{slot}", "declared",
                                            n.lineno, "runtime"))
                if slot in ("MIDDLEWARE", "MIDDLEWARE_CLASSES"):
                    self.entry_points.append(EntryPointClaim(v, "http_filter", v, n.lineno, "declared"))
            if slot == "ROOT_URLCONF" and names:
                self.extras["root_urlconf"] = names[-1]

    # ---- Django URL lists
    def _url_view(self, node, prefix: str):
        s = _str(node)
        if s is not None:
            self.consumed.add(id(node))
            return {"kind": "route", "target": f"{prefix}.{s}" if prefix and s else s, "target_kind": "view_string"}
        if isinstance(node, ast.Call) and _func_name(node) == "include":
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Tuple) and arg.elts:
                arg = arg.elts[0]
            s = _str(arg)
            if s is not None:
                self.consumed.add(id(arg))
                return {"kind": "include", "target": s, "target_kind": "module_string"}
            target, kind = self._qualify(_dotted(arg))
            if target is not None:
                return {"kind": "include", "target": target, "target_kind": kind}
            return {"kind": "include", "target": None, "target_kind": "dynamic"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "as_view":
            target, kind = self._qualify(_dotted(node.func.value))
            return {"kind": "route", "target": target, "target_kind": f"class_view:{kind}"}
        if isinstance(node, ast.Call) and node.args and _func_name(node) not in ("include", "as_view"):
            # a wrapped view such as login_required(View.as_view()) or csrf_exempt(view)
            inner = self._url_view(node.args[0], prefix)
            if inner.get("target") is not None:
                inner["wrapped_by"] = _func_name(node)
                return inner
        target, kind = self._qualify(_dotted(node))
        return {"kind": "route", "target": target, "target_kind": kind if target else "dynamic"}

    def _url_entry(self, node, prefix: str):
        if isinstance(node, ast.Call) and _func_name(node) in URL_FUNCS and len(node.args) >= 2:
            pattern, view = node.args[0], node.args[1]
        elif isinstance(node, ast.Tuple) and len(node.elts) >= 2:
            pattern, view = node.elts[0], node.elts[1]
        else:
            return None
        p = _str(pattern)
        if p is None:
            # a pattern built at run time (for example from a setting): keep the entry, say so
            entry = self._url_view(view, prefix)
            entry.update(pattern="<computed>", line=node.lineno, computed_pattern=True)
            return entry
        self.consumed.add(id(pattern))
        entry = self._url_view(view, prefix)
        entry.update(pattern=p, line=node.lineno)
        return entry

    def _url_list(self, node):
        """-> list of items: entries, {"ref": dotted name}, or {"unrecognized": n}."""
        if isinstance(node, ast.Call) and _func_name(node) == "patterns":
            prefix = _str(node.args[0]) if node.args else ""
            if node.args and prefix is not None:
                self.consumed.add(id(node.args[0]))
            items = []
            for a in node.args[1:]:
                e = self._url_entry(a, prefix or "")
                items.append(e if e else {"unrecognized": type(a).__name__, "line": getattr(a, "lineno", None)})
            return items
        if isinstance(node, (ast.List, ast.Tuple)):
            items = []
            for a in node.elts:
                e = self._url_entry(a, "")
                if e is None and isinstance(a, ast.Starred):
                    items += self._url_list(a.value)
                    continue
                items.append(e if e else {"unrecognized": type(a).__name__, "line": getattr(a, "lineno", None)})
            return items
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self._url_list(node.left) + self._url_list(node.right)
        if isinstance(node, (ast.Name, ast.Attribute)):
            target, kind = self._qualify(_dotted(node))
            return [{"ref": target, "ref_kind": kind}]
        return [{"unrecognized": type(node).__name__, "line": getattr(node, "lineno", None)}]

    def _module_statements(self, body, conditional=False):
        """Module-level statements, including both branches of module-level if/try blocks."""
        for n in body:
            if isinstance(n, ast.If):
                yield from self._module_statements(n.body, True)
                yield from self._module_statements(n.orelse, True)
            elif isinstance(n, ast.Try) or type(n).__name__ == "TryStar":
                yield from self._module_statements(n.body, True)
                for h in n.handlers:
                    yield from self._module_statements(h.body, True)
                yield from self._module_statements(n.orelse, True)
                yield from self._module_statements(n.finalbody, conditional)
            else:
                yield n, conditional

    def _urls(self):
        lists: dict[str, list] = {}
        conditional_items = 0
        for n, conditional in self._module_statements(self.tree.body):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                name, value, aug = n.targets[0].id, n.value, False
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and isinstance(n.op, ast.Add):
                name, value, aug = n.target.id, n.value, True
            else:
                continue
            looks_like_urls = name == "urlpatterns" or (isinstance(value, ast.Call) and _func_name(value) == "patterns") \
                or (isinstance(value, (ast.List, ast.Tuple)) and value.elts and all(
                    isinstance(e, ast.Call) and _func_name(e) in URL_FUNCS for e in value.elts))
            if not looks_like_urls:
                continue
            items = self._url_list(value)
            if conditional:
                conditional_items += len(items)
                for it in items:
                    it["conditional"] = True
                if not aug and name in lists:
                    aug = True   # another branch already set it: keep both (every possible list)
            if not aug and name in lists and all("unrecognized" in it for it in items) and any(
                    isinstance(x, ast.Name) and x.id == name for x in ast.walk(value)):
                # urlpatterns = f(..., urlpatterns, ...): the old list stays, extended at run time
                nested = [e for x in ast.walk(value) if isinstance(x, ast.List)
                          for e in (self._url_entry(el, "") for el in x.elts) if e]
                items = lists[name] + nested + [{"unrecognized": "runtime_extension", "line": n.lineno}]
                self.extras["url_runtime_extension"] = True
            if aug and name not in lists and name in self.alias:
                # urlpatterns += ... on a list imported from another module starts from that list
                lists[name] = [{"ref": self.alias[name], "ref_kind": "py_via_import"}]
            # a local name on the right of urlpatterns = a + b refers to this module's own list
            for it in items:
                if "ref" in it and it.get("ref_kind") == "py_builtin_or_unknown" and it["ref"] in lists:
                    it["ref"], it["ref_kind"] = f"{self.ctx.module}:{it['ref']}", "local_list"
            lists[name] = (lists.get(name, []) + items) if aug else items
        if lists:
            self.extras["url_lists"] = lists
            self.extras["url_conditional_items"] = conditional_items
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "send" \
                    and any(k.arg == "patterns" for k in n.keywords):
                self.extras.setdefault("url_dynamic_hooks", []).append({"hook": _dotted(n.func.value), "line": n.lineno})

    def _dynamic_and_shapes(self):
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Call):
                fname = _func_name(n)
                if fname in DYNAMIC_IMPORT_FUNCS:
                    arg = _str(n.args[0]) if n.args else None
                    if arg is not None:
                        self.consumed.add(id(n.args[0]))
                        self.edges.append(EdgeClaim(self.anchor, "import", arg, "py_dynamic_literal", "inferred",
                                                    n.lineno, self.phase))
                    else:
                        self.problems.append(ProblemClaim("dynamic_import_unresolved", f"{fname} at line {n.lineno}"))
                elif fname == "connect" and isinstance(n.func, ast.Attribute) and n.args:
                    self.problems.append(ProblemClaim("unsupported_entry_point_shape", f"signal_receiver line {n.lineno}"))
                elif fname == "register" and (_dotted(n.func) or "").endswith("site.register"):
                    self.problems.append(ProblemClaim("unsupported_entry_point_shape", f"admin_register line {n.lineno}"))
                elif fname == "admin_url":
                    self.problems.append(ProblemClaim("unsupported_entry_point_shape", f"route_helper:admin_url line {n.lineno}"))
                elif fname in ("get_wsgi_application", "WSGIHandler", "get_asgi_application"):
                    self.problems.append(ProblemClaim("unsupported_entry_point_shape", f"wsgi_application line {n.lineno}"))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for d in n.decorator_list:
                    name = _dotted(d.func if isinstance(d, ast.Call) else d) or ""
                    last = name.rsplit(".", 1)[-1]
                    if last == "receiver":
                        self.problems.append(ProblemClaim("unsupported_entry_point_shape", f"signal_receiver line {n.lineno}"))
                    elif last in ("task", "shared_task", "periodic_task"):
                        self.problems.append(ProblemClaim("unsupported_entry_point_shape", f"task_queue line {n.lineno}"))
                    elif name.startswith("register.") and last in ("tag", "filter", "simple_tag", "inclusion_tag",
                                                                    "assignment_tag"):
                        self.problems.append(ProblemClaim("unsupported_entry_point_shape", f"template_tag line {n.lineno}"))

    def _string_refs(self):
        refs = []
        for n in ast.walk(self.tree):
            s = _str(n)
            if s is not None and id(n) not in self.consumed and DOTTED.match(s):
                refs.append([s, getattr(n, "lineno", None)])
        self.extras["string_refs"] = refs
