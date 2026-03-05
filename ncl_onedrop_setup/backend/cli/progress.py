
import argparse, json, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
data = ROOT / 'backend' / 'data' / 'progress.json'

def load():
    if data.exists():
        return json.loads(data.read_text())
    return {"completed": 150, "total": 500, "updated": datetime.datetime.utcnow().isoformat()+"Z"}

def save(obj):
    data.write_text(json.dumps(obj, indent=2))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--complete', type=int, help='Set insights completed')
    args = ap.parse_args()
    obj = load()
    if args.complete is not None:
        obj['completed'] = args.complete
    obj['percent'] = round(obj['completed']/obj.get('total',500)*100,2)
    obj['updated'] = datetime.datetime.utcnow().isoformat()+"Z"
    save(obj)
    print(json.dumps(obj, indent=2))
