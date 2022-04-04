from io import BytesIO

import yaml
from flask import Flask
from flask import jsonify
from flask import make_response
from flask import render_template
from flask import Response
from flask import send_file
from flask_caching import Cache
from redis.client import Redis

from main import base_image
from main import draw_updates
from main import get_updates
from main import initialize_image
from main import MULTIPLIER
from main import refresh2
from main import save_image
from main import update_pos
from main import xy_to_pos

config = {
    "DEBUG": False,  # some Flask specific configs
    "CACHE_TYPE": "SimpleCache",  # Flask-Caching related configs
    "CACHE_DEFAULT_TIMEOUT": 300,
    "TEMPLATES_AUTO_RELOAD": True,
}

size = width, height = (50, 50)

app = Flask(__name__)
# tell Flask to use the above defined config
app.config.from_mapping(config)
cache = Cache(app)


def get_redis():
    return Redis.from_url("redis://redis:6379/0")


@app.route("/image/full")
def full():
    rc = get_redis()
    cached_val = cache.get("full_image")
    if cached_val:
        cursor, image = cached_val
        print(f"{cursor=}")
        cursor, updates = get_updates(rc, cursor)
    else:
        image = base_image(size)
        cursor, updates = refresh2(rc, width, height)
    draw_updates(image, updates)

    cache.set("full_image", (cursor, image))

    buffer = BytesIO()
    save_image(image, buffer)
    buffer.seek(0)

    response = make_response(send_file(buffer, mimetype="image/png"))
    response.headers["X-Cursor"] = cursor
    return response


@app.route("/image/<int:cursor>")
def updates(cursor: int):
    rc = get_redis()
    image = base_image(size)
    cursor, updates = get_updates(rc, cursor)
    if not updates:
        resp = Response(status=200)
        resp.headers["X-Cursor"] = cursor
        return resp
    draw_updates(image, updates)
    buffer = BytesIO()
    save_image(image, buffer)
    buffer.seek(0)
    response = make_response(send_file(buffer, mimetype="image/png"))
    response.headers["X-Cursor"] = cursor
    return response


@app.route("/image/cursor")
def view_cursor():
    rc = get_redis()
    return rc.get("cursor")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/init")
def init():
    rc = get_redis()
    if rc.exists("image", "cursor", "updates") == 3:
        return "Already initialized"
    initialize_image(rc, width, height)
    return f"Initialized image size ({width}, {height})"


@app.route("/image/place/<int:x>/<int:y>/<int:color>")
def place(x: int, y: int, color: int):
    rc = get_redis()
    update_pos(
        rc, xy_to_pos(x // MULTIPLIER, y // MULTIPLIER, width), color, check=True
    )
    return Response(status=200)


# @app.route("/image/clear")
# def clear():
#     rc = get_redis()
#     draw_square(rc, 0, 0, width, width, "white", True)
#     return Response(status=200)


@app.route("/colors")
def colors():
    with open("colors.yaml") as fp:
        conf = yaml.safe_load(fp)
    return jsonify(list(conf["colors"].items()))
