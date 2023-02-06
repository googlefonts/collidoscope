from collidoscope.babelfont import Collidoscope
from pathlib import Path
from kurbopy import Point


DATADIR = Path(__file__).parent / "data"

def test_glyphs():
    font = DATADIR / "Nunito.glyphs"
    c = Collidoscope(font, rules={"bases": True})
    glyphs = [
        c.get_positioned_glyph("a", Point(0, 0)),
        c.get_positioned_glyph("a", Point(514, 0)),
    ]
    assert not c.has_collisions(glyphs)
    glyphs = [
        c.get_positioned_glyph("idieresis", Point(0, 0)),
        c.get_positioned_glyph("idieresis", Point(212, 0)),
    ]
    assert c.has_collisions(glyphs)


def test_masters():
    font = DATADIR / "Nunito.glyphs"
    c = Collidoscope(font, rules={"bases": True})
    glyphs = [
        c.get_positioned_glyph("Uhorn", Point(0, 0)),
        c.get_positioned_glyph("idieresis", Point(720, 0)),
    ]
    assert not c.has_collisions(glyphs)

    c = Collidoscope(font, rules={"bases": True}, master="Bold")
    glyphs = [
        c.get_positioned_glyph("Uhorn", Point(0, 0)),
        c.get_positioned_glyph("idieresis", Point(738, 0)),
    ]
    assert c.has_collisions(glyphs)
