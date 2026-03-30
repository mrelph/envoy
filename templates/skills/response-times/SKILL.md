---
name: response-times
description: Analyze email response time patterns — how fast you reply and how fast others reply to you. Shows average response times, who you're slow to reply to, and who's slow to reply to you. Use when the user asks about response times or email patterns.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: email_worker
---

# Response Time Tracker

## When to use
Use when the user asks about email response times, reply patterns, or wants to know who they're slow to respond to.

## Steps
1. **Fetch sent emails** via email_worker — last N days
2. **Fetch inbox emails** via email_worker — same period
3. **Match threads** — pair sent replies with the emails they responded to
4. **Calculate response times** — time between received and reply
5. **Identify patterns** — who's fast, who's slow, volume trends

## Output format
```
## Email Response Patterns (last N days)

### Your Response Time
- Average: [time]
- Fastest: [time] (to [person])
- Slowest: [time] (to [person])

### People You're Slow to Reply To
| Person | Avg Response Time | Pending Replies |
|--------|-------------------|-----------------|

### People Slow to Reply to You
| Person | Avg Response Time | Pending Replies |
|--------|-------------------|-----------------|

### Volume Patterns
- Busiest day: [day]
- Most emails from: [person]
- Most emails to: [person]
```

## Tips
- Default to 7 days if no timeframe specified
- Exclude automated/no-reply addresses
- Flag any unanswered emails over 48 hours old
