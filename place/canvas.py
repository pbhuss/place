from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple

import PIL.Image
import PIL.ImageDraw
import yaml

from place.util import get_redis
from place.util import pos_to_xy
from place.util import xy_to_pos


class Color(NamedTuple):

    name: str
    hex_color: str

    @property
    def rgb(self) -> tuple[int, ...]:
        s_hex = self.hex_color.lstrip("#")
        return tuple(int(s_hex[i : i + 2], 16) for i in (0, 2, 4))


class Palette:
    def __init__(self, colors: Iterable[Color]):
        self._color_map = {}
        self._color_names = []
        for color in colors:
            self._color_map[color.name] = color
            self._color_names.append(color.name)

    def __getitem__(self, item: str | int) -> Color:
        if isinstance(item, str):
            return self._color_map[item]
        elif isinstance(item, int):
            return self._color_map[self._color_names[item]]
        raise ValueError(f"Invalid item type: {type(item)}")

    def __iter__(self) -> Iterator:
        return iter(self._color_map.values())

    def __len__(self) -> int:
        return len(self._color_names)

    def __contains__(self, color: Color | str) -> bool:
        if isinstance(color, Color):
            color_name = color.name
        else:
            color_name = color
        return color_name in self._color_map

    def index(self, color: Color | str) -> int:
        if isinstance(color, Color):
            color_name = color.name
        else:
            color_name = color
        return self._color_names.index(color_name)

    def to_pillow(self) -> list[int]:
        result: list[int] = []
        for color in self._color_map.values():
            result.extend(color.rgb)
        return result


class PaletteLoader:
    def __init__(self, path: str = "config/palette.yaml"):
        with open(path) as fp:
            self._config = yaml.safe_load(fp)

    def __contains__(self, palette_name: str) -> bool:
        return palette_name in self._config

    def load(self, name: str = "default") -> Palette:
        if name not in self:
            raise ValueError(f"Missing palette: {name}")
        return Palette(
            Color(name, hex_color) for name, hex_color in self._config[name].items()
        )

    def for_json(self, name: str = "default") -> list[tuple[str, str]]:
        return list(self._config[name].items())


@dataclass
class CanvasUpdate:

    new_cursor: int
    color_positions: dict[int, list[int]]

    def __bool__(self) -> bool:
        return len(self.color_positions) > 0


