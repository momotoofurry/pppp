-- EMG pipeline schema (TimescaleDB)
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE emg_window (
    time    timestamptz NOT NULL,
    subject text NOT NULL,
    session text NOT NULL,
    seq     integer NOT NULL,
    phase   text NOT NULL,
    label   smallint NOT NULL,
    pred    smallint NOT NULL,
    rms1 real, rms2 real, rms3 real, rms4 real,
    hum1 real, hum2 real, hum3 real, hum4 real,
    src_ms  double precision
);
SELECT create_hypertable('emg_window', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON emg_window (session, time DESC);

CREATE TABLE emg_reject (time timestamptz NOT NULL, topic text, payload text, reason text);
CREATE TABLE ingest_gap (time timestamptz NOT NULL, session text, prev_seq integer, seq integer);
CREATE TABLE IF NOT EXISTS alert_log (time timestamptz NOT NULL, status text, alertname text, severity text, summary text,
                                      starts_at timestamptz, fingerprint text);

-- 10 s summary per session (continuous aggregate; real-time, so the newest bucket is included)
CREATE MATERIALIZED VIEW emg_10s WITH (timescaledb.continuous) AS
SELECT time_bucket('10 seconds', time) AS bucket, session,
       count(*) AS windows,
       avg(rms1) AS rms1, avg(rms2) AS rms2, avg(rms3) AS rms3, avg(rms4) AS rms4,
       max(hum1) AS hum1_max, max(hum2) AS hum2_max, max(hum3) AS hum3_max, max(hum4) AS hum4_max,
       count(*) FILTER (WHERE label >= 0) AS labelled,
       count(*) FILTER (WHERE label >= 0 AND pred = label) AS correct
FROM emg_window GROUP BY bucket, session WITH NO DATA;
SELECT add_continuous_aggregate_policy('emg_10s', start_offset => INTERVAL '1 hour', end_offset => INTERVAL '10 seconds',
                                       schedule_interval => INTERVAL '10 seconds');
ALTER MATERIALIZED VIEW emg_10s SET (timescaledb.materialized_only = false);

-- data-quality rule (report 35.97): mains hum above 5 uV on any channel while the user is cued to rest
CREATE VIEW rest_hum_alert AS
SELECT time, session, phase, greatest(hum1, hum2, hum3, hum4) AS hum_max, rms1, rms2, rms3, rms4
FROM emg_window WHERE label = 8 AND greatest(hum1, hum2, hum3, hum4) > 5;

-- donning-to-donning drift: per class and channel, mean log RMS of the cued (cal) windows, and the change from the
-- subject's first session (log ratio; +0.69 = twice the amplitude)
CREATE VIEW class_level AS
SELECT subject, session, label, min(time) AS first_time,
       avg(ln(rms1)) AS l1, avg(ln(rms2)) AS l2, avg(ln(rms3)) AS l3, avg(ln(rms4)) AS l4, count(*) AS n
FROM emg_window WHERE phase = 'cal' AND label >= 0 GROUP BY subject, session, label;

CREATE VIEW class_drift AS
WITH first AS (SELECT DISTINCT ON (subject) subject, session FROM emg_window ORDER BY subject, src_ms)
SELECT c.subject, c.session, c.label,
       round((c.l1 - b.l1)::numeric, 2) AS ch1, round((c.l2 - b.l2)::numeric, 2) AS ch2,
       round((c.l3 - b.l3)::numeric, 2) AS ch3, round((c.l4 - b.l4)::numeric, 2) AS ch4
FROM class_level c
JOIN first f ON f.subject = c.subject
JOIN class_level b ON b.subject = c.subject AND b.session = f.session AND b.label = c.label
WHERE c.session <> f.session;

-- retention: raw windows are kept 30 days (the 10 s summaries stay)
SELECT add_retention_policy('emg_window', INTERVAL '30 days');
