---
name: prep-1on1
description: Generate a 1:1 prep brief for a meeting with anyone. Pulls their Phonetool profile, recent email threads, shared to-do items, and upcoming shared meetings. Use when the user asks to prep for a 1:1 or wants talking points for a meeting with a specific person.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: research_worker email_worker calendar_worker productivity_worker
---

# 1:1 Prep Brief

## When to use
Use when the user asks to prepare for a 1:1 meeting, wants talking points for a meeting with someone, or says "prep for my 1:1 with [person]".

## CRITICAL: Resolving who the 1:1 is with

If the user does NOT provide an alias or name:
1. **Check calendar first** via calendar_worker — look at today's remaining meetings (or tomorrow's if evening). Find the 1:1 meeting.
2. Extract the other attendee's name/alias from the calendar event.
3. If multiple 1:1s exist, ask the user which one. Do NOT guess.
4. If no 1:1 is found on the calendar, ask the user: "Who is your 1:1 with? Give me their alias."

**NEVER** proceed with the prep steps below until you have a confirmed alias. Do NOT call lookup_person with an empty or guessed alias. Do NOT send messages or fire outbound comms.

## Steps
1. **Resolve the person** — if alias not given, check calendar first (see above)
2. **Look up the person** via research_worker — get their Phonetool profile (role, team, tenure, manager, location)
3. **Find recent email threads** between the user and this person via email_worker — last 14 days of sent and received
4. **Check shared calendar** via calendar_worker — any upcoming shared meetings in the next 5 days
5. **Check to-dos** via productivity_worker — any action items mentioning this person
6. **Synthesize** into a prep brief

## Output format
```
## 1:1 Prep: [Name] ([alias])
**Role:** [title] | **Team:** [team] | **Tenure:** [time at Amazon]

### Recent Context
- [Summary of recent email threads between you]
- [Any shared meetings coming up]

### Suggested Talking Points
1. [Based on email threads — active topics]
2. [Based on their recent activity — what they're focused on]
3. [Based on shared to-dos or open items]

### Open Items
- [Any action items involving this person]
```

## Tips
- If no recent email history exists, note that and suggest ice-breaker topics based on their profile
- Flag if this person is new (< 90 days tenure) — suggest onboarding-oriented topics
- If they report to the user, emphasize career development and blockers
- NEVER send messages, emails, or any outbound communication during a prep — this is read-only research
- If a tool returns 404 or empty, skip that section gracefully — don't retry with guessed inputs
