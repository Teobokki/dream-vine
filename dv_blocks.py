"""DREAM VINE - blocks, items, recipes and procedurally generated pixel-art textures (all original). (c)2026 EX Inc."""
import numpy as np

T = 16          # texture tile size (px)
ATLAS_N = 16    # tiles per atlas row
AIR, GRASS, DIRT, STONE, COBBLE, SAND, WATER, BEDROCK, LOG, LEAVES, PLANKS, COAL_ORE, IRON_ORE, GOLD_ORE, \
    DIAMOND_ORE, GRAVEL, GLASS, TABLE, BRICKS, WOOL, MOSSY, VINE_BLOCK = range(22)
# decorative building blocks (added in 1.3.0 for VINE BUILD; also in the creative inventory)
RED_WOOD, DARK_WOOD, ROOF_TILE, WHITE_STONE, GOLD_BLOCK, LANTERN, CHERRY_LEAVES, RED_WOOL, BLACK_WOOL, BLUE_WOOL, \
    YELLOW_WOOL, GREEN_WOOL, PINK_WOOL, SANDSTONE, SNOW, STONE_BRICKS, CONCRETE, THATCH = range(22, 40)
# autumn foliage (added in 1.4.0)
AUTUMN_ORANGE, AUTUMN_RED, AUTUMN_GOLD, AUTUMN_BROWN = range(40, 44)
LEAF_LITTER, LEAF_PILE = 44, 45
AUTUMN_LEAVES = (AUTUMN_ORANGE, AUTUMN_RED, AUTUMN_GOLD, AUTUMN_BROWN)
AUTUMN_RGB = {AUTUMN_ORANGE: (226, 118, 34), AUTUMN_RED: (186, 42, 30), AUTUMN_GOLD: (236, 186, 48), AUTUMN_BROWN: (146, 94, 50)}

# item ids (non-block)
STICK, COAL, IRON, GOLD, DIAMOND, APPLE, RAW_MEAT = 100, 101, 102, 103, 104, 105, 106
TOOL_BASE = 120  # tool id = TOOL_BASE + kind*4 + tier
TOOL_KINDS = ["pickaxe", "axe", "shovel", "sword"]
TIERS = ["Wooden", "Stone", "Iron", "Diamond"]
TIER_SPEED = [2.0, 4.0, 6.0, 8.0]
TIER_COLOR = [(166, 124, 72), (128, 128, 132), (222, 222, 226), (88, 232, 220)]


def tool_id(kind, tier):
    return TOOL_BASE + TOOL_KINDS.index(kind) * 4 + tier


def tool_info(item):
    if TOOL_BASE <= item < TOOL_BASE + 16:
        k = (item - TOOL_BASE) // 4
        return TOOL_KINDS[k], (item - TOOL_BASE) % 4
    return None, -1


class B:
    def __init__(self, name, tiles, hard=1.0, tool=None, tier=-1, drop=None, transparent=False, solid=True,
                 selfcull=True, cutout=False):
        self.name, self.tiles, self.hard, self.tool, self.tier = name, tiles, hard, tool, tier
        self.drop, self.transparent, self.solid, self.selfcull, self.cutout = drop, transparent, solid, selfcull, cutout


