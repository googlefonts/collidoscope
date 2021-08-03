# collidoscope - brute force detection of glyph collisions

`collidoscope` reports on situations where paths overlap in a shaped
piece of text. For example, the sequence "ؼجب" might cause a collision like so:

![](sample-collision.png)

This software tries every combination of glyphs within a specified Unicode range and up to a specified length of string and outputs a report of all situations where the glyphs collide. It has a number of collision tests:

* Paths in non-adjacent glyphs are never allowed to collide.
* If the *cursive* test is turned on, then paths with a cursive attachment anchor are allowed to overlap with paths in an adjacent glyph which also contain a cursive attachment anchor, but are *not* allowed to overlap with a path *without* a cursive attachment anchor.
* If the *area* test is turned on, then paths in adjacent glyphs may collide so long as the area of overlap does not exceed a given percentage of the smallest path's area. i.e. if the area percentage is set to 25%, then two strokes may *connect*, because the overlap is likely to be quite small compared to the size of the paths involved. But if a stroke significantly overlaps a nukta, it will be reported as a collision. (Of course, this will not detect strokes which merely graze a nukta.)

Depending on the length of the string and the number of glyphs tested, this may take a *very* long time.

## Command Line Usage

To use it:

    python3 -m collidoscope -r 0620-064A yourfont.otf

This creates a collision report on `report.html` for all sequences of three characters within the range 0x620 to 0x64A.

    python3 -m collidoscope -r 0620-064A,0679-06D3 -area 10 yourfont.otf

This creates a collision report on `report.html` for all sequences of three characters within the range 0x620 to 0x64A and also 0x679 to 0x6D3, and turns on the area test at a tolerance of 10% of the area of the smallest path involved in collision.

    python3 -m collidoscope -c 5 --cursive yourfont.otf

This tests for non-adjacent glyphs and collisions not involving cursive connection for *all combinations of glyphs in your font* with a five-character string. This may take a number of years to compute.

    python3 -m collidoscope -c 2 -r 0620-064A --area 5 yourfont.otf

This just runs an area test for two-character sequences across the basic Arabic range.

## Library Usage

```python
class Collidoscope()
```

Detect collisions between font glyphs

<a name="collidoscope.Collidoscope.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(fontfilename, rules, direction="LTR", ttFont=None)
```

Create a collision detector.

The rules dictionary may contain the following entries:

* faraway (boolean): If true, non-adjacent base glyphs are tested for
overlap. Mark glyphs are ignored. All collisions are reported.
* marks (boolean): If true, collisions between all pairs of marks in
the string are reported.
* bases (boolean): If *false*, collisions between all pairs of bases in
the string are *ignored*.
* cursive (boolean): If true, adjacent glyphs are tested for overlap.
Paths containing cursive anchors are allowed to overlap, but
collisions between other paths are reported.
* area (float): If provided, adjacent glyphs are tested for overlap.
Collisions are reported if the intersection area is greater than
the given proportion of the smallest path. (i.e. where cursive
connection anchors are not used in an Arabic font, you may wish
to ignore collisions if the overlaid area is less than 5% of the
smallest path, because this is likely to be the connection point
between the glyphs. But collisions affecting more than 5% of the
glyph will be reported.)

**Arguments**:

- `fontfilename` - file name of font.
- `rules` - dictionary of collision rules.
- `ttFont` - fontTools object (loaded from file if not given).
- `direction` - "LTR" or "RTL"

<a name="collidoscope.Collidoscope.get_glyphs"></a>
#### get\_glyphs

```python
 | get_glyphs(text)
```

Returns an list of dictionaries representing a shaped string.

This is the first step in collision detection; the dictionaries
returned can be fed to ``draw_overlaps`` and ``has_collisions``.

<a name="collidoscope.Collidoscope.draw_overlaps"></a>
#### draw\_overlaps

```python
 | draw_overlaps(glyphs, collisions, attribs="")
```

Return an SVG string displaying the collisions.

**Arguments**:

- `glyphs` - A list of glyphs dictionaries.
- `collisions` - A list of Collision objects.
- `attribs` - String of attributes added to SVG header.

<a name="collidoscope.Collidoscope.has_collisions"></a>
#### has\_collisions

```python
 | has_collisions(glyphs_in)
```

Run the collision detection algorithm according to the rules provided.

Note that this does not find *all* overlaps, but returns as soon
as some collisions are found.

**Arguments**:

- `glyphs` - A list of glyph dictionaries returned by ``get_glyphs``.
  
- `Returns` - A list of Collision objects.


## Requirements

This requires some Python modules to be installed. You can install them like so:

    pip3 install -r example-requirements.txt
