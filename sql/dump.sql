CREATE TABLE IF NOT EXISTS players (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(100) NOT NULL,
    code VARCHAR(200) NOT NULL
);

CREATE TABLE IF NOT EXISTS machines (
    ip VARCHAR(16) PRIMARY KEY,
    player_id INTEGER REFERENCES players (id)
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

CREATE TABLE IF NOT EXISTS player_guesses (
    player_id INTEGER REFERENCES players (id),
    level INTEGER,
    stage_guess INTEGER,
    PRIMARY KEY (player_id, level, stage_guess),
    guess VARCHAR(200),
    correct BOOLEAN
);

CREATE TABLE IF NOT EXISTS leagues (
    name VARCHAR(200) PRIMARY KEY,
    description VARCHAR(200),
    owner INTEGER REFERENCES players (id)
);

CREATE TABLE IF NOT EXISTS league_membership (
    league VARCHAR(200) REFERENCES leagues (name),
    player INTEGER REFERENCES players (id),
    PRIMARY KEY (league, player)
);

-- CREATE TABLE IF NOT EXISTS headtoheads (

-- )