# tiles: one name, or (top, side, bottom)
BLOCKS = {
    GRASS: B("Grass Block", ("grass_top", "grass_side", "dirt"), 0.6, "shovel", drop=DIRT),
    DIRT: B("Dirt", "dirt", 0.5, "shovel"),
    STONE: B("Stone", "stone", 1.5, "pickaxe", 0, drop=COBBLE),
    COBBLE: B("Cobblestone", "cobble", 2.0, "pickaxe", 0),
    SAND: B("Sand", "sand", 0.5, "shovel"),
    WATER: B("Water", "water", 100, transparent=True, solid=False),
    BEDROCK: B("Bedrock", "bedrock", -1),
    LOG: B("Dreamwood Log", ("log_top", "log_side", "log_top"), 2.0, "axe"),
    LEAVES: B("Vine Leaves", "leaves", 0.2, None, drop=0, transparent=True, cutout=True),
    PLANKS: B("Dreamwood Planks", "planks", 2.0, "axe"),
    COAL_ORE: B("Coal Ore", "coal_ore", 3.0, "pickaxe", 0, drop=COAL),
    IRON_ORE: B("Iron Ore", "iron_ore", 3.0, "pickaxe", 1, drop=IRON),
    GOLD_ORE: B("Gold Ore", "gold_ore", 3.0, "pickaxe", 2, drop=GOLD),
    DIAMOND_ORE: B("Diamond Ore", "diamond_ore", 3.0, "pickaxe", 2, drop=DIAMOND),
    GRAVEL: B("Gravel", "gravel", 0.6, "shovel"),
    GLASS: B("Glass", "glass", 0.3, None, drop=0, transparent=True, cutout=True),
    TABLE: B("Crafting Table", ("table_top", "table_side", "planks"), 2.5, "axe"),
    BRICKS: B("Bricks", "bricks", 2.0, "pickaxe", 0),
    WOOL: B("Cloud Wool", "wool", 0.8),
    MOSSY: B("Mossy Cobblestone", "mossy", 2.0, "pickaxe", 0),
    VINE_BLOCK: B("Dream Vine Block", ("vine_top", "vine_side", "vine_top"), 0.8, "axe"),
    RED_WOOD: B("Red Lacquered Wood", "red_wood", 2.0, "axe"),
    DARK_WOOD: B("Dark Wood Planks", "dark_wood", 2.0, "axe"),
    ROOF_TILE: B("Roof Tiles", "roof_tile", 2.0, "pickaxe", 0),
    WHITE_STONE: B("White Stone", "white_stone", 2.0, "pickaxe", 0),
    GOLD_BLOCK: B("Gold Block", "gold_block", 3.0, "pickaxe", 2),
    LANTERN: B("Paper Lantern", ("lantern_top", "lantern_side", "lantern_top"), 0.5),
    CHERRY_LEAVES: B("Cherry Blossom Leaves", "cherry_leaves", 0.2, None, drop=0, transparent=True, cutout=True),
    RED_WOOL: B("Red Wool", "red_wool", 0.8),
    BLACK_WOOL: B("Black Wool", "black_wool", 0.8),
    BLUE_WOOL: B("Blue Wool", "blue_wool", 0.8),
    YELLOW_WOOL: B("Yellow Wool", "yellow_wool", 0.8),
    GREEN_WOOL: B("Green Wool", "green_wool", 0.8),
    PINK_WOOL: B("Pink Wool", "pink_wool", 0.8),
    SANDSTONE: B("Sandstone", ("sandstone_top", "sandstone", "sandstone_top"), 1.2, "pickaxe", 0),
    SNOW: B("Snow Block", "snow", 0.4, "shovel"),
    STONE_BRICKS: B("Stone Bricks", "stone_bricks", 2.0, "pickaxe", 0),
    CONCRETE: B("Grey Concrete", "concrete", 2.0, "pickaxe", 0),
    THATCH: B("Thatch", "thatch", 0.5),
    AUTUMN_ORANGE: B("Orange Autumn Leaves", "autumn_orange", 0.2, None, drop=0, transparent=True, cutout=True),
    AUTUMN_RED: B("Red Autumn Leaves", "autumn_red", 0.2, None, drop=0, transparent=True, cutout=True),
    AUTUMN_GOLD: B("Golden Autumn Leaves", "autumn_gold", 0.2, None, drop=0, transparent=True, cutout=True),
    AUTUMN_BROWN: B("Brown Autumn Leaves", "autumn_brown", 0.2, None, drop=0, transparent=True, cutout=True),
    LEAF_LITTER: B("Leaf-Covered Grass", ("litter_top", "litter_side", "dirt"), 0.6, "shovel", drop=DIRT),
    LEAF_PILE: B("Fallen Leaf Pile", "leaf_pile", 0.2, None, transparent=True, cutout=True),
}
LEAF_BLOCKS = (LEAVES, CHERRY_LEAVES) + AUTUMN_LEAVES
ITEMS = {STICK: "Stick", COAL: "Coal", IRON: "Iron Ingot", GOLD: "Gold Ingot", DIAMOND: "Diamond", APPLE: "Apple",
         RAW_MEAT: "Mossbuck Meat"}
for k in TOOL_KINDS:
    for t in range(4):
        ITEMS[tool_id(k, t)] = "%s %s" % (TIERS[t], k.capitalize())
