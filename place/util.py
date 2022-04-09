import PIL.Image
from redis.client import Redis


def get_redis():
    return Redis.from_url("redis://redis:6379/0")


def pos_to_xy(pos: int, width: int) -> tuple[int, int]:
    return pos % width, pos // width


def xy_to_pos(x: int, y: int, width: int) -> int:
    return y * width + x


def save_image(image: PIL.Image.Image, io):
    image.convert(mode="RGBA", palette=PIL.Image.Palette.ADAPTIVE).save(
        io, format="PNG"
    )
