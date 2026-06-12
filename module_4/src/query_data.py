import psycopg
from decimal import Decimal

import os

def get_database_url():
    """Return the ``DATABASE_URL`` environment variable if set.

    :returns: PostgreSQL connection URL, or ``None`` if unset.
    :rtype: str | None
    """
    return os.environ.get("DATABASE_URL")

def get_connection():
    """Open a connection to the applicant database.

    Uses ``DATABASE_URL`` when available; otherwise connects to the local
    ``applicant_db`` database as ``postgres``.

    :returns: Active psycopg connection.
    :rtype: psycopg.Connection
    """
    database_url = get_database_url()
    if database_url:
        return psycopg.connect(conninfo=database_url)
    return psycopg.connect(user="postgres", dbname="applicant_db")

connection = get_connection()

def convert_decimal(value):
    """Convert PostgreSQL ``Decimal`` values to ``float`` for display.

    :param value: Query result cell value.
    :type value: object
    :returns: ``float`` if ``value`` is a ``Decimal``; otherwise ``value``.
    :rtype: object
    """
    if isinstance(value, Decimal):
        return float(value)
    return value

def execute_query(connection, query):
    """Execute a SQL query and return a formatted result.

    :param connection: Open psycopg database connection.
    :type connection: psycopg.Connection
    :param query: SQL statement to execute.
    :type query: str
    :returns: Scalar, tuple, or list depending on row/column count; ``None``
        if no rows returned.
    :rtype: object | None
    """
    #Set up cursor and execute SQL queries to answer the questions about the data in the applicants table.
    with connection.cursor() as cur:
        
        cur.execute(query)
        results = cur.fetchall()
    
    #Format the results based on the number of rows and columns returned by the query to make it easier to read.
    if not results:
        answer = None
    elif len(results) == 1 and len(results[0]) == 1:
        answer = convert_decimal(results[0][0])
    elif len(results) == 1:
        answer = tuple(convert_decimal(x) for x in results[0])
    elif len(results[0]) == 1:
        answer = [convert_decimal(row[0]) for row in results]
    else:
        answer = [tuple(convert_decimal(x) for x in row) for row in results]

    return answer

