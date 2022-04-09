import subprocess
from io import BytesIO

from flask import Blueprint
from flask import jsonify
from flask import make_response
from flask import render_template
from flask import request
from flask import Response
from flask import send_file

from place import cache
from place.canvas import canvas
from place.canvas import palette_loader
from place.util import get_redis
from place.util import save_image
from place.util import xy_to_pos


bp = Blueprint("routes", __name__)


@bp.route("/")
def index():
    sha = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()
    return render_template("index.html", sha=sha)


@bp.route("/image/full")
def get_image_full():
    cached_val = cache.get("full_image")
    if cached_val:
        cursor, image = cached_val
        print(f"{cursor=}")
        cursor, updates = canvas.get_updates(cursor)
    else:
        image = canvas.base_image()
        cursor, updates = canvas.refresh()
    canvas.draw_updates(image, updates)

    cache.set("full_image", (cursor, image))

    buffer = BytesIO()
    save_image(image, buffer)
    buffer.seek(0)

    response = make_response(send_file(buffer, mimetype="image/png"))
    response.headers["X-Cursor"] = cursor
    return response


@bp.route("/image/<int:cursor>")
def get_image_updates(cursor: int):
    image = canvas.base_image()
    cursor, updates = canvas.get_updates(cursor)
    if not updates:
        resp = Response(status=200)
        resp.headers["X-Cursor"] = cursor
        return resp
    canvas.draw_updates(image, updates)
    buffer = BytesIO()
    save_image(image, buffer)
    buffer.seek(0)
    response = make_response(send_file(buffer, mimetype="image/png"))
    response.headers["X-Cursor"] = cursor
    return response


@bp.route("/image/cursor")
def get_image_cursor():
    rc = get_redis()
    return rc.get("cursor")


@bp.route("/init")
def init():
    rc = get_redis()
    if rc.exists("image", "cursor", "updates") == 3:
        return "Already initialized"
    canvas.initialize_canvas()
    return f"Initialized image size ({canvas.width}, {canvas.height})"


@bp.route("/image/place", methods=["POST"])
def place() -> Response:
    data = request.get_json()
    x = data["x"]
    y = data["y"]
    color = data["color"]
    canvas.update_pos(
        xy_to_pos(x // canvas.MULTIPLIER, y // canvas.MULTIPLIER, canvas.width),
        color,
        check=True,
    )
    return Response(status=200)


@bp.route("/colors")
def colors() -> Response:
    return jsonify(palette_loader.for_json("default"))


@bp.route("/image/clear", methods=["POST"])
def clear_image():
    canvas.draw_square(0, 0, canvas.width, "white", True)
    return Response(status=200)