import os
import psycopg
from flask import Flask, render_template

app = Flask(__name__)

def get_db_connection(dbname, user):
    """A function to connect to the database"""

    connection = psycopg.connect(
        dbname=dbname,
        user=user
    )

    return connection

@app.route('/')
def index():
    conn = get_db_connection(dbname="studentCourses", user="postgres")
    cur = conn.cursor()
    cur.execute('SELECT * FROM courses;')
    courses = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', courses=courses)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
