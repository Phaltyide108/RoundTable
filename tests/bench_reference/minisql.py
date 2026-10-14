"""Reference for checking the `sql` benchmark's hidden tests themselves: it hands every
statement to SQLite, which the task forbids contenders to do (the test scores it with
the forbidden-import check turned off)."""

import sqlite3


class SQLError(Exception):
    pass


class Database:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")

    def execute(self, sql):
        try:
            return self.db.execute(sql).fetchall()
        except sqlite3.Error as exc:
            raise SQLError(str(exc)) from None