class Canvas:

    FLUSH_INTERVAL = 5000
    MULTIPLIER: int = 20

    def __init__(self, width: int, height: int, palette: Palette):
        self.width = width
        self.height = height
        self.palette = palette
        self.palette_flat = palette.to_pillow()
        self.redis = get_redis()

    def base_image(self) -> PIL.Image.Image:
        size = (self.width * self.MULTIPLIER, self.height * self.MULTIPLIER)
        # "PA" is a valid value for mode
        image = PIL.Image.new("PA", size)  # type: ignore[arg-type]
        image.putpalette(self.palette_flat, "RGB")
        return image

    def initialize_canvas(self) -> None:
        cursor: int = self.redis.incr("cursor")
        self.redis.delete("updates")
        self.redis.delete("image")
        base_color = self.palette.index("white")
        starting: dict[str | bytes, int] = {}
        bitfield = self.redis.bitfield("image")
        flush_counter = 0
        for i in range(self.width):
            for j in range(self.height):
                pos = str(xy_to_pos(i, j, self.width))
                starting[pos] = cursor
                bitfield.set("u8", f"#{pos}", base_color)
                flush_counter += 1
                if flush_counter > self.FLUSH_INTERVAL:
                    bitfield.execute()
                    self.redis.zadd("updates", starting)
                    starting = {}
                    flush_counter = 0
        if flush_counter > 0:
            bitfield.execute()
            self.redis.zadd("updates", starting)

    def refresh(self) -> CanvasUpdate:
        cursor = self.redis.get("cursor")
        assert isinstance(cursor, bytes)
        image_bytes = self.redis.get("image")
        assert isinstance(image_bytes, bytes)
        color_positions = defaultdict(list)
        for pos in range(0, self.width * self.height):
            color = image_bytes[pos]
            color_positions[color].append(pos)
        return CanvasUpdate(int(cursor), color_positions)

    def get_update(self, cursor: int) -> CanvasUpdate:
        pipeline = self.redis.pipeline()
        pipeline.get("cursor")
        # str is a valid type for start and end
        pipeline.zrange(
            "updates",
            start=f"({cursor}",  # type: ignore[arg-type]
            end="+inf",  # type: ignore[arg-type]
            byscore=True,
        )
        new_cursor, positions = pipeline.execute()
        bitfield = self.redis.bitfield("image")
        for pos in positions:
            bitfield.get("u8", f"#{pos.decode()}")
        colors = bitfield.execute()
        color_positions = defaultdict(list)
        for color, pos in zip(colors, positions):
            color_positions[color].append(int(pos))
        new_cursor = int(new_cursor)
        if new_cursor > cursor + 1:
            # EXPERIMENTAL
            new_cursor -= 1
        return CanvasUpdate(new_cursor, color_positions)

    def update_pos(self, pos: int, color: int, check: bool = False) -> int | None:
        if check:
            (prev_color,) = self.redis.bitfield("image").get("u8", f"#{pos}").execute()
        if not check or color != prev_color:
            self.redis.bitfield("image").set("u8", f"#{pos}", color).execute()
            cursor = self.redis.incr("cursor")
            self.redis.zadd("updates", {str(pos): cursor})
            return int(cursor)
        return None

    def save_data(self, filename: str = "backup.dat") -> None:
        image_bytes = self.redis.get("image")
        assert isinstance(image_bytes, bytes)
        with open(filename, "wb") as fp:
            fp.write(image_bytes)

    def restore_data(self, filename: str = "backup.dat") -> None:
        with open(filename, "rb") as fp:
            image_bytes = fp.read()
        cursor = self.redis.get("cursor")
        assert isinstance(cursor, bytes)
        cursor = int(cursor) + 1
        self.redis.delete("updates")
        self.redis.delete("image")
        starting: dict[str | bytes, int] = {}
        bitfield = self.redis.bitfield("image")
        flush_counter = 0
        for i in range(self.width):
            for j in range(self.height):
                pos = xy_to_pos(i, j, self.width)
                starting[str(pos)] = cursor
                bitfield.set("u8", f"#{pos}", image_bytes[pos])
                flush_counter += 1
                if flush_counter > self.FLUSH_INTERVAL:
                    bitfield.execute()
                    self.redis.zadd("updates", starting)
                    starting = {}
                    flush_counter = 0
        if flush_counter > 0:
            bitfield.execute()
            self.redis.zadd("updates", starting)
        self.redis.set("cursor", cursor)

    def draw_square(
        self,
        x: int,
        y: int,
        size: int,
        color: Color,
        check: bool = False,
    ) -> None:
        color_num = palette.index(color)
        for i in range(x, x + size):
            for j in range(y, y + size):
                self.update_pos(xy_to_pos(i, j, self.width), color_num, check=check)

    def draw_update(self, image: PIL.Image.Image, update: CanvasUpdate) -> None:
        draw = PIL.ImageDraw.Draw(image)
        width, height = image.size
        width = width // self.MULTIPLIER
        for color, positions in update.color_positions.items():
            coords = [pos_to_xy(pos, width) for pos in positions]
            coords = explode_coords(coords)
            # tuple[int, int] is a valid type for fill
            draw.point(coords, (color, 0xFF))  # type: ignore[arg-type]


palette_loader = PaletteLoader()
palette = palette_loader.load("default")
canvas = Canvas(50, 50, palette)


def explode_coords(
    coords: Iterable[tuple[int, int]], multiplier: int = canvas.MULTIPLIER
) -> list[tuple[int, int]]:
    new_coords = []
    for x, y in coords:
        for i in range(multiplier):
            for j in range(multiplier):
                new_coords.append((x * multiplier + i, y * multiplier + j))
    return new_coords
