"""
Schema files for the NCL SQLite persistence layer.

Each .sql file in this directory is applied once, idempotently, in lex
order at SqliteStore startup. To add a new schema:

    1. Create NNN_<name>.sql here (number prefix sorts the order).
    2. Drop a matching migration .py in runtime/persistence/migrations/
       only if you need code-side post-migration work (most don't).
    3. The next SqliteStore.initialize() call applies it.

DO NOT edit an applied .sql in place — write a follow-up file that
ALTERs the table. SQLite supports ALTER TABLE ADD COLUMN and rename
operations natively.
"""
