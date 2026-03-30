---
name: followup-nagger
description: Scan sent emails for unanswered threads — things you sent that never got a reply. Ranks by urgency and suggests nudge messages. Use when the user asks about follow-ups, unanswered emails, or things that need a nudge.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: email_worker
---

# Follow-Up Nagger

## When to use
Use when the user asks about unanswered emails, follow-ups needed, or wants to know what they sent that got no reply.

## Steps
1. **Fetch sent emails** via email_worker — last N days
2. **Check for replies** — for each sent email, search inbox for replies in the same thread
3. **Identify unanswered** — sent emails with no reply received
4. **Rank by urgency** — based on age, recipient seniority, and content
5. **Suggest nudge messages**

## Urgency ranking
- **Follow up now**: > 3 days old, sent to individuals (not lists), contains a question or request
- **Gentle reminder**: 1-3 days old, or sent to a group
- **No action needed**: FYI emails, broadcasts, or very recent sends

## Output format
```
## Unanswered Sent Emails (last N days)

### 🔴 Follow Up Now
- **[subject]** → [recipient] — sent [date] ([N days ago])
  Suggested nudge: "[draft nudge message]"

### 🟡 Gentle Reminder
- **[subject]** → [recipient] — sent [date]

### 🟢 No Action Needed
- [count] FYI/broadcast emails with no expected reply
```

## Tips
- Default to 7 days if no timeframe specified
- Exclude emails to distribution lists and no-reply addresses
- Draft nudge messages should be brief and friendly
- If the original email was a question, reference it specifically in the nudge
