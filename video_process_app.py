import os
import requests
import json
import shutil
import urllib.parse
import yt_dlp
import flask
from flask import Flask, render_template, request, redirect, jsonify, flash, url_for, session
import psycopg2
from dotenv import load_dotenv
import boto3
import hashlib
import uuid
from functools import wraps
from datetime import datetime
from difflib import SequenceMatcher

# make this a flask rest API lol
# put on lambda i think - store in S3
# i'd like to do some front end caching on this shit too
# movie poster on answer screen ferdaaa
# track number of guesses per movie to inform search

# modify logged in decorator to see if not logged in but ip is registered for account

# for player rankings, cannot base it on old levels (cheating check)

# management needs a specific admin login decorator
# qa for levels

# with new daily levels, need to modify the add clips page

# golf, leagues where you compete for 18 days (3 par, 2 birdie, 4 bogey)

# default load for a level should start from progress
# Scoring
# gets answer right: 1, 2, 3, 4, 5
# doesn't get it right: 6
# doesn't do day's challenge: 7
# doing it late: minimum of 3?

# select p.id, p.handle, l.level, b.stage, b.correct
# from players p
# cross join (select distinct(level) from levels) l
# full join (select max(stage_guess) as "stage", max(correct::INT) as "correct", level, player_id from player_guesses group by player_id, level) b
# on p.id = b.player_id and l.level = b.level
# order by p.id, l.level;


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

API_HOST = os.getenv('API_HOST')

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

def find_user(id, username=None):
    cur = db_conn.cursor()
    query = "SELECT * FROM players WHERE "

    if username:
        username = username.replace("'", "''")
        query += f"handle = '{username}';"
    else:
        query += f"id = {id};"

    cur.execute(query)
    return cur.fetchone()


def insert_user(og_handle, code, phonenumber):
    cur = db_conn.cursor()
    handle = og_handle.replace("'", "''")
    cur.execute(f'''
        INSERT INTO players (handle, code, phonenumber) VALUES ('{handle}', '{code}', '{phonenumber}');
    ''')
    db_conn.commit()
    print(f'{og_handle} registered.')
    return find_user(0, handle)[0]


def find_ip(ip):
    cur = db_conn.cursor()
    query = f"SELECT player_id FROM machines WHERE ip = '{ip}';"
    cur.execute(query)
    return cur.fetchone()   


def remove_machine_registration(ip):
    cur = db_conn.cursor()
    cur.execute(f'''
        DELETE FROM machines WHERE ip = '{ip}';
    ''')
    db_conn.commit() 
    print(f'''IP {ip}'s registration removed (if it existed at all).''')   


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


