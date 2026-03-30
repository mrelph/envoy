# Commands

Predefined prompts for common workflows. Each command maps a CLI shortcut to an agent instruction.

## digest

Generate a team email digest for `{alias}` covering the last `{days}` days.
{if vip} Track my management chain instead of direct reports.
{if select} Only include these people: `{select}`.
{if email} Email the digest to me when done.
{if slack} Send the digest to me as a Slack DM.
{if todo} Extract action items and add them to my To-Do list.
{if no_ai} Skip AI summary — just show the raw email listing.

Defaults: alias=$USER, days=14

## cleanup

Scan my inbox for non-critical email (last `{days}` days, up to `{limit}` emails). Classify each as DELETE, REVIEW, or KEEP. Show me the results and let me choose what to delete.

Defaults: days=14, limit=100

## customers

Scan for external (non-Amazon) customer emails with action items across me and my direct reports over the last `{days}` days. Categorize by urgency: Action Required, Follow-Up, FYI.
{if team} Only scan these team members: `{team}`.
{if email} Email the report to me.
{if slack} Send the report as a Slack DM.

Defaults: alias=$USER, days=14

## catchup

I was out for `{days}` days. Give me a comprehensive catch-up combining: team digest, boss tracker, Slack, customer emails, and to-dos. Prioritize into a "first day back" plan — what needs immediate attention vs FYI.

Defaults: days=5

## slack-catchup

Catch me up on Slack from the last `{days}` days. Surface: unread DMs needing replies, @mentions I missed, and important channel activity.

Defaults: days=3

## cal-audit

Audit my calendar for the next `{days}` days. Calculate meeting load percentage, identify back-to-backs and conflicts, suggest meetings to decline, and find/protect focus time blocks.

Defaults: days=5

## response-times

Analyze my email response patterns over the last `{days}` days. Show my average response time, who I'm slow to reply to, who's slow to reply to me, and volume patterns.

Defaults: days=7

## followup

Scan my sent emails from the last `{days}` days for unanswered threads — things I sent that never got a reply. Rank by urgency and suggest nudge messages for overdue items.

Defaults: days=7

## prep-1on1

Prepare a 1:1 brief for my meeting with `{person}`. Pull their Phonetool profile, find recent email threads between us, surface shared to-do items and upcoming shared meetings, and suggest talking points.

## commitments

Scan my sent emails and Slack messages from the last `{days}` days for promises and commitments I made. Look for language like "I'll send", "by Friday", "action on me". Categorize as overdue, due this week, open, or likely fulfilled.

Defaults: days=7

## prep-meeting

Prepare a brief for my upcoming meeting: `{meeting}`. Look up attendees on Phonetool, find related email threads, and suggest prep actions and talking points.
{if no meeting specified} Prep for my next calendar meeting.

## yesterbox

Run yesterbox on the last `{days}` days. Show me yesterday's direct messages (email and Slack DMs), prioritized with action items.

Defaults: days=1

## morning-briefing

Give me a morning briefing. Gather email, Slack, calendar, to-dos, and tickets. Cross-reference everything and present by priority: 🔴 Action Required, 🟡 Heads Up, 🟢 FYI.

## eod-summary

End of day summary. Review what happened today — emails sent, meetings attended, to-dos completed, Slack activity. Highlight anything still open or deferred.

## weekly-review

Weekly review. Summarize the past 7 days: key accomplishments, open items, commitments made, and priorities for next week.
