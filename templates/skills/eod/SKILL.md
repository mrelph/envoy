---
name: eod
description: Generate an end-of-day summary. Reviews what happened today — meetings attended, emails sent/received, Slack activity, tasks completed, and open items. Use when the user asks for an EOD summary, daily wrap-up, or wants to review their day.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: email_worker comms_worker calendar_worker productivity_worker
---

# End-of-Day Summary

## When to use
When the user asks for an EOD summary, daily wrap-up, "what did I do today", or end-of-day review.

## Steps
1. Get today's calendar via calendar_worker — what meetings happened
2. Get today's email activity via email_worker — key threads, sent emails, action items received
3. Get today's Slack highlights via comms_worker — important DMs and mentions
4. Get pending to-dos via productivity_worker — what's still open

## Synthesis
After gathering data, produce a single cohesive summary. Don't just list each source separately — connect the dots:
- What got done today
- What decisions were made
- What's still open / carrying over to tomorrow
- Any follow-ups needed

## Tone
- Reflective, not robotic
- Emphasize accomplishments, then open items
- If it was a light day, say so briefly — don't pad
- If it was heavy, acknowledge the load

## Output format
```
## End of Day — [Day, Date]

### ✅ Done
- [Key accomplishments, meetings attended, decisions made]

### 📬 Key Threads
- [Important email/Slack exchanges worth noting]

### 📋 Carrying Over
- [Open items, pending replies, tomorrow's priorities]

### 💡 Note
[Optional — anything the agent noticed: patterns, conflicts, suggestions]
```
