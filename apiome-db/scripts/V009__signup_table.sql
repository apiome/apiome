-- Signup Table

SET search_path TO apiome, public;

DROP TABLE IF EXISTS signup CASCADE;

CREATE TABLE signup (
    name VARCHAR(255) NOT NULL,
    email_address VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    signup_source VARCHAR(255),
    signup_date TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_signup_email_address ON signup(email_address);
CREATE INDEX idx_signup_signup_source ON signup(signup_source);
CREATE UNIQUE INDEX idx_signup_email_unique ON signup(email_address);
