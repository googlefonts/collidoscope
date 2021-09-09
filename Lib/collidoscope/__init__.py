import uharfbuzz as hb
import re
from pathlib import Path
from fontTools.ttLib import TTFont
from beziers.path import BezierPath
from beziers.path.geometricshapes import Rectangle
from beziers.utils.linesweep import bbox_intersections
from beziers.point import Point
from beziers.boundingbox import BoundingBox
from glyphtools import categorize_glyph, get_beziers
import glyphtools
import sys
from typing import NamedTuple


class Collision(NamedTuple):
    glyph1: str
    glyph2: str
    path1: BezierPath
    path2: BezierPath
    point: Point


def _get_sequential_cluster_ids(glyphs):
    cur_cluster = None
    sci = 0  # sequential cluster ID
    scis = []
    for g in glyphs:
        if g["cluster"] != cur_cluster:
            sci += 1
            cur_cluster = g["cluster"]
        scis.append(sci)
    return scis


_KNOWN_RULES = ["faraway", "marks", "adjacent_clusters", "cursive", "area"]


class Collidoscope:
    """Detect collisions between font glyphs"""

    def __init__(self, fontfilename, rules, direction="LTR", ttFont=None, scale_factor=1.0):
        """Create a collision detector.

        The rules dictionary may contain the following entries:
            faraway (boolean): If true, non-adjacent base glyphs are tested for
                overlap. Mark glyphs are ignored. All collisions are reported.
            marks (boolean): If true, collisions between all pairs of marks in
                the string are reported.
            bases (boolean): If *false*, collisions between all pairs of bases in
                the string are *ignored*.
            adjacent_clusters (boolean): If true, collisions between all pairs 
                of glyphs in adjacent clusters are reported.
            cursive (boolean): If true, adjacent glyphs are tested for overlap.
                Paths containing cursive anchors are allowed to overlap, but
                collisions between other paths are reported.
            area (float): If provided, adjacent glyphs are tested for overlap.
                Collisions are reported if the intersection area is greater than
                the given proportion of the smallest path. (i.e. where cursive
                connection anchors are not used in an Arabic font, you may wish
                to ignore collisions if the overlaid area is less than 5% of the
                smallest path, because this is likely to be the connection point
                between the glyphs. But collisions affecting more than 5% of the
                glyph will be reported.)

        Args:
            fontfilename: file name of font.
            rules: dictionary of collision rules.
            ttFont: fontTools object (loaded from file if not given).
            direction: "LTR" or "RTL"
            scale_factor: Outlines are scaled by this factor before comparison.
        """
        self.fontfilename = fontfilename
        self.glyphcache = {}
        self.direction = direction
        self.fontbinary = None
        self.scale_factor = scale_factor
        if ttFont:
            self.font = ttFont
            if not glyphtools.babelfont.isbabelfont(ttFont):
                self.fontbinary = ttFont.reader.file.read()
        else:
            self.fontbinary = Path(fontfilename).read_bytes()
            self.font = TTFont(fontfilename)
        self.rules = rules
        if self.fontbinary:
            self.prep_shaper()
        if "cursive" in self.rules and self.rules["cursive"]:
            self.get_anchors()
        else:
            self.anchors = {}

    def get_rules(self):
        """Return all rules that are known.

        This can be used to implement a kind of versioning of the interface
        to collidoscope.

        E.g. if the client wants to be sure that it is running against a
        version of collidoscope with the new adjacent_clusters rule,
        the client can just make sure that the adjacent_clusters rule gets
        "echoed back" or "acknowledged" by this routine.

        In practice, just the existence of this routine accomplishes the
        same version-detection for this particular adjacent_clusters feature.

        Alternately, we could use whatever the real/official mechanism is
        for versioning a Python module, presumably a 3-integer dotted SemVer?

        Version: 0.0.6 in collidoscope.egg-info/PKG-INFO?

        But this routine provides something perhaps useful beyond versioning:
        it can be used to make sure that the rules passed in don't have a typo
        in them.

        One might imagine enforcing all this in the constructor, e.g.
        throwing an exception if an unknown rule is passed in.

        But that would prevent a more gentle "use this rule if you have it"
        semantics for some future rule.
        """
        return {rk: rv for rk, rv in self.rules.items() if rk in _KNOWN_RULES}

    def prep_shaper(self):
        face = hb.Face(self.fontbinary)
        font = hb.Font(face)
        upem = face.upem
        font.scale = (upem, upem)
        hb.ot_font_set_funcs(font)
        self.hbfont = font

    def shape_a_text(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hbfont, buf)
        self.direction = buf.direction
        return buf

    def bb2path(bb):
        vec = bb.tr - bb.bl
        return Rectangle(vec.x, vec.y, origin=bb.bl + vec * 0.5)

    def get_anchors(self):
        # Find the GPOS CursiveAttachment lookups
        cursives = filter(
            lambda x: x.LookupType == 3, self.font["GPOS"].table.LookupList.Lookup
        )
        anchors = {}
        for c in cursives:
            for s in c.SubTable:
                for glyph, record in zip(s.Coverage.glyphs, s.EntryExitRecord):
                    anchors[glyph] = []
                    if record.EntryAnchor:
                        anchors[glyph].append(
                            (
                                record.EntryAnchor.XCoordinate,
                                record.EntryAnchor.YCoordinate,
                            )
                        )
                    if record.ExitAnchor:
                        anchors[glyph].append(
                            (
                                record.ExitAnchor.XCoordinate,
                                record.ExitAnchor.YCoordinate,
                            )
                        )
        self.anchors = anchors

    def scale_path(self, p, centroid):
        if self.scale_factor == 1.0:
            return p
        p.translate(centroid * -1)
        p.scale(self.scale_factor)
        p.translate(centroid)
        return p

    def get_cached_glyph(self, name):
        if name in self.glyphcache:
            return self.glyphcache[name]
        paths = get_beziers(self.font, name)
        pathbounds = []
        paths = list(filter(lambda p: p.length > 0, paths))

        # First find pre-scale centroid
        glyphbounds = BoundingBox()
        for p in paths:
            glyphbounds.extend(p.bounds())

        paths = [self.scale_path(p, glyphbounds.centroid) for p in paths]

        for p in paths:
            p.hasAnchor = False
            p.glyphname = name
            if name in self.anchors:
                for a in self.anchors[name]:
                    if p.pointIsInside(Point(*a)):
                        p.hasAnchor = True
            bounds = p.bounds()
            pathbounds.append(bounds)

        glyphbounds = BoundingBox()
        if pathbounds:
            for p in pathbounds:
                glyphbounds.extend(p)
        else:
            glyphbounds.tr = Point(0, 0)
            glyphbounds.bl = Point(0, 0)
        self.glyphcache[name] = {
            "name": name,
            "paths": paths,
            "pathbounds": pathbounds,
            "glyphbounds": glyphbounds,
            "category": categorize_glyph(self.font, name)[0],
            "pathconvexhull": None,  # XXX
        }
        assert len(self.glyphcache[name]["pathbounds"]) == len(
            self.glyphcache[name]["paths"]
        )
        return self.glyphcache[name]

    def get_positioned_glyph(self, name, pos):
        g = self.get_cached_glyph(name)
        positioned = {
            "name": g["name"],
            "paths": [p.clone().translate(pos) for p in g["paths"]],
            "pathbounds": [b.translated(pos) for b in g["pathbounds"]],
            "glyphbounds": g["glyphbounds"].translated(pos),
            "category": g["category"],
        }
        assert len(positioned["pathbounds"]) == len(positioned["paths"])
        # Copy path info
        for old, new in zip(g["paths"], positioned["paths"]):
            new.hasAnchor = old.hasAnchor
            new.glyphname = old.glyphname
        return positioned

    def find_overlaps(self, g1, g2):
        # print("Testing %s against %s" % (g1["name"], g2["name"]))
        if not (g1["glyphbounds"].overlaps(g2["glyphbounds"])):
            return []
        # print("Glyph bounds overlap")

        overlappingPathBounds = bbox_intersections(g1["paths"], g2["paths"])

        if not overlappingPathBounds:
            return []

        overlappingPaths = {}
        for p1, p2 in overlappingPathBounds:
            left_segs = p1.asSegments()
            right_segs = p2.asSegments()
            overlappingSegBounds = bbox_intersections(left_segs, right_segs)
            for s1, s2 in overlappingSegBounds:
                intersects = s1.intersections(s2)
                if len(intersects) > 0:
                    overlappingPaths[(p1, p2)] = Collision(
                        glyph1=g1["name"],
                        glyph2=g2["name"],
                        path1=p1,
                        path2=p2,
                        point=intersects[0].point,
                    )
        return list(overlappingPaths.values())

    def get_glyphs(self, text, buf=None):
        """Returns an list of dictionaries representing a shaped string.

        Args:
            text: text to check
            buf: (Optional) already shaped uharfbuzz buffer.

        This is the first step in collision detection; the dictionaries
        returned can be fed to ``draw_overlaps`` and ``has_collisions``."""
        if not buf:
            buf = self.shape_a_text(text)
        glyf = self.font["glyf"]
        cursor = 0
        glyphs = []
        ix = 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            position = Point(cursor + pos.position[0], pos.position[1])

            name = glyf.getGlyphName(info.codepoint)
            g = self.get_positioned_glyph(name, position)
            g["cluster"] = info.cluster
            glyphs.append(g)
            ix = ix + 1
            cursor = cursor + pos.position[2]
        return glyphs

    def draw_overlaps(self, glyphs, collisions, attribs=""):
        """Return an SVG string displaying the collisions.

        Args:
            glyphs: A list of glyphs dictionaries.
            collisions: A list of Collision objects.
            attribs: String of attributes added to SVG header.
        """
        svgpaths = []
        bbox = glyphs[0]["glyphbounds"]
        col = ["green", "red", "purple", "blue", "yellow"]
        for ix, g in enumerate(glyphs):
            bbox.extend(g["glyphbounds"])
            for p in g["paths"]:
                svgpaths.append(
                    '<path d="%s" fill="%s"/>' % (p.asSVGPath(), col[ix % len(col)])
                )
        for c in collisions:
            intersect = c.path1.intersection(c.path2)
            for i in intersect:
                svgpaths.append('<path d="%s" fill="black"/>' % (i.asSVGPath()))
        return '<svg %s viewBox="%i %i %i %i">%s</svg>\n' % (
            attribs,
            bbox.left,
            bbox.bottom,
            bbox.width,
            bbox.height,
            "\n".join(svgpaths),
        )

    def has_collisions(self, glyphs_in):
        """Run the collision detection algorithm according to the rules provided.

        Note that this does not find *all* overlaps, but returns as soon
        as some collisions are found.

        Args:
            glyphs: A list of glyph dictionaries returned by ``get_glyphs``.

        Returns: A list of Collision objects.
        """
        # Rules for collision detection:
        #   "Far away" (adjacency > 1) glyphs should not interact at all
        # print("Faraway test")
        glyphs = glyphs_in
        if self.direction == "RTL":
            glyphs = list(reversed(glyphs))
        if "faraway" in self.rules:
            for firstIx, first in enumerate(glyphs):
                nonAdjacent = firstIx + 1
                # print("Considering %i" % firstIx)
                if first["category"] == "base":
                    # Skip mark and next base
                    while (
                        nonAdjacent < len(glyphs)
                        and glyphs[nonAdjacent]["category"] == "mark"
                    ):
                        nonAdjacent = nonAdjacent + 1
                    nonAdjacent = nonAdjacent + 1
                if nonAdjacent >= len(glyphs):
                    continue

                for secondIx in range(nonAdjacent, len(glyphs)):
                    second = glyphs[secondIx]
                    if (
                        first["category"] == "base"
                        and second["category"] == "base"
                        and not self.rules.get("bases", True)
                    ):
                        continue

                    # print("Faraway test %s %s" % (first["name"], second["name"]))
                    overlaps = self.find_overlaps(first, second)
                    if overlaps:
                        return overlaps

        if "adjacent_clusters" in self.rules:
            scis = _get_sequential_cluster_ids(glyphs)
            for i in range(0, len(glyphs) - 1):
                for j in range(i + 1, len(glyphs)):
                    if scis[i] - scis[j] in (-1, 0, 1):
                        overlaps = self.find_overlaps(glyphs[i], glyphs[j])
                        if (
                            glyphs[i]["category"] == "base"
                            and glyphs[j]["category"] == "base"
                            and not self.rules.get("bases", True)
                        ):
                            continue

                        if overlaps:
                            return overlaps

        if "marks" in self.rules:
            # print("Mark testing")
            for i in range(1, len(glyphs) - 1):
                if glyphs[i]["category"] != "mark":
                    continue
                for j in range(i + 1, len(glyphs)):
                    if glyphs[j]["category"] != "mark":
                        continue
                    overlaps = self.find_overlaps(glyphs[i], glyphs[j])
                    # print(overlaps)
                    if overlaps:
                        return overlaps

        #   Where there anchors between a glyph pair, the anchored paths should be
        #   allowed to collide but others should not
        # XX this rule does not work when cursive attachment is used occasionally
        # print("Area and anchor test")
        if "cursive" in self.rules or "area" in self.rules:
            for firstIx in range(0, len(glyphs) - 1):
                first = glyphs[firstIx]
                second = glyphs[firstIx + 1]
                if "cursive" in self.rules and self.rules["cursive"]:
                    firstHasAnchors = any([x.hasAnchor for x in first["paths"]])
                    secondHasAnchors = any([x.hasAnchor for x in first["paths"]])
                    if firstHasAnchors or secondHasAnchors:
                        overlaps = self.find_overlaps(first, second)
                        overlaps = list(
                            filter(
                                lambda x: (
                                    (x.path1.hasAnchor and not x.path2.hasAnchor)
                                    or (x.path2.hasAnchor and not x.path1.hasAnchor)
                                ),
                                overlaps,
                            )
                        )
                        if not overlaps:
                            continue
                        return overlaps
                if "area" in self.rules:
                    if (
                        first["category"] == "base"
                        and second["category"] == "base"
                        and not self.rules.get("bases", True)
                    ):
                        continue

                    overlaps = self.find_overlaps(first, second)
                    if not overlaps:
                        continue
                    newoverlaps = []
                    for i1 in overlaps:
                        intersect = i1.path1.intersection(i1.path2, flat=True)
                        for i in intersect:
                            ia = i.area
                            # print("Intersection area: %i Path 1 area: %i Path 2 area: %i" % (ia, p1.area, p2.area))
                            if (
                                ia > i1.path1.area * self.rules["area"]
                                or ia > i1.path2.area * self.rules["area"]
                            ):
                                newoverlaps.append(i1)
                    if newoverlaps:
                        return newoverlaps
        return []
