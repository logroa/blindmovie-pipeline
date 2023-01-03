import os
import requests
import json
import urllib.parse
import pafy
from flask import Flask, render_template, request, redirect, jsonify, flash, url_for, session
import psycopg2
from dotenv import load_dotenv
import boto3
import time

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


def lookup_movie(title):
    encoded_title = urllib.parse.quote(title)
    url = f'{TMDB_URL}/search/movie?api_key={TMDB_KEY}&language=en-US&query={encoded_title}&page=1&include_adult=false'
    response = requests.get(url).text
    data = json.loads(response)
    movies = ''
    for i in range(min(5, len(data['results']))):
        movies += f"{data['results'][i]['original_title']}^{data['results'][i]['release_date'].split('-')[0]}*"
    return movies


def build_clips(movie_title, movie_year, vid_info):
    clip = 1
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
        upload_s3('blindmoviebucket', trim_title, s3_title)

        clip += 1
        print('\n\n\n')


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

###############################################################
############################ API ##############################
###############################################################

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        input_title = request.form['firsttitle']
        movies = lookup_movie(input_title)
        if len(movies) == 0:
            return render_template('find_movie.html', warning=f'NO MOVIES SIMILAR TO TITLE: {input_title}')
        return redirect(url_for('add', movies=movies))

    if 'user' not in session:
        return redirect(url_for('validate'))

    return render_template('find_movie.html')


@app.route('/add', methods=['GET', 'POST'])
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
        build_clips(movie_title, movie_year, vid_info)

        return redirect(url_for('index'))
    
    movies_args = urllib.parse.unquote(request.args.get('movies'))
    print(movies_args)
    movies = []
    for m in movies_args.split('*')[:-1]:
        title, year = m.split('^')
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


if __name__ == '__main__':
    if not os.path.exists("raw_downloads"):
        os.makedirs("raw_downloads")
        print("'raw_downloads' directory created.")
    if not os.path.exists("trimmed_audio"):
        os.makedirs("trimmed_audio")
        print("'trimmed_audio' directory created.")
    app.run()