FOOD = {APPLE: 4, RAW_MEAT: 5}
CREATIVE_ITEMS = [GRASS, DIRT, STONE, COBBLE, SAND, GRAVEL, LOG, PLANKS, LEAVES, GLASS, TABLE, BRICKS, WOOL, MOSSY,
                  VINE_BLOCK, RED_WOOD, DARK_WOOD, ROOF_TILE, WHITE_STONE, GOLD_BLOCK, LANTERN, CHERRY_LEAVES, AUTUMN_ORANGE, AUTUMN_RED, AUTUMN_GOLD, AUTUMN_BROWN, LEAF_PILE, LEAF_LITTER, RED_WOOL,
                  BLACK_WOOL, BLUE_WOOL, YELLOW_WOOL, GREEN_WOOL, PINK_WOOL, SANDSTONE, SNOW, STONE_BRICKS, CONCRETE, THATCH, COAL_ORE, IRON_ORE, GOLD_ORE, DIAMOND_ORE, BEDROCK, WATER, STICK, COAL, IRON, GOLD,
                  DIAMOND, APPLE, RAW_MEAT] + [tool_id(k, t) for t in range(4) for k in TOOL_KINDS]


def name_of(item):
    return BLOCKS[item].name if item in BLOCKS else ITEMS.get(item, "?")


def max_stack(item):
    return 1 if TOOL_BASE <= item < TOOL_BASE + 16 else 64


# recipes: (result, count, {ingredient: n}, needs_table)
RECIPES = [(PLANKS, 4, {LOG: 1}, False), (STICK, 4, {PLANKS: 2}, False), (TABLE, 1, {PLANKS: 4}, False),
           (VINE_BLOCK, 2, {LEAVES: 2, LOG: 1}, False), (GLASS, 1, {SAND: 4}, True), (BRICKS, 1, {GRAVEL: 2, SAND: 2}, True),
           (MOSSY, 2, {COBBLE: 2, LEAVES: 1}, True)]
MATS = [PLANKS, COBBLE, IRON, DIAMOND]
for t, m in enumerate(MATS):
    RECIPES += [(tool_id("pickaxe", t), 1, {m: 3, STICK: 2}, True), (tool_id("axe", t), 1, {m: 3, STICK: 2}, True),
                (tool_id("shovel", t), 1, {m: 1, STICK: 2}, True), (tool_id("sword", t), 1, {m: 2, STICK: 1}, True)]

# per-block lookup tables for the mesher
NB = 32
OPAQUE = np.zeros(256, bool)
TRANSP = np.zeros(256, bool)
SELFCULL = np.zeros(256, bool)
SOLID = np.zeros(256, bool)
for bid, b in BLOCKS.items():
    OPAQUE[bid] = not b.transparent
    TRANSP[bid] = b.transparent
    SELFCULL[bid] = b.selfcull
    SOLID[bid] = b.solid


# ----------------------------------------------------------------------------- texture generation
def _rng(name):
    return np.random.RandomState(abs(hash(name)) % (2 ** 31) if False else sum(ord(c) * (i + 7) for i, c in enumerate(name)))


def _noise(rng, base, var, size=T):
    n = rng.uniform(-1, 1, (size, size, 1)) * var
    return np.clip(np.array(base, np.float32)[None, None] + n, 0, 255)


def _rgba(rgb, a=255):
    return np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), a, np.float32)], 2)


def _blobs(rng, img, color, n, rmin=1, rmax=2, var=18):
    for _ in range(n):
        cx, cy = rng.randint(1, T - 1, 2)
        r = rng.randint(rmin, rmax + 1)
        for y in range(cy - r, cy + r):
            for x in range(cx - r, cx + r):
                if 0 <= x < T and 0 <= y < T and rng.rand() < 0.8:
                    img[y, x, :3] = np.clip(np.array(color) + rng.uniform(-var, var), 0, 255)
    return img


