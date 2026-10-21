"""LaTeX -> spoken words, for the TTS pipeline.

Converts a LaTeX math expression into a plain-English string a speech engine can
read aloud, following the conventions of the ClearSpeak / SimpleSpeak speech styles
(common forms said simply: "x squared", "the fraction a over b", "three point five").
Physics-oriented: Greek letters, units inside \\mathrm/\\text (with SI prefixes),
vectors, dots, derivatives and integrals are read the way a person would read them.

`verbalize` raises `Unsupported` on constructs it does not cover (matrices, custom
macros, ...); callers fall back to their previous behavior, e.g. the word "(formula)".

Read like a lecturer, not a screen reader: the hierarchy of the expression is carried
by the wording and by pauses.
- Words that name the structure: "rho times the quantity ...", "a plus b, all over c",
  "the gradient of p", "the divergence of tau", "the Laplacian of u", "u dot del u",
  "f of x", "one half".
- Pauses at three strengths, emitted as marks (P1 < P2 < P3): a short one closing a
  bracketed group or before a differential ("..., d x"), a medium one between the
  terms of each side, a long one before the relation ("..., equals ...").
  `verbalize_marked` keeps the marks for the voice (tts.prosody renders them for each
  engine: commas, or timed breaks where the engine has them); `verbalize` writes each
  as a comma. A short expression ("E equals m c squared") is read without pauses.
"""

from __future__ import annotations

import re


class Unsupported(Exception):
    """The expression uses a construct mathspeak cannot say."""


# pause marks, weakest to strongest (private-use characters: they survive the text clean-up)
P1, P2, P3 = "\ue001", "\ue002", "\ue003"
MARKS = (P1, P2, P3)
# an expression of at most this many words is read in one breath
SHORT = 10


# ---------------------------------------------------------------------------
# vocabularies

GREEK = {
    "alpha": "alpha", "beta": "beta", "gamma": "gamma", "delta": "delta",
    "epsilon": "epsilon", "varepsilon": "epsilon", "zeta": "zeta", "eta": "eta",
    "theta": "theta", "vartheta": "theta", "iota": "iota", "kappa": "kappa",
    "lambda": "lambda", "mu": "mu", "nu": "nu", "xi": "xi", "pi": "pi",
    "rho": "rho", "sigma": "sigma", "tau": "tau", "phi": "phi", "varphi": "phi",
    "chi": "chi", "psi": "psi", "omega": "omega",
}
GREEK_CAP = {
    "Gamma": "capital gamma", "Delta": "capital delta", "Theta": "capital theta",
    "Lambda": "capital lambda", "Xi": "capital xi", "Pi": "capital pi",
    "Sigma": "capital sigma", "Phi": "capital phi", "Psi": "capital psi",
    "Omega": "capital omega",
}

