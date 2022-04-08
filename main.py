from collections import defaultdict
from collections.abc import Iterable
from typing import NamedTuple
from typing import Optional
from typing import Union

import PIL.Image
import PIL.ImageDraw
import yaml
from redis.client import Redis


def pos_to_xy(pos: int, width: int) -> tuple[int, int]:
    return pos % width, pos // width


def xy_to_pos(x: int, y: int, width: int) -> int:
    return y * width + x


class Color(NamedTuple):

    name: str
    hex_color: str

    @property
    def rgb(self):
        s_hex = self.hex_color.lstrip("#")
        return tuple(int(s_hex[i : i + 2], 16) for i in (0, 2, 4))


class Palette:
    def __init__(self, colors: Iterable[Color]):
        self._color_map = {}
        self._color_names = []
        for color in colors:
            self._color_map[color.name] = color
            self._color_names.append(color.name)

    def __getitem__(self, item: Union[str, int]) -> Color:
        if isinstance(item, str):
            return self._color_map[item]
        elif isinstance(item, int):
            return self._color_map[self._color_names[item]]
        raise ValueError(f"Invalid item type: {type(item)}")

    def __iter__(self):
        return iter(self._color_map.values())

    def __len__(self):
        return len(self._color_names)

    def __contains__(self, item):
        return item in self._color_map

    def index(self, color_name: str) -> int:
        return self._color_names.index(color_name)

    def to_pillow(self) -> list[int]:
        result = []
        for color in self._color_map.values():
            result.extend(color.rgb)
        return result


class PaletteLoader:
    def __init__(self, path: str = "colors.yaml"):
        with open(path) as fp:
            self._config = yaml.safe_load(fp)

    def __contains__(self, item):
        return item in self._config

    def load(self, name: str = "default") -> Palette:
        if name not in self:
            raise ValueError(f"Missing palette: {name}")
        return Palette(
            Color(name, hex_color) for name, hex_color in self._config[name].items()
        )

    def for_json(self, name: str = "default"):
        return list(self._config[name].items())


palette_loader = PaletteLoader()
palette = palette_loader.load()
palette_flat = palette.to_pillow()


MULTIPLIER: int = 20


def base_image(size: tuple[int, int]) -> PIL.Image.Image:
    size = (size[0] * MULTIPLIER, size[1] * MULTIPLIER)
    image = PIL.Image.new("PA", size)
    image.putpalette(palette_flat, "RGB")
    return image


def save_image(image, io):
    image.convert(mode="RGBA", palette=PIL.Image.Palette.ADAPTIVE).save(
        io, format="PNG"
    )


FLUSH_INTERVAL: int = 5000


def initialize_image(redis: Redis, width: int = 10, height: int = 10) -> None:
    cursor: int = redis.incr("cursor")
    redis.delete("updates")
    redis.delete("image")
    base_color = palette.index("white")
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


def get_updates(redis: Redis, cursor: int) -> tuple[int, dict[int, list[int]]]:
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


def update_pos(redis, pos, color, check=False) -> Optional[int]:
    if check:
        (prev_color,) = redis.bitfield("image").get("u8", f"#{pos}").execute()
    if not check or color != prev_color:
        redis.bitfield("image").set("u8", f"#{pos}", color).execute()
        cursor = redis.incr("cursor")
        redis.zadd("updates", {pos: cursor})
        return int(cursor)


def draw_updates(image: PIL.Image.Image, color_to_pos: dict[int, tuple[int, int]]):
    draw = PIL.ImageDraw.Draw(image)
    width, height = image.size
    width = width / MULTIPLIER
    for color, positions in color_to_pos.items():
        coords = [pos_to_xy(pos, width) for pos in positions]
        coords = explode_coords(coords)
        draw.point(coords, (color, 0xFF))


def explode_coords(
    coords: Iterable[tuple[int, int]], multiplier: int = MULTIPLIER
) -> list[tuple[int, int]]:
    new_coords = []
    for x, y in coords:
        for i in range(multiplier):
            for j in range(multiplier):
                new_coords.append((x * multiplier + i, y * multiplier + j))
    return new_coords


def draw_square(
    redis: Redis,
    x: int,
    y: int,
    size: int,
    width: int,
    color_name: str,
    check: bool = False,
) -> None:
    if color_name not in palette:
        raise ValueError(f"Invalid color {color_name}")
    color = palette.index(color_name)
    for i in range(x, x + size):
        for j in range(y, y + size):
            update_pos(redis, xy_to_pos(i, j, width), color, check=check)


def get_update_image(
    redis: Redis, cursor: int, width: int, height: int
) -> tuple[int, PIL.Image.Image]:
    image = base_image((width, height))
    cursor, updates = get_updates(redis, cursor)
    draw_updates(image, updates)
    return cursor, image


def save_data(redis: Redis, filename: str = "backup.dat") -> None:
    image_bytes = redis.get("image")
    with open(filename, "wb") as fp:
        fp.write(image_bytes)


def restore_data(
    redis: Redis, filename: str = "backup.dat", width: int = 50, height: int = 50
) -> None:
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
