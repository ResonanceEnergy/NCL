import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.memory import kuzu_bridge


print("available:", kuzu_bridge.is_available())
print("init_schema:", kuzu_bridge.init_schema())

kuzu_bridge.execute('CREATE (:Concept {name: "bitcoin", kind: "asset", importance: 90})')
kuzu_bridge.execute('CREATE (:Concept {name: "halving", kind: "event", importance: 80})')
kuzu_bridge.execute(
    'MATCH (a:Concept), (b:Concept) WHERE a.name = "bitcoin" AND b.name = "halving" CREATE (a)-[:RELATES_TO {rel_type: "affected_by", weight: 0.9}]->(b)'
)

rows = kuzu_bridge.query("MATCH (c:Concept) RETURN c.name, c.kind, c.importance")
print(f"concepts: {len(rows)}")
for r in rows:
    print(" ", r)

rels = kuzu_bridge.query(
    "MATCH (a:Concept)-[r:RELATES_TO]->(b:Concept) RETURN a.name AS src, r.rel_type AS rel, b.name AS dst, r.weight AS w"
)
print(f"relationships: {len(rels)}")
for r in rels:
    print(" ", r)
