from flask import Blueprint, render_template

bp = Blueprint('pages', __name__)

@bp.route('/')
def home():
    return render_template('base.html')

@bp.route('/contacts')
def contacts():
    return """<h2>Contact Information:</h2>
    <p>Email: clocricchio@gmail.com</p>
    <p><a href="https://www.linkedin.com/in/christopher-locricchio" target="_blank">LinkedIn</a></p>
    <p><a href="https://github.com/cmlocric" target="_blank">github.com/cmlocric</a></p>
    <p><a href="/" class="btn btn-primary">Back to Home</a></p>
    """

@bp.route('/publications')
def publications():
    return """<h2>Publications:</h2>
    <p>Module 1: Personal Website App</p>
    <p>My first personal developer website that includes a biography, contact information/links, 
        and details about current and future Python projects.</p>
    <p><a href="https://github.com/cmlocric/jhu_software_concepts/tree/main/module_1" target="_blank">module_1_repository</a></p>
    <p><a href="/" class="btn btn-primary">Back to Home</a></p>
    """