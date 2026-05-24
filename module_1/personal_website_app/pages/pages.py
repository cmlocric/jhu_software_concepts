from flask import Blueprint, render_template

bp = Blueprint('pages', __name__)

@bp.route('/')
def home():
    return render_template('index.html')

@bp.route('/about')
def about():
    return 'The about page'

@bp.route('/contacts')
def contacts():
    return 'For more info, contact me'