WORDS = {
    # relations
    "=": "equals", "<": "is less than", ">": "is greater than",
    "leq": "is less than or equal to", "le": "is less than or equal to",
    "geq": "is greater than or equal to", "ge": "is greater than or equal to",
    "neq": "is not equal to", "approx": "is approximately equal to",
    "equiv": "is equivalent to", "propto": "is proportional to",
    "sim": "is similar to", "simeq": "is approximately equal to",
    "cong": "is congruent to", "ll": "is much less than", "gg": "is much greater than",
    "in": "is an element of", "notin": "is not an element of",
    "subset": "is a subset of", "supset": "is a superset of",
    "subseteq": "is a subset of or equal to",
    # arrows
    "to": "to", "rightarrow": "to", "leftarrow": "left arrow",
    "Rightarrow": "implies", "Leftarrow": "is implied by",
    "mapsto": "maps to", "leftrightarrow": "corresponds to",
    # operators and constants
    "cdot": "times", "times": "times", "div": "divided by", "pm": "plus or minus",
    "mp": "minus or plus", "circ": "degrees", "degree": "degrees",
    "infty": "infinity", "partial": "partial", "nabla": "del",
    "prime": "prime", "emptyset": "the empty set",
    "forall": "for all", "exists": "there exists",
    "perp": "is perpendicular to", "parallel": "is parallel to",
    "angle": "angle", "hbar": "h bar", "ell": "ell", "ldots": "dot dot dot",
    "cdots": "dot dot dot", "dots": "dot dot dot", "ast": "times", "star": "star",
}
OPS = {
    "+": "plus", "-": "minus", "=": "equals", "<": "is less than",
    ">": "is greater than", "/": "divided by", "*": "times", "%": "percent",
}
# the spoken relations: before one, at the top level, the long pause
RELATIONS = {
    "equals", "is less than", "is greater than", "is less than or equal to",
    "is greater than or equal to", "is not equal to", "is approximately equal to",
    "is equivalent to", "is proportional to", "is similar to", "is congruent to",
    "is much less than", "is much greater than", "implies", "is implied by",
}
SIGNS = {"plus", "minus", "plus or minus", "minus or plus"}
# what makes a following \cdot a dot product and \times a cross product
VECTORISH = {"mathbf", "boldsymbol", "bm", "vec", "nabla"}
# del applied to what follows: the operator by name, as a lecturer says it
NABLA_OF = ("the gradient of", "the divergence of", "the curl of", "the Laplacian of")
# small fractions by their names
NAMED_FRACTIONS = {
    ("1", "2"): "one half", ("1", "3"): "one third", ("2", "3"): "two thirds",
    ("1", "4"): "one quarter", ("3", "4"): "three quarters",
}
TRIG = {
    "sin": "sine", "cos": "cosine", "tan": "tangent", "cot": "cotangent",
    "sec": "secant", "csc": "cosecant", "arcsin": "arc sine", "arccos": "arc cosine",
    "arctan": "arc tangent",
}
# functions whose bracketed argument is read "of ...": sine of the quantity k x minus omega t
FUNCTIONS = set(TRIG.values())
# wrappers whose letters are words (\text{if}, \mathrm{Re}), not products of symbols
WORD_WRAPPERS = {"text", "textbf", "textit", "mathrm", "mathit", "mathsf", "operatorname"}
ACCENTS_SUFFIX = {  # decoration spoken after its argument
    "hat": "hat", "widehat": "hat", "bar": "bar", "overline": "bar",
    "dot": "dot", "ddot": "double dot", "tilde": "tilde",
}
SPACING = {",", ";", ":", "!", " ", "thinspace", "medspace", "thickspace"}
IGNORED = {"displaystyle", "limits", "nonumber", "quad", "qquad"}
TEXT_LIKE = {"mathrm", "mathbf", "mathit", "mathsf", "textbf", "textit", "text",
             "operatorname", "boldsymbol", "bm"}
UNIT_WRAPPERS = {"mathrm", "text", "operatorname"}  # only these try the unit grammar
FRACS = {"frac", "dfrac", "tfrac", "cfrac"}
SIZING = {"big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr"}
BRACKETS = {
    "(": ("open bracket", "close bracket"),
    ")": ("open bracket", "close bracket"),
    "[": ("open square bracket", "close square bracket"),
    "]": ("open square bracket", "close square bracket"),
    "{": ("open brace", "close brace"),
    "}": ("open brace", "close brace"),
    "|": ("open absolute value", "close absolute value"),
    "<": ("open angle bracket", "close angle bracket"),
    ">": ("open angle bracket", "close angle bracket"),
    "langle": ("open angle bracket", "close angle bracket"),
    "rangle": ("open angle bracket", "close angle bracket"),
    "lbrace": ("open brace", "close brace"),
    "rbrace": ("open brace", "close brace"),
    "lvert": ("open absolute value", "close absolute value"),
    "rvert": ("open absolute value", "close absolute value"),
    "Vert": ("open absolute value", "close absolute value"),
}
NO_PLURAL = {"hertz", "lux", "siemens", "kelvin"}

# units: symbol -> (singular, plural); the greedy matcher tries the longest symbol
UNITS = {
    "mol": ("mole", "moles"), "min": ("minute", "minutes"), "Hz": ("hertz", "hertz"),
    "Pa": ("pascal", "pascals"), "Wh": ("watt hour", "watt hours"),
    "eV": ("electronvolt", "electronvolts"), "Ohm": ("ohm", "ohms"),
    "bar": ("bar", "bars"), "rad": ("radian", "radians"),
    "m": ("metre", "metres"), "s": ("second", "seconds"), "g": ("gram", "grams"),
    "A": ("ampere", "amperes"), "V": ("volt", "volts"), "W": ("watt", "watts"),
    "J": ("joule", "joules"), "N": ("newton", "newtons"), "K": ("kelvin", "kelvin"),
    "L": ("litre", "litres"), "l": ("litre", "litres"), "h": ("hour", "hours"),
    "d": ("day", "days"), "T": ("tesla", "teslas"), "F": ("farad", "farads"),
    "H": ("henry", "henries"), "S": ("siemens", "siemens"), "C": ("coulomb", "coulombs"),
    "Bq": ("becquerel", "becquerels"), "Gy": ("gray", "grays"), "Sv": ("sievert", "sieverts"),
    "lm": ("lumen", "lumens"), "lx": ("lux", "lux"), "kat": ("katal", "katals"),
}
PREFIXES = {
    "f": "femto", "p": "pico", "n": "nano", "u": "micro", "m": "milli",
    "c": "centi", "d": "deci", "da": "deca", "h": "hecto", "k": "kilo",
    "M": "mega", "G": "giga", "T": "tera", "P": "peta",
}
# siunitx-style commands inside \si{...}
SI_PREFIX = {
    "femto": "femto", "pico": "pico", "nano": "nano", "micro": "micro",
    "milli": "milli", "centi": "centi", "deci": "deci", "deca": "deca",
    "hecto": "hecto", "kilo": "kilo", "mega": "mega", "giga": "giga",
    "tera": "tera",
}
SI_UNITS = {
    "metre": "metre", "meter": "metre", "second": "second", "gram": "gram",
    "ampere": "ampere", "volt": "volt", "watt": "watt", "joule": "joule",
    "newton": "newton", "pascal": "pascal", "kelvin": "kelvin", "hertz": "hertz",
    "ohm": "ohm", "mole": "mole", "litre": "litre", "liter": "litre",
    "hour": "hour", "minute": "minute", "bar": "bar", "tesla": "tesla",
    "farad": "farad", "henry": "henry",
}
RAW_CHARS = {"°": "degrees", "Ω": "ohms"}

