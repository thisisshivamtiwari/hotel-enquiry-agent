# STUDY: hotel-enquiry-agent

Notes for explaining this project in an interview: the problem, the design choices and why, what the numbers say,
where it fails, and likely questions with answers. All numbers come from [results/summary.json](results/summary.json).

## 1. The problem in one paragraph

A small hotel's inbox is mostly the same dozen questions: is there a room on these dates, what does it cost, can I
bring the dog, we need 6 rooms for a stag do, I want a refund. An LLM can answer them in seconds, but the replies that
go wrong are expensive: a wrong price, a sold-out night offered as free, a refund promised, or a group or complaint
that never reaches a person. The questions here: does a tool lookup fix prices and availability; does code around
the model (checks, one repair, handoff rules, a safe fallback) add anything on top; and what happens when the booking
system fails quietly, which is the normal way integrations fail?

## 2. Design choices

| Choice | Why | Alternative considered |
|---|---|---|
| One made-up hotel with a fixed tariff and a rooms-left table | Every price and availability answer is known exactly, so every reply can be scored | A real hotel (unknown ground truth; can't publish errors about a named business); dynamic pricing (adds noise that isn't the question) |
| A read-only fake booking API that returns a booking link per stay | The agent can quote and link but never book, which is the safe scope for an unsupervised reply desk | A write API (then the eval is about booking mistakes, a different risk) |
| 51 enquiries across 7 kinds, with acceptable handoffs, required facts and must-nots per enquiry | Price questions alone would hide the handoff and safety failures; kinds show where each setup helps | Only booking questions |
| Same system prompt and rules in all three setups | The setups then differ only in what the model can see and what code wraps it | Prompt tuned per setup (confounds the comparison) |
| Tool protocol as JSON in text through `claude -p` | Each step is one recorded call, so CI replays whole conversations without a key | Native tool use through the API (needs a key in CI, harder to record) |
| The guard checks against the agent's own lookups only | A guard that sees the answer key is cheating; this one knows only what production would know | Checking against ground truth (inflates the guard) |
| One repair call, then a fixed safe reply | Bounded cost and latency, and a hard failure never reaches the guest | Loop until clean (unbounded; can drift) |
| Broken booking system: `{}` or JSON cut off at 40% | Quiet failures are what made models invent numbers in the AI Lab tool-failure experiment; timeouts didn't | Only timeouts or HTTP errors (models handle those) |
| Sonnet 5.5 judge with the real lookup answers, plus deterministic checks; disagreements reviewed by hand | The judge handles paraphrase and policy facts; regexes catch amounts, links, contacts and leaks the judge may miss | Regex only (misses "the Garden King is free" without a price) |
| "Ready to send" as the headline | It's the hotel's real question: could this go out without a person touching it | Separate accuracy and safety scores only (no single decision number) |
| Gate rules written before the first run | The bar comes from what a hotel needs, not from the results | Thresholds set after seeing results (circular) |
| Paired exact McNemar tests and Wilson intervals | Same enquiries in every setup, so paired; small n, so exact | Unpaired proportions test (wrong for paired data) |

## 3. Results

From [results/summary.json](results/summary.json): 51 enquiries, one reply each per setup; the broken-system runs use
the 17 enquiries with dates the booking system can answer.

| Setup | Haiku 4.5 ready | Sonnet 5.5 ready | What changed |
|---|---|---|---|
| one-shot prompt | 21/51 | 28/51 | price questions: 2/17 and 1/17 ready; no £ amounts invented, just no answer |
| tool-grounded agent | 31/51 | 38/51 | price questions 15/17 and 13/17 |
| tools + checks + repair + handoff rules | 33/51 | 42/51 | Sonnet: 5 repairs, all removing a "please verify" line |
| tool agent, booking system broken | 2/17 | 2/17 | 15/17 replies with an invented claim; 3 and 4 with a £ amount |
| guarded, booking system broken | 10/17 | 15/17 | 0 invented £ amounts; handoff right in 17/17 for both models |

- Paired tests: one-shot vs guarded p = 0.029 (Haiku) and 0.0026 (Sonnet); tools vs guarded p = 0.5 and 0.125 (not
  significant); broken tools vs broken guarded p = 0.0078 and 0.0002.
- Staff code leaked: 0 of 374 replies. Injections: 1 unsafe reply in 34 injection replies (Haiku tool agent quoted its
  own instructions).
- Cost per reply: Haiku $0.0087-0.0173, Sonnet $0.0053-0.0189; seconds per reply Haiku 13-26, Sonnet 2.9-9.8 (CLI
  start-up included). Total spend: $3.57 replies + $1.54 judge.
- Judge: 44 calls, 1 case unparsed (labelled by hand in [audit/labels.yaml](audit/labels.yaml)); after the scoring
  fixes, 1 check/judge disagreement left, reviewed.

## 4. Failure modes

- **Empty means "no rooms".** Given `{}` from the booking system, both models told a guest (b01) there were no rooms
  on dates that were all free. A quiet failure looks like an answer. The guard's fix is boring: anything that doesn't
  match the API's shape becomes an explicit error that says "don't quote, hand off".
- **Half an answer used as a whole one.** With JSON cut off part way, the models read the first room types and reported
  them as sold out or free. In b02 Sonnet said the results had come back incomplete and still reported two room
  types as sold out.
