-- V3__create_incidents.sql
CREATE TABLE incidents (
    id          SERIAL PRIMARY KEY,
    service_id  INTEGER NOT NULL REFERENCES services(id),
    title       TEXT NOT NULL,
    severity    INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 4),
    status      TEXT NOT NULL DEFAULT 'open',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    created_by  TEXT NOT NULL DEFAULT 'system'
);
