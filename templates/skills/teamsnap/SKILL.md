---
name: teamsnap
description: Check TeamSnap sports schedules, rosters, and game availability. Use when the user asks about their kids' sports schedule, upcoming games, team roster, or who's available for a game.
metadata:
  author: envoy
  version: "1.0"
allowed-tools: teamsnap_schedule teamsnap_roster teamsnap_availability
---

# TeamSnap Integration

## When to use
Use when the user asks about sports schedules, games, practices, team rosters, or availability for their kids' teams.

## Steps

### View schedule
1. Get schedule via teamsnap_schedule — optionally filter by date range
2. Present upcoming games and practices

### Check roster
1. Get roster via teamsnap_roster with the team ID
2. Present players and coaches

### Check availability
1. Get availability via teamsnap_availability with the event ID
2. Show who's in, out, or hasn't responded

## Output format
```
## [Team Name] Schedule

### Upcoming
| Date | Event | Location | Time |
|------|-------|----------|------|

### Availability for [Event]
- ✅ Available: [names]
- ❌ Not available: [names]
- ❓ No response: [names]
```

## Tips
- If the user has multiple teams, ask which one
- Highlight games vs practices differently
- Note any events in the next 48 hours prominently
