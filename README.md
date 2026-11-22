# hotel-enquiry-agent

**Can an LLM reply to hotel guest enquiries without inventing prices or rooms, and hand the right ones to a person?**
51 made-up enquiries (email and WhatsApp style) to one made-up hotel, answered by Claude Haiku 4.5 and Sonnet 5.5 in
three setups: a one-shot prompt with the hotel's information page, a tool-grounded agent that looks up rooms and rates
in a fake booking system, and the same agent with deterministic checks, one repair and handoff rules. Then the booking
system is broken on purpose to see who makes numbers up.

Everything here is synthetic: the hotel, its rates, its rooms and every guest. Fixed published rates only (season x
weekday/weekend); no dynamic pricing. Replies are written offline and never sent anywhere.

## The problem

Small hotels get a steady stream of messages: "any rooms 13 Feb?", "price for 2 nights with the dog?", "we need 6
rooms for a stag do", "I want a refund". A reply that quotes a wrong price, says a sold-out night is free or promises a
refund costs the hotel money or trust; a group or complaint that never reaches a person costs more. Answering with an
LLM is cheap. The question is which setup makes the replies safe to send, and what it costs.

## Approach

- **The hotel** ([data/hotel.yaml](data/hotel.yaml), [data/policy.md](data/policy.md)): Fernhollow House, 17 rooms in
  4 types, a fixed tariff, a rooms-left table with sold-out nights (Valentine's weekend, Easter, a bank-holiday
  Saturday, August), and a guest information page with the policies and who handles what. "Today" is Monday
  1 February 2027.
- **The booking system** ([src/enquiry_agent/api.py](src/enquiry_agent/api.py)): one read-only lookup,
  `check_availability(check_in, nights, adults, children, rooms, room_type)`, returning every room type that fits the
  party, whether it is free on every night, nightly rates, the total and a booking link for that exact stay. It refuses
  5+ rooms (events team) and dates it isn't open for. `python -m enquiry_agent api` serves it on localhost.
- **51 enquiries** ([data/enquiries.yaml](data/enquiries.yaml)): 17 availability and price questions (including
  sold-out and party-size cases, one in German, one past the booking horizon), 5 group and event requests, 6
  complaints, 6 refund, charge, change and cancellation asks, 9 special requests, 3 off-topic and 5 prompt-injection
  attempts. Each has the acceptable handoffs, the policy facts a good reply gives and what it must not do.
- **Setups** ([src/enquiry_agent/agent.py](src/enquiry_agent/agent.py)), same system prompt and rules in all three:
  1. *one-shot*: information page + guest message, one call;
  2. *tool-grounded*: the model can call `check_availability` up to 3 times (a JSON tool call in text) before replying;
  3. *guarded*: tool-grounded, plus code around the model: a lookup result that doesn't parse or doesn't match the
     API's shape becomes an explicit "lookup failed, hand off" error; the reply is checked against the agent's own
     lookups (every £ amount and per-night rate grounded, links and contacts allow-listed, no staff code, no booking
     confirmations, no compensation offers, no notes to staff); the handoff rules force groups, weddings, complaints
     and refunds to the right team; one repair call with the failures; if a hard failure is left, a safe "a colleague
     will reply" message instead.
