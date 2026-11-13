"""Complete v2 SQL storage port. No knowledge of logical key types."""
import sqlite3

DDL = """CREATE TABLE entries2(
    k BLOB PRIMARY KEY CHECK(typeof(k)='blob'),
    raw TEXT NOT NULL,rev INTEGER NOT NULL,
    value TEXT NOT NULL,deleted INTEGER NOT NULL) WITHOUT ROWID"""

def create(c):
    c.execute(DDL)

def get(c, k):
    return c.execute('SELECT raw,rev,value,deleted FROM entries2 WHERE k=?', (k,)).fetchone()

def put(c, k, raw, rev, value, deleted):
    c.execute('INSERT OR REPLACE INTO entries2 VALUES(?,?,?,?,?)',
              (k, raw, rev, value, deleted))

def all_rows(c):
    return c.execute('SELECT raw,rev,value,deleted FROM entries2 ORDER BY k')

def range_rows(c, lower, upper, after, limit):
    clauses = ['deleted=0']
    args = []
    for bound, op in ((lower, '>='), (upper, '<'), (after, '>')):
        if bound is not None:
            clauses.append('k ' + op + ' ?')
            args.append(bound)
    return c.execute('SELECT raw,rev,value,deleted FROM entries2 WHERE '
                     + ' AND '.join(clauses) + ' ORDER BY k LIMIT ?', args + [limit])

def selfcheck():
    c = sqlite3.connect(':memory:')
    create(c)
    for k in (b'\x02', b'\x01\x00', b'\x01', b'\x00'):
        put(c, k, k.hex(), 1, '{}', 0)
    assert [r[0] for r in range_rows(c, b'\x01', b'\x02', b'\x01', 9)] == ['0100']
    assert get(c, b'\x00')[0] == '00'
    assert c.execute("SELECT sql FROM sqlite_master WHERE name='entries2'").fetchone()[0].endswith('WITHOUT ROWID')
    c.close()
    print('BLOB_RANGE_OK')

if __name__ == '__main__':
    selfcheck()
