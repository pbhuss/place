import subprocess
from io import BytesIO

from flask import abort
from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import make_response
from flask import render_template
from flask import request
from flask import Response
from flask import send_file

from place import cache
from place.canvas import canvas
from place.canvas import palette
from place.canvas import palette_loader
from place.util import get_redis
from place.util import save_image
from place.util import xy_to_pos


bp = Blueprint("routes", __name__)


@bp.route("/")
def index() -> str:
    sha = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()
    return render_template("index.html", sha=sha, env=current_app.config["ENV"])


@bp.route("/image/full")
def get_image_full() -> Response:
    cached_val = cache.get("full_image")
    if cached_val:
        cursor, image = cached_val
        update = canvas.get_update(cursor)
    else:
        image = canvas.base_image()
        update = canvas.refresh()
    canvas.draw_update(image, update)

    cache.set("full_image", (update.new_cursor, image))

    buffer = BytesIO()
    save_image(image, buffer)
    buffer.seek(0)

    response = make_response(send_file(buffer, mimetype="image/png"))
    response.headers["X-Cursor"] = update.new_cursor
    return response


@bp.route("/image/<int:cursor>")
def get_image_updates(cursor: int) -> Response:
    image = canvas.base_image()
    update = canvas.get_update(cursor)
    if not update:
        resp = Response(status=200)
        resp.headers["X-Cursor"] = cursor
        return resp
    canvas.draw_update(image, update)
    buffer = BytesIO()
    save_image(image, buffer)
    buffer.seek(0)
    response = make_response(send_file(buffer, mimetype="image/png"))
    response.headers["X-Cursor"] = cursor
    return response


@bp.route("/image/cursor")
def get_image_cursor() -> bytes:
    rc = get_redis()
    cursor = rc.get("cursor")
    assert isinstance(cursor, bytes)
    return cursor


@bp.route("/init")
def init() -> str:
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
def clear_image() -> Response:
    if current_app.config["ENV"] != "development":
        abort(404)
    canvas.draw_square(0, 0, canvas.width, palette["white"], True)
    return Response(status=200)
