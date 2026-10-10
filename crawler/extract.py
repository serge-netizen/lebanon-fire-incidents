"""Structured extraction with Claude via the Message Batches API (BRIEF §4.4). Task 4.

Haiku 4.5 first; records below the confidence threshold or carrying casualties go to a
Sonnet 5 second pass. Output is constrained to a JSON schema derived from
schema/incident.schema.json. Names are never requested and are stripped if present."""
