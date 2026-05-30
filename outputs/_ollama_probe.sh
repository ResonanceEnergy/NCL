#!/bin/bash
# Direct Ollama probe
curl -s -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:32b","prompt":"Reply with the literal text: ok","stream":false,"options":{"num_predict":10}}' \
  > /tmp/ollama_probe.json 2>&1
echo "size=$(stat -f%z /tmp/ollama_probe.json)"
head -c 400 /tmp/ollama_probe.json