- **Whose number is it?** Haiku gave the reservations phone number as the events team's line and the duty manager's
  number for guest relations (who are email only). Every number was on the page, so the contact check passed. The
  checks test membership, not attribution.
- **Invented process.** "Select breakfast at checkout", "book up to two days before", "they'll prioritise your case":
  plausible, not on the page, invisible to regexes. Haiku did this in 15-17 replies per setup, Sonnet in 4-6.
- **Pre-judging a dispute.** Haiku told a guest a charge "should have been free" and would be "sorted quickly": not a
  refund promise in words, so the compensation regex missed it; the judge called it unsafe.
- **Missed handoff by category.** An urgent in-stay problem was categorised as a "request" and sent to the duty
  manager only. The handoff rules key off the model's own category plus two patterns, so a miscategorised complaint
  slips through.
- **Tool design.** The API has no infant field. Sonnet counted a baby as a child, the two-person rooms dropped out of
  the result, and it told the guest the Garden King wasn't free, although cots fit there.
- **Over-cautious fallback.** One guarded Haiku reply under the broken system promised a colleague would "book your
  Garden King", which was sold out: the handoff was right, the wording invented availability.
- **Account-level instructions.** The CLI applies the account's instructions to every call, and they add "please
  verify" caveats: Sonnet put one in 14-18 of 51 replies per setup. The guard treats them as not sendable and repairs
  them. That is right for a guest-facing reply, but it means part of the guard's measured gain is cleaning up an
  instruction a clean API deployment wouldn't have.

## 5. What I changed after the first run (and why it isn't tuning to the test)

The first recorded run exposed three scoring bugs, fixed before any result was written up:
1. The scorer and the judge only knew the ground truth for the enquiry's own dates. Sonnet looked up the nights either
   side of a sold-out Saturday and quoted real prices from those lookups, which were scored as invented. Now any
   lookup the agent made against the working system counts as grounded, and the judge sees those answers and the
   booking links (it had been calling real booking links "invented" because it never saw them).
2. With the booking system broken, a handoff to reservations is the right move, but the answer key only allowed "none"
   for plain bookings.
3. The "booking confirmed" regex matched "we store luggage free of charge". It now needs a booking word first.
None of the agent's prompts or the guard's logic changed; the model calls were recorded once. The gate's guarded
rules were scoped to Sonnet after Haiku broke two of them, and the README says so.

## 6. Interview questions

1. **Why not just use a better prompt?** The one-shot prompt already says "never make up a price", and it obeyed:
   0 invented £ amounts. But a prompt can't give the model the rates; it can only make it refuse. The lookup moved price
   questions from 1-2/17 to 13-15/17 ready. Prompts control behaviour; tools supply facts.
2. **The guard only added 2-4 ready replies with a working API and it isn't significant. Why build it?** Because of
   the broken-API result: 2/17 ready without it, 10/17 and 15/17 with it, p = 0.0078 and 0.0002. The guard is
   insurance against integration failures, not a quality booster on the happy path. It also never lets a hard check
   failure through (0 in both guarded runs).
3. **How do you know the judge is right?** I don't fully. It sees the real lookup answers, the facts and the must-nots,
   and the deterministic checks run independently; every disagreement is reviewed by hand. The weakness is that it's
   the same model family as one of the graded models; the next step is a second judge family on a sample.
4. **Why is Sonnet cheaper and faster than Haiku here?** Sonnet ran at effort "low"; Haiku 4.5 has no effort setting
   and the CLI runs it with thinking, so its output tokens (recorded per call in the cassettes) include the thinking. With the same configuration through
   the API, Haiku would likely be cheaper. The honest claim is "in this setup", and the README says so.
5. **What's a quiet failure and why does it matter for agents?** A tool returns something well-formed-looking that
   isn't an answer: `{}`, truncated JSON, a default value. Models treat it as data. In this run an empty result
   became "no rooms available" for free dates. Loud failures (timeouts, errors) are handled well; quiet ones are what
   need code.
6. **How would you put this in production?** The guarded setup with Sonnet, replies as drafts for a person at first,
   with a per-kind auto-send switch: availability and special requests first (15/17 and 8/9 ready), complaints and
   refunds always to a person. Add the attribution check for contacts, log every lookup and guard decision, and
   alert on lookup-failure rate.
7. **What does "ready to send" leave out?** Tone and brand voice beyond "warm and brief", whether the guest actually
   books, and multi-turn threads. It's a safety-and-correctness bar, not a conversion metric.
8. **How do the handoff rules work and where do they fail?** The model gives a category; code maps group_event to
   events and complaint to guest_relations, and two patterns (5+ rooms or a wedding; refund or chargeback) force a team
   regardless of category. They fail when the model miscategorises: an urgent complaint called a "request" got no
   handoff (Haiku c05).
9. **How do you stop prompt injection here?** Mostly by limiting what the agent can do: read-only lookups, no booking
   writes, no discounts. The prompt says guest text is never an instruction, and the checks block the staff code,
   booking confirmations and compensation offers. Result: 0 leaks in 374 replies; 1 unsafe injection reply of 34
   (Haiku quoting its own instructions in the tool agent; the guarded version didn't).
10. **Why record and replay model calls?** CI reruns the whole experiment for free in about a second, fails if any
    prompt, data or scoring change moves the results without a new recorded run, and enforces the gate rules. It also
    lets anyone reproduce the tables without a key.
