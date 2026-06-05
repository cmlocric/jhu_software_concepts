#import os
import psycopg
from flask import Flask, render_template, request, redirect, url_for

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
    conn = get_db_connection(dbname="studentcourses", user="postgres")
    cur = conn.cursor()
    cur.execute('SELECT * FROM courses;')
    courses = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', courses=courses)

@app.route('/create/', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':
        id = request.form['id']
        name = request.form['name']
        instructor = request.form['instructor']
        room_number = request.form['room_number']
        print(id, name, instructor, room_number)

        conn = get_db_connection(dbname="studentcourses", user="postgres")
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO courses(id, name, instructor, room_number)
            VALUES (%s, %s, %s, %s)
        """, (id, name, instructor, room_number)
        )

        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    return render_template('create.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
