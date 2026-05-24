from flask import Flask

from personal_website_app.pages import bp

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.register_blueprint(bp)
    return app

def run_app(app, host, port):
    app.run(host=host, port=port, debug=True)
