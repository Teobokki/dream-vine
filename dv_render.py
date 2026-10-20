"""DREAM VINE - Panda3D geometry helpers (chunk meshes from numpy, boxes, block icons, textures). (c)2026 EX Inc."""
import numpy as np
from panda3d.core import (Geom, GeomEnums, GeomNode, GeomTriangles, GeomVertexArrayFormat, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, NodePath, Texture, SamplerState, LineSegs)
import dv_blocks as bl

_fmt = None


def vformat():
    global _fmt
    if _fmt is None:
        a = GeomVertexArrayFormat()
        a.add_column("vertex", 3, GeomEnums.NT_float32, GeomEnums.C_point)
        a.add_column("texcoord", 2, GeomEnums.NT_float32, GeomEnums.C_texcoord)
        a.add_column("color", 4, GeomEnums.NT_uint8, GeomEnums.C_color)
        _fmt = GeomVertexFormat.register_format(GeomVertexFormat(a))
    return _fmt


def mesh_node(name, verts, idx):
    """GeomNode from a VDT structured vertex array + uint32 index array (bulk copy via buffer protocol)."""
    vd = GeomVertexData(name, vformat(), Geom.UH_static)
    vd.unclean_set_num_rows(len(verts))
    arr = vd.modify_array(0)
    memoryview(arr).cast("B")[:] = verts.tobytes()
    tri = GeomTriangles(Geom.UH_static)
    tri.set_index_type(GeomEnums.NT_uint32)
    h = tri.modify_vertices()
    h.unclean_set_num_rows(len(idx))
    memoryview(h).cast("B")[:] = idx.astype(np.uint32).tobytes()
    g = Geom(vd); g.add_primitive(tri)
    n = GeomNode(name); n.add_geom(g)
    return n


def np_texture(rgba, name="tex", nearest=True):
    """Texture from an RGBA uint8 numpy image whose row 0 is the top."""
    h, w = rgba.shape[:2]
    t = Texture(name)
    t.setup_2d_texture(w, h, Texture.T_unsigned_byte, Texture.F_rgba8)
    bgra = np.ascontiguousarray(rgba[::-1, :, [2, 1, 0, 3]])
    t.set_ram_image(bgra.tobytes())
    if nearest:
        t.set_magfilter(SamplerState.FT_nearest); t.set_minfilter(SamplerState.FT_nearest)
    else:
        t.set_magfilter(SamplerState.FT_linear); t.set_minfilter(SamplerState.FT_linear_mipmap_linear)
    t.set_wrap_u(SamplerState.WM_clamp); t.set_wrap_v(SamplerState.WM_clamp)
    return t


def box_geom(parent, size, color, origin=(0.5, 0.5, 0.0), name="box", tex_uv=None):
    """Axis-aligned box (sx, sy, sz), flat face shading. origin = pivot as fraction of size."""
    sx, sy, sz = size
    ox, oy, oz = origin
    fmt = GeomVertexFormat.get_v3c4t2()
    vd = GeomVertexData(name, fmt, Geom.UH_static)
    vw, cw, tw = GeomVertexWriter(vd, "vertex"), GeomVertexWriter(vd, "color"), GeomVertexWriter(vd, "texcoord")
    tri = GeomTriangles(Geom.UH_static)
    from dv_world import FACES, SHADE
    r, g, b = color[:3]
    a = color[3] if len(color) > 3 else 1.0
    n = 0
    for d in range(6):
        s = SHADE[d]
        for k, (x, y, z) in enumerate(FACES[d]):
            vw.add_data3((x - ox) * sx, (y - oy) * sy, (z - oz) * sz)
            cw.add_data4(r * s, g * s, b * s, a)
            if tex_uv:
                u0, v0, u1, v1 = tex_uv[d] if isinstance(tex_uv[0], (tuple, list)) else tex_uv
                tw.add_data2([u0, u1, u1, u0][k], [v0, v0, v1, v1][k])
            else:
                tw.add_data2(0, 0)
        tri.add_vertices(n, n + 1, n + 2); tri.add_vertices(n, n + 2, n + 3); n += 4
    gm = Geom(vd); gm.add_primitive(tri)
    gn = GeomNode(name); gn.add_geom(gm)
    return parent.attach_new_node(gn)


def block_uvs(bid):
    return [bl.tile_uv(bl.FACE_TILE[bid, d]) for d in range(6)]


def icon_node(parent, item, atlas, size=1.0):
    """2D icon (in aspect2d units): isometric mini-block for blocks, flat sprite for items."""
    fmt = GeomVertexFormat.get_v3c4t2()
    vd = GeomVertexData("icon", fmt, Geom.UH_static)
    vw, cw, tw = GeomVertexWriter(vd, "vertex"), GeomVertexWriter(vd, "color"), GeomVertexWriter(vd, "texcoord")
    tri = GeomTriangles(Geom.UH_static)
    quads = []
    s = size / 2.0
    if item in bl.BLOCKS:
        top = bl.tile_uv(bl.FACE_TILE[item, 4]); side = bl.tile_uv(bl.FACE_TILE[item, 2])
        c, h = 0.866 * s, 0.5 * s
        # points in (x, z) screen plane
        T0, T1, T2, T3 = (0, s), (c, h), (0, 0), (-c, h)     # top rhombus (back, right, front, left)
        B1, B2, B3 = (c, -h), (0, -s), (-c, -h)
        quads.append(((T3, T2, T1, T0), top, 1.0))
        quads.append(((B3, B2, T2, T3), side, 0.78))
        quads.append(((B2, B1, T1, T2), side, 0.6))
    else:
        uv = bl.tile_uv(bl.icon_tile(item))
        quads.append((((-s, -s), (s, -s), (s, s), (-s, s)), uv, 1.0))
    n = 0
    for pts, (u0, v0, u1, v1), shade in quads:
        for k, (x, z) in enumerate(pts):
            vw.add_data3(x, 0, z)
            cw.add_data4(shade, shade, shade, 1)
            tw.add_data2([u0, u1, u1, u0][k], [v0, v0, v1, v1][k])
        tri.add_vertices(n, n + 1, n + 2); tri.add_vertices(n, n + 2, n + 3); n += 4
    gm = Geom(vd); gm.add_primitive(tri)
    gn = GeomNode("icon"); gn.add_geom(gm)
    np_ = parent.attach_new_node(gn)
    np_.set_texture(atlas)
    np_.set_transparency(True)
    return np_


def wire_cube(parent, color=(0, 0, 0, 0.8), thick=2.0, e=0.004):
    ls = LineSegs(); ls.set_thickness(thick); ls.set_color(*color)
    p = [(-e, -e, -e), (1 + e, -e, -e), (1 + e, 1 + e, -e), (-e, 1 + e, -e),
         (-e, -e, 1 + e), (1 + e, -e, 1 + e), (1 + e, 1 + e, 1 + e), (-e, 1 + e, 1 + e)]
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)):
        ls.move_to(*p[a]); ls.draw_to(*p[b])
    return parent.attach_new_node(ls.create())
