import psycopg

# DB connection parameters
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "applicant_db",
    "user": "postgres"
}

column_list = [

      'program',
      'comments',
      'date_added',
       'url',
       'status',
       'term',
       'us_or_international',
       'gpa',
       'gre',
       'gre_v',
       'gre_aw',
       'degree',
       'llm_generated_program',
       'llm_generated_university'
       
       ]

#for col in column_list:
col = 'term'

with psycopg.connect(**DB_CONFIG) as connection:
    with connection.cursor() as cur:
        cur.execute(f"""
        
        SELECT {col}, COUNT(*) AS total
        FROM public.applicants_raw
        GROUP BY {col}
        ORDER BY {col}
        LIMIT 15;""")

        print(cur.fetchall())