from flask import Blueprint, render_template

bp = Blueprint('pages', __name__)

#Declare routes for the pages blueprint (tells app the URL for each page and the function to call when that URL is accessed)
@bp.route('/')
def home():
    return render_template('index.html')

@bp.route('/contacts')
def contacts():
     return render_template('contacts.html')

@bp.route('/publications')
def publications():
      return render_template('publications.html')