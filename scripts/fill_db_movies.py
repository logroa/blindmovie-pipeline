import os
from dotenv import load_dotenv
import psycopg2
import csv

load_dotenv()

DB_USERNAME = os.getenv('DB_USERNAME')
DB_PASSWORD = os.getenv('DB_PASSWORD') 
DB_PORT = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_ENDPOINT = os.getenv('DB_ENDPOINT')

TMDB_URL=os.getenv('TMDB_URL')
TMDB_KEY=os.getenv('TMDB_KEY')

try:
    db_conn = psycopg2.connect(
        database=DB_NAME,
        user=DB_USERNAME,
        password=DB_PASSWORD,
        host=DB_ENDPOINT,
        port=DB_PORT
    )
    print("Successful DB connection.")
except:
    print("DB connection failed")
    exit(1)

cur = db_conn.cursor()
# with open('archive/tmdb_5000_movies.csv') as f:
#     reader = csv.reader(f)
#     count = 0
#     for row in reader:
#         id = row[3]

#         og_title = row[6]
#         title = og_title.replace("'", "''")

#         release_year = row[11].split('-')[0]
#         if count > 0:
#             cur.execute(f'''
#                 INSERT INTO movies (imdb_id, title, year_released) VALUES ({id}, '{title}', {release_year});
#             ''')
#             db_conn.commit()
#             print(f'{title} - {release_year} added to DB')
#         count += 1
with open('archive/TMDB 10000 Movies Dataset.csv') as f:
    reader = csv.reader(f)
    count = 0
    for row in reader:
        id = row[0]

        og_title = row[2]
        title = og_title.replace("'", "''")

        release_year = row[5].split('-')[0]
        if count > 0:

            # cur.execute(f'''
            #     SELECT imdb_id FROM movies where imdb_id = {id};
            # ''')

            # if cur.fetchone():
            #     print(f'{title} already in DB.')
            #     continue

            # cur.execute(f'''
            #     INSERT INTO movies (imdb_id, title, year_released) VALUES ({id}, '{title}', {release_year});
            # ''')
            cur.execute(f'''
                UPDATE movies SET year_released = {release_year} WHERE imdb_id = {id};
            ''')
            db_conn.commit()
            print(f'{title} - {release_year} added to DB')
        count += 1