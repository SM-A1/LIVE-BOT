CREATE TABLE users (
    id          BIGINT PRIMARY KEY,
    username    TEXT,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT,
    is_banned   BOOLEAN NOT NULL DEFAULT FALSE,
    bot_limit   INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE bots (
    id          BIGSERIAL PRIMARY KEY,
    owner_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tg_bot_id   BIGINT NOT NULL UNIQUE,
    username    TEXT NOT NULL,
    first_name  TEXT NOT NULL,
    token_enc   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'offline' CHECK (status IN ('online','starting','offline','error')),
    last_error  TEXT,
    is_disabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX bots_owner_idx ON bots(owner_id);

CREATE TABLE bot_admins (
    bot_id   BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    user_id  BIGINT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (bot_id, user_id)
);

CREATE TABLE bot_users (
    bot_id        BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    user_id       BIGINT NOT NULL,
    username      TEXT,
    first_name    TEXT NOT NULL DEFAULT '',
    last_name     TEXT,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active   TIMESTAMPTZ NOT NULL DEFAULT now(),
    message_count INT NOT NULL DEFAULT 1,
    is_banned     BOOLEAN NOT NULL DEFAULT FALSE,
    is_blocked    BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (bot_id, user_id)
);
CREATE INDEX bot_users_active_idx ON bot_users(bot_id, last_active DESC);
CREATE INDEX bot_users_seen_idx   ON bot_users(bot_id, first_seen);

CREATE TABLE media (
    id         BIGSERIAL PRIMARY KEY,
    bot_id     BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('photo','video','document','audio','voice')),
    filename   TEXT NOT NULL DEFAULT 'file',
    data       BYTEA NOT NULL,
    tg_file_id TEXT,              -- file_id as seen by THIS bot (file_ids are bot-specific)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX media_bot_idx ON media(bot_id);

CREATE TABLE script_projects (
    id         BIGSERIAL PRIMARY KEY,
    bot_id     BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    name       TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 40),
    code       TEXT NOT NULL DEFAULT '',
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bot_id, name)
);

CREATE TABLE commands (
    id            BIGSERIAL PRIMARY KEY,
    bot_id        BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    name          TEXT NOT NULL CHECK (name ~ '^[a-z0-9_]{1,32}$'),
    description   TEXT NOT NULL DEFAULT '',
    aliases       TEXT[] NOT NULL DEFAULT '{}',
    response_type TEXT NOT NULL DEFAULT 'text'
                  CHECK (response_type IN ('text','photo','video','document','audio','voice','script')),
    text          TEXT NOT NULL DEFAULT '',
    media_id      BIGINT REFERENCES media(id) ON DELETE SET NULL,
    script_id     BIGINT REFERENCES script_projects(id) ON DELETE SET NULL,
    scope         TEXT NOT NULL DEFAULT 'any' CHECK (scope IN ('any','private','group')),
    admin_only    BOOLEAN NOT NULL DEFAULT FALSE,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bot_id, name)
);

CREATE TABLE responses (
    id               BIGSERIAL PRIMARY KEY,
    bot_id           BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    trigger          TEXT NOT NULL CHECK (char_length(trigger) BETWEEN 1 AND 200),
    match_mode       TEXT NOT NULL DEFAULT 'contains'
                     CHECK (match_mode IN ('exact','contains','startswith','endswith','regex')),
    case_insensitive BOOLEAN NOT NULL DEFAULT TRUE,
    text             TEXT NOT NULL,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bot_id, trigger, match_mode)
);

-- set_key: 'c<command id>' | 'r<response id>' | 'w' (welcome) | 'b<broadcast id>'
CREATE TABLE buttons (
    id      BIGSERIAL PRIMARY KEY,
    bot_id  BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    set_key TEXT NOT NULL,
    row_idx INT NOT NULL,
    pos     INT NOT NULL,
    label   TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 40),
    kind    TEXT NOT NULL CHECK (kind IN ('url','callback','command','web_app','switch_inline')),
    value   TEXT NOT NULL DEFAULT '',
    UNIQUE (bot_id, set_key, row_idx, pos)
);

CREATE TABLE welcome_messages (
    bot_id          BIGINT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    text            TEXT NOT NULL DEFAULT E'👋 Welcome {first_name}!\n\nYou are now connected to {bot_name}.',
    media_id        BIGINT REFERENCES media(id) ON DELETE SET NULL,
    delete_previous BOOLEAN NOT NULL DEFAULT FALSE,
    private_only    BOOLEAN NOT NULL DEFAULT FALSE,
    group_enabled   BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE welcome_sent (
    bot_id     BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    chat_id    BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    PRIMARY KEY (bot_id, chat_id)
);

CREATE TABLE broadcasts (
    id           BIGSERIAL PRIMARY KEY,
    bot_id       BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    owner_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_type TEXT NOT NULL DEFAULT 'text' CHECK (content_type IN ('text','photo','video','document','audio')),
    text         TEXT NOT NULL DEFAULT '',
    media_id     BIGINT REFERENCES media(id) ON DELETE SET NULL,
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK (status IN ('draft','running','paused','cancelled','done','failed')),
    total        INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ
);
CREATE INDEX broadcasts_bot_idx ON broadcasts(bot_id, created_at DESC);

CREATE TABLE broadcast_recipients (
    broadcast_id BIGINT NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
    user_id      BIGINT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','blocked')),
    error        TEXT,
    PRIMARY KEY (broadcast_id, user_id)
);
CREATE INDEX broadcast_recipients_status_idx ON broadcast_recipients(broadcast_id, status);

CREATE TABLE settings (
    bot_id              BIGINT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
    maintenance_mode    BOOLEAN NOT NULL DEFAULT FALSE,
    maintenance_text    TEXT,
    group_mode          BOOLEAN NOT NULL DEFAULT TRUE,
    attribution_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    attribution_text    TEXT,
    attribution_pending BOOLEAN NOT NULL DEFAULT TRUE,
    logging_enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    developer_mode      BOOLEAN NOT NULL DEFAULT FALSE,
    update_mode         TEXT NOT NULL DEFAULT 'polling' CHECK (update_mode IN ('polling','webhook'))
);

CREATE TABLE platform_settings (
    key   TEXT PRIMARY KEY,
    value JSONB NOT NULL
);

CREATE TABLE command_usage (
    bot_id  BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    name    TEXT NOT NULL,
    used_on DATE NOT NULL DEFAULT current_date,
    count   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (bot_id, name, used_on)
);

CREATE TABLE bot_daily (
    bot_id    BIGINT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    day       DATE NOT NULL DEFAULT current_date,
    messages  INT NOT NULL DEFAULT 0,
    new_users INT NOT NULL DEFAULT 0,
    PRIMARY KEY (bot_id, day)
);

CREATE TABLE logs (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id    BIGINT,
    bot_id     BIGINT,
    action     TEXT NOT NULL,
    status     TEXT NOT NULL,
    error_code TEXT,
    detail     TEXT
);
CREATE INDEX logs_ts_idx  ON logs(ts DESC);
CREATE INDEX logs_bot_idx ON logs(bot_id, ts DESC);

CREATE TABLE sessions (
    user_id    BIGINT PRIMARY KEY,
    state      TEXT NOT NULL,
    data       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
