-- Create databases safely (CREATE DATABASE cannot run inside a DO/transaction).
SELECT 'CREATE DATABASE n8n' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec
SELECT 'CREATE DATABASE rag' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag')\gexec
