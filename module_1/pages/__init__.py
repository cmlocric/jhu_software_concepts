from flask import Flask

from module_1.pages import pages

def create_app():
    app = Flask(__name__)

    app.register_blueprint(pages.bp)

    return app

def run_app(app, host, port):
    app.run(host=host, port=port, debug=True)
