\set ON_ERROR_STOP on
CREATE TABLE accounts (
  id bigint PRIMARY KEY,
  name text NOT NULL,
  country text NOT NULL,
  risk_score integer NOT NULL,
  segment text NOT NULL
);
CREATE TABLE transfers (
  id bigint PRIMARY KEY,
  sender bigint NOT NULL REFERENCES accounts(id),
  receiver bigint NOT NULL REFERENCES accounts(id),
  amount double precision NOT NULL,
  reason text NOT NULL,
  occurred_at timestamptz NOT NULL
);
INSERT INTO accounts VALUES
  (1, 'Ada', 'GB', 85, 'business'),
  (2, 'Ben', 'US', 73, 'business'),
  (3, 'Chen', 'SG', 91, 'business'),
  (4, 'Dia', 'DE', 60, 'personal'),
  (5, 'Elena', 'ES', 12, 'personal'),
  (6, 'Finn', 'IE', 8, 'personal'),
  (7, 'Gio', 'IT', 5, 'personal'),
  (8, 'Hana', 'JP', 3, 'personal');
INSERT INTO transfers VALUES
  (101,1,2,10,'invoice','2026-10-01T09:00:00Z'),
  (102,1,3,50,'invoice','2026-10-01T09:01:00Z'),
  (103,1,4,12,'refund','2026-10-01T09:02:00Z'),
  (104,2,3,10,'invoice','2026-10-01T09:03:00Z'),
  (105,2,4,13,'invoice','2026-10-01T09:04:00Z'),
  (106,3,4,10,'refund','2026-10-01T09:05:00Z'),
  (107,4,5,5,'subscription','2026-10-01T09:06:00Z'),
  (108,5,6,5,'subscription','2026-10-01T09:07:00Z'),
  (109,6,7,5,'subscription','2026-10-01T09:08:00Z'),
  (110,7,8,5,'subscription','2026-10-01T09:09:00Z');
\getenv reader_password GRAPHMINE_DEMO_READER_PASSWORD
CREATE ROLE graphmine_reader LOGIN PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE graphmine_demo TO graphmine_reader;
GRANT USAGE ON SCHEMA public TO graphmine_reader;
GRANT SELECT ON accounts, transfers TO graphmine_reader;
