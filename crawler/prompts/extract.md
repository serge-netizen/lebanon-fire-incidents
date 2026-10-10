# Extraction prompt — written in task 4

Rules the prompt must carry (BRIEF §4.4, §11):
- An article may describe several incidents (roundups): return a list.
- `null` when the text does not say. 0 only when the text says none.
- A verbatim evidence quote for every non-null field.
- Never output a person's name — not in any field, not in evidence.
- Classify each item: `incident`, `aggregate_report` (daily tallies, seasonal totals) or `not_a_fire`.
- Military fire language ("نيران العدو", "قصف") is not a fire unless a civilian fire resulted; then origin = conflict_related.
- Causes are as reported; never attribute fault to a named business, owner or installer.
