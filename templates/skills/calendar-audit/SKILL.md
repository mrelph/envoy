---
name: calendar-audit
description: Audit your calendar for meeting load, focus time, back-to-backs, conflicts, and optimization opportunities. Suggests meetings to decline and protects focus time. Use when the user asks to audit their calendar, reduce meetings, or find focus time.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: calendar_worker
---

# Calendar Audit

## When to use
Use when the user asks to audit their calendar, wants to reduce meeting load, find focus time, or optimize their schedule.

## Steps
1. **Fetch calendar** via calendar_worker — next N days
2. **Calculate metrics** — meeting hours, meeting %, focus blocks
3. **Identify issues** — back-to-backs, conflicts, overloaded days
4. **Suggest optimizations** — meetings to decline, focus blocks to protect

## Output format
```
## Calendar Audit (next N days)

### Meeting Load
- Total meetings: [count]
- Meeting hours: [hours] / [available hours] ([percentage]%)
- Avg meetings/day: [count]

### 🔴 Issues
- **Back-to-backs:** [list of consecutive meetings with no break]
- **Conflicts:** [overlapping meetings]
- **Overloaded days:** [days with > 6 hours of meetings]

### 🟡 Decline Candidates
Meetings that may not need you:
- [meeting] — [reason: large group, optional, recurring with no agenda]

### 🟢 Focus Time
- Available blocks: [list of 2+ hour gaps]
- Recommendation: [suggest blocking specific times]
```

## Decline criteria
Consider suggesting decline for:
- Large meetings (> 10 attendees) where the user isn't presenting
- Recurring meetings with no recent agenda updates
- Meetings where the user is optional
- Informational meetings that could be an email

Never suggest declining:
- 1:1s with the user's manager
- Meetings the user organized
- Interviews or candidate debriefs
