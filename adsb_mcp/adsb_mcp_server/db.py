"""Shared SQLite database setup for the ADS-B MCP server.

Creates and returns connections with all required tables:
  - faa_reg        : FAA aircraft registration data
  - lol_aircraft   : Real-time ADS-B tracking data (adsb.lol)
  - opensky_*      : OpenSky Network response cache (1-hour TTL)
"""

import sqlite3


def setup_aircraft_db(db_path: str = "aircraft.db") -> sqlite3.Connection:
    """Open (or create) the database and ensure all tables exist.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An open sqlite3.Connection with foreign-key enforcement enabled.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript("""
        -- FAA aircraft registration -----------------------------------------
        CREATE TABLE IF NOT EXISTS faa_reg (
            n_number                  TEXT PRIMARY KEY,
            serial_number             TEXT,
            manufacturer              TEXT,
            model                     TEXT,
            type_registrant           TEXT,
            name                      TEXT,
            street                    TEXT,
            city                      TEXT,
            state                     TEXT,
            zip_code                  TEXT,
            region                    TEXT,
            county                    TEXT,
            country                   TEXT,
            last_action_date          TEXT,
            certificate_issue_date    TEXT,
            certification             TEXT,
            type_aircraft             TEXT,
            type_engine               TEXT,
            status                    TEXT,
            mode_s_code_hex           TEXT,
            fractional_ownership      TEXT,
            airworthiness_date        TEXT,
            other_names               TEXT,
            expiration_date           TEXT,
            weight_category           TEXT,
            date_change_authorization TEXT,
            other_change_authorization TEXT,
            date_of_registration      TEXT,
            registered_owner          TEXT,
            manufacturer_name         TEXT,
            model_designation         TEXT,
            series_name               TEXT,
            aircraft_category         TEXT,
            builder                   TEXT,
            year_manufactured         TEXT,
            number_of_engines         TEXT,
            number_of_seats           TEXT,
            weight                    TEXT,
            cruising_speed            TEXT,
            engine_manufacturer       TEXT,
            engine_model              TEXT,
            propeller_manufacturer    TEXT,
            propeller_model           TEXT,
            fetch_date                TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- adsb.lol real-time aircraft data -----------------------------------
        CREATE TABLE IF NOT EXISTS lol_aircraft (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp             INTEGER NOT NULL,
            hex                   TEXT    NOT NULL,
            alert                 INTEGER,
            alt_baro              TEXT,
            alt_geom              INTEGER,
            baro_rate             INTEGER,
            category              TEXT,
            emergency             TEXT,
            flight                TEXT,
            gs                    REAL,
            gva                   INTEGER,
            lat                   REAL,
            lon                   REAL,
            messages              INTEGER,
            mlat                  TEXT,
            nac_p                 INTEGER,
            nac_v                 INTEGER,
            nav_altitude_mcp      INTEGER,
            nav_heading           REAL,
            nav_qnh               REAL,
            nic                   INTEGER,
            nic_baro              INTEGER,
            r                     TEXT,
            rc                    INTEGER,
            rssi                  REAL,
            sda                   INTEGER,
            seen                  REAL,
            seen_pos              REAL,
            sil                   INTEGER,
            sil_type              TEXT,
            spi                   INTEGER,
            squawk                TEXT,
            t                     TEXT,
            tisb                  TEXT,
            track                 REAL,
            type                  TEXT,
            version               INTEGER,
            geom_rate             INTEGER,
            db_flags              INTEGER,
            nav_modes             TEXT,
            true_heading          REAL,
            ias                   INTEGER,
            mach                  REAL,
            mag_heading           REAL,
            oat                   INTEGER,
            roll                  REAL,
            tas                   INTEGER,
            tat                   INTEGER,
            track_rate            REAL,
            wd                    INTEGER,
            ws                    INTEGER,
            gps_ok_before         REAL,
            gps_ok_lat            REAL,
            gps_ok_lon            REAL,
            last_position_lat     REAL,
            last_position_lon     REAL,
            last_position_nic     INTEGER,
            last_position_rc      INTEGER,
            last_position_seen_pos REAL,
            rr_lat                REAL,
            rr_lon                REAL,
            calc_track            INTEGER,
            nav_altitude_fms      INTEGER,
            FOREIGN KEY (r) REFERENCES faa_reg(n_number) ON DELETE CASCADE
        );

        -- OpenSky Network cache tables ---------------------------------------
        CREATE TABLE IF NOT EXISTS opensky_requests_cache (
            params_json       TEXT    PRIMARY KEY,
            api_type          TEXT    NOT NULL,
            timestamp         INTEGER NOT NULL,
            api_response_time INTEGER
        );

        CREATE TABLE IF NOT EXISTS opensky_states_data (
            request_params_json TEXT    NOT NULL,
            icao24              TEXT    NOT NULL,
            last_contact        INTEGER NOT NULL,
            callsign            TEXT,
            origin_country      TEXT,
            time_position       INTEGER,
            longitude           REAL,
            latitude            REAL,
            baro_altitude       REAL,
            on_ground           BOOLEAN,
            velocity            REAL,
            true_track          REAL,
            vertical_rate       REAL,
            sensors             TEXT,
            geo_altitude        REAL,
            squawk              TEXT,
            spi                 BOOLEAN,
            position_source     INTEGER,
            category            INTEGER,
            PRIMARY KEY (request_params_json, icao24, last_contact),
            FOREIGN KEY (request_params_json)
                REFERENCES opensky_requests_cache(params_json) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS opensky_flights_data (
            request_params_json                   TEXT    NOT NULL,
            icao24                                TEXT    NOT NULL,
            firstSeen                             INTEGER NOT NULL,
            callsign                              TEXT,
            estDepartureAirport                   TEXT,
            lastSeen                              INTEGER,
            estArrivalAirport                     TEXT,
            estDepartureAirportHorizDistance      INTEGER,
            estDepartureAirportVertDistance       INTEGER,
            estArrivalAirportHorizDistance        INTEGER,
            estArrivalAirportVertDistance         INTEGER,
            departureAirportCandidatesCount       INTEGER,
            arrivalAirportCandidatesCount         INTEGER,
            PRIMARY KEY (request_params_json, icao24, firstSeen),
            FOREIGN KEY (request_params_json)
                REFERENCES opensky_requests_cache(params_json) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS opensky_tracks_data (
            request_params_json TEXT NOT NULL PRIMARY KEY,
            icao24              TEXT NOT NULL,
            startTime           INTEGER,
            endTime             INTEGER,
            callsign            TEXT,
            FOREIGN KEY (request_params_json)
                REFERENCES opensky_requests_cache(params_json) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS opensky_track_waypoints_data (
            track_request_params_json TEXT    NOT NULL,
            waypoint_index            INTEGER NOT NULL,
            time                      INTEGER NOT NULL,
            latitude                  REAL,
            longitude                 REAL,
            baro_altitude             REAL,
            true_track                REAL,
            on_ground                 BOOLEAN,
            PRIMARY KEY (track_request_params_json, waypoint_index),
            FOREIGN KEY (track_request_params_json)
                REFERENCES opensky_tracks_data(request_params_json) ON DELETE CASCADE
        );
    """)
    conn.commit()
    return conn


def init_db(db_path: str = "aircraft.db") -> None:
    """Compatibility initializer expected by server lifespan startup."""
    conn = setup_aircraft_db(db_path=db_path)
    conn.close()
