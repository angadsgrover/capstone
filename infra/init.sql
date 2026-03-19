-- infra/init.sql
-- Runs automatically on first postgres container start.
-- Extensions must be installed before table creation.

CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector

-- ── Apache AGE (graph layer) ──────────────────────────────────────────────────
-- Requires the custom postgres image (see infra/Dockerfile.postgres).
-- The DO block silently skips if AGE is not installed so the plain
-- pgvector/pgvector:pg16 image still works for non-graph deployments.
DO $$
BEGIN
    EXECUTE 'CREATE EXTENSION IF NOT EXISTS age';
    EXECUTE 'LOAD ''age''';
    EXECUTE 'SET search_path = ag_catalog, "$user", public';
    -- Create the aviation knowledge graph (idempotent)
    PERFORM create_graph('aviation');
    -- Seed a few well-known airports so graph queries work out of the box
    PERFORM * FROM cypher('aviation', $$
        MERGE (:Airport {icao: 'VHHH', name: 'Hong Kong Intl',   lat: 22.31,  lon: 113.92})
        MERGE (:Airport {icao: 'EGLL', name: 'London Heathrow',  lat: 51.48,  lon: -0.45})
        MERGE (:Airport {icao: 'KJFK', name: 'New York JFK',     lat: 40.64,  lon: -73.78})
        MERGE (:Airport {icao: 'WSSS', name: 'Singapore Changi', lat: 1.36,   lon: 103.99})
        MERGE (:Airport {icao: 'OMDB', name: 'Dubai Intl',       lat: 25.25,  lon: 55.36})
        MERGE (:Airport {icao: 'RJTT', name: 'Tokyo Haneda',     lat: 35.55,  lon: 139.78})
        RETURN 1
    $$) AS (result agtype);
EXCEPTION WHEN OTHERS THEN
    -- AGE not available — skip graph initialisation silently
    RAISE NOTICE 'Apache AGE not available; graph features disabled. %', SQLERRM;
END;
$$;

-- ── Conversation history ─────────────────────────────────────────────────────
-- Persistent alternative / supplement to MemorySaver's in-process dict.
CREATE TABLE IF NOT EXISTS conversations (
    id          BIGSERIAL    PRIMARY KEY,
    session_id  TEXT         NOT NULL,
    role        TEXT         NOT NULL CHECK (role IN ('human', 'ai', 'tool')),
    content     TEXT         NOT NULL,
    metadata    JSONB,
    created_at  TIMESTAMPTZ  DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversations_session
    ON conversations (session_id, created_at);

-- ── Vector embeddings (central index for RAG) ────────────────────────────────
CREATE TABLE IF NOT EXISTS embeddings (
    id          BIGSERIAL    PRIMARY KEY,
    source_type TEXT         NOT NULL,   -- 'metar' | 'taf' | 'safety' | 'conversation'
    source_id   BIGINT,
    content     TEXT         NOT NULL,
    embedding   vector(1536),            -- text-embedding-3-small dimension
    metadata    JSONB,
    created_at  TIMESTAMPTZ  DEFAULT now()
);
-- HNSW index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
    ON embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_embeddings_source
    ON embeddings (source_type, created_at DESC);

-- ── Historical METAR archive ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS metar_history (
    id              BIGSERIAL    PRIMARY KEY,
    icao            CHAR(4)      NOT NULL,
    raw_text        TEXT         NOT NULL,
    obs_time        TIMESTAMPTZ  NOT NULL,
    flight_cat      TEXT,                -- VFR | MVFR | IFR | LIFR
    temp_c          REAL,
    dewpoint_c      REAL,
    wind_dir        INT,
    wind_speed_kt   INT,
    wind_gust_kt    INT,
    visibility_sm   REAL,
    ceiling_ft      INT,
    altimeter       REAL,
    wx_string       TEXT,
    fetched_at      TIMESTAMPTZ  DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_metar_icao_obs
    ON metar_history (icao, obs_time);
CREATE INDEX IF NOT EXISTS idx_metar_recent_hot
    ON metar_history (icao, obs_time DESC);

-- ── Historical TAF archive ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS taf_history (
    id          BIGSERIAL    PRIMARY KEY,
    icao        CHAR(4)      NOT NULL,
    raw_text    TEXT         NOT NULL,
    issue_time  TIMESTAMPTZ  NOT NULL,
    valid_from  TIMESTAMPTZ,
    valid_to    TIMESTAMPTZ,
    fetched_at  TIMESTAMPTZ  DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_taf_icao_issue
    ON taf_history (icao, issue_time);

-- ── Safety events / incident database ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS safety_events (
    id           BIGSERIAL  PRIMARY KEY,
    source       TEXT       NOT NULL,    -- 'ASRS' | 'NTSB' | 'ICAO' | 'CAD' | 'custom'
    event_date   DATE,
    aircraft     TEXT,
    airport_icao CHAR(4),
    event_type   TEXT,                   -- 'incident' | 'accident' | 'bulletin'
    severity     TEXT,
    narrative    TEXT,
    metadata     JSONB,
    created_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_safety_airport
    ON safety_events (airport_icao, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_safety_source
    ON safety_events (source, event_date DESC);

-- ── Phase 14 performance surfaces ─────────────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS airport_stats AS
SELECT
    icao,
    AVG(wind_speed_kt)::REAL AS avg_wind,
    COUNT(*)::INT            AS metar_count
FROM metar_history
GROUP BY icao;

CREATE UNIQUE INDEX IF NOT EXISTS idx_airport_stats_icao
    ON airport_stats (icao);
