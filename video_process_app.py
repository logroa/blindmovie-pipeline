import os
import requests
import json
import urllib.parse
import pafy
import flask
from flask import Flask, render_template, request, redirect, jsonify, flash, url_for, session
import psycopg2
from dotenv import load_dotenv
import boto3
import hashlib
import uuid
from functools import wraps

# make this a flask rest API lol
# put on lambda i think - store in S3
# i'd like to do some front end caching on this shit too
# movie poster on answer screen ferdaaa
# track number of guesses per movie to inform search

###############################################################
########################## SET UP #############################
###############################################################

app = Flask(__name__)
app.secret_key = 'logan'
load_dotenv()

DB_USERNAME = os.getenv('DB_USERNAME')
DB_PASSWORD = os.getenv('DB_PASSWORD') 
DB_PORT = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_ENDPOINT = os.getenv('DB_ENDPOINT')

S3_BUCKET = os.getenv('S3_BUCKET')

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

S3_RESOURCE = boto3.resource('s3')

###############################################################
########################## HELPERS ############################
###############################################################

def find_user(id):
    cur = db_conn.cursor()
    cur.execute(f'''
        SELECT * FROM players WHERE id = {id};
    ''')
    return cur.fetchone()

def insert_machine_registration(ip, id):
    cur = db_conn.cursor()
    cur.execute(f'''
        INSERT INTO machines (ip, player_id) VALUES ('{ip}', {id});
    ''')
    db_conn.commit()
    print(f'IP {ip} - user {id} added to DB.')   


def lookup_movie(title, year=None):
    encoded_title = urllib.parse.quote(title)
    url = f'{TMDB_URL}/search/movie?api_key={TMDB_KEY}&language=en-US&query={encoded_title}&page=1&include_adult=false'
    if year:
        url += f'&year={year}'
    response = requests.get(url).text
    data = json.loads(response)
    movies = ''
    for i in range(min(5, len(data['results']))):
        movies += f"{data['results'][i]['original_title']}^{data['results'][i]['release_date'].split('-')[0]}^{data['results'][i]['id']}*"
    return movies


def build_clips(movie_title, movie_year, vid_info):
    clip = 1
    level = get_max_level() + 1
    movie_id = get_movie_id_from_db(movie_title, movie_year)
    already_scraped = []
    already_scraped_titles = []
    for vid in vid_info:
        url = vid['url']
        if url not in already_scraped:
            try:
                print(f"Scraping video: {url}")
                video = pafy.new(url)
            except:
                print(f"Error scraping video: {url}")

            title = video.title
            download_title = f'raw_downloads/{title.split(".")[0]}.mp3'
            audio = video.audiostreams[-1]
            audio.download(filepath=download_title)
            print(f'{title} downloaded at {download_title}.')
            already_scraped.append(url)
            already_scraped_titles.append(title)

        else:
            title = already_scraped_titles[already_scraped.index(url)]
            download_title = f'raw_downloads/{title.split(".")[0]}.mp3'
            print(f'{title} ALREADY downloaded at {download_title}')

        start = vid['start']
        end = vid['end']
        trim_title = f'trimmed_audio/{title.split(".")[0]}-{start}-{end}.mp3'
        command = f"ffmpeg -hide_banner -loglevel error -i '{download_title}' -acodec libmp3lame -ss {start} -to {end} '{trim_title}'"
        os.system(command)
        print(f'Audio trimed to seconds {start}-{end} and placed at {trim_title}.')

        s3_title = f'{movie_title}-{movie_year}/clip{clip}.mp3'
        upload_s3(S3_BUCKET, trim_title, s3_title)

        insert_level(level, clip, movie_id, s3_title)

        clip += 1
        print('\n\n\n')
    os.system('rm -r raw_downloads/*')
    os.system('rm -r trimmed_audio/*')
    return level


def upload_s3(bucket_name, file_name, key_name):
    try:
        S3_RESOURCE.Bucket(bucket_name).upload_file(
            Filename=file_name,
            Key=key_name
        )
        print(f"{file_name} uploaded S3 at s3://{bucket_name}/{key_name}.\n")
    except Exception as e:
        print(e)
        print("Error likely from video not scraping and downloading correctly.")


