#!/bin/bash
# Runs once, on the first start of an empty MySQL data volume (docker-entrypoint-initdb.d).
# Creates the five logical databases and, per service, a runtime user (DML on its own
# database only) and a migration user (DDL + DML on its own database only).
# Credentials come from .env; nothing secret is stored in this file.
set -euo pipefail

sql=""
for svc in AUTH USER PRODUCT ORDER PAYMENT; do
    db_var="${svc}_DB_NAME"; user_var="${svc}_DB_USER"; pass_var="${svc}_DB_PASSWORD"
    mig_user_var="${svc}_DB_MIGRATION_USER"; mig_pass_var="${svc}_DB_MIGRATION_PASSWORD"
    db="${!db_var:?missing ${db_var}}"
    user="${!user_var:?missing ${user_var}}"
    pass="${!pass_var:?missing ${pass_var}}"
    mig_user="${!mig_user_var:?missing ${mig_user_var}}"
    mig_pass="${!mig_pass_var:?missing ${mig_pass_var}}"

    sql+="
CREATE DATABASE IF NOT EXISTS \`${db}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS '${user}'@'%' IDENTIFIED BY '${pass}';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`${db}\`.* TO '${user}'@'%';
CREATE USER IF NOT EXISTS '${mig_user}'@'%' IDENTIFIED BY '${mig_pass}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES ON \`${db}\`.* TO '${mig_user}'@'%';
"
done

mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<< "${sql} FLUSH PRIVILEGES;"
echo "ShopEase: created 5 databases with runtime and migration users."
