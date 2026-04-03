---
name: weekly
description: Generate a weekly review. Looks back at the past 5-7 days — key accomplishments, themes, meetings, email volume, open items, and what to focus on next week. Use when the user asks for a weekly review, weekly summary, or week-in-review.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: email_worker comms_worker calendar_worker productivity_worker
---

# Weekly Review

## When to use
When the user asks for a weekly review, weekly summary, "how was my week", or week-in-review.

## Steps
1. Get this week's calendar via calendar_worker — meetings, how time was spent
2. Get this week's email highlights via email_worker — key threads, volume, who you interacted with most
3. Get this week's Slack highlights via comms_worker — important conversations
4. Get pending to-dos via productivity_worker — what's open, what was completed

## Synthesis
Produce a strategic review, not a daily log. Look for:
- Themes — what dominated the week
- Wins — what went well
- Patterns — who you spent the most time with, what topics recurred
- Gaps — what didn't get attention that should have
- Next week — what's coming up, what to prioritize

## Tone
- Strategic and reflective, like a weekly 1:1 with yourself
- Opinionated — call out if the week was meeting-heavy, if important threads went cold, if priorities shifted
- Brief on quiet weeks, detailed on busy ones

## Output format
```
## Week in Review — [Date Range]

### 🏆 Wins
- [Key accomplishments and progress]

### 📊 By the Numbers
- [Meetings, emails sent/received, Slack volume — quick stats]

### 🔥 Key Themes
- [What dominated the week, recurring topics]

### 📋 Open Items
- [What's carrying over, pending decisions]

### 👀 Next Week
- [What's coming up, suggested priorities]

### 💡 Observations
[Optional — patterns noticed, suggestions for improvement]
```
