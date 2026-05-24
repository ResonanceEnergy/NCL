"""
Python-side migration hooks.

Most schema changes are pure SQL — they live in runtime/persistence/schema/
and are applied by SqliteStore at startup. Use this directory only when a
schema change needs code-side post-processing (e.g., back-filling a new
column from another store, or running a one-shot bulk transform).

Naming: NNN_<verb>.py to match the .sql lex-order convention.
"""
