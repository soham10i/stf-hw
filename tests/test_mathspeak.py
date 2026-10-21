"""Golden tests for services/api/mathspeak.py - LaTeX as spoken words."""

import pytest

from services.api import mathspeak
from services.api.tts import speakable

CASES = [
    # numbers
    ("3.5", "3 point 5"),
    ("-12", "minus 12"),
    ("1{,}000", "1, 000"),
    # letters, acronyms, Greek
    ("x", "x"),
    ("OEE", "O E E"),
    ("\\eta = 0.9", "eta equals 0 point 9"),
    ("\\omega = 2\\pi f", "omega equals 2 pi f"),
    ("\\Delta t", "capital delta t"),
    # operators and relations
    ("a \\cdot b", "a times b"),
    ("a \\times 10^3", "a times 10 to the power of 3"),
    ("x \\leq 5", "x is less than or equal to 5"),
    ("F \\propto a", "F is proportional to a"),
    # fractions
    ("\\frac{1}{2}", "one half"),
    ("\\frac{3}{4}", "three quarters"),
    ("\\frac{a}{b}", "a over b"),
    ("\\dfrac{a+b}{c}", "a plus b, all over c"),
    ("\\frac{1}{a+b}", "the fraction 1 over the quantity a plus b"),
    ("\\frac{dy}{dx}", "d y by d x"),
    ("\\frac{\\partial f}{\\partial x}", "partial f by partial x"),
    # scripts
    ("x^2", "x squared"),
    ("x^3", "x cubed"),
    ("v^2", "v squared"),
    ("e^x", "e to the x"),
    ("x_i", "x sub i"),
    ("v_0^2", "v sub 0 squared"),
    ("x^{n+1}", "x to the power of n plus 1"),
    # radicals
    ("\\sqrt{x}", "the square root of x"),
    ("\\sqrt[3]{x}", "the cube root of x"),
    ("\\sqrt[5]{32}", "the 5th root of 32"),
    # functions and calculus
    ("\\sin x", "sine x"),
    ("\\ln x", "the natural log of x"),
    ("\\log_2 8", "log base 2 of 8"),
    ("\\frac{dE}{dt} = P", "d E by d t equals P"),
    ("\\int_0^1 x^2 dx", "the integral from 0 to 1 of x squared, d x"),
    ("\\sum_{i=1}^{n} x_i", "the sum from i equals 1 to n of x sub i"),
    ("\\lim_{x \\to 0} \\frac{\\sin x}{x}", "the limit as x approaches 0 of "
     "the fraction sine x over x"),
    # physics decoration
    ("\\vec{F} = m\\vec{a}", "vector F equals m vector a"),
    ("\\dot{x}", "x dot"),
    ("\\ddot{x} + \\omega^2 x = 0", "x double dot plus omega squared x equals 0"),
    ("\\hat{n}", "n hat"),
    ("\\bar{x}", "x bar"),
    # brackets and absolute value
    ("\\left( a + b \\right)^2", "the quantity a plus b, squared"),
    ("(a+b)(a-b)", "the quantity a plus b, times the quantity a minus b"),
    ("|x|", "the absolute value of x"),
    # units in \\mathrm / \\text
    ("\\mathrm{m}", "metres"),
    ("\\text{kg}", "kilograms"),
    ("\\mathrm{m/s^2}", "metres per second squared"),
    ("\\mathrm{km/h}", "kilometres per hour"),
    ("\\mathrm{N}", "newtons"),
    ("\\mathrm{N\\,m}", "newton metres"),
    ("\\mathrm{Pa}", "pascals"),
    ("\\mathrm{5\\,kWh}", "5 kilowatt hours"),
    ("\\si{\\kilo\\gram\\per\\second}", "kilograms per second"),
    ("90^\\circ", "90 degrees"),
    ("20\\,^\\circ\\mathrm{C}", "20 degrees Celsius"),
    # misc
    ("n!", "n factorial"),
    ("a \\to b", "a to b"),
    ("x' ", "x prime"),
    # Navier-Stokes momentum balance forms
    ("\\rho \\left( \\frac{\\partial \\mathbf{u}}{\\partial t} + \\mathbf{u} \\cdot "
     "\\nabla \\mathbf{u} \\right) = -\\nabla p + \\mu \\nabla^2 \\mathbf{u} + "
     "\\mathbf{f}",
     "rho times the quantity partial u by partial t, plus u dot del u, "
     "equals minus the gradient of p, plus mu times the Laplacian of u, plus f"),
    # the form in the copilot's answer: (u . del) u, and a body force rho f
    ("\\rho\\left(\\frac{\\partial \\mathbf{u}}{\\partial t} + (\\mathbf{u}\\cdot\\nabla)"
     "\\mathbf{u}\\right) = -\\nabla p + \\mu\\nabla^2\\mathbf{u} + \\rho\\mathbf{f}",
     "rho times the quantity partial u by partial t, plus u dot del u, "
     "equals minus the gradient of p, plus mu times the Laplacian of u, plus rho f"),
    ("\\rho \\left( \\frac{\\partial \\mathbf{v}}{\\partial t} + \\mathbf{v} \\cdot "
     "\\nabla \\mathbf{v} \\right) = -\\nabla p + \\nabla \\cdot \\boldsymbol{\\tau} "
     "+ \\rho \\mathbf{g}",
     "rho times the quantity partial v by partial t, plus v dot del v, "
     "equals minus the gradient of p, plus the divergence of tau, plus rho g"),
    ("\\rho \\frac{D\\vec{u}}{Dt} = -\\nabla p + \\nabla \\cdot "
     "\\boldsymbol{\\tau}_{ij} + \\rho \\vec{g}",
     "rho D vector u by D t, equals minus the gradient of p, plus the divergence of "
     "tau sub i j, plus rho vector g"),
    # structure by name: functions, products of symbols, del's operators
    ("u(x,t) = A\\sin(kx - \\omega t)",
     "u of x, t, equals A sine of the quantity k x minus omega t"),
    ("x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}",
     "x equals minus b plus or minus the square root of b squared minus 4 a c, all over 2 a"),
    ("\\nabla \\times \\mathbf{B} = \\mu_0 \\mathbf{J}", "the curl of B equals mu sub 0 J"),
    ("\\mathbf{a} \\cdot \\mathbf{b}", "a dot b"),
    ("\\text{if } x > 0", "if x is greater than 0"),
]


