---
name: slack-catchup
description: Focused Slack catch-up — surfaces unread DMs needing replies, @mentions you missed, and important channel activity. Use when the user asks to catch up on Slack, check unread messages, or see what they missed on Slack.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: comms_worker
---

# Slack Catch-Up

## When to use
Use when the user asks to catch up on Slack, check unread messages, or see what they missed.

## Steps
1. **Scan unread DMs** via comms_worker — find DMs with unread messages
2. **Scan @mentions** via comms_worker — find mentions in channels
3. **Scan important channels** via comms_worker — recent activity in key channels
4. **Prioritize and present**

## Output format
```
## Slack Catch-Up (last N days)

### 🔴 DMs Needing Reply
- **[person]**: [summary of their message] — [time ago]

### 🟡 @Mentions You Missed
- **#[channel]** — [who mentioned you]: [context] — [time ago]

### 🟢 Channel Highlights
- **#[channel]**: [summary of important discussion]
```

## Tips
- Default to 3 days if no timeframe specified
- Prioritize DMs from the user's manager and direct reports
- For channel activity, focus on threads with many replies or reactions
- Offer to mark channels as read after presenting
