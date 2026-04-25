---
name: teamsnap
description: Check TeamSnap sports schedules, rosters, game availability, event details, locations, contacts, announcements, assignments, standings, and RSVP. Use when the user asks about their kids' sports schedule, upcoming games, team roster, who's available, where a game is, snack duty, or wants to set an RSVP.
metadata:
  author: envoy
  version: "2.0"
allowed-tools: teamsnap_schedule teamsnap_roster teamsnap_availability teamsnap_event_detail teamsnap_location teamsnap_contacts teamsnap_announcements teamsnap_rsvp teamsnap_assignments teamsnap_standings
---

# TeamSnap Integration

## When to use
Use when the user asks about sports schedules, games, practices, team rosters, availability, event details, locations, contacts, announcements, snack/volunteer assignments, standings, or wants to RSVP.

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

### Get event details
1. Get details via teamsnap_event_detail with the event ID
2. Show location, uniform, arrival time, and notes

### Find location
1. Get location via teamsnap_location with the event ID
2. Show address, map link, and parking notes

### Get contacts
1. Get contacts via teamsnap_contacts with team_id or member_id
2. Show parent/guardian names, phone numbers, and emails

### Check announcements
1. Get announcements via teamsnap_announcements with the team ID
2. Show recent team broadcasts

### Set RSVP
1. Confirm the event, member, and status (yes/no/maybe) with the user
2. Set RSVP via teamsnap_rsvp

### Check assignments
1. Get assignments via teamsnap_assignments with team_id or event_id
2. Show who's signed up for snacks, carpool, volunteering, etc.

### Check standings
1. Get standings via teamsnap_standings with the team ID
2. Show win/loss/tie record and division standings

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
- For "where's the game?" — use teamsnap_location for the map link
- For RSVP, always confirm with the user before calling teamsnap_rsvp
- For "who's bringing snacks?" — use teamsnap_assignments
