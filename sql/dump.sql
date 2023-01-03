CREATE TABLE IF NOT EXISTS players (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(24) NOT NULL,
    code VARCHAR(24) NOT NULL
);

CREATE TABLE IF NOT EXISTS machines (
    id SERIAL PRIMARY KEY,
    ip VARCHAR(16),
    player_id INTEGER REFERENCES players (id)
);

INSERT INTO players (handle, code) VALUES ('keysersoze', '1980');

CREATE TABLE IF NOT EXISTS movies (
    imdb_id INTEGER PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    year_released INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS levels (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER REFERENCES movies (imdb_id),
    level INTEGER,
    stage INTEGER,
    url VARCHAR(200)
);