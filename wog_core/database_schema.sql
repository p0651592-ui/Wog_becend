CREATE TABLE IF NOT EXISTS users (
 id BIGSERIAL PRIMARY KEY,
 telegram_id BIGINT UNIQUE NOT NULL,
 username TEXT,
 role TEXT DEFAULT 'user',
 status TEXT DEFAULT 'active',
 created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wallets (
 user_id BIGINT PRIMARY KEY REFERENCES users(id),
 balance BIGINT DEFAULT 0,
 updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
 id BIGSERIAL PRIMARY KEY,
 user_id BIGINT REFERENCES users(id),
 amount BIGINT NOT NULL,
 type TEXT NOT NULL,
 balance_before BIGINT,
 balance_after BIGINT,
 created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS games (
 id BIGSERIAL PRIMARY KEY,
 user_id BIGINT REFERENCES users(id),
 game_type TEXT NOT NULL,
 bet BIGINT NOT NULL,
 result TEXT NOT NULL,
 win_amount BIGINT DEFAULT 0,
 server_seed TEXT NOT NULL,
 nonce BIGINT NOT NULL,
 created_at TIMESTAMP DEFAULT NOW()
);