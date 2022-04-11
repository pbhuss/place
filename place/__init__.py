from flask import Flask
from flask_caching import Cache

config = {
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "TEMPLATES_AUTO_RELOAD": True,
}


cache = Cache()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(config)
    cache.init_app(app)

    from place import routes

    app.register_blueprint(routes.bp)

    return app
