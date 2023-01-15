CREATE TABLE IF NOT EXISTS players (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(100) NOT NULL,
    code VARCHAR(200) NOT NULL
);

CREATE TABLE IF NOT EXISTS machines (
    ip VARCHAR(16),
    player_id INTEGER REFERENCES players (id),
    PRIMARY KEY (ip, player_id)
);

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
    url VARCHAR(200),
    date_used DATE DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS player_progess (
    player_id INTEGER REFERENCES players (id),
    level INTEGER,
    PRIMARY KEY (player_id, level),
    stage_on INTEGER,
    complete BOOLEAN
);