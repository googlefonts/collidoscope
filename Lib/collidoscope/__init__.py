import uharfbuzz as hb
import re
from pathlib import Path
from fontTools.ttLib import TTFont
from beziers.path import BezierPath
from beziers.path.geometricshapes import Rectangle
from beziers.point import Point
from beziers.boundingbox import BoundingBox
import sys
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

class Collidoscope:
    def __init__(self, fontfilename, rules):
        self.fontfilename = fontfilename
        self.glyphcache = {}
        self.fontbinary = Path(fontfilename).read_bytes()
        self.font = TTFont(fontfilename)
        self.rules = rules
        self.prep_shaper()
        self.get_anchors()

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
        return buf

    def bb2path(bb):
        vec = bb.tr-bb.bl
        return Rectangle(vec.x, vec.y, origin= bb.bl+vec*0.5)

    def get_anchors(self):
        glyf = self.font["glyf"]
        # Find the GPOS CursiveAttachment lookups
        cursives = filter(lambda x: x.LookupType==3, self.font["GPOS"].table.LookupList.Lookup)
        anchors = {}
        for c in cursives:
            for s in c.SubTable:
                for glyph, record in zip(s.Coverage.glyphs, s.EntryExitRecord):
                    anchors[glyph] = []
                    if record.EntryAnchor:
                        anchors[glyph].append( (record.EntryAnchor.XCoordinate, record.EntryAnchor.YCoordinate) )
                    if record.ExitAnchor:
                        anchors[glyph].append( (record.ExitAnchor.XCoordinate, record.ExitAnchor.YCoordinate) )
        self.anchors = anchors

    def get_cached_glyph(self, name):
        if name in self.glyphcache: return self.glyphcache[name]
        paths = BezierPath.fromFonttoolsGlyph(self.font, name)
        pathbounds = []
        paths = list(filter(lambda p: p.length > 0, paths))
        for p in paths:
            p.hasAnchor = False
            p.glyphname = name
            if name in self.anchors:
                for a in self.anchors[name]:
                    if p.pointIsInside(Point(*a)): p.hasAnchor = True
            bounds = p.bounds()
            pathbounds.append(bounds)

        glyphbounds = BoundingBox()
        if pathbounds:
            for p in pathbounds:
                glyphbounds.extend(p)
        else:
            glyphbounds.tr = Point(0,0)
            glyphbounds.bl = Point(0,0)
        self.glyphcache[name] = {
            "name": name,
            "paths": paths,
            "pathbounds": pathbounds,
            "glyphbounds": glyphbounds,
            "pathconvexhull": None # XXX
        }
        assert(len(self.glyphcache[name]["pathbounds"]) == len(self.glyphcache[name]["paths"]))
        return self.glyphcache[name]

    def get_positioned_glyph(self, name, pos):
        g = self.get_cached_glyph(name)
        positioned = {
            "name": g["name"],
            "paths": [ p.clone().translate(pos) for p in g["paths"] ],
            "pathbounds": [b.translated(pos) for b in g["pathbounds"]],
            "glyphbounds": g["glyphbounds"].translated(pos),
        }
        assert(len(positioned["pathbounds"]) == len(positioned["paths"]))
        # Copy path info
        for old,new in zip(g["paths"], positioned["paths"]):
            new.hasAnchor = old.hasAnchor
            new.glyphname = old.glyphname
        return positioned

    def find_overlapping_paths(self, g1, g2):
        if not (g1["glyphbounds"].overlaps(g2["glyphbounds"])): return []
        # print("Glyph bounds overlap")

        overlappingPathBounds = []
        for ix1,p1 in enumerate(g1["pathbounds"]):
            for ix2,p2 in enumerate(g2["pathbounds"]):
                if p1.overlaps(p2):
                    # print("Path bounds overlap ", ix1, ix2)
                    overlappingPathBounds.append( (ix1,ix2) )

        if not overlappingPathBounds: return []

        overlappingPaths = {}
        for ix1, ix2 in overlappingPathBounds:
            p1 = g1["paths"][ix1]
            p2 = g2["paths"][ix2]
            for s1 in p1.asSegments():
              for s2 in p2.asSegments():
                if len(s1.intersections(s2))>0:
                    overlappingPaths[(p1,p2)] = 1

        return list(overlappingPaths.keys())

    def get_glyphs(self, text):
        buf = self.shape_a_text(text)
        glyf = self.font["glyf"]
        cursor = 0
        glyphs = []
        ix = 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            position = Point(cursor + pos.position[0], pos.position[1])

            name = glyf.getGlyphName(info.codepoint)
            g = self.get_positioned_glyph(name, position)
            g["advance"] = pos.position[2]
            for p in g["paths"]:
                p.origin = info.cluster
                p.glyphIndex = ix
            glyphs.append(g)
            ix = ix + 1
            cursor = cursor + pos.position[2]
        return glyphs

    def draw_overlaps(self, glyphs, overlaps, filename):
        fig, ax = plt.subplots()
        for ix, g in enumerate(glyphs):
            col = "bgrcmy"
            for p in g["paths"]:
                p.clone().plot(ax, drawNodes = False, color=col[ix % len(col)], fill = p.hasAnchor)
            # for p in g["pathbounds"]:
                # bb2path(p).plot(ax, fill= False, drawNodes = False, color=col[ix])
        for p1,p2 in overlaps:
            intersect = p1.intersection(p2)
            for i in intersect: i.clone().plot(ax, fill= True, drawNodes = False)
        plt.axis('off')
        plt.savefig(filename)
        plt.close(fig)

    def has_collisions(self, glyphs, counter):
        # Rules for collision detection:
        #   "Far away" (adjacency > 1) glyphs should not interact at all
        if self.rules["faraway"]:
            for firstIx, first in enumerate(glyphs):
                nonAdjacent = firstIx+2
                while nonAdjacent < len(glyphs):
                    if glyphs[nonAdjacent]["advance"] == 0:
                        nonAdjacent = nonAdjacent+1
                    else: break
                for secondIx in range(nonAdjacent,len(glyphs)):
                    second = glyphs[secondIx]
                    overlaps = self.find_overlapping_paths(first, second)
                    if not overlaps: continue
                    self.draw_overlaps(glyphs, overlaps, 'col-%06i.png' % counter)
                    return True

        #   Where there anchors between a glyph pair, the anchored paths should be
        #   allowed to collide but others should not
        # XX this rule does not work when cursive attachment is used occasionally
        for firstIx in range(0,len(glyphs)-1):
            first = glyphs[firstIx]
            firstHasAnchors = any([x.hasAnchor for x in first["paths"]])
            second = glyphs[firstIx+1]
            if self.rules["cursive"]:
                secondHasAnchors = any([x.hasAnchor for x in first["paths"]])
                if firstHasAnchors or secondHasAnchors:
                    overlaps = self.find_overlapping_paths(first, second)
                    overlaps = list(filter(lambda x: ((x[0].hasAnchor and not x[1].hasAnchor) or (x[1].hasAnchor and not x[0].hasAnchor)), overlaps))
                    if not overlaps: continue
                    self.draw_overlaps(glyphs, overlaps, 'col-%06i.png' % counter)
                    return True
            if self.rules["area"] > 0:
                overlaps = self.find_overlapping_paths(first, second)
                if not overlaps: continue
                newoverlaps = []
                for p1,p2 in overlaps:
                    intersect = p1.intersection(p2,flat=True)
                    for i in intersect:
                        ia = i.area
                        # print("Intersection area: %i Path 1 area: %i Path 2 area: %i" % (ia, p1.area, p2.area))
                        if ia > p1.area * rules["area"] or ia > p2.area*rules["area"]:
                            newoverlaps.append((p1,p2))
                if newoverlaps:
                    self.draw_overlaps(glyphs, newoverlaps, 'col-%06i.png' % counter)
                    return True
        return False

