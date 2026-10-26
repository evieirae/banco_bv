// Cypher script to clear all data from Neo4j
// Generated from CSV migration data - Time BV
// Version: Data-Driven (100% dynamic)

// Delete all relationships
MATCH ()-[r]-() DELETE r;

// Delete all nodes
MATCH (n) DELETE n;

// Drop all constraints (optional - comment out if you want to keep constraints)
// CALL apoc.schema.assert({}, {});
