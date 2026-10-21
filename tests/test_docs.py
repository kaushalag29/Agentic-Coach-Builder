"""The docs say only what the code does: every `ytbrain …` / `founder-coach …` command and flag named in the README
and docs/ exists in the CLI, every YTBRAIN_* / FOUNDER_COACH_* setting is read by the code, and every relative link
and repo path points at a file that exists. Offline; no network, no models. ADRs and research notes are dated
records and are left as written."""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("YTBRAIN_DOTENV", "0")
for _k in ("YTBRAIN_DATA", "YTBRAIN_DIST", "YTBRAIN_PRIVATE_TERMS"):   # hermetic: never your data, builds or terms list
    os.environ.pop(_k, None)

DOCS = sorted([ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "AGENTS.md", *(ROOT / "docs").rglob("*.md")])
DOCS = [p for p in DOCS if p.exists() and not ({"adr", "research"} & set(p.relative_to(ROOT).parts))]
CODE = "\n".join(p.read_text(encoding="utf-8") for d in ("ytbrain", "founder_coach", "scripts", "ops")
                 for p in (ROOT / d).rglob("*") if p.suffix in (".py", ".sh") and "__pycache__" not in p.parts)
CODE += (ROOT / ".env.example").read_text(encoding="utf-8")


class _Got(Exception):
    def __init__(self, parser):
        self.parser = parser


def _parser(main, prog):
    """The CLI's argparse parser, caught as `main` is about to parse (each CLI builds it inside main)."""
    real = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        if self.prog == prog:
            raise _Got(self)
        return real(self, *a, **k)
    argparse.ArgumentParser.parse_args = grab
    try:
        main(["--help"])
    except _Got as g:
        return g.parser
    finally:
        argparse.ArgumentParser.parse_args = real
    raise AssertionError(f"{prog}: no parser built")


def _subs(parser):
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a.choices
    return {}


def _flags(parser):
    return {o for a in parser._actions for o in a.option_strings}


def _code_spans(text):
    """Inline code and fenced code lines: where commands are written."""
    out, fence = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            out.append(line.split(" #")[0])
        else:
            out += re.findall(r"`([^`]+)`", line)
    return out


def _commands(prog):
    for p in DOCS:
        for span in _code_spans(p.read_text(encoding="utf-8")):
            for m in re.finditer(rf"(?:^|[\s;&|(]){re.escape(prog)}((?:\s+[^\s;&|)]+)*)", span):
                yield p, m.group(1).split()


def _check_cli(prog, parser):
    bad = []
    for path, words in _commands(prog):
        node, i = parser, 0
        while i < len(words) and (subs := _subs(node)):
            w = words[i]
            if w.startswith("-") or w.startswith("<") or w.startswith("["):
                break
            if w not in subs and "|" not in w:
                if not re.fullmatch(r"[a-z][a-z-]*", w):
                    break
                bad.append(f"{path.name}: `{prog} {' '.join(words[:i + 1])}`: no such command")
                break
            if "|" in w:
                for alt in w.split("|"):
                    if alt.strip("[]") and alt.strip("[]") not in subs:
                        bad.append(f"{path.name}: `{prog} … {alt}`: no such command")
                break
            node, i = subs[w], i + 1
        known = _flags(node)
        rest = words[i:]
        rest = rest[:rest.index("--")] if "--" in rest else rest      # after a bare --: another program's arguments
        for w in rest:
            for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", w):
                if flag not in known and flag != "--help":
                    bad.append(f"{path.name}: `{prog} {' '.join(words[:i])}` has no {flag}")
    return bad


def test_every_ytbrain_command_and_flag_in_the_docs_exists():
    from ytbrain import cli
    bad = _check_cli("ytbrain", _parser(cli.main, "ytbrain"))
    assert not bad, "\n".join(sorted(set(bad)))


def test_every_founder_coach_command_and_flag_in_the_docs_exists():
    from founder_coach import cli, product
    bad = _check_cli("founder-coach", _parser(cli.main, product.ID))
    assert not bad, "\n".join(sorted(set(bad)))


def test_every_setting_named_in_the_docs_is_read_by_the_code():
    bad = []
    for p in DOCS:
        for name in set(re.findall(r"\b((?:YTBRAIN|FOUNDER_COACH)_[A-Z0-9_]*[A-Z0-9])\b", p.read_text(encoding="utf-8"))):
            suffix = name.split("_", 2)[-1] if name.startswith("FOUNDER_COACH_") else name
            if name not in CODE and f'"{suffix}"' not in CODE and f"'{suffix}'" not in CODE and f"}}{suffix}" not in CODE:
                bad.append(f"{p.relative_to(ROOT)}: {name}")
    assert not bad, "settings the code never reads:\n" + "\n".join(sorted(bad))


def test_every_link_and_repo_path_in_the_docs_exists():
    bad = []
    tops = {p.name for p in ROOT.iterdir()}
    for p in DOCS:
        text = p.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            if not (p.parent / target.split("#")[0]).exists():
                bad.append(f"{p.relative_to(ROOT)}: link {target}")
        for span in _code_spans(text):
            for ref in re.findall(r"(?<![\w./~$-])((?:[\w.-]+/)+[\w.-]+\.(?:py|md|toml|yaml|yml|json|sh|plist|txt))\b", span):
                if ref.split("/")[0] in tops and ref.split("/")[0] not in ("data", "dist") and not (ROOT / ref).exists():
                    bad.append(f"{p.relative_to(ROOT)}: path {ref}")
    assert not bad, "\n".join(sorted(set(bad)))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  PASS", name)
