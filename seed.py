"""Create the complete supplied v1 database from its historical input batches."""
import json
import sys
from legacy import Store

def main():
    s = Store(sys.argv[1])
    try:
        with open('samples.json', encoding='utf-8') as f:
            for batch in json.load(f):
                s.apply(batch['request'], batch['rows'])
        print(json.dumps(s.snapshot(), ensure_ascii=False, indent=2))
    finally:
        s.close()

if __name__ == '__main__':
    main()