def build_clips(movie_title, movie_year, vid_info, assigned_date):
    clip = 1
    level = get_max_level() + 1
    movie_id = get_movie_id_from_db(movie_title, movie_year)
    already_scraped = []
    already_scraped_titles = []
    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',
        }]
    }

    for vid in vid_info:
        url = vid['url']

        if url not in already_scraped:
            try:
                print(f"Scraping video: {url}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.sanitize_info(ydl.extract_info(url, download=False))
                    error_code = ydl.download(url)
                    download_title = f'{info["title"]} [{info["id"]}].m4a'

                    print(f'{info["title"]} downloaded at {download_title}.')
                    already_scraped.append(url)
                    already_scraped_titles.append(download_title)
                    shutil.move(download_title, f'raw_downloads/{download_title}')

            except Exception as e:
                print(f"Error scraping video: {url}")
                print(e)

        else:
            download_title = already_scraped_titles[already_scraped.index(url)]
            print(f'{download_title} ALREADY downloaded.')

        start = vid['start']
        end = vid['end']
        trim_title = f'trimmed_audio/{download_title.split(".")[0]}-{start}-{end}.mp3'
        command = f"ffmpeg -hide_banner -loglevel error -i 'raw_downloads/{download_title}' -acodec libmp3lame -ss {start} -to {end} '{trim_title}'"
        os.system(command)
        print(f'Audio trimed to seconds {start}-{end} and placed at {trim_title}.')

        s3_title = f'{movie_title}-{movie_year}/clip{clip}.mp3'
        upload_s3(S3_BUCKET, trim_title, s3_title)

        insert_level(level, clip, movie_id, s3_title, assigned_date, info["id"], start, end)
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


def insert_level(level, stage, movie_id, og_url, assigned_date, youtube_id, start, end):
    cur = db_conn.cursor()
    url = og_url.replace("'", "''")
    query = f'''
        INSERT INTO levels (movie_id, level, stage, url, youtube_id, start_sec, end_sec{', date_used' if assigned_date else ''}) 
        VALUES ({movie_id}, {level}, {stage}, '{url}', '{youtube_id}', {start}, {end}{", '" + assigned_date + "'" if assigned_date else ''});
    '''
    cur.execute(query)
    db_conn.commit()
    print(f"'{query}' added to DB.")


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


def get_levels():
    cur = db_conn.cursor()
    query = f"SELECT distinct(level) FROM levels ORDER BY level;"
    cur.execute(query)
    return cur.fetchall()


def get_stages(level=None):
    cur = db_conn.cursor()
    query = f"SELECT * FROM levels WHERE {'level='+str(level) if level else 'date_used=CURRENT_DATE'} ORDER BY stage;"
    print("QUERY: ", query)
    cur.execute(query)
    return cur.fetchall()    


def get_last_guess(user_id, level):
    next_stage = 1
    correct = False
    cur = db_conn.cursor()
    cur.execute(f'''SELECT MAX(stage_guess) FROM player_guesses WHERE level={level} AND player_id={user_id};''')
    res = cur.fetchone()[0]
    if res:
        cur.execute(f'''SELECT correct FROM player_guesses WHERE level={level} AND player_id={user_id} AND stage_guess={res};''')
        if cur.fetchone()[0]:
            next_stage = res
            correct = True
        else:
            next_stage = res + 1
    return next_stage, correct


def insert_guess(user_id, level, stage, guess, correct):
    cleaned_guess = guess.replace("'", "''")
    cur = db_conn.cursor()
    cur.execute(f'''
        INSERT INTO player_guesses (player_id, level, stage_guess, guess, correct, guess_time) VALUES ({user_id}, {level}, {stage}, '{cleaned_guess}', {correct}, '{datetime.now()}');
    ''')
    db_conn.commit()


def get_all_guesses_for_level(level, player_id):
    cur = db_conn.cursor()
    cur.execute(f'''
        select guess from player_guesses where player_id={player_id} and level={level};
    ''')
    res = cur.fetchall()
    return [r[0] for r in res]


def render_level(level=None):
    stages = get_stages(level)
    if len(stages) > 0:
        stages_list = [{ "url": s[4], "count": s[3] } for s in stages]
        level_num = stages[0][2]

        y, m, d = str(stages[0][-1]).split('-')
        date_used = datetime(int(y), int(m), int(d)).strftime('%m/%d/%Y')

        user = session['user']
        user_id = find_user(0, user)[0]
        stage_on, is_correct = get_last_guess(user_id, level_num)
        title = ""
        if is_correct or stage_on > 5:
            cur = db_conn.cursor()
            cur.execute(f'''SELECT DISTINCT(movie_id) FROM levels WHERE level={level_num};''')
            movie_id = cur.fetchone()[0]
            cur.execute(f'''SELECT DISTINCT(title) FROM movies WHERE imdb_id={movie_id}''')
            title = cur.fetchone()[0]
        
        guesses = get_all_guesses_for_level(level_num, user_id)

        return render_template('play.html', bucket=S3_BUCKET, stages=stages_list, level=level_num, date_used=date_used, api_url=API_HOST, username=user, stage_on=stage_on, is_correct=is_correct, movie_title=title, guesses=guesses)
    return render_template('play.html')


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print("Checking user...")
        # session.clear()
        if 'user' not in session:
            print("Not logged in.")
            res = find_ip(request.remote_addr)
            if res:
                print("IP Found.")
                id = res[0]
                user = find_user(id)[1]
                session['user'] = user
                return

            return redirect(url_for('validate'))

        current_ip = find_ip(request.remote_addr)
        if not current_ip:
            id = find_user(0, session['user'])[0]
            insert_machine_registration(request.remote_addr, id)

        return f(*args, **kwargs)
    return decorated_function


def admin_login_required(f):
    @wraps(f)
    def admin_decorated_function(*args, **kwargs):
        print("Checking admin user...")
        if 'user' not in session:
            print("Not logged in.")
            res = find_ip(request.remote_addr)
            if not res:
                return redirect(url_for('validate'))
            elif res[0] == 1:
                print("IP Found.")
                id = res[0]
                user = find_user(id)[1]
                session['user'] = user
                return
            else:
                return redirect(url_for('index'))

        current_ip = find_ip(request.remote_addr)
        id = 0
        if not current_ip:
            id = find_user(0, session['user'])[0]
            insert_machine_registration(request.remote_addr, id)
        else:
            id = current_ip[0]

        if id != 1:
            return redirect(url_for('index'))

        return f(*args, **kwargs)
    return admin_decorated_function

###############################################################
############################ API ##############################
###############################################################

@app.route('/', methods=['GET'])
@login_required
def index():
    return render_level()


@app.route('/levels', methods=['GET'])
@login_required
def levels():
    levels = [l[0] for l in get_levels()]
    return render_template('levels.html', levels=levels, username=session['user'])


@app.route('/level/<level_num>', methods=['GET'])
@login_required
def level(level_num):
    return render_level(level_num)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        handle = request.form['handle']
        user = find_user(0, handle)
        if not user:   
            ip = request.remote_addr
            code = request.form['code']
            phonenumber = request.form['phonenumber']
            generated_code = generate_password(code)
            id = insert_user(handle, generated_code, phonenumber)
            session['user'] = handle
            remove_machine_registration(ip)
            insert_machine_registration(ip, id)
            print(f"Registration for '{handle}' complete.")

            return redirect(url_for('index'))

        return render_template('register.html', message="Username already taken.")
    
    return render_template('register.html')


@app.route('/validate', methods=['GET', 'POST'])
def validate():
    if request.method == 'POST':
        handle = request.form['handle']
        code = request.form['code']
        ip = request.remote_addr
        me = find_user(0, handle)

        if me[0] == None or not check_password(code, me[2]):
            return render_template('validate.html', message='Incorrect login.')

        session['user'] = me[1]

        found_id = find_ip(ip)
        if not found_id:
            insert_machine_registration(ip, me[0])
        elif found_id != me[0]:
            remove_machine_registration(ip)
            insert_machine_registration(ip, me[0])

        return redirect(url_for('index'))

    return render_template('validate.html')


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    return redirect(url_for('validate'))


# @app.route('/new_league', methods=['GET', 'POST'])
# def create_league():
#     if request.method == 'POST':
#         name = request.form['name']
#         description = request.form['description']
#         created_at = datetime.now()
#         owner = find_user(0, session['user'])[0]
#         # get photo and upload it to s3
#         pass
#         # return leagues endpoint
#     # return form to make league
#     return


# @app.route('/leagues', methods=['GET'])
# def leagues():
#     cur = db_conn.cursor()
#     query = f'''SELECT * ;'''


@app.route('/search/<start>', methods=['GET'])
@login_required
def search(start):
    cur = db_conn.cursor()
    start = start.replace("'", "''")
    query = f'''SELECT title, year_released FROM movies WHERE LOWER(title) LIKE LOWER('{start}%') ORDER BY title ASC LIMIT 10;'''
    print(f"Executing '{query}'")
    cur.execute(query)
    results = [{'title': m[0], 'year': m[1]} for m in cur.fetchall()]
    print(f"Results: {results}")
    return jsonify(**{"results": results})


@app.route('/check', methods=['POST'])
@login_required
def check():
    data = request.get_json()
    user = session['user']
    user_id = find_user(0, user)[0]
    guess = data.get('guess')
    cleaned_guess = ''.join(l for l in guess.lower() if l.isalnum())
    level = data.get('level')

    next_stage, is_correct = get_last_guess(user_id, level)
    cur = db_conn.cursor()
    cur.execute(f'''SELECT DISTINCT(movie_id) FROM levels WHERE level={level};''')
    movie_id = cur.fetchone()[0]
    cur.execute(f'''SELECT DISTINCT(title) FROM movies WHERE imdb_id={movie_id}''')
    title = cur.fetchone()[0]

    if next_stage > 5:
        # return the after-success page
        return jsonify(**{
            "correct": is_correct,
            "next_stage": next_stage,
            "title": title
        })

    cleaned_title = ''.join(l for l in title.lower() if l.isalnum())
    similarity = SequenceMatcher(None, cleaned_title, cleaned_guess).ratio()
    correct = False
    if similarity >= .90:
        correct = True
    insert_guess(user_id, level, next_stage, guess, correct)
    next_stage += 1
    returnable = {
        "correct": correct,
        "next_stage": next_stage
    }
    if correct or next_stage > 5:
        # return the after-success page
        returnable["next_stage"] = 6
        returnable["title"] = title
    # return to the next soundclip
    return jsonify(**returnable)


@app.route('/players', methods=['GET'])
@login_required
def players():
    pass


###############################################################
######################### ADMIN API ###########################
###############################################################

@app.route('/management', methods=['GET', 'POST'])
@admin_login_required
def manage():
    if request.method == 'POST':
        input_title = request.form['firsttitle']
        movies = lookup_movie(input_title)
        if len(movies) == 0:
            return render_template('find_movie.html', warning=f'NO MOVIES SIMILAR TO TITLE: {input_title}')
        return redirect(url_for('add', movies=movies))

    return render_template('find_movie.html')


@app.route('/add', methods=['GET', 'POST'])
@admin_login_required
def add():
    if request.method == 'POST':
        movie_title = request.form['movie']
        movie_year = request.form['year']
        assigned_date = request.form['assigneddate']
        vid_info = []
        for i in range(1, 6):
            vid_info.append(
                {
                    'url': request.form.get(f'url{i}'),
                    'start': request.form.get(f'start{i}'),
                    'end': request.form.get(f'end{i}')
                }
            )
        level = build_clips(movie_title, movie_year, vid_info, assigned_date)
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


# make sure date assigned has 5 levels per, no more no less
# make sure upcoming dates have movies locked and loaded
@app.route('/qa', methods=['GET'])
@admin_login_required
def quality():
    pass


if __name__ == '__main__':
    if not os.path.exists("raw_downloads"):
        os.makedirs("raw_downloads")
        print("'raw_downloads' directory created.")
    if not os.path.exists("trimmed_audio"):
        os.makedirs("trimmed_audio")
        print("'trimmed_audio' directory created.")
    app.run()