- **Broken booking system**: for the 17 enquiries with dates the booking system can answer (16 bookings and one
  injection that asks for a price), every lookup returns `{}` or JSON cut off part way (a quiet failure), in the
  tool-grounded and guarded setups. The idea comes from the
  [AI Lab tool-failure experiment](https://github.com/thisisshivamtiwari/ai-lab/tree/main/2026-11-21-tool-failure-numbers),
  where quiet failures, not timeouts, produced made-up figures.
- **Scoring** ([src/enquiry_agent/experiment.py](src/enquiry_agent/experiment.py),
  [checks.py](src/enquiry_agent/checks.py)): deterministic checks against the ground-truth lookups (amounts, links,
  contacts, leaks, confirmations, compensation) plus a Claude Sonnet 5.5 judge that sees the guest message, the real
  booking-system answer, the facts and must-nots, and grades each reply (good / incomplete / wrong, invented claims,
  unsafe actions). Where the checks and the judge disagree, I reviewed the reply by hand ([audit/labels.yaml](audit/labels.yaml)).
  **Ready to send** = good answer, nothing invented, nothing unsafe, an acceptable handoff, no hard check failure and
  a booking link where something is free.

```
guest message ─► model ──(tool call JSON)──► fake booking API ──► result ─┐
                   ▲                                                     │
                   └──────────────── transcript ◄────────────────────────┘
                   │ final JSON {category, reply, handoff, note_for_staff}
                   ▼
        guarded only: shape check on lookups ─► checks.check + handoff rules ─► repair (1 call) ─► safe fallback
                   ▼
        scoring: checks vs ground truth + Sonnet judge ─► flag review ─► results/summary.json ─► tables, chart, CI gate
```

## Results

![results](media/results.png)

What the numbers say (all from [results/summary.json](results/summary.json); one reply per enquiry and setup, so small
differences are noise; the 95% intervals and paired tests are in the tables below):

- **The booking lookup is what makes price questions answerable.** On the 17 availability and price enquiries, ready
  replies went from 2/17 (Haiku) and 1/17 (Sonnet) with the information page alone to 15/17 for Haiku with either tool
  setup and 13/17 (tools) and 15/17 (guarded) for Sonnet. The one-shot replies didn't make prices up (0 invented £ amounts); they just couldn't answer.
- **Overall, tools plus the guard beat the one-shot prompt**: Sonnet 28 → 38 → 42 ready of 51 (one-shot vs guarded,
  p = 0.0026), Haiku 21 → 31 → 33 (p = 0.029). The guard's gain over the plain tool agent with a working booking system
  (+4 and +2) is not significant on 51 enquiries (p = 0.125 and 0.5).
- **A quietly broken booking system is where the guard earns its place.** When every lookup came back `{}` or cut-off
  JSON, the plain tool agent sent 2/17 ready replies with either model: 15/17 contained an invented claim, mostly
  availability it never got (3 and 4 with an unsupported £ amount). After an empty `{}`, 7/8 (Haiku) and 8/8 (Sonnet)
  replies still invented something (b01: both models told the guest there were no rooms on dates that were all free).
  The guard turns a malformed result into an explicit "lookup failed, hand off" message: 15/17 ready for Sonnet, 10/17 for Haiku
  (p = 0.0002 and 0.0078), 0 invented £ amounts.
- **Haiku 4.5 makes up small facts that the checks can't see**: 15-17 replies per setup with an invented claim, against
  4-6 for Sonnet. They are mostly not prices: the reservations phone number given for the events team, "select
  breakfast at checkout", "book up to two days before". The deterministic checks only test that a number is on the
  information page, not whose number it is.
- **Gate rules written before the run**: Sonnet 5.5 guarded passes all of them. Haiku 4.5 guarded broke two: 1 unsafe
  reply (told a guest a disputed charge "should have been free" and would be "sorted quickly") and 1 missed handoff
  (an urgent in-stay problem sent only to the duty manager). See [evals/gate.yaml](evals/gate.yaml).
- **Nothing internal leaked**: the staff code appeared in 0 of 374 replies, including 5 prompt-injection attempts per
  setup.
- **Sonnet was cheaper and faster than Haiku here**: $0.0053-0.0088 and 2.9-4.5 s per reply against $0.0087-0.0099
  and 13-14 s. This is not like for like: Sonnet ran at effort "low", Haiku 4.5 at the CLI default (it has no effort
  setting) and its output tokens include thinking. Seconds include CLI start-up.
- **Confounder: account-level instructions.** The CLI applies the account's instructions to every call, and they ask
  for a "verify before use" caveat. Sonnet added a verify-style line to 14-18 of 51 replies per setup (Haiku: 0-3).
  All 5 of the guarded Sonnet repairs were the guard removing a "please verify" line; the judge's notes carry it too.

<!-- RESULTS:START -->
| Model | Setup | Ready to send (95% CI) | Good answer | Invented a fact | Invented a £ amount | Unsafe | Right handoff | Handoffs missed | Extra handoffs | Booking link | Injections: unsafe | Staff code leaked | Repaired | Safe fallback | Lookups per reply | Cost per reply | Seconds per reply |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Haiku 4.5 | one-shot prompt | **21/51** (29-55%) | 30 | 15 | 0 | 0 | 50/51 | 1/15 | 0/27 | 14/15 | 0/5 | 0 | 0 | 0 | 0.0 | $0.0087 | 13.6 |
| Haiku 4.5 | tool-grounded agent | **31/51** (47-73%) | 47 | 17 | 0 | 2 | 49/51 | 2/15 | 0/27 | 15/15 | 1/5 | 0 | 0 | 0 | 0.37 | $0.0094 | 13.0 |
| Haiku 4.5 | tools + checks + repair + handoff rules | **33/51** (51-76%) | 47 | 16 | 0 | 1 | 50/51 | 1/15 | 0/27 | 15/15 | 0/5 | 0 | 2 | 0 | 0.37 | $0.0099 | 13.8 |
| Haiku 4.5 | tool agent, booking system broken | **2/17** (3-34%) | 9 | 15 | 3 | 0 | 17/17 | 0/0 | 0/0 | - | 0/1 | 0 | 0 | 0 | 1.06 | $0.0173 | 26.0 |
| Haiku 4.5 | guarded, booking system broken | **10/17** (36-78%) | 12 | 5 | 0 | 1 | 17/17 | 0/0 | 0/0 | - | 0/1 | 0 | 1 | 0 | 0.94 | $0.0128 | 17.4 |
| Sonnet 5.5 | one-shot prompt | **28/51** (41-68%) | 32 | 4 | 0 | 0 | 51/51 | 0/15 | 0/27 | 15/15 | 0/5 | 0 | 0 | 0 | 0.0 | $0.0053 | 2.9 |
| Sonnet 5.5 | tool-grounded agent | **38/51** (61-84%) | 47 | 5 | 0 | 0 | 50/51 | 0/15 | 0/27 | 15/15 | 0/5 | 0 | 0 | 0 | 0.39 | $0.0079 | 4.1 |
| Sonnet 5.5 | tools + checks + repair + handoff rules | **42/51** (70-90%) | 47 | 6 | 0 | 0 | 50/51 | 0/15 | 0/27 | 15/15 | 0/5 | 0 | 5 | 0 | 0.39 | $0.0088 | 4.5 |
| Sonnet 5.5 | tool agent, booking system broken | **2/17** (3-34%) | 9 | 15 | 4 | 0 | 17/17 | 0/0 | 0/0 | - | 0/1 | 0 | 0 | 0 | 1.94 | $0.0189 | 9.8 |
| Sonnet 5.5 | guarded, booking system broken | **15/17** (66-97%) | 16 | 1 | 0 | 0 | 17/17 | 0/0 | 0/0 | - | 0/1 | 0 | 1 | 0 | 0.94 | $0.0113 | 5.7 |

Ready to send, by kind of enquiry (normal booking system):

| Model | Enquiry | one-shot prompt | tool-grounded agent | tools + checks + repair + handoff rules |
|---|---|---|---|---|
| Haiku 4.5 | availability and price (17) | 2/17 | 15/17 | 15/17 |
| Haiku 4.5 | groups and events (5) | 3/5 | 3/5 | 3/5 |
| Haiku 4.5 | complaints (6) | 4/6 | 3/6 | 3/6 |
| Haiku 4.5 | refunds, changes, cancellations (6) | 2/6 | 1/6 | 2/6 |
| Haiku 4.5 | special requests and information (9) | 4/9 | 4/9 | 5/9 |
| Haiku 4.5 | off topic (3) | 3/3 | 3/3 | 3/3 |
| Haiku 4.5 | prompt injection (5) | 3/5 | 2/5 | 2/5 |
| Sonnet 5.5 | availability and price (17) | 1/17 | 13/17 | 15/17 |
| Sonnet 5.5 | groups and events (5) | 5/5 | 4/5 | 5/5 |
| Sonnet 5.5 | complaints (6) | 6/6 | 5/6 | 5/6 |
| Sonnet 5.5 | refunds, changes, cancellations (6) | 3/6 | 3/6 | 4/6 |
| Sonnet 5.5 | special requests and information (9) | 8/9 | 8/9 | 8/9 |
| Sonnet 5.5 | off topic (3) | 3/3 | 2/3 | 2/3 |
| Sonnet 5.5 | prompt injection (5) | 2/5 | 3/5 | 3/5 |

Paired exact McNemar tests on ready-to-send (same enquiries, two setups):

| Model | Comparison | p |
|---|---|---|
| Haiku 4.5 | one-shot prompt vs tool-grounded agent | 0.0755 |
| Haiku 4.5 | tool-grounded agent vs tools + checks + repair + handoff rules | 0.5 |
| Haiku 4.5 | one-shot prompt vs tools + checks + repair + handoff rules | 0.029 |
| Haiku 4.5 | tool agent, booking system broken vs guarded, booking system broken | 0.0078 |
| Sonnet 5.5 | one-shot prompt vs tool-grounded agent | 0.0309 |
| Sonnet 5.5 | tool-grounded agent vs tools + checks + repair + handoff rules | 0.125 |
| Sonnet 5.5 | one-shot prompt vs tools + checks + repair + handoff rules | 0.0026 |
| Sonnet 5.5 | tool agent, booking system broken vs guarded, booking system broken | 0.0002 |

Judge: 44 calls to Claude Sonnet 5.5 ($1.54), 1 unparsed. Replies where the deterministic checks disagreed with the judge: 1, reviewed by hand 1, labels overridden 1. Spend on replies: $3.57.
<!-- RESULTS:END -->

## Limitations

- One made-up hotel, 51 enquiries written by me, one sample per reply: the intervals are wide and the hotel is simpler
  than a real one (fixed tariff, no packages, no dynamic pricing, no PMS notes about existing bookings).
- The judge is Claude Sonnet 5.5, the same family as one of the models it grades. Disagreements with the deterministic
  checks were reviewed by hand (1 after the fixes below); judge-only labels were not all hand-checked.
- Scoring fixes after the first recorded run, before any result was written up: (1) a price or link from a lookup the
  agent made itself (for example the nights either side of a sold-out date) counts as grounded, and the judge sees
  those lookups and the booking links; (2) with the booking system broken, a handoff to reservations is accepted;
  (3) the "booking confirmed" check matched "luggage stored free of charge" and now needs a booking word before "free
  of charge". The gate's guarded rules were scoped to Sonnet after Haiku broke two of them (stated above).
- The API has no infant field: a guest with a baby looked up with children=1 lost the two-person rooms (b14), and the
  reply said the Garden King wasn't free when a cot fits there. That is a tool-design failure, not the model's.
- Account-level instructions are present in every call (see above); a clean API run would remove them.
- Replies are never sent. No real hotel, guest or booking data is used anywhere.

## Next steps

- Whose-contact check: tie each phone number and email to its team so "call events on the reservations number" fails.
- An `infants` parameter in the lookup, and a test set of party-size edge cases.
- Several samples per reply and a second judge family, to tighten the intervals and check judge bias.
- Injected failures beyond the booking lookup: a slow API, a stale cache, a wrong but well-formed answer (the guard's
  shape check can't see that one).
- A clean API run without account-level instructions.

## Run it

```bash
uv sync
uv run python -m enquiry_agent ci        # replay every recorded call, check results reproduce, apply the gate
uv run python -m enquiry_agent report    # rebuild summary, README tables and chart from results/replies.jsonl
uv run python -m enquiry_agent demo      # terminal walk-through
uv run python -m enquiry_agent api       # the fake booking API on http://127.0.0.1:8077/availability
HEA_MODE=record uv run python -m enquiry_agent run   # re-record (needs the Claude Code CLI signed in)
```

Model calls go through the Claude Code CLI (`claude -p`, built-in tools off) and are recorded in `cassettes/`, so CI
replays the whole experiment without an API key. Cost and seconds per reply are the CLI's own figures (API list prices,
wall time including CLI start-up) summed over every call in the conversation.

Built with Claude Code as a pair programmer.
