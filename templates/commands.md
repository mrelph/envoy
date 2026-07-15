# Commands

Predefined prompts for common workflows. Each command maps a CLI shortcut to an agent instruction.

## briefing

Give me a full briefing — calendar, inbox, and Slack. Cross-reference everything and present by priority: Action Required, Heads Up, FYI.

## calendar

Review my calendar for today. Show meetings, conflicts, and free blocks.

## week

Review my calendar for the week ahead. Highlight key meetings, conflicts, and focus time.

## todo

What action items do I have pending? Show my to-do list prioritized by urgency.

## digest

Generate a team email digest for `{alias}` covering the last `{days}` days.
{if vip} Track my management chain instead of direct reports.
{if select} Only include these people: `{select}`.
{if email} Email the digest to me when done.
{if slack} Send the digest to me as a Slack DM.
{if todo} Extract action items and add them to my To-Do list.
{if no_ai} Skip AI summary — just show the raw email listing.

Defaults: alias=$USER, days=14

## boss

Track my management chain's recent emails. Summarize what my bosses are talking about, decisions made, and anything that needs my attention.

## customers

Scan for external (non-Amazon) customer emails with action items across me and my direct reports over the last `{days}` days. Categorize by urgency: Action Required, Follow-Up, FYI.
{if team} Only scan these team members: `{team}`.
{if email} Email the report to me.
{if slack} Send the report as a Slack DM.

Defaults: alias=$USER, days=14

## cleanup

Scan my inbox for non-critical email (last `{days}` days, up to `{limit}` emails). Classify each as DELETE, REVIEW, or KEEP. Show me the results and let me choose what to delete.

Defaults: days=14, limit=100

## slack

Scan my Slack channels for critical info and actions. Surface: important announcements, decisions made, action items for me, and threads I should weigh in on.

## catchup

I was out for `{days}` days. Give me a comprehensive catch-up combining: team digest, boss tracker, Slack, customer emails, and to-dos. Prioritize into a "first day back" plan — what needs immediate attention vs FYI.

Defaults: days=5

## slack-catchup

Catch me up on Slack from the last `{days}` days. Surface: unread DMs needing replies, @mentions I missed, and important channel activity.

Defaults: days=3

## yesterbox

Run yesterbox on the last `{days}` days. Show me yesterday's direct messages (email and Slack DMs), prioritized with action items.

Defaults: days=1

## triage

Build my unified triage queue for the last `{days}` days. Use the `gather` tool to pull email, Slack, and to-dos in one parallel pass, then merge everything into a SINGLE ranked list of "what actually needs me right now" — not one section per source.

Ranking rules, applied in order:
1. **Deduplicate across sources.** If the same thread, person, or topic shows up in more than one place (use the CROSS-REFERENCES the gather returns), collapse it into one item and note where it appeared, e.g. "(email + Slack)".
2. **Score each item** on: does it need a reply or decision *from me* (highest), is someone blocked waiting on me, is it time-sensitive (deadline, meeting today, aging thread), and who it's from (boss/management chain and external customers rank above internal FYIs).
3. **Sort into three tiers**, most urgent first inside each:
   - 🔴 **Needs me now** — direct asks, blockers, decisions, anything due today or overdue.
   - 🟡 **Should handle soon** — replies expected, follow-ups, aging items not yet critical.
   - 🔵 **FYI / can wait** — awareness only, no action required.
4. Keep each item to one line: a plain-language summary of what's needed, who from, and a suggested next action ("reply", "prep", "delegate", "close"). Do NOT print the internal ref IDs — refer to items by their description; when I ask about one in plain language, drill in using the ref internally.

End with a one-line count per tier so I know the size of the day. Don't pad — if a tier is empty, say so and move on.
{if email} Email me the triage queue when done.
{if slack} Send me the triage queue as a Slack DM.
{if todo} Add the 🔴 items to my To-Do list.

Defaults: days=1

## cal-audit

Audit my calendar for the next `{days}` days. Calculate meeting load percentage, identify back-to-backs and conflicts, suggest meetings to decline, and find/protect focus time blocks.

Defaults: days=5

## team-health

Build a team health dashboard for `{alias}`'s direct reports over the last `{days}` days. For each person, roll up email sent/received volume and Slack recency (silent 3+ days = flag). Present a per-person markdown table, then "Needs Attention" and "Looking Good" sections.

Defaults: alias=$USER, days=7

## response-times

Analyze my email response patterns over the last `{days}` days. Show my average response time, who I'm slow to reply to, who's slow to reply to me, and volume patterns.

Defaults: days=7

## followup

Scan my sent emails from the last `{days}` days for unanswered threads — things I sent that never got a reply. Rank by urgency and suggest nudge messages for overdue items.

Defaults: days=7

## commitments

Scan my sent emails and Slack messages from the last `{days}` days for promises and commitments I made. Look for language like "I'll send", "by Friday", "action on me". Categorize as overdue, due this week, open, or likely fulfilled.

Defaults: days=7

## prep-1on1

Prepare a 1:1 brief for my meeting with `{person}`. Pull their Phonetool profile, find recent email threads between us, surface shared to-do items and upcoming shared meetings, and suggest talking points.

## prep-meeting

Prepare a brief for my upcoming meeting: `{meeting}`. Look up attendees on Phonetool, find related email threads, and suggest prep actions and talking points.
{if no meeting specified} Prep for my next calendar meeting.

## reply

Reply to the email about {arg}. Draft a response and show it to me for approval before sending.

## ea

Send this to my EA: {arg}

## book

Find me a room in {arg}. Check room availability and book it.

## findtime

Find me available meeting times this week. Check my calendar and suggest open slots.

## schedule

Smart-schedule a meeting from this request: `{arg}`. Parse out the duration, attendees, timeframe, and any room/building preference. Look up each attendee on Phonetool to get their verified email address — never guess emails. Check everyone's availability with the calendar worker and propose 2-3 open time slots as numbered options, each with full day, date, and start-end times. Do NOT create the event yet — wait for the user to confirm an option (e.g. "book option 2"), then create the event with the verified attendee emails and book a room in the requested building for that slot.

## search

Search Slack for: {arg}

## sharepoint

On SharePoint/OneDrive: {arg}

## eod

Activate the eod skill and generate my end-of-day summary. Review what happened today — emails sent, meetings attended, to-dos completed, Slack activity. Highlight anything still open or deferred.

## weekly

Activate the weekly skill and generate my weekly review. Summarize the past 7 days: key accomplishments, open items, commitments made, and priorities for next week.

## cron

Show my cron jobs and available presets. List scheduled automation and suggest useful new jobs.

## vault

Activate the brain-query skill and search my vault for: {arg}

## synthesize

Activate the brain-synthesize skill and synthesize what I know about: {arg}

## pulse

Activate the partner-pulse skill and show me the partner pulse. Check relationship health across my key partners.

## dossier

Activate the partner-dossier skill and build a dossier on: {arg}

## pre-game

Activate the pre-game skill and pre-game for: {arg}

## daily-note

Activate the daily-note skill and create my daily note. Reflect on today's activities and capture key thoughts.

## vault-health

Activate the brain-lint skill and lint my vault. Check structural health and flag issues.

## ingest

Activate the brain-ingest skill and ingest my brain inbox. Process new sources and notes.

## exec-sponsor

Activate the exec-sponsor-insights skill and build an exec sponsor brief for: {arg}

## save-email

Activate the email-to-vault skill and save that email to my vault: {arg}