_CMD_RE = re.compile(r"\\([A-Za-z]+)\*?|\\.")  # \name, \[, \\, \%, \,, ...
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")


# ---------------------------------------------------------------------------
# tokenizer

def _tokenize(s: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
        elif c == "\\":
            m = _CMD_RE.match(s, i)
            if not m:
                raise Unsupported("dangling backslash")
            v = m.group(1) if m.group(1) is not None else m.group(0)[1:]
            toks.append(("cmd", v))
            i = m.end()
        elif c == "{":
            toks.append(("open", c))
            i += 1
        elif c == "}":
            toks.append(("close", c))
            i += 1
        elif c == "[":
            toks.append(("osq", c))
            i += 1
        elif c == "]":
            toks.append(("csq", c))
            i += 1
        elif c == "^":
            toks.append(("sup", c))
            i += 1
        elif c == "_":
            toks.append(("sub", c))
            i += 1
        elif c in OPS:
            toks.append(("op", c))
            i += 1
        elif c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
            m = _NUM_RE.match(s, i)
            toks.append(("num", m.group(0)))
            i = m.end()
        elif c.isalpha() or c in RAW_CHARS:
            m = re.match(r"[A-Za-z]+|[°Ωµ]", s[i:])
            toks.append(("let", m.group(0)))
            i += m.end()
        elif c in ",;.":
            toks.append(("punct", c))
            i += 1
        elif c == "'":
            m = re.match(r"'+", s[i:])
            toks.append(("cmd", "prime" if m.end() == 1 else "dprime"))
            i += m.end()
        elif c == "!":
            toks.append(("fact", c))
            i += 1
        elif c == "&":
            toks.append(("amp", c))
            i += 1
        elif c == "|":
            toks.append(("bar", c))
            i += 1
        elif c in "()":
            toks.append(("del", c))
            i += 1
        else:
            raise Unsupported(f"character {c!r}")
    return toks


def _number_words(raw: str) -> list[str]:
    raw = raw.replace(",", "")
    if "." in raw:
        left, right = raw.split(".", 1)
        return [left or "0", "point", right]
    return [raw]


# ---------------------------------------------------------------------------
# parser

class _P:
    def __init__(self, toks: list[tuple[str, str]]):
        self.toks = toks
        self.i = 0
        self.abs_open = False  # alternating |...| state
        self.last: str | None = None  # last word emitted, for context (°C)
        self.vec_last = False  # the last atom was a vector: \cdot is a dot product
        self.integrals = 0  # integrals still waiting for their differential
        self.in_text = False  # inside \text{...}: letters are words, not products

    def peek(self) -> tuple[str, str] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> tuple[str, str]:
        t = self.peek()
        if t is None:
            raise Unsupported("unexpected end")
        self.i += 1
        return t

    def parse(self) -> list[str]:
        words = self.expr((), top=True)
        if self.peek() is not None:
            raise Unsupported("trailing input")
        if len(" ".join(w for w in words if w not in MARKS).split()) <= SHORT:
            # one breath: only the pauses that close a group stay
            words = [w for w in words if w not in (P2, P3)]
        return words

    @staticmethod
    def _is_quant(t: tuple[str, str] | None) -> int:
        """Whether an atom starting with this token is a quantity, so that two strong
        quantities in a row mean implicit multiplication (2x, m\\vec{a}). Greek
        letters, groups and differentials (dx) read naturally without a "times"."""
        if t is None:
            return 0
        kind, val = t
        if kind in ("num",):
            return 2
        if kind == "let":
            if re.fullmatch(r"d[A-Za-z]", val):  # dx, dt: a differential, not d*x
                return 1
            return 2
        if kind == "open":
            return 1
        if kind == "del":
            return 2 if val == "(" else 0
        if kind == "cmd":
            if val in GREEK or val in GREEK_CAP:
                return 1
            if val in ("sqrt", "vec", "si") or val in ACCENTS_SUFFIX or val in TEXT_LIKE:
                return 2
        return 0

    def expr(self, stops: tuple[str, ...], top: bool = False, quantity: bool = False,
             until: tuple[str, str] | None = None) -> list[str]:
        """A run of atoms. `top`: the whole expression (pauses between terms and before
        the relation); `quantity`: inside a bracketed group (a short pause between its
        terms); `until`: the token that closes the group (a bracket)."""
        words: list[str] = []
        prev_quant = 0
        while True:
            t = self.peek()
            if t is None or t[0] in stops or t[0] == "close" or t == until:
                return words
            quant = self._is_quant(t)
            vec = t[0] == "cmd" and t[1] in VECTORISH
            base = self.atom()
            sub = sup = None
            while True:
                t2 = self.peek()
                if t2 is None or t2[0] not in ("sub", "sup"):
                    break
                self.next()
                if t2[0] == "sub":
                    sub = self.script()
                else:
                    sup = self.script()
            added = self.attach(base, sub, sup)
            if added:
                head, prev = added[0], _last_word(words)
                if head in SIGNS and prev is not None and prev not in RELATIONS | SIGNS:
                    if top:  # a new term of this side
                        words.append(P2)
                    elif quantity and _term_len(words) >= 3:
                        words.append(P1)  # a long term in a group: a breath before the next
                elif head in RELATIONS or head == "and":
                    # the long pause, unless the side before it is a name (x =, E sub k =)
                    side = words[_last_index(words, P3) + 1:]
                    if top and len(" ".join(w for w in side if w not in MARKS).split()) > 3:
                        words.append(P3)
                elif _times_before(head, prev, quant, prev_quant):
                    words.append("times")  # implicit multiplication: 2x, m\vec{a}, rho (...)
                words += added
                self.last = _last_word(added) or self.last
                self.vec_last = vec
            prev_quant = quant

    def script(self) -> list[str]:
        """One sub/superscript argument: a group or a single symbol (x_0^2: the
        sup belongs to x, so the sub's argument must not swallow it)."""
        t = self.peek()
        if t is None:
            raise Unsupported("missing script")
        if t[0] == "open":
            self.next()
            words = self.expr(("close",))
            if self.peek() is None or self.next()[0] != "close":
                raise Unsupported("unbalanced brace")
            return words
        return self.atom()

    def arg(self) -> list[str]:
        """One argument: a braced group or a single atom with its own scripts."""
        t = self.peek()
        if t is None:
            raise Unsupported("missing argument")
        if t[0] == "open":
            self.next()
            words = self.expr(("close",))
            if self.peek() is None or self.next()[0] != "close":
                raise Unsupported("unbalanced brace")
            return words
        base = self.atom()
        sub = sup = None
        while True:
            t = self.peek()
            if t is None or t[0] not in ("sub", "sup"):
                break
            self.next()
            if t[0] == "sub":
                sub = self.script()
            else:
                sup = self.script()
        return self.attach(base, sub, sup)

    @staticmethod
    def attach(base: list[str], sub: list[str] | None, sup: list[str] | None) -> list[str]:
        if not base:  # a spacing atom carrying a script: 20\,^\circ C
            return list(sub or []) + list(sup or [])
        out = list(base)
        if sub is not None:
            out += ["sub"] + sub
        if sup is not None:
            if sup == ["degrees"]:
                out.append("degrees")
            elif sup == ["2"] and not base[0][:1].isdigit():
                out.append("squared")
            elif sup == ["3"] and not base[0][:1].isdigit():
                out.append("cubed")
            elif len(sup) == 1 and len(sup[0]) == 1 and sup[0].isalpha():
                out += ["to the", sup[0]]
            else:
                out += ["to the power of"] + sup
        return out

    def atom(self) -> list[str]:
        kind, val = self.next()
        if kind == "num":
            return _number_words(val)
        if kind == "let":
            if self.integrals and re.fullmatch(r"d[A-Za-z]", val):
                self.integrals -= 1
                return [P1, "d", val[1]]  # the integral's differential, after a breath
            if val in RAW_CHARS:
                return [RAW_CHARS[val]]
            if len(val) > 1 and val.isupper():
                return list(val)  # an acronym: OEE -> "O E E"
            if len(val) > 1 and val.islower() and not self.in_text:
                return list(val)  # a product of symbols: ac -> "a c", kx -> "k x"
            return [val]
        if kind == "punct":
            return [","] if val == "," else [val]
        if kind == "fact":
            return ["factorial"]
        if kind == "amp":
            return []  # an alignment column marker: nothing to say
        if kind == "bar":  # |x|: alternating absolute-value markers
            if not self.abs_open:
                self.abs_open = True
                return ["the absolute value of"]
            self.abs_open = False
            return []
        if kind == "del":  # a bare ( x ) group
            if val != "(":
                raise Unsupported("unbalanced bracket")
            before = self.last
            words = self.expr((), quantity=True, until=("del", ")"))
            if self.peek() != ("del", ")"):
                raise Unsupported("unbalanced bracket")
            self.next()
            return self.group("(", words, before)
        if kind == "osq":
            before = self.last
            words = self.expr(("csq",), quantity=True)
            if self.peek() is None or self.next()[0] != "csq":
                raise Unsupported("unbalanced bracket")
            return self.group("[", words, before)
        if kind == "op":
            if val in OPS:
                return [OPS[val]]
            raise Unsupported(f"operator {val!r}")
        if kind == "open":
            words = self.expr(("close",))
            if self.peek() is None or self.next()[0] != "close":
                raise Unsupported("unbalanced brace")
            return words
        if kind != "cmd":
            raise Unsupported(f"token {val!r}")
        return self.command(val)

    # -- commands -----------------------------------------------------------

    def command(self, name: str) -> list[str]:
        if name in SPACING or name in IGNORED or name in SIZING:
            return []
        if name in ("begin", "end"):
            env = "".join(self.arg()).replace("*", "")
            if env in ("aligned", "align", "gathered", "multline", "equation",
                       "displaymath", "math", "split"):
                return []  # the content between begin/end is parsed as usual
            raise Unsupported(f"environment {env!r}")
        if name == "\\":
            return ["and"]
        if name == "right":
            raise Unsupported("unbalanced \\right")
        if name == "left":
            d = self.next()[1]
            if d not in BRACKETS and d != ".":
                raise Unsupported(f"delimiter {d!r}")
            before = self.last
            words = self.expr((), quantity=True, until=("cmd", "right"))
            if self.peek() != ("cmd", "right"):
                raise Unsupported("unbalanced \\left")
            self.next()
            self.next()  # the closing delimiter
            return self.group(d, words, before)
        if name == "nabla":
            return self.nabla()
        if name in ("cdot", "times"):
            t = self.peek()
            if self.vec_last or (t is not None and t[0] == "cmd" and t[1] in VECTORISH):
                return ["dot" if name == "cdot" else "cross"]  # vectors: dot and cross products
            return ["times"]
        if name in GREEK:
            return [GREEK[name]]
        if name in GREEK_CAP:
            return [GREEK_CAP[name]]
        if name in FRACS:
            num = self.arg()
            den = self.arg()
            if (len(num) <= 2 and len(den) <= 2 and num and den
                    and (num[0] == "partial" or (num[0].startswith("d") and len(num[0]) <= 2))
                    and (den[0] == "partial" or (den[0].startswith("d") and len(den[0]) <= 2))
                    and all(w.isalpha() for w in num + den)):
                n = (list(num[0]) if len(num[0]) == 2 else [num[0]]) + num[1:]
                d = (list(den[0]) if len(den[0]) == 2 else [den[0]]) + den[1:]
                return n + ["by"] + d
            return self.fraction(num, den)
        if name == "sqrt":
            root = None
            if self.peek() is not None and self.peek()[0] == "osq":  # \sqrt[n]{...}
                self.next()
                root = " ".join(self.expr(("csq",)))
                if self.peek() is None or self.next()[0] != "csq":
                    raise Unsupported("unbalanced root index")
            words = self.arg()
            if len(words) > 2:
                words = words + [P1]  # a long radicand ends with a breath
            if root is None or root == "2":
                return ["the square root of"] + words
            if root == "3":
                return ["the cube root of"] + words
            return ["the", root + "th", "root of"] + words
        if name in ACCENTS_SUFFIX:
            return self.arg() + [ACCENTS_SUFFIX[name]]
        if name == "vec":
            return ["vector"] + self.arg()
        if name in TEXT_LIKE:
            self._unit_wrapper = name in UNIT_WRAPPERS
            was, self.in_text = self.in_text, name in WORD_WRAPPERS
            try:
                return self.text_like()
            finally:
                self.in_text = was
        if name in TRIG:
            return [TRIG[name]]
        if name in ("ln", "log"):
            if name == "ln":
                return ["the natural log of"]
            if self.peek() is not None and self.peek()[0] == "sub":  # \log_2
                self.next()
                return ["log base"] + self.script() + ["of"]
            return ["log of"]
        if name == "exp":
            return ["e to the power of"]
        if name == "lim":
            if self.peek() is not None and self.peek()[0] == "sub":
                self.next()
                cond = re.sub(r"\bto\b", "approaches", " ".join(self.script()))
                return ["the limit as", cond, "of"]
            return ["the limit of"]
        if name in ("int", "iint", "iiint", "sum", "prod"):
            lead = {"int": "the integral", "iint": "the double integral",
                    "iiint": "the triple integral", "sum": "the sum",
                    "prod": "the product"}[name]
            sub = sup = None
            while True:
                t = self.peek()
                if t is None or t[0] not in ("sub", "sup"):
                    break
                self.next()
                if t[0] == "sub":
                    sub = self.script()
                else:
                    sup = self.script()
            out = [lead]
            if name in ("int", "iint", "iiint"):
                self.integrals += 1
            if sub is not None and sup is not None:
                out += ["from"] + sub + ["to"] + sup + ["of"]
            elif sub is not None:
                out += ["over"] + sub + ["of"]
            elif name in ("int", "iint", "iiint") and sup is not None:
                out += ["up to"] + sup + ["of"]
            else:
                out.append("of")
            return out
        if name in ("min", "max"):
            return ["minimum"] if name == "min" else ["maximum"]
        if name == "binom":
            return self.arg() + ["choose"] + self.arg()
        if name == "pmod":
            return ["modulo"] + self.arg()
        if name == "si":
            t = self.peek()
            if t is None or t[0] != "open":
                raise Unsupported("\\si without braces")
            self.next()
            return self.units(group_end="close")
        if name == "tag":
            self.arg()
            return []
        if name == "prime":
            return ["prime"]
        if name == "dprime":
            return ["double prime"]
        if name in WORDS:
            return [WORDS[name]]
        raise Unsupported(f"\\{name}")

    # -- structure: groups, del, fractions ------------------------------------

    def group(self, delim: str, words: list[str], before: str | None) -> list[str]:
        """A bracketed group as a lecturer says it: "the quantity ..." with a breath at its
        end, "f of x" after a function's letter, the absolute value or the norm of, and an
        operator group such as (u . del) as it is."""
        plain = [w for w in words if w not in MARKS]
        if not plain:
            return []
        if delim in ("|", "lvert", "rvert", "vert"):
            return ["the absolute value of"] + words + [P1]
        if delim == "Vert":
            return ["the norm of"] + words + [P1]
        if delim in ("langle", "<"):
            return ["the mean of"] + words + [P1]
        if delim == "." or plain[-1] == "del":
            return words  # an invisible delimiter, or an operator: (u . del) u
        operators = SIGNS | RELATIONS | {"times", "dot", "cross"}
        if before in FUNCTIONS:  # sine of the quantity k x minus omega t
            return ["of"] + (["the quantity"] + words + [P1] if any(w in SIGNS for w in plain[1:])
                             else words)
        if (before is not None and len(before) == 1 and before.isalpha()
                and not any(w in operators for w in plain)):
            return ["of"] + words  # f(x), u(x, t)
        if len(plain) == 1 or (len(plain) == 2 and plain[0] in SIGNS):
            return words  # (x), (-1)
        return ["the quantity"] + words + [P1]

    def nabla(self) -> list[str]:
        """Del by what it does to what follows: the gradient, divergence, curl or Laplacian
        of it - or plain "del" where it is an operator itself (u . del)."""
        if self.last in ("dot", "cross"):
            return ["del"]
        t = self.peek()
        if t == ("sup", "^"):
            save = self.i
            self.next()
            if self.script() == ["2"] and self.peek() is not None:
                return ["the Laplacian of"]
            self.i = save
            return ["del"]
        if t == ("cmd", "cdot"):
            self.next()
            return ["the divergence of"]
        if t == ("cmd", "times"):
            self.next()
            return ["the curl of"]
        if t is not None and (t[0] in ("let", "open") or (t[0] == "cmd" and (
                t[1] in GREEK or t[1] in GREEK_CAP or t[1] in TEXT_LIKE or t[1] == "vec"))):
            return ["the gradient of"]
        return ["del"]

    @staticmethod
    def fraction(num: list[str], den: list[str]) -> list[str]:
        """one half; a over b; a plus b, all over c; the fraction ... over the quantity ..."""
        n = [w for w in num if w not in MARKS]
        d = [w for w in den if w not in MARKS]
        if not n or not d:
            raise Unsupported("empty fraction")
        if (" ".join(n), " ".join(d)) in NAMED_FRACTIONS:
            return [NAMED_FRACTIONS[(" ".join(n), " ".join(d))]]
        # the material derivative D u / D t
        if n[0] == "D" and len(d) == 1 and re.fullmatch(r"D[a-z]", d[0]):
            return ["D"] + [w for w in num[1:] if w != "times"] + ["by", "D", d[0][1]]
        compound = lambda ws: any(w in SIGNS for w in ws[1:])  # noqa: E731
        under = ["the quantity"] + den + [P1] if compound(d) else den
        if compound(n):
            return num + [P1, "all over"] + under
        if len(n) == 1 and len(d) == 1:
            return num + ["over"] + den
        return ["the fraction"] + num + ["over"] + under + ([] if compound(d) else [P1])

    # -- \mathrm / \text content: units if it looks like units, else text ----

    def text_like(self) -> list[str]:
        """\\mathrm / \\text / \\mathbf / ... content: units when the wrapper is one
        that carries units (\\mathrm{m/s^2}), otherwise the content itself
        (\\mathbf{u}, \\boldsymbol{\\tau}, \\text{if})."""
        t = self.peek()
        if self._unit_wrapper and t is not None and t[0] == "open":
            start = self.i
            self.next()  # the brace: group_tokens starts just past it
            inner = _P(self.group_tokens())
            inner.last = self.last  # so units() sees e.g. the "degrees" before °C
            try:
                words = inner.units(group_end=None)
                if inner.peek() is None:
                    return words
            except Unsupported:
                pass  # not units: read the content as ordinary math/text
            self.i = start + 1  # re-parse from just after the brace
            words = self.expr(("close",))
            if self.peek() is None or self.next()[0] != "close":
                raise Unsupported("unbalanced brace")
            return words
        return self.arg()

    def group_tokens(self) -> list[tuple[str, str]]:
        """The token list of one {...} group (self is just past the 'open')."""
        depth = 0
        out = []
        while True:
            t = self.next()
            if t[0] == "open":
                depth += 1
            elif t[0] == "close":
                if depth == 0:
                    return out
                depth -= 1
            out.append(t)

    # -- unit grammar --------------------------------------------------------

    def units(self, group_end: str | None) -> list[str]:
        """A unit expression; raises Unsupported if the content is not units."""
        words: list[str] = []
        unit_count = 0
        after_per = False
        pending_prefix: str | None = None
        first_unit = -1  # index into words of the first unit said
        while True:
            t = self.peek()
            if t is None:
                if group_end is not None:
                    raise Unsupported("unbalanced units")
                break
            if group_end is not None and t[0] == group_end:
                break
            if t[0] == "cmd" and t[1] in SPACING:
                self.next()  # \, \; ... between units
            elif t[0] == "num":
                self.next()
                words += _number_words(t[1])
            elif t[0] == "let" and t[1].isalpha():
                self.next()
                found = self._unit_run(t[1])
                if first_unit < 0:
                    first_unit = len(words)
                for prefix, sing, plur in found:
                    if sing == "coulomb" and self.last == "degrees":
                        word = "Celsius"  # 20^\circ\mathrm{C}
                    else:
                        word = (prefix or "") + \
                            (sing if after_per or unit_count == 0 else plur)
                    pending_prefix = None
                    words.append(word)
                    unit_count += 1
                    after_per = False
            elif t[0] == "cmd" and t[1] in SI_PREFIX:
                self.next()
                pending_prefix = SI_PREFIX[t[1]]
            elif t[0] == "cmd" and t[1] in SI_UNITS:
                self.next()
                if first_unit < 0:
                    first_unit = len(words)
                sing = SI_UNITS[t[1]]
                words.append((pending_prefix or "") +
                             (sing if after_per or unit_count == 0 else _plural(sing)))
                pending_prefix = None
                unit_count += 1
                after_per = False
            elif t == ("op", "/") or t == ("cmd", "per"):
                self.next()
                words.append("per")
                after_per = True
            elif t == ("cmd", "squared") or t == ("cmd", "cubed"):
                self.next()
                if unit_count == 0:
                    raise Unsupported("dangling squared")
                words.append(t[1])
            elif t[0] == "sup":
                self.next()
                n = self._signed_number()
                if unit_count == 0:
                    raise Unsupported("dangling exponent")
                if n < 0:
                    words.insert(len(words) - 1, "per")
                    n = -n
                words.append({2: "squared", 3: "cubed"}.get(n, "to the " + str(n)))
            else:
                raise Unsupported("not units")
        if unit_count == 0:
            raise Unsupported("empty units")
        if first_unit >= 0 and words[first_unit] != "per" and (
                unit_count == 1 or first_unit + 1 < len(words)
                and words[first_unit + 1] == "per"):
            # "5 metres", "metres per second" - but "newton metres", "mole per second"
            words[first_unit] = _plural(words[first_unit])
        if group_end is not None:
            self.next()  # consume the closing brace
        return words

    def _signed_number(self) -> int:
        sign = 1
        if self.peek() == ("op", "-"):
            self.next()
            sign = -1
        kind, val = self.next()
        if kind == "open":
            kind, val = self.next()
            if self.next()[0] != "close":
                raise Unsupported("bad unit exponent")
        if kind != "num" or not val.isdigit():
            raise Unsupported("bad unit exponent")
        return sign * int(val)

    @staticmethod
    def _unit_run(s: str) -> list[tuple[str | None, str, str]]:
        """A letter run like 'km' or 'Nms' -> [(prefix, singular, plural), ...]."""
        out: list[tuple[str | None, str, str]] = []
        i = 0
        while i < len(s):
            found = None
            for plen in (2, 1):  # prefix + unit first, so 'mm' is millimetres
                p = PREFIXES.get(s[i:i + plen])
                if not p:
                    continue
                for ulen in (3, 2, 1):
                    u = UNITS.get(s[i + plen:i + plen + ulen])
                    if u:
                        found = (p, u[0], u[1])
                        i += plen + ulen
                        break
                if found:
                    break
            if not found:
                for ulen in (3, 2, 1):
                    u = UNITS.get(s[i:i + ulen])
                    if u:
                        found = (None, u[0], u[1])
                        i += ulen
                        break
            if not found:
                raise Unsupported(f"unknown unit {s[i:]!r}")
            out.append(found)
        return out


def _plural(word: str) -> str:
    parts = word.split(" ")
    base = parts[-1]
    if base.endswith("s") or base in NO_PLURAL:
        return word
    parts[-1] = base + "s"
    return " ".join(parts)


def _term_len(words: list[str]) -> int:
    """How many words the current term has: back to the last sign or pause."""
    n = 0
    for w in reversed(words):
        if w in MARKS or w in SIGNS:
            break
        n += len(w.split())
    return n


def _last_index(words: list[str], w: str) -> int:
    return max((i for i, x in enumerate(words) if x == w), default=-1)


def _last_word(words: list[str]) -> str | None:
    return next((w for w in reversed(words) if w not in MARKS), None)


# words after which a quantity is not multiplied: an operator or an "of" is waiting for it
_AWAITING = RELATIONS | SIGNS | {"times", "dot", "cross", "over", "all over", "by", "and",
                                 ",", "to", "from", "sub", "to the", "to the power of", "del"}


def _times_before(head: str, prev: str | None, quant: int, prev_quant: int) -> bool:
    """Whether to say "times" before an atom starting with `head`."""
    if prev is None or prev in _AWAITING or prev.endswith(" of") or head == "of":
        return False
    if head == "the quantity" or head in NABLA_OF:
        return True  # rho times the quantity ..., mu times the Laplacian of u
    # a lecturer says "m v squared", "2 pi f", "4 a c": "times" only between two numbers
    return quant == 2 and prev_quant == 2 and prev[:1].isdigit() and head[:1].isdigit()


def _tidy(words: list[str], marks: bool = False) -> str:
    """The words as a string. Marks: the stronger of two in a row, none at either end, a
    comma beside one absorbed; without `marks` each is written as a comma."""
    out: list[str] = []
    for w in words:
        if w in MARKS:
            if not out:
                continue
            if out[-1] in MARKS:
                out[-1] = max(out[-1], w)
            elif out[-1] == ",":
                out[-1] = w
            else:
                out.append(w)
        elif w == "," and out and out[-1] in MARKS:
            continue
        else:
            out.append(w)
    while out and out[-1] in MARKS:
        out.pop()
    if not marks:
        out = ["," if w in MARKS else w for w in out]
    s = " ".join(out)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",(\S)", r", \1", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _words(latex: str) -> list[str]:
    words = _P(_tokenize(latex)).parse()
    if not [w for w in words if w not in MARKS]:
        raise Unsupported("empty expression")
    return words


def verbalize(latex: str) -> str:
    """A LaTeX expression as words, its pauses written as commas. Raises Unsupported if
    it cannot be said."""
    return _tidy(_words(latex))


def verbalize_marked(latex: str) -> str:
    """The same words with the pause marks P1 < P2 < P3 kept, for the voice
    (tts.prosody renders them)."""
    return _tidy(_words(latex), marks=True)
