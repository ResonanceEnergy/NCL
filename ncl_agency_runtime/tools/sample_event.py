#!/usr/bin/env python3
import argparse, json, uuid, datetime, urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://localhost:8787/event')
    ap.add_argument('--event_type', default='intent.capture.quicklog')
    args = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    payload = {
        "schema_version": "ncl.event.v1",
        "event_id": str(uuid.uuid4()),
        "event_type": args.event_type,
        "occurred_at": now.isoformat(),
        "source": {"device": "iphone", "origin": "sample", "collector_version": "runtime-mac-v1"},
        "privacy": {"level": "P1", "raw_retention": "none", "derived_retention_days": 365},
        "payload": {"note": "sample event", "energy": 3, "stress": 2}
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(args.url, data=data, method='POST', headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(resp.read().decode('utf-8'))


if __name__ == '__main__':
    main()