def insert_level(level, stage, movie_id, og_url):
    cur = db_conn.cursor()
    url = og_url.replace("'", "''")
    cur.execute(f'''
        INSERT INTO levels (movie_id, level, stage, url) VALUES ({movie_id}, {level}, {stage}, '{url}');
    ''')
    db_conn.commit()
    print(f'Level {level}, Stage {stage}, Movie {movie_id} added to DB.')


def get_max_level():
    cur = db_conn.cursor()
    cur.execute('''
        SELECT MAX(level) FROM levels;
    ''')
    res = cur.fetchone()[0]
    if res:
        return res
    return 0


def insert_movie_into_db(og_title, release_year, id):
    cur = db_conn.cursor()
    title = og_title.replace("'", "''")
    cur.execute(f'''
        INSERT INTO movies (imdb_id, title, year_released) VALUES ({id}, '{title}', {release_year});
    ''')
    db_conn.commit()
    print(f'{title} - {release_year} inserted into DB.')


def get_movie_id_from_db(og_movie_title, release_year):
    cur = db_conn.cursor()

    movies = lookup_movie(og_movie_title, release_year)
    og_title, year, id = movies.split('*')[0].split('^')

    cur.execute(f'''
        SELECT * FROM movies WHERE imdb_id = {id};
    ''')
    res = cur.fetchone()
    if res == None:
        # need to add to DB
        print(f"'{og_title}' not in database")
        insert_movie_into_db(og_title, year, id)
        return id
    return res[0] 


def generate_password(password):
    algorithm = 'sha512'
    salt = uuid.uuid4().hex
    hash_obj = hashlib.new(algorithm)
    password_salted = salt + password
    hash_obj.update(password_salted.encode('utf-8'))
    password_hash = hash_obj.hexdigest()
    password_db_string = "$".join([algorithm, salt, password_hash])
    return password_db_string


def check_password(password, password_db_string):
    [algorithm, salt, password_hash] = password_db_string.split("$")
    hash_obj = hashlib.new(algorithm)
    password_salted = salt + password
    hash_obj.update(password_salted.encode('utf-8'))
    return hash_obj.hexdigest() == password_hash


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print("Checking user...")
        if 'user' not in session:
            print("Not logged in.")
            return redirect(url_for('validate'))
        return f(*args, **kwargs)
    return decorated_function


###############################################################
############################ API ##############################
###############################################################

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        input_title = request.form['firsttitle']
        movies = lookup_movie(input_title)
        if len(movies) == 0:
            return render_template('find_movie.html', warning=f'NO MOVIES SIMILAR TO TITLE: {input_title}')
        return redirect(url_for('add', movies=movies))

    return render_template('find_movie.html')


@app.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        movie_title = request.form['movie']
        movie_year = request.form['year']
        
        vid_info = []
        for i in range(1, 6):
            vid_info.append(
                {
                    'url': request.form.get(f'url{i}'),
                    'start': request.form.get(f'start{i}'),
                    'end': request.form.get(f'end{i}')
                }
            )
        level = build_clips(movie_title, movie_year, vid_info)
        return render_template('response.html', level=level, movie=movie_title, year=movie_year)
    
    movies_args = urllib.parse.unquote(request.args.get('movies'))
    print(movies_args)
    movies = []
    for m in movies_args.split('*')[:-1]:
        title, year, id = m.split('^')
        movies.append(
            {
                'title': title,
                'year': year
            }
        )
    return render_template('create_entry.html', movies=movies)


@app.route('/validate', methods=['GET', 'POST'])
def validate():
    if request.method == 'POST':
        code = request.form['code']
        me = find_user(1)
        if code == me[2]:
            session['user'] = me[1]
            return redirect(url_for('index'))

        else:
            flash("No.")

    return render_template('validate.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('validate'))


if __name__ == '__main__':
    if not os.path.exists("raw_downloads"):
        os.makedirs("raw_downloads")
        print("'raw_downloads' directory created.")
    if not os.path.exists("trimmed_audio"):
        os.makedirs("trimmed_audio")
        print("'trimmed_audio' directory created.")
    app.run()