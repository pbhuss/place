from collections import defaultdict
from collections.abc import Iterable
from functools import reduce

import PIL.Image
import PIL.ImageDraw
import yaml
from redis.client import Redis


rc = Redis()


def pos_to_xy(pos, width):
    return pos % width, pos // width


def xy_to_pos(x, y, width):
    return y * width + x


def load_palette():
    with open("colors.yaml") as fp:
        config: dict[str, dict[str, str]] = yaml.safe_load(fp)

    palette = {}
    for color_name, hex_color in config["colors"].items():
        hex_color = hex_color.lstrip("#")
        rgb = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        palette[color_name] = rgb
    return palette


def extend_list(li: list, v: Iterable):
    li.extend(v)
    return li


MULTIPLIER = 20


def base_image(size):
    size = (size[0] * MULTIPLIER, size[1] * MULTIPLIER)
    image = PIL.Image.new("PA", size)
    image.putpalette(palette_flat, "RGB")
    return image


def save_image(image, io):
    image.convert(mode="RGBA", palette=PIL.Image.Palette.ADAPTIVE).save(
        io, format="PNG"
    )


FLUSH_INTERVAL = 5000


def initialize_image(redis: Redis, width=10, height=10):
    cursor: int = redis.incr("cursor")
    redis.delete("updates")
    redis.delete("image")
    palette = load_palette()
    base_color = list(palette).index("white")
    starting = {}
    bitfield = redis.bitfield("image")
    flush_counter = 0
    for i in range(width):
        for j in range(height):
            pos = xy_to_pos(i, j, width)
            starting[pos] = cursor
            bitfield.set("u8", f"#{pos}", base_color)
            flush_counter += 1
            if flush_counter > FLUSH_INTERVAL:
                bitfield.execute()
                redis.zadd("updates", starting)
                starting = {}
                flush_counter = 0
    if flush_counter > 0:
        bitfield.execute()
        redis.zadd("updates", starting)


def refresh(redis: Redis, width: int, height: int) -> tuple[int, dict[int, list[int]]]:
    cursor = redis.get("cursor")
    bitfield = redis.bitfield("image")
    color_to_pos = defaultdict(list)
    for start in range(0, width * height, FLUSH_INTERVAL):
        pos_range = range(start, int(min(start + FLUSH_INTERVAL, width * height)))
        for pos in pos_range:
            bitfield.get("u8", f"#{pos}")
        colors = bitfield.execute()
        for color, pos in zip(colors, pos_range):
            color_to_pos[color].append(int(pos))
    return int(cursor), color_to_pos


def refresh2(redis: Redis, width: int, height: int) -> tuple[int, dict[int, list[int]]]:
    cursor = redis.get("cursor")
    image_bytes = redis.get("image")
    color_to_pos = defaultdict(list)
    for pos in range(0, width * height):
        color = image_bytes[pos]
        color_to_pos[color].append(pos)
    return int(cursor), color_to_pos


def get_updates(redis: Redis, cursor) -> tuple[int, dict[int, list[int]]]:
    pipeline = redis.pipeline()
    pipeline.get("cursor")
    pipeline.zrange("updates", start=f"({cursor}", end="+inf", byscore=True)
    new_cursor, positions = pipeline.execute()
    bitfield = redis.bitfield("image")
    for pos in positions:
        bitfield.get("u8", f"#{pos.decode()}")
    colors = bitfield.execute()
    color_to_pos = defaultdict(list)
    for color, pos in zip(colors, positions):
        color_to_pos[color].append(int(pos))
    new_cursor = int(new_cursor)
    if new_cursor > cursor + 1:
        # EXPERIMENTAL
        new_cursor -= 1
    return new_cursor, color_to_pos


def update_pos(redis, pos, color, check=False):
    if check:
        (prev_color,) = redis.bitfield("image").get("u8", f"#{pos}").execute()
    if not check or color != prev_color:
        redis.bitfield("image").set("u8", f"#{pos}", color).execute()
        cursor = redis.incr("cursor")
        redis.zadd("updates", {pos: cursor})
        return int(cursor)


palette = load_palette()
palette_flat = reduce(extend_list, palette.values(), [])


def draw_updates(image: PIL.Image.Image, color_to_pos):
    draw = PIL.ImageDraw.Draw(image)
    width, height = image.size
    width = width / MULTIPLIER
    update_strs = []
    for color, positions in color_to_pos.items():
        coords = [pos_to_xy(pos, width) for pos in positions]
        coords = explode_coords(coords)
        color_name = list(palette)[color]
        update_strs.append(f"{color_name}: {len(coords)}")
        draw.point(coords, (color, 0xFF))
    print(f"Updates: {', '.join(update_strs)}")


def explode_coords(coords, multiplier=MULTIPLIER):
    new_coords = []
    for x, y in coords:
        for i in range(multiplier):
            for j in range(multiplier):
                new_coords.append((x * multiplier + i, y * multiplier + j))
    return new_coords


def draw_square(redis, x, y, size, width, color_name, check=False):
    if color_name not in palette:
        raise ValueError(f"Invalid color {color_name}")
    color = list(palette).index(color_name)
    for i in range(x, x + size):
        for j in range(y, y + size):
            update_pos(redis, xy_to_pos(i, j, width), color, check=check)


def get_update_image(redis: Redis, cursor: int, width: int, height: int):
    image = base_image((width, height))
    cursor, updates = get_updates(redis, cursor)
    draw_updates(image, updates)
    return cursor, image


def save_data(redis: Redis, filename: str = "backup.dat"):
    image_bytes = redis.get("image")
    with open(filename, "wb") as fp:
        fp.write(image_bytes)


def restore_data(redis: Redis, filename: str = "backup.dat", width=50, height=50):
    with open(filename, "rb") as fp:
        image_bytes = fp.read()
    cursor = int(redis.get("cursor")) + 1
    redis.delete("updates")
    redis.delete("image")
    starting = {}
    bitfield = redis.bitfield("image")
    flush_counter = 0
    for i in range(width):
        for j in range(height):
            pos = xy_to_pos(i, j, width)
            starting[pos] = cursor
            bitfield.set("u8", f"#{pos}", image_bytes[pos])
            flush_counter += 1
            if flush_counter > FLUSH_INTERVAL:
                bitfield.execute()
                redis.zadd("updates", starting)
                starting = {}
                flush_counter = 0
    if flush_counter > 0:
        bitfield.execute()
        redis.zadd("updates", starting)
    redis.set("cursor", cursor)
