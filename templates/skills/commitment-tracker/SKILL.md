---
name: commitment-tracker
description: Scan sent emails and Slack messages for promises and commitments you made to others. Detects language like "I'll send", "by Friday", "action on me" and categorizes as overdue, due this week, open, or likely fulfilled. Use when the user wants to track their commitments or check what they promised.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: email_worker comms_worker
---

# Commitment Tracker

## When to use
Use when the user asks about commitments, promises, things they owe people, or wants to make sure they haven't dropped anything.

## Steps
1. **Scan sent emails** via email_worker — search sent folder for the specified time period
2. **Scan Slack messages** via comms_worker — search for sent DMs and channel messages
3. **Identify commitments** — look for commitment language patterns (see below)
4. **Cross-reference** — check if commitments appear fulfilled (follow-up email sent, item completed)
5. **Categorize and present**

## Commitment language patterns
Look for these in sent messages:
- "I'll send", "I'll share", "I'll follow up", "I'll get back to you"
- "by Friday", "by end of week", "by tomorrow", "by [date]"
- "action on me", "I owe you", "let me check", "I'll look into"
- "will do", "on it", "I'll take care of", "I'll handle"
- "promise", "commit", "guarantee"

## Output format
```
## Commitments Tracker (last N days)

### 🔴 Overdue
- [commitment] → [who you promised] — was due [date]

### 🟡 Due This Week
- [commitment] → [who] — due [date]

### 🟢 Open (no deadline)
- [commitment] → [who] — sent [date]

### ✅ Likely Fulfilled
- [commitment] → [who] — [evidence of completion]
```

## Tips
- Default to 7 days if no timeframe specified
- Be conservative — only flag clear commitments, not vague statements
- Suggest nudge messages for overdue items
