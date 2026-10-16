"""Checagem estrutural do M gerado (F0.F5, plano B).

Não é um parser de M: verifica o que costuma quebrar quando o código é
gerado por concatenação — strings e comentários bem fechados, parênteses,
colchetes e chaves balanceados, ``let``/``in`` pareados e nenhum resquício
de sintaxe Python. A validação de verdade é manual no Power BI Desktop
(F2.A).
"""

import re

_PAIRS = {")": "(", "]": "[", "}": "{"}
_PYTHONISMS = re.compile(r"\b(True|False|None|elif|lambda)\b|==|!=|'")


def _strip(code: str) -> str:
    """Troca strings, identificadores entre aspas e comentários por espaço,
    preservando o resto. Falha se algum ficar aberto."""
    out, i, n = [], 0, len(code)
    while i < n:
        if code.startswith("//", i):
            end = code.find("\n", i)
            i = n if end == -1 else end
        elif code.startswith("/*", i):
            end = code.find("*/", i + 2)
            if end == -1:
                raise AssertionError("comentário /* sem fechamento")
            i = end + 2
        elif code[i] == '"' or code.startswith('#"', i):
            i += 2 if code[i] == "#" else 1
            while True:
                if i >= n:
                    raise AssertionError("texto entre aspas sem fechamento")
                if code[i] == '"':
                    if code.startswith('""', i):
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
        else:
            out.append(code[i])
            i += 1
    return "".join(out)


def check_m(code: str) -> None:
    """Levanta ``AssertionError`` com o motivo se o M não passar."""
    bare = _strip(code)
    stack = []
    for pos, ch in enumerate(bare):
        if ch in "([{":
            stack.append(ch)
        elif ch in _PAIRS and (not stack or stack.pop() != _PAIRS[ch]):
            raise AssertionError(f"{ch!r} sem abertura correspondente na posição {pos}")
    if stack:
        raise AssertionError(f"{stack[-1]!r} sem fechamento")
    words = re.findall(r"[A-Za-z_][\w.]*", bare)
    if words.count("let") != words.count("in"):
        raise AssertionError(f"{words.count('let')} let para {words.count('in')} in")
    if m := _PYTHONISMS.search(bare):
        raise AssertionError(f"sintaxe que não é M: {m.group(0)!r}")
