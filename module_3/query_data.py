import psycopg
from decimal import Decimal

#connect to the PostgreSQL database using psycopg and the connection parameters.
connection = psycopg.connect(
     user="postgres",
     dbname='applicant_db'
 )

def convert_decimal(value):
    if isinstance(value, Decimal):
        return float(value)
    return value

def execute_query(connection, query):

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

question_query_dict = {
    #Question/Query 1
    '1) How many entries do you have in your database who have applied for Fall 2026?': 

    """SELECT COUNT(*) 
    FROM public.applicants 
    WHERE term = 'Fall 2026';""",

    #Question/Query 2
    '2) What percentage of entries are from international students (not American or Other) (to two decimal places)?':

    """SELECT ROUND(COUNT(*) / (SELECT COUNT(*) FROM public.applicants)::DECIMAL * 100.00,2) AS percentage_international
        FROM public.applicants 
        WHERE us_or_international NOT IN ('American', 'Other') 
            AND us_or_international IS NOT NULL;""",

     #Question/Query 3
    '3) What is the average GPA, GRE, GRE V, GRE AW of applicants who provide these metrics?':

    """SELECT ROUND(AVG(gpa)::numeric, 2) AS average_gpa,
    ROUND(AVG(gre)::numeric, 2) AS average_gre,
    ROUND(AVG(gre_v)::numeric, 2) AS average_gre_v,
    ROUND(AVG(gre_aw)::numeric, 2) AS average_gre_aw
    FROM public.applicants;""",

     #Question/Query 4
    '4) What is the average GPA of American students in Fall 2026?':

    """SELECT ROUND(AVG(gpa)::numeric, 2) AS average_gpa
        FROM public.applicants
        WHERE us_or_international = 'American' AND term = 'Fall 2026';""",

    #Question/Query 5
    '5) What percent of entries for Fall 2026 are Acceptances (to two decimal places)?':

    #This is better than numbers 2's approach because it doesn't require a subquery to get the total count of entries for Fall 2026. Clever 
    """SELECT ROUND(AVG(CASE WHEN status ILIKE '%Accept%' THEN 1 ELSE 0 END)::numeric * 100, 2) AS acceptance_percentage
        FROM public.applicants
        WHERE term = 'Fall 2026';""",

     #Question/Query 6
    '6) What is the average GPA of applicants who applied for Fall 2026 who are Acceptances?':

    """SELECT ROUND(AVG(gpa)::numeric, 2) AS average_gpa
        FROM public.applicants
        WHERE term = 'Fall 2026' AND status ILIKE '%Accept%';""",

     #Question/Query 7
    '7) How many entries are from applicants who applied to JHU for a masters degrees in Computer Science?':

    """SELECT COUNT(*) 
        FROM public.applicants
        WHERE program ILIKE '%Johns Hopkins University%' 
            AND degree ILIKE '%Masters%' 
            AND program ILIKE '%Computer Science%';""",

     #Question/Query 8
     '8) How many entries from 2026 are acceptances from applicants who applied to Georgetown University, MIT, Stanford University, or Carnegie Mellon University for a PhD in Computer Science?':

    """SELECT COUNT(*) 
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

    SELECT CASE WHEN total_count_llm = total_count_downloaded THEN 'No' ELSE 'Yes' END AS llm_discrepancy
    FROM CTE_LLM CROSS JOIN CTE_DOWNLOADED ;""",

    #Question/Query 10
    '10) Among Fall 2026 applicants, how does the acceptance rate differ by applicant type (American, International, Other)?':

    """SELECT us_or_international,
    COUNT(*) AS total_applicants,
    COUNT(*) FILTER (WHERE status ILIKE 'Accepted%') AS accepted_applicants,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status ILIKE 'Accepted%') / COUNT(*), 2) AS acceptance_rate_pct
    FROM public.applicants
    WHERE term = 'Fall 2026'
    AND us_or_international IS NOT NULL
    GROUP BY us_or_international
    ORDER BY acceptance_rate_pct DESC;""",

    #Question/Query 11
    '11) For Computer Science applicants, which universities have the most acceptances (at least 20) in the dataset when using the LLM-generated university/program fields?':

    """SELECT llm_generated_university,
    COUNT(*) AS acceptance_count
    FROM public.applicants
    WHERE status ILIKE 'Accept%'
    AND llm_generated_program ILIKE '%Computer Science%'
    AND llm_generated_university IS NOT NULL
    GROUP BY llm_generated_university
    HAVING COUNT(*) > 20
    ORDER BY acceptance_count DESC, llm_generated_university;"""

}

# Execute the queries and store the answers in a list
answer_list = [execute_query(connection, query) for query in question_query_dict.values()]

#Print the questions and answers iteratively 
for key, answer in zip(question_query_dict.keys(), answer_list):
    print(f"{key} Answer: {answer}\n")