#Pair question with query in a dictonary
question_query_dict = {
    #Question/Query 1
    '1) How many entries do you have in your database who have applied for Fall 2026?': 

    """SELECT 'Applicant Count:', COUNT(*)
    FROM public.applicants 
    WHERE term = 'Fall 2026';""",

    #Question/Query 2
    '2) What percentage of entries are from international students (not American or Other) (to two decimal places)?':

    """SELECT 'Percent International:', ROUND(COUNT(*) / (SELECT COUNT(*) FROM public.applicants)::DECIMAL * 100.00,2) AS percentage_international
        FROM public.applicants 
        WHERE us_or_international NOT IN ('American', 'Other') 
            AND us_or_international IS NOT NULL;""",

     #Question/Query 3
    '3) What is the average GPA, GRE, GRE V, GRE AW of applicants who provide these metrics?':

    """SELECT 'Average GPA:', ROUND(AVG(gpa)::numeric, 2) AS average_gpa,
    'Average_gre', ROUND(AVG(gre)::numeric, 2) AS average_gre,
    'Average_gre_v', ROUND(AVG(gre_v)::numeric, 2) AS average_gre_v,
    'Average_gre_aw', ROUND(AVG(gre_aw)::numeric, 2) AS average_gre_aw
    FROM public.applicants;""",

     #Question/Query 4
    '4) What is the average GPA of American students in Fall 2026?':

    """SELECT 'Average GPA American:', ROUND(AVG(gpa)::numeric, 2) AS average_gpa
        FROM public.applicants
        WHERE us_or_international = 'American' AND term = 'Fall 2026';""",

    #Question/Query 5
    '5) What percent of entries for Fall 2026 are Acceptances (to two decimal places)?':

    #This is better than numbers 2's approach because it doesn't require a subquery to get the total count of entries for Fall 2026. Clever 
    """SELECT 'Acceptance Percent:', ROUND(AVG(CASE WHEN status ILIKE '%Accept%' THEN 1 ELSE 0 END)::numeric * 100, 2) AS acceptance_percentage
        FROM public.applicants
        WHERE term = 'Fall 2026';""",

     #Question/Query 6
    '6) What is the average GPA of applicants who applied for Fall 2026 who are Acceptances?':

    """SELECT 'Average GPA Acceptance:', ROUND(AVG(gpa)::numeric, 2) AS average_gpa
        FROM public.applicants
        WHERE term = 'Fall 2026' AND status ILIKE '%Accept%';""",

     #Question/Query 7
    '7) How many entries are from applicants who applied to JHU for a masters degrees in Computer Science?':

    """SELECT 'JHU MS in Computer Science', COUNT(*) 
        FROM public.applicants
        WHERE program ILIKE '%Johns Hopkins University%' 
            AND degree ILIKE '%Masters%' 
            AND program ILIKE '%Computer Science%';""",

     #Question/Query 8
     '8) How many entries from 2026 are acceptances from applicants who applied to Georgetown University, MIT, Stanford University, or Carnegie Mellon University for a PhD in Computer Science?':

    """SELECT '2026 Computer Science PhD Program Acceptances from Georgetown University, MIT, Stanford University, or Carnegie Mellon University:', COUNT(*) 
        FROM public.applicants
        WHERE term = 'Fall 2026' 
            AND status ILIKE '%Accept%' 
            AND degree ILIKE '%PhD%' 
            AND program ILIKE '%Computer Science%' 
            AND (
                program ILIKE '%Georgetown University%' OR 
                program ILIKE '%MIT%' OR 
                program ILIKE '%Stanford University%' OR 
                program ILIKE '%Carnegie Mellon University%'
            );""",
        
     #Question/Query 9
    '9) Do your numbers for question 8 change if you use LLM Generated Fields (rather than your downloaded fields)?':

       """WITH CTE_LLM AS (
       
       SELECT COUNT(*) AS total_count_llm
        FROM public.applicants
        WHERE term = 'Fall 2026' 
            AND status ILIKE '%Accept%' 
            AND degree ILIKE '%PhD%' 
            AND llm_generated_program ILIKE '%Computer Science%' 
            AND (
                llm_generated_university ILIKE '%Georgetown University%' OR 
                llm_generated_university ILIKE '%MIT%' OR 
                llm_generated_university ILIKE '%Stanford University%' OR 
                llm_generated_university ILIKE '%Carnegie Mellon University%')
            )
            
        ,CTE_DOWNLOADED AS (

        SELECT COUNT(*) AS total_count_downloaded
        FROM public.applicants
        WHERE term = 'Fall 2026' 
            AND status ILIKE '%Accept%' 
            AND degree ILIKE '%PhD%' 
            AND program ILIKE '%Computer Science%' 
            AND (
                program ILIKE '%Georgetown University%' OR 
                program ILIKE '%MIT%' OR 
                program ILIKE '%Stanford University%' OR 
                program ILIKE '%Carnegie Mellon University%')
            )

    SELECT 'LLM Generated Fields change your previous answer:', CASE WHEN total_count_llm = total_count_downloaded THEN 'No' ELSE 'Yes' END AS llm_discrepancy
    FROM CTE_LLM CROSS JOIN CTE_DOWNLOADED ;""",

    #Question/Query 10
    '10) Among Fall 2026 applicants, how does the acceptance rate differ by applicant type (American, International, Other)?':

    """SELECT 'Fall 2026 Acceptance Rate by applicant type:', us_or_international,
    'Total Applicants:', COUNT(*) AS total_applicants,
    'Accepted Applicants:', COUNT(*) FILTER (WHERE status ILIKE 'Accepted%') AS accepted_applicants,
    'Acceptance Rate:', ROUND(100.0 * COUNT(*) FILTER (WHERE status ILIKE 'Accepted%') / COUNT(*), 2) AS acceptance_rate_pct
    FROM public.applicants
    WHERE term = 'Fall 2026'
    AND us_or_international IS NOT NULL
    GROUP BY us_or_international
    ORDER BY acceptance_rate_pct DESC;""",

    #Question/Query 11
    '11) For Computer Science applicants, which universities have the most acceptances (at least 20) in the dataset when using the LLM-generated university/program fields?':

    """SELECT 'Universities with at least 20 acceptances in Computer Science:', llm_generated_university,
    COUNT(*) AS acceptance_count
    FROM public.applicants
    WHERE status ILIKE 'Accept%'
    AND llm_generated_program ILIKE '%Computer Science%'
    AND llm_generated_university IS NOT NULL
    GROUP BY llm_generated_university
    HAVING COUNT(*) > 20
    ORDER BY acceptance_count DESC, llm_generated_university;"""

}

#Function to execute and store results as a module that can be imported into the Flask app to render the results on the webpage. 
def get_all_query_results(connection):
    """Run all analysis queries and pair each with its question text.

    :param connection: Open psycopg database connection (closed on return).
    :type connection: psycopg.Connection
    :returns: List of ``(question, answer)`` tuples.
    :rtype: list[tuple[str, object]]
    """
    try:
        answer_list = [execute_query(connection, query) for query in question_query_dict.values()]
        return list(zip(question_query_dict.keys(), answer_list))
    finally:
        connection.close()

if __name__ == "__main__":
    #Print the results of all of the queries to the console if not imported as a module
    query_results = get_all_query_results(connection=connection)
    for key, answer in query_results:
        print(f"{key} Answer: {answer}\n")