def tex(name):
    r = _rng(name)
    if name == "dirt":
        return _rgba(_blobs(r, _noise(r, (134, 96, 67), 18), (105, 74, 50), 9, 0, 1))
    if name == "grass_top":
        return _rgba(_blobs(r, _noise(r, (98, 168, 64), 22), (78, 140, 50), 14, 0, 1))
    if name == "grass_side":
        d = tex("dirt")
        g = _noise(r, (98, 168, 64), 20)
        for x in range(T):
            h = 3 + r.randint(0, 3)
            d[:h, x, :3] = g[:h, x]
        return d
    if name == "stone":
        return _rgba(_blobs(r, _noise(r, (125, 125, 128), 14), (104, 104, 108), 10, 0, 2, 8))
    if name in ("cobble", "mossy"):
        img = _noise(r, (118, 118, 120), 10)
        pts = r.randint(0, T, (9, 2))
        yy, xx = np.mgrid[0:T, 0:T]
        d = np.stack([np.minimum.reduce([(np.abs(xx - px + o) ** 2 + np.abs(yy - py + p) ** 2)
                                          for o in (-T, 0, T) for p in (-T, 0, T)]) for px, py in pts], 0)
        srt = np.sort(d, 0)
        edge = (np.sqrt(srt[1]) - np.sqrt(srt[0])) < 0.75
        shade = (np.argmin(d, 0) % 3) * 9.0
        img = img + shade[..., None]
        img[edge] = (72, 72, 76)
        if name == "mossy":
            img = _blobs(r, img, (82, 138, 60), 16, 0, 2, 16)
        return _rgba(np.clip(img, 0, 255))
    if name == "sand":
        return _rgba(_noise(r, (222, 208, 152), 12))
    if name == "gravel":
        img = _noise(r, (130, 122, 116), 20)
        return _rgba(_blobs(r, _blobs(r, img, (96, 90, 86), 12, 0, 1), (160, 150, 140), 8, 0, 1))
    if name == "bedrock":
        img = _noise(r, (70, 70, 72), 40)
        return _rgba(_blobs(r, img, (30, 30, 32), 14, 0, 2))
    if name == "log_side":
        img = _noise(r, (104, 78, 52), 10)
        for x in range(T):
            if r.rand() < 0.35:
                img[:, x] *= 0.72
        img[:, ::5] *= 0.85
        return _rgba(img)
    if name == "log_top":
        yy, xx = np.mgrid[0:T, 0:T]
        rr = np.sqrt((xx - 7.5) ** 2 + (yy - 7.5) ** 2)
        img = _noise(r, (176, 140, 92), 8)
        img[(rr.astype(int) % 3) == 0] *= 0.8
        img[rr > 6.8] = (104, 78, 52)
        return _rgba(img)
    if name == "leaves":
        img = _noise(r, (62, 140, 58), 30)
        img = _blobs(r, img, (110, 190, 80), 6, 0, 1)
        a = np.where(r.rand(T, T) < 0.18, 0, 255).astype(np.float32)
        return np.concatenate([img, a[..., None]], 2)
    if name in ("planks", "table_top", "table_side"):
        img = _noise(r, (176, 134, 84), 10)
        for y in range(T):
            img[y] *= 0.94 + 0.06 * np.sin(y * 1.7 + r.rand())
        img[3::4] = (120, 88, 52)
        for row in range(4):
            x = r.randint(0, T)
            img[row * 4:row * 4 + 3, x] = (130, 96, 58)
        if name == "table_top":
            img[0, :] = img[-1, :] = img[:, 0] = img[:, -1] = (96, 70, 40)
            img[7:9, 2:14] = (96, 70, 40); img[2:14, 7:9] = (96, 70, 40)
        if name == "table_side":
            img[2:5, 3:12] = (100, 100, 108)   # saw blade
            img[5:11, 4:6] = (90, 64, 36)      # handle
            img[6:8, 9:14] = (150, 150, 158); img[8:13, 11:12] = (90, 64, 36)  # hammer
        return _rgba(img)
    if name.endswith("_ore"):
        col = {"coal_ore": (34, 34, 36), "iron_ore": (214, 172, 140), "gold_ore": (250, 214, 60),
               "diamond_ore": (90, 236, 226)}[name]
        img = tex("stone")
        return _blobs(r, img, col, 6, 1, 1, 14)
    if name == "water":
        img = _noise(r, (52, 104, 214), 12)
        for y in range(1, T, 5):
            for x in range(T):
                if (x + y) % 7 < 3:
                    img[y, x] = (90, 140, 236)
        return _rgba(img, 170)
    if name == "glass":
        img = np.zeros((T, T, 4), np.float32)
        img[..., :3] = 220; img[..., 3] = 30
        img[0, :] = img[-1, :] = img[:, 0] = img[:, -1] = (236, 246, 250, 255)
        for i in range(3, 7):
            img[i, 10 - i, :] = (250, 250, 255, 200)
        return img
    if name == "bricks":
        img = _noise(r, (160, 72, 56), 14)
        img[3::4] = (196, 188, 176)
        for row in range(4):
            off = 0 if row % 2 else 4
            img[row * 4:row * 4 + 3, off::8] = (196, 188, 176)
        return _rgba(img)
    if name == "wool":
        return _rgba(_noise(r, (236, 238, 244), 10))
    if name in ("vine_side", "vine_top"):
        img = tex("log_side" if name == "vine_side" else "log_top")[..., :3].copy()
        t = np.arange(T)
        xs = (7 + 4 * np.sin(t * 0.8)).astype(int)
        for y in t:
            img[y, max(0, xs[y] - 1):xs[y] + 2] = (60, 176, 70)
            if y % 4 == 1:
                img[y, min(T - 1, xs[y] + 2):min(T, xs[y] + 4)] = (120, 214, 90)
        return _rgba(img)
    if name in ("red_wood", "dark_wood"):
        img = tex("planks")[..., :3]
        tint = np.array((196, 44, 38) if name == "red_wood" else (82, 56, 38), np.float32) / np.array((176, 134, 84), np.float32)
        img = img * tint[None, None]
        if name == "red_wood":
            img[0, :] = img[-1, :] = (120, 24, 22)
        return _rgba(np.clip(img, 0, 255))
    if name == "roof_tile":
        img = _noise(r, (62, 68, 84), 8)
        for row in range(4):
            y0 = row * 4
            for x in range(T):
                k = (x + (2 if row % 2 else 0)) % 4
                img[y0 + 3, x] = (34, 38, 50)
                if k == 0:
                    img[y0:y0 + 3, x] = (44, 48, 62)
                if k == 2:
                    img[y0, x] = (96, 104, 124)
        return _rgba(img)
    if name == "white_stone":
        img = _noise(r, (234, 230, 222), 5)
        img[0, :] = img[:, 0] = (246, 244, 240); img[-1, :] = img[:, -1] = (200, 196, 188)
        return _rgba(_blobs(r, img, (220, 216, 208), 4, 0, 1, 4))
    if name == "gold_block":
        img = _noise(r, (238, 196, 58), 8)
        img[0, :] = img[:, 0] = (255, 236, 140); img[-1, :] = img[:, -1] = (180, 130, 30)
        img[2, 2:6] = (255, 246, 190)
        return _rgba(img)
    if name in ("lantern_side", "lantern_top"):
        yy, xx = np.mgrid[0:T, 0:T]
        if name == "lantern_top":
            img = _noise(r, (60, 30, 22), 6); img[5:11, 5:11] = (255, 210, 120)
            return _rgba(img)
        glow = 1.0 - (np.abs(xx - 7.5) / 9.0) ** 2
        img = np.stack([255 * np.ones_like(glow), 120 + 90 * glow, 40 + 60 * glow], -1).astype(np.float32)
        img[(yy % 4) == 0] *= 0.82
        img[:2] = (60, 30, 22); img[-2:] = (60, 30, 22)
        img[2, :] = img[-3, :] = (200, 40, 30)
        return _rgba(np.clip(img, 0, 255))
    if name == "cherry_leaves":
        img = _noise(r, (238, 164, 204), 24)
        img = _blobs(r, img, (255, 214, 236), 7, 0, 1, 10)
        img = _blobs(r, img, (196, 104, 150), 4, 0, 0, 10)
        a = np.where(r.rand(T, T) < 0.16, 0, 255).astype(np.float32)
        return np.concatenate([img, a[..., None]], 2)
    if name.startswith("autumn_"):
        base = {"autumn_orange": (226, 118, 34), "autumn_red": (186, 42, 30), "autumn_gold": (236, 186, 48),
                "autumn_brown": (146, 94, 50)}[name]
        img = _noise(r, base, 28)
        img = _blobs(r, img, tuple(min(255, v + 34) for v in base), 6, 0, 1, 12)
        img = _blobs(r, img, tuple(int(v * 0.7) for v in base), 4, 0, 0, 10)
        a = np.where(r.rand(T, T) < 0.18, 0, 255).astype(np.float32)
        return np.concatenate([img, a[..., None]], 2)
    if name in ("litter_top", "leaf_pile"):
        img = tex("grass_top")[..., :3].copy() if name == "litter_top" else _noise(r, (176, 104, 40), 26)
        for col, n in (((226, 118, 34), 9), ((186, 42, 30), 6), ((236, 186, 48), 8), ((146, 94, 50), 6)):
            img = _blobs(r, img, col, n if name == "litter_top" else n + 4, 0, 1, 16)
        if name == "litter_top":
            return _rgba(img)
        a = np.where(r.rand(T, T) < 0.08, 0, 255).astype(np.float32)
        return np.concatenate([img, a[..., None]], 2)
    if name == "litter_side":
        d = tex("grass_side")
        for x in range(T):
            if r.rand() < 0.55:
                d[0:2, x, :3] = [(226, 118, 34), (186, 42, 30), (236, 186, 48), (146, 94, 50)][r.randint(0, 4)]
        return d
    if name == "falling_leaf":
        img = np.zeros((T, T, 4), np.float32)
        yy, xx = np.mgrid[0:T, 0:T]
        m = ((xx - 7.5) / 6.5) ** 2 + ((yy - 7.5) / 4.0) ** 2 <= 1.0
        img[m] = (235, 235, 235, 255)
        img[7:9, 1:15][m[7:9, 1:15]] = (170, 170, 170, 255)
        return img
    if name.endswith("_wool"):
        col = {"red_wool": (190, 40, 40), "black_wool": (34, 34, 40), "blue_wool": (52, 80, 190), "yellow_wool": (236, 200, 50),
               "green_wool": (70, 140, 52), "pink_wool": (238, 140, 176)}[name]
        img = _noise(r, col, 9)
        for y in range(0, T, 3):
            img[y, (np.arange(T) + y) % 2 == 0] *= 0.92
        return _rgba(img)
    if name in ("sandstone", "sandstone_top"):
        img = _noise(r, (218, 196, 136), 7)
        if name == "sandstone":
            img[3] *= 0.9; img[4:6] *= 1.04; img[11] *= 0.88; img[12:14] *= 0.96
        else:
            img[0, :] = img[-1, :] = img[:, 0] = img[:, -1] = (190, 168, 112)
        return _rgba(np.clip(img, 0, 255))
    if name == "snow":
        return _rgba(_blobs(r, _noise(r, (244, 248, 255), 6), (222, 232, 246), 6, 0, 1, 4))
    if name == "stone_bricks":
        img = _noise(r, (122, 122, 126), 9)
        img[7] = img[15] = (84, 84, 88)
        img[0:7, 7] = (84, 84, 88); img[8:15, 0] = (84, 84, 88); img[8:15, 15] = (96, 96, 100)
        img[0, :] *= 1.12; img[8, :] *= 1.12
        return _rgba(np.clip(img, 0, 255))
    if name == "concrete":
        return _rgba(_noise(r, (148, 150, 156), 4))
    if name == "thatch":
        img = _noise(r, (198, 168, 82), 14)
        for x in range(T):
            if r.rand() < 0.4:
                img[:, x] *= 0.82
        img[::5] *= 0.86
        return _rgba(img)
    raise KeyError(name)


