"""
setup_schema.py - create the HW5 database and tables on Cloud SQL (MySQL).

Safe to run more than once: everything uses IF NOT EXISTS.

Requirements (on whatever machine runs this):
    pip install "cloud-sql-python-connector[pymysql]" google-cloud-secret-manager
    gcloud auth application-default login   # or a VM service account with
                                            # Cloud SQL Client + Secret Accessor

Usage:
    python3 setup_schema.py
The database password is read from Secret Manager (secret: db-root-password).
Setting DB_PASS in the environment overrides it, e.g. for local testing.
"""
import os

from google.cloud import secretmanager
from google.cloud.sql.connector import Connector

# Hardcode your project ID: the assignment says not to look it up dynamically.
PROJECT_ID = "project-8aeecca0-4f70-4c6b-8e3"
REGION = "us-east1"
INSTANCE = "my-class-db"
INSTANCE_CONNECTION_NAME = f"{PROJECT_ID}:{REGION}:{INSTANCE}"

DB_USER = os.environ.get("DB_USER", "root")
DB_NAME = os.environ.get("DB_NAME", "hw5")
DB_PASS_SECRET = "db-root-password"


def get_secret(secret_id: str, version: str = "latest") -> str:
    """Fetch a secret's value from Google Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


DB_PASS = os.environ.get("DB_PASS") or get_secret(DB_PASS_SECRET)

SCHEMA = [
    # BCNF: is_banned depends only on country (country -> is_banned),
    # so it lives in its own table keyed by country.
    """
    CREATE TABLE IF NOT EXISTS countries (
        country    VARCHAR(64) PRIMARY KEY,
        is_banned  BOOLEAN NOT NULL
    )
    """,
    # One row per request received by the web server.
    """
    CREATE TABLE IF NOT EXISTS requests (
        request_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
        country         VARCHAR(64) NOT NULL,
        client_ip       VARCHAR(45) NOT NULL, -- 45 chars fits IPv6
        gender          VARCHAR(16),
        age             VARCHAR(16),          -- age group string, e.g. '17-25'
        income          VARCHAR(32),          -- income group string
        time_of_day     VARCHAR(32),          -- value of the client's time header
        requested_file  VARCHAR(255) NOT NULL,
        FOREIGN KEY (country) REFERENCES countries(country)
    )
    """,
    # Failed requests (any status other than 200): only time, file, and code.
    """
    CREATE TABLE IF NOT EXISTS failed_requests (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        time_of_request TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        requested_file  VARCHAR(255) NOT NULL,
        error_code      SMALLINT NOT NULL
    )
    """,
]


def main():
    connector = Connector()
    conn = connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pymysql",
        user=DB_USER,
        password=DB_PASS,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
            cur.execute(f"USE `{DB_NAME}`")
            for stmt in SCHEMA:
                cur.execute(stmt)
            conn.commit()

            cur.execute("SHOW TABLES")
            print(f"Tables in {DB_NAME}:", [row[0] for row in cur.fetchall()])
    finally:
        conn.close()
        connector.close()


if __name__ == "__main__":
    main()