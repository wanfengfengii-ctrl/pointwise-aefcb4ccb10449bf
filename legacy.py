"""Shipped v1 warehouse index; a reference for the public API."""
import copy
import json
import sqlite3
from fractions import Fraction

def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)

def normalize(key):
    if not isinstance(key, list) or len(key) > 8:
        raise ValueError('KEY')
    out = []
    for part in key:
        if not isinstance(part, list) or not part:
            raise ValueError('KEY')
        tag = part[0]
        if tag == 'z' and len(part) == 1:
            out.append((0, None))
        elif tag == 'n' and len(part) == 3:
            a, b = part[1:]
            numbers = []
            for s in (a, b):
                if not isinstance(s, str) or not s or s in ('-', '+'):
                    raise ValueError('KEY')
                body = s[1:] if s[:1] in '+-' else s
                if not body.isascii() or not body.isdigit():
                    raise ValueError('KEY')
                digits = body.lstrip('0') or '0'
                if len(digits) > 1234:
                    raise ValueError('KEY')
                numbers.append((-1 if s[:1] == '-' else 1) * int(digits))
            p, q = numbers
            if not q or abs(p).bit_length() > 4096 or abs(q).bit_length() > 4096:
                raise ValueError('KEY')
            out.append((1, Fraction(p, q)))
        elif tag == 's' and len(part) == 2 and isinstance(part[1], str):
            if any(0xD800 <= ord(c) <= 0xDFFF for c in part[1]):
                raise ValueError('KEY')
            out.append((2, part[1]))
        elif tag == 'b' and len(part) == 2 and isinstance(part[1], str):
            h = part[1]
            if len(h) % 2 or any(c not in '0123456789abcdefABCDEF' for c in h):
                raise ValueError('KEY')
            out.append((3, bytes.fromhex(h)))
        else:
            raise ValueError('KEY')
    return tuple(out)

def canonical(key):
    out = []
    for tag, value in normalize(key):
        if tag == 0:
            out.append(['z'])
        elif tag == 1:
            out.append(['n', str(value.numerator), str(value.denominator)])
        elif tag == 2:
            out.append(['s', value])
        else:
            out.append(['b', value.hex()])
    return out

def compare(left, right):
    a, b = normalize(left), normalize(right)
    return (a > b) - (a < b)

def collation(a, b):
    return compare(json.loads(a), json.loads(b))

def prepare(request, rows):
    if not isinstance(request, str) or not request or not isinstance(rows, list):
        raise ValueError('INPUT')
    checked = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'key', 'rev', 'value', 'deleted'}:
            raise ValueError('INPUT')
        key = normalize(row['key'])
        if key in seen:
            raise ValueError('DUPLICATE_KEY')
        seen.add(key)
        if type(row['rev']) is not int or row['rev'] <= 0 or type(row['deleted']) is not bool:
            raise ValueError('INPUT')
        if row['deleted']:
            if row['value'] is not None:
                raise ValueError('INPUT')
        elif not isinstance(row['value'], dict):
            raise ValueError('INPUT')
        checked.append(copy.deepcopy(row))
    payload = dump(checked)
    return checked, payload

def receipt(c, request, payload):
    old = c.execute('SELECT payload,result FROM receipts WHERE request=?', (request,)).fetchone()
    if old:
        if old[0] != payload:
            raise ValueError('REQUEST_CONFLICT')
        return json.loads(old[1])
    return None

def record(c, request, payload, accepted):
    generation = c.execute('SELECT generation FROM meta').fetchone()[0] + 1
    result = {'generation': generation, 'accepted': accepted}
    c.execute('UPDATE meta SET generation=?', (generation,))
    c.execute('INSERT INTO receipts VALUES(?,?,?)', (request, payload, dump(result)))
    return result