def item_tex(item):
    """16x16 RGBA icon for non-block items."""
    img = np.zeros((T, T, 4), np.float32)
    def put(mask, colors):
        for y, row in enumerate(mask):
            for x, ch in enumerate(row):
                if ch in colors:
                    img[y, x] = colors[ch] + (255,)
    if item == STICK:
        put(["" for _ in range(3)] + [" " * (12 - i) + "s" for i in range(10)], {"s": (120, 88, 50)})
    elif item in (COAL, IRON, GOLD, DIAMOND):
        c = {COAL: (40, 40, 44), IRON: (226, 226, 230), GOLD: (250, 210, 60), DIAMOND: (100, 240, 230)}[item]
        hi = tuple(min(255, v + 50) for v in c)
        if item in (IRON, GOLD):
            put(["", "", "", "", "   hhhhhhhhh", "  hcccccccccc", " cccccccccccc", " cccccccccccc", "  ccccccccc"],
                {"h": hi, "c": c})
        else:
            put(["", "", "      hh", "     hcch", "    hccccc", "   ccccccc", "  cccccccc", "   ccccccc", "    ccccc",
                 "     ccc", "      c"], {"h": hi, "c": c})
    elif item == APPLE:
        put(["", "       s", "      s", "   rrr rrr", "  rrrrrrrrr", "  rhrrrrrrr", "  rhrrrrrrr", "  rrrrrrrrr",
             "  rrrrrrrrr", "   rrrrrrr", "    rr rr"], {"r": (214, 40, 46), "h": (255, 140, 140), "s": (90, 60, 30)})
    elif item == RAW_MEAT:
        put(["", "", "    pppp", "   pppppp", "  pppwpppp", "  ppwwpppp", "  pppppppp", "   pppppp", "    pppp"],
            {"p": (220, 110, 110), "w": (250, 230, 230)})
    else:
        kind, tier = tool_info(item)
        h = TIER_COLOR[tier]; s = (120, 88, 50)
        masks = {
            "pickaxe": ["", "  hhhhhhhhh", " hh   s   hh", " h    s    h", "      s", "      s", "      s", "      s",
                        "      s", "      s", "      s", "      s"],
            "axe": ["", "    hhh", "   hhhhs", "   hhh s", "    h  s", "       s", "       s", "       s", "       s",
                    "       s", "       s"],
            "shovel": ["", "     hhh", "     hhh", "     hhh", "      s", "      s", "      s", "      s", "      s",
                       "      s", "     sss"],
            "sword": ["", "          hh", "         hhh", "        hhh", "       hhh", "      hhh", "  s  hhh", "   shhh",
                      "    ss", "   s  s", "  s"],
        }
        put(masks[kind], {"h": h, "s": s})
    return img


def crack_tex(stage):
    r = np.random.RandomState(99)
    img = np.zeros((T, T, 4), np.float32)
    pts = [(7, 7)]
    for i in range((stage + 1) * 5):
        x, y = pts[r.randint(len(pts))]
        x = int(np.clip(x + r.randint(-1, 2), 0, T - 1)); y = int(np.clip(y + r.randint(-1, 2), 0, T - 1))
        pts.append((x, y))
        img[y, x] = (16, 16, 16, 220)
    return img


TILE_NAMES = ["grass_top", "grass_side", "dirt", "stone", "cobble", "sand", "water", "bedrock", "log_top", "log_side",
              "leaves", "planks", "coal_ore", "iron_ore", "gold_ore", "diamond_ore", "gravel", "glass", "table_top",
              "table_side", "bricks", "wool", "mossy", "vine_top", "vine_side", "red_wood", "dark_wood", "roof_tile",
              "white_stone", "gold_block", "lantern_side", "lantern_top", "cherry_leaves", "red_wool", "black_wool", "blue_wool",
              "yellow_wool", "green_wool", "pink_wool", "sandstone", "sandstone_top", "snow", "stone_bricks", "concrete", "thatch",
              "autumn_orange", "autumn_red", "autumn_gold", "autumn_brown", "falling_leaf", "litter_top", "litter_side", "leaf_pile"]
