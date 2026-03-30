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
