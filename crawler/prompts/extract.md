You read one news article from a Lebanese outlet and record every fire it reports, for a public database of fires in Lebanon. Accuracy matters more than completeness: when the article does not say something, record it as not stated (null, an empty list, or "not_established") — never guess, and never fill a field from what is typical for a place.

Return a list `items`, one per distinct event:
- record_type "incident": a specific fire, or an explosion that caused a fire, at a specific time and place. A round-up of several fires gives one item each.
- "aggregate_report": totals across many fires (a Civil Defense "X missions in 24 hours" bulletin, seasonal statistics).
- "not_a_fire": the article is not about an actual fire — figurative fire, gunfire ("نيران" meaning shooting), prevention campaigns, training, policy or court news. Return one such item with every other field at its not-stated value.
- is_lebanon is false for fires abroad (Iran, Gaza, Syria, Europe…); fill nothing else for them.

Rules:
1. Use only what the article states.
2. Never write a person's name anywhere. In evidence quotes, replace names with […].
3. summary: one English sentence in your own words, no names.
4. occurred_on: YYYY-MM-DD when the article gives or clearly implies the date of the fire ("yesterday" counts from the publication date); otherwise null. date_precision says how sure.
5. place_text: the place exactly as printed, most specific first, with the district if given (e.g. "بلدة تول - قضاء النبطية"). Null if no place is given.
6. site_primary: where the fire started; if the article does not say, what burned most. site_others: up to {max_others} other site types the fire reached or involved.
7. hazard_primary: what started or fed the fire, as reported; "not_established" if the article does not say or says it is under investigation. hazard_others: up to {max_others} other hazards the article mentions.
8. materials: what was burning, only as stated, up to {max_materials}. Empty if not stated.
9. origin: accidental; deliberate (set on purpose, arson); conflict_related (a strike, shelling or other military action); unknown. Why a fire started is never a hazard: arson with petrol is hazard "fuel_flammable_liquid" with origin "deliberate".
10. Numbers are null when not stated, and 0 only when the article says none ("no casualties" gives deaths 0 and injuries 0). Area: 1 dunum = 1,000 m², 1 hectare = 10,000 m².
11. responders: who fought the fire, as stated.
12. evidence: for every field you filled except record_type and is_lebanon, one short verbatim quote from the article (field = the field name).
13. confidence: from 0 to 1, how sure you are that the item is right.

SITE TYPES — what kind of place burned (use the sub-type id):
{sites}

HAZARDS — what started or fed the fire:
{hazards}

MATERIALS — what was burning:
{materials}

DAMAGE fields:
{damages}
