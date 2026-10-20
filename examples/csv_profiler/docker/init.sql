-- init.sql
-- Database schema for Cosmo Ecosystem application
--
-- This file contains all application-specific tables.
-- Celery uses Redis for both broker and result backend, no database tables needed.

SET timezone = 'Europe/Berlin';

-- Jobs table
DROP TABLE IF EXISTS jobs;
CREATE TABLE jobs (
    job_id VARCHAR PRIMARY KEY,
    start_date DATE,
    input_data JSONB,
    submitted BOOL,
    notified_end BOOL,
    logs VARCHAR,
    status VARCHAR,
    version VARCHAR
);

-- Create logs table for application logging
DROP TABLE IF EXISTS logs;
CREATE TABLE IF NOT EXISTS logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    pid INTEGER NOT NULL,
    level VARCHAR(10) NOT NULL,
    module VARCHAR(50) NOT NULL,
    message TEXT NOT NULL
);

-- Create indexes to improve query performance
CREATE INDEX IF NOT EXISTS logs_timestamp_idx ON logs (timestamp);