TILE = {n: i for i, n in enumerate(TILE_NAMES)}
ICON_TILE = {}      # item id -> tile index for non-block items
CRACK_TILE0 = 0


def build_atlas():
    """Returns RGBA uint8 atlas (row 0 = top) of 16x16 tiles."""
    global CRACK_TILE0
    tiles = [tex(n) for n in TILE_NAMES]
    for it in [STICK, COAL, IRON, GOLD, DIAMOND, APPLE, RAW_MEAT] + [tool_id(k, t) for k in TOOL_KINDS for t in range(4)]:
        ICON_TILE[it] = len(tiles); tiles.append(item_tex(it))
    CRACK_TILE0 = len(tiles)
    tiles += [crack_tex(s) for s in range(10)]
    atlas = np.zeros((ATLAS_N * T, ATLAS_N * T, 4), np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, ATLAS_N)
        atlas[r * T:(r + 1) * T, c * T:(c + 1) * T] = np.clip(t, 0, 255).astype(np.uint8)
    return atlas


# face direction order: +X, -X, +Y, -Y, +Z(top), -Z(bottom)
FACE_TILE = np.zeros((256, 6), np.int32)
for bid, b in BLOCKS.items():
    if isinstance(b.tiles, str):
        FACE_TILE[bid] = TILE[b.tiles]
    else:
        top, side, bot = b.tiles
        FACE_TILE[bid] = [TILE[side]] * 4 + [TILE[top], TILE[bot]]


def tile_uv(t):
    """(u0, v0, u1, v1) of tile t in Panda UV space (v up)."""
    r, c = divmod(int(t), ATLAS_N)
    return c / ATLAS_N, 1 - (r + 1) / ATLAS_N, (c + 1) / ATLAS_N, 1 - r / ATLAS_N


def icon_tile(item):
    if item in BLOCKS:
        b = BLOCKS[item]
        return TILE[b.tiles if isinstance(b.tiles, str) else b.tiles[1]]
    return ICON_TILE[item]
