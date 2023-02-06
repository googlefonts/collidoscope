from collidoscope import Collidoscope
from collidoscope.babelfont import Collidoscope as BabelfontCollidoscope
from pathlib import Path
from kurbopy import Point


DATADIR = Path(__file__).parent / "data"


def test_binary():
    font = DATADIR / "Nunito-Subset.ttf"
    c = Collidoscope(font, rules={"bases": True})
    glyphs = c.get_glyphs("aa")
    assert not c.has_collisions(glyphs)
    glyphs = c.get_glyphs("ïï")
    assert c.has_collisions(glyphs)


def test_variations():
    font = DATADIR / "Nunito-Subset.ttf"
    c = Collidoscope(font, rules={"bases": True})
    glyphs = c.get_glyphs("Ưï")
    assert not c.has_collisions(glyphs)

    c = Collidoscope(font, rules={"bases": True}, location={"wght": 1000})
    glyphs = c.get_glyphs("Ưï")
    assert c.has_collisions(glyphs)


def test_rules():
    font = DATADIR / "Nunito-Subset.ttf"
    c = Collidoscope(font, rules={"bases": False})
    glyphs = c.get_glyphs("ïï")
    assert not c.has_collisions(glyphs)

    c = Collidoscope(font, rules={"bases": True, "area": 0.05})
    glyphs = c.get_glyphs("ïï")
    assert c.has_collisions(glyphs)

    c = Collidoscope(font, rules={"bases": True, "area": 0.5})
    glyphs = c.get_glyphs("ïï")
    assert not c.has_collisions(glyphs)
