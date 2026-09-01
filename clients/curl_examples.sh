#!/usr/bin/env bash
# Shell / curl client - proves ANY language or tool can connect to ACI over HTTP.
B="${ACI_URL:-http://127.0.0.1:7077}"

echo "health:"
curl -s "$B/health"; echo

echo "monadise (a sensor reading):"
curl -s -XPOST "$B/monadise" -H 'Content-Type: application/json' \
  -d '{"content":"Server room temperature threshold is 27C","source_type":"SENSOR","metadata":{"subject":"server room","predicate":"temp threshold","object":"27C"},"truth_value":2.0}'; echo

echo "recall:"
curl -s -XPOST "$B/recall" -H 'Content-Type: application/json' \
  -d '{"query":"server room temperature","k":2}'; echo

echo "compress stats:"
curl -s "$B/compress"; echo
