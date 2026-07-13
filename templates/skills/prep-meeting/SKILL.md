---
name: prep-meeting
description: Generate a prep brief for any upcoming meeting. Looks up attendees on Phonetool, finds related email threads, and suggests prep actions and talking points. Use when the user asks to prep for a meeting or wants context before a specific meeting.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: research_worker email_worker calendar_worker
---

# Meeting Prep Brief

## When to use
Use when the user asks to prepare for a meeting, wants context before a meeting, or says "prep for [meeting name]". If no meeting is specified, prep for their next calendar meeting.

## CRITICAL: Resolving which meeting to prep for

If the user does NOT specify a meeting name:
1. **Check calendar** via calendar_worker — find the next upcoming meeting today (or tomorrow if evening).
2. If multiple meetings are coming up, present the list and ask the user which one. Do NOT guess.
3. If no meetings found, ask the user: "Which meeting do you want to prep for?"

**NEVER** proceed with the prep steps below until you have identified a specific meeting. Do NOT look up attendees or search emails without a confirmed meeting target.

## Steps
1. **Find the meeting** via calendar_worker — search by subject or get the next upcoming meeting
2. **Identify attendees** — extract the attendee list from the meeting
3. **Look up attendees** via research_worker — Phonetool profiles for each (role, team, level)
4. **Find related emails** via email_worker — search for the meeting subject and attendee names in recent email (7 days)
5. **Synthesize** into a prep brief

## Output format
```
## Meeting Prep: [Subject]
**When:** [date/time] | **Duration:** [length] | **Location:** [room/virtual]

### Attendees
| Name | Role | Team |
|------|------|------|
| [name] | [title] | [team] |

### Context
- [Related email threads]
- [Previous meetings on this topic]

### Suggested Prep
1. [Action items to complete before the meeting]
2. [Questions to raise]
3. [Decisions needed]
```

## Tips
- If the meeting has > 8 attendees, summarize by team rather than listing individually
- Flag if any attendee is a VP+ (executive engagement)
- Note if there's no agenda — suggest the user send one
- NEVER send messages, emails, or any outbound communication during a prep — this is read-only research
- If a tool returns 404 or empty, skip that section gracefully — don't retry with guessed inputs