@pytest.mark.parametrize("latex,expected", CASES)
def test_verbalize(latex, expected):
    assert mathspeak.verbalize(latex) == expected


def test_matrix_falls_back():
    with pytest.raises(mathspeak.Unsupported):
        mathspeak.verbalize("\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}")


def test_unknown_macro_falls_back():
    with pytest.raises(mathspeak.Unsupported):
        mathspeak.verbalize("\\qubit{x}")


def test_speakable_verbalizes_math_end_to_end():
    md = ("Kinetic energy is $$E_k = \\frac{1}{2} m v^2$$ and the frequency is "
          "$\\omega = 2\\pi f$.")
    s = speakable(md)
    assert "one half m v squared" in s
    assert "omega equals 2 pi f" in s
    assert "$" not in s and "\\frac" not in s


def test_speakable_keeps_formula_word_for_unsupported_math():
    md = "The matrix $$\\begin{pmatrix} 1 & 2 \\end{pmatrix}$$ is singular."
    s = speakable(md)
    assert "(formula)" in s
    assert "is singular" in s


def test_marked_keeps_the_hierarchy_for_the_voice():
    """The pauses as marks: the long one before the relation, the medium ones between
    terms, the short one closing a group - and a short expression in one breath."""
    ns = ("\\rho\\left(\\frac{\\partial \\mathbf{u}}{\\partial t} + (\\mathbf{u}\\cdot\\nabla)"
          "\\mathbf{u}\\right) = -\\nabla p + \\mu\\nabla^2\\mathbf{u} + \\rho\\mathbf{f}")
    m = mathspeak.verbalize_marked(ns)
    P1, P2, P3 = mathspeak.P1, mathspeak.P2, mathspeak.P3
    assert m.index(P1) < m.index(P3) < m.index(P2)
    assert m.count(P3) == 1 and m.count(P2) == 2
    assert P3 + " equals" in m
    assert all(p not in mathspeak.verbalize_marked("E = mc^2") for p in (P1, P2, P3))
