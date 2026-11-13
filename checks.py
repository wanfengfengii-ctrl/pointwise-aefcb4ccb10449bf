import json
import sys
from legacy import compare, canonical
from warehouse import Store

def load_samples():
    with open('samples.json', encoding='utf-8') as f:
        return json.load(f)

def populate(s):
    batches = load_samples()
    assert s.apply(batches[0]['request'], batches[0]['rows']) == {'generation':1,'accepted':9}
    assert s.apply(batches[1]['request'], batches[1]['rows']) == {'generation':2,'accepted':3}
    assert s.apply(batches[0]['request'], batches[0]['rows']) == {'generation':1,'accepted':9}
    return batches

def expect_error(call, marker):
    try:
        call()
    except ValueError as exc:
        assert str(exc) == marker, (str(exc), marker)
    else:
        raise AssertionError('missing ' + marker)

def check(s):
    before = s.snapshot()
    assert before['generation'] == 2 and len(before['rows']) == 9
    page = s.scan(lower=[['n','1','3']], upper=[['s','A']], limit=2)
    assert [r['value']['amount'] for r in page['rows']] == [25,22]
    assert page['after'] == [['n','1','3'],['s','']]
    assert [r['value']['amount'] for r in s.scan(after=page['after'])['rows']] == [31,30,-40]
    assert canonical(before['rows'][2]['key']) == [['n','-7','3'],['s','井甲']]
    assert [r['key'] for r in s.scan(limit=1)['rows']] == [[]]
    bad = [{'key':[['s','rollback']], 'rev':1,'value':{},'deleted':False},
           {'key':[['n','3','9']], 'rev':2,'value':{'amount':999},'deleted':False}]
    expect_error(lambda: s.apply('conflict', bad), 'REVISION_CONFLICT')
    assert s.snapshot() == before
    duplicate = [{'key':[['n',a,b]],'rev':4,'value':{},'deleted':False}
                 for a,b in [('1','2'),('-2','-4')]]
    expect_error(lambda: s.apply('duplicate', duplicate), 'DUPLICATE_KEY')
    assert s.snapshot() == before
    expect_error(lambda: s.apply('load', []), 'REQUEST_CONFLICT')
    assert compare([['n','-1','3']], [['n','-1','4']]) < 0
    assert compare([['s','A']], [['s','A\u0000井']]) < 0
    assert s.apply('old', [{'key':[['n','1','3']],'rev':1,
                          'value':{},'deleted':False}]) == {'generation':3,'accepted':0}
    assert s.apply('resurrect', [{'key':[['n','1','3'],['z']],'rev':3,
                                'value':{'amount':90},'deleted':False}]) == {'generation':4,'accepted':1}
    assert len(s.scan()['rows']) == 9

def main():
    mode = sys.argv[1] if len(sys.argv)>1 else 'normal'
    if mode not in ('normal', 'demo'):
        raise ValueError('MODE')
    s = Store(':memory:')
    populate(s)
    if mode == 'demo':
        print(json.dumps({'snapshot':s.snapshot(),
                          'first_page':s.scan(limit=3),
                          'fraction_range':s.scan(lower=[['n','1','3']],
                                                  upper=[['s','A']])},
                         ensure_ascii=False, indent=2))
    else:
        check(s)
        print('WAREHOUSE_REGRESSION_OK')
    s.close()

if __name__ == '__main__':
    main()
