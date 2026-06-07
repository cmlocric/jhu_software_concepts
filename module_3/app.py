import psycopg
from flask import Flask, render_template
from query_data import get_all_query_results

app = Flask(__name__)

def get_db_connection(dbname, user):
    connection = psycopg.connect(
        dbname=dbname,
        user=user
    )
    return connection

@app.route('/')
def index():
    connection = get_db_connection(dbname="applicant_db", user="postgres")
    try:
        query_results = get_all_query_results(connection)

        return render_template(
            'index.html',
            query_results=query_results
        )
    finally:
        connection.close()

@app.route('/pull-data')
def pull_data():
    return "Pull Data page"

@app.route('/update-analysis')
def update_analysis():
    return "Update Analysis page"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