class Store:
    def __init__(self, path):
        self.c = sqlite3.connect(path, isolation_level=None)
        self.c.create_collation('KEY1', collation)
        self.c.executescript("""
            CREATE TABLE IF NOT EXISTS meta(format INTEGER NOT NULL,generation INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS entries(
                raw TEXT COLLATE KEY1 PRIMARY KEY, rev INTEGER NOT NULL,
                value TEXT NOT NULL, deleted INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(
                request TEXT PRIMARY KEY,payload TEXT NOT NULL,result TEXT NOT NULL);
        """)
        if not self.c.execute('SELECT 1 FROM meta').fetchone():
            self.c.execute('INSERT INTO meta VALUES(1,0)')
        if self.c.execute('SELECT format FROM meta').fetchone()[0] != 1:
            self.c.close()
            raise ValueError('FORMAT')

    def close(self):
        self.c.close()

    def apply(self, request, rows):
        rows, payload = prepare(request, rows)
        self.c.execute('BEGIN IMMEDIATE')
        try:
            replay = receipt(self.c, request, payload)
            if replay is not None:
                self.c.execute('COMMIT')
                return replay
            accepted = 0
            for row in rows:
                raw = dump(row['key'])
                old = self.c.execute(
                    'SELECT raw,rev,value,deleted FROM entries WHERE raw=?', (raw,)).fetchone()
                if old and row['rev'] < old[1]:
                    continue
                value = dump(row['value'])
                if old and row['rev'] == old[1]:
                    if value != old[2] or int(row['deleted']) != old[3]:
                        raise ValueError('REVISION_CONFLICT')
                    continue
                if old:
                    self.c.execute('DELETE FROM entries WHERE raw=?', (raw,))
                self.c.execute('INSERT INTO entries VALUES(?,?,?,?)',
                               (raw, row['rev'], value, int(row['deleted'])))
                accepted += 1
            result = record(self.c, request, payload, accepted)
            self.c.execute('COMMIT')
            return result
        except BaseException:
            if self.c.in_transaction:
                self.c.execute('ROLLBACK')
            raise

    def snapshot(self):
        self.c.execute('BEGIN')
        try:
            generation = self.c.execute('SELECT generation FROM meta').fetchone()[0]
            rows = [dict(key=json.loads(k), rev=r, value=json.loads(v), deleted=bool(d))
                    for k,r,v,d in self.c.execute(
                        'SELECT raw,rev,value,deleted FROM entries ORDER BY raw COLLATE KEY1')]
            receipts = [list(r) for r in self.c.execute(
                'SELECT request,payload,result FROM receipts ORDER BY request')]
            self.c.execute('COMMIT')
            return {'generation': generation, 'rows': rows, 'receipts': receipts}
        except BaseException:
            self.c.execute('ROLLBACK')
            raise

    def scan(self, lower=None, upper=None, after=None, limit=20):
        for bound in (lower, upper, after):
            if bound is not None:
                normalize(bound)
        if type(limit) is not int or limit <= 0:
            raise ValueError('LIMIT')
        clauses = ['deleted=0']
        args = []
        for bound, op in ((lower, '>='), (upper, '<'), (after, '>')):
            if bound is not None:
                clauses.append('raw ' + op + ' ? COLLATE KEY1')
                args.append(dump(bound))
        self.c.execute('BEGIN')
        try:
            generation = self.c.execute('SELECT generation FROM meta').fetchone()[0]
            rows = [dict(key=json.loads(k), rev=r, value=json.loads(v), deleted=False)
                    for k,r,v in self.c.execute(
                        'SELECT raw,rev,value FROM entries WHERE ' + ' AND '.join(clauses)
                        + ' ORDER BY raw COLLATE KEY1 LIMIT ?', args + [limit])]
            self.c.execute('COMMIT')
            return {'generation': generation, 'rows': rows,
                    'after': copy.deepcopy(rows[-1]['key']) if rows else None}
        except BaseException:
            self.c.execute('ROLLBACK')
            raise
