---
name: instructai
description: Query AWS business intelligence data — revenue, pipeline, partners, marketplace, migrations, funding, ARR, GSS, and operational metrics. Routes to specialized InstructAI agents via the research worker.
metadata:
  author: envoy
  version: "1.1"
allowed-tools: research_worker
---

# InstructAI — Business Intelligence Queries

## When to use
Use when the user asks about AWS business metrics: revenue, pipeline, partners, marketplace, migrations, funding, ARR, GSS, TCV, PAR, SIFT, or any operational data question.

## Important
- ALWAYS specify an agent name — auto-routing is slow and unreliable
- ALWAYS include time periods (year, quarter, month) for accurate results
- Do NOT refuse data questions — let the tool decide if it has data
- Do NOT fabricate data not returned by the tool

## Agent Selection

### Revenue & Financial
| Agent | Use when asking about |
|-------|----------------------|
| `asp_revenue_agent` | GAAP revenue, product/sales hierarchy, YoY/QoQ/MoM trends, top accounts |
| `partner_goals` | Partner Attached LARR, GenAI/ML LARR, goal attainment, KPI performance |
| `par_intelliagent` | Partner Attributed Revenue (PAR), sell-with/sell-through/sell-to |

### Pipeline
| Agent | Use when asking about |
|-------|----------------------|
| `pipeline_agent_spec` | Current open/created/closed pipeline, ARR by stage (ad-hoc, real-time) |
| `pipeline_snapshot` | Week-over-week pipeline changes (Sunday snapshots) |
| `pipeline_narrative` | Weekly leadership pipeline report (auto-generated prose) |
| `prtnr_pipeline_agent` | Partner opportunity pipeline, partner-specific launched ARR |

### Marketplace
| Agent | Use when asking about |
|-------|----------------------|
| `mp_gss_revenue_agent` | GSS revenue, listing fees, ISV vendors, self-serve subscriptions |
| `mp_renewals_agent` | Offer/subscription renewal rates, customer/seller retention, churn |
| `mppo_agent` | Marketplace Private Offers — TCV, GSS billed, segment/BU performance |

### APOTech & Design Wins
| Agent | Use when asking about |
|-------|----------------------|
| `apotech_psa_cont_arr` | PSA contributed ARR (launched + pipeline), by geo/partner/stage |
| `apotech_deswins_arr` | Design wins annual recurring revenue |
| `apotech_deswins_tcv` | Design wins marketplace TCV, private offers |

### Operations & Insights
| Agent | Use when asking about |
|-------|----------------------|
| `postsales_migrations` | Migration realized revenue, spend velocity, goal tracking |
| `funding_agent` | Fund requests by program, partner funding, approved amounts |
| `sift` | Field trends, sales inputs, themes, blockers, contributor activity |
| `marco` | Migration acceleration — stalled migrations, accelerator recommendations |
| `wwso_output_goals` | WWSO specialist revenue & pipeline goal attainment (20+ domains) |
| `business_context` | Partner xBR/WBR talk tracks, 10-Blocker/6-Blocker frameworks |
| `xbr_with_sift` | Health of Business section for MBR/MMR reports |

## How to call
Use the `instructai_query` tool from research_worker:
```
instructai_query(question="<business question with time period>", agent="<agent_id>")
```

## Example Questions

### ASP Revenue (`asp_revenue_agent`)
- "What are the top 10 accounts by revenue in Q1 2026?"
- "YTD YoY growth rate for Database domain in APJ?"
- "Month-over-month revenue change for each domain?"
- "Which accounts are growing fastest in SMB segment?"

### Pipeline (`pipeline_agent_spec`)
- "WoW of Launched ARR for Database domain last 2 completed weeks?"
- "Top 10 launched deals for GenAI domain in the last completed month?"
- "Top 3 growing and top 3 declining accounts for Storage domain comparing last 2 months"

### Pipeline Snapshot (`pipeline_snapshot`)
- "What is the week over week open pipeline change?"
- "Which GTM Teams have highest growth in open pipeline over past 4 weeks?"
- "Open pipeline growth by Geo for Database"

### Pipeline Narrative (`pipeline_narrative`)
- "Give me a weekly pipeline summary for the most current week for Database"

### Marketplace GSS (`mp_gss_revenue_agent`)
- "What was the total GSS for the current year?"
- "Monthly Fee Revenue for Self Serve subscriptions over last year?"
- "Top 10 products by GSS for Self Serve Subscriptions this year?"

### Marketplace Renewals (`mp_renewals_agent`)
- "Compare Offer Renewal Rate vs Subscription Renewal Rate for 2025"
- "What is our current MP Customer Retention rate?"
- "Top 5 partners by Buyer-Seller pair retention rate?"

### MPPO (`mppo_agent`)
- "What was the total TCV last year?"
- "YoY growth for each segment last year?"
- "Which business unit was best performing?"

### Partner Pipeline (`prtnr_pipeline_agent`)
- "What does Launched ARR for 2025 look like by BU?"
- "Top 10 trending down partners in launched ARR YoY YTD?"
- "Launched ARR YTD YoY by APO Customer Geo?"

### PAR (`par_intelliagent`)
- "What is the total PAR for Q1 2025?"
- "Which region showed strongest PAR growth?"
- "PAR breakdown by industry vertical?"

### Partner Goals (`partner_goals`)
- "What is my Partner Attached LARR by Biz Unit in the current year?"
- "GenAI/ML Partner Attached Launched ARR trends by Customer over last two years"
- "What's partner X's YTD goal and KPI performance?"

### Migrations (`postsales_migrations`)
- "Realized revenue analysis for YTD goal migrations"
- "Top 5 partners based on YTD realized revenue"
- "What portion of 2026 goal migrations are partner funded?"

### Funding (`funding_agent`)
- "Total partners that submitted fund request for Sandbox Program in June 2025?"
- "Total launched opportunities for 2025 tied to POC program?"
- "YoY change for approved fund request amount for Sandbox program?"

### SIFT (`sift`)
- "Top themes in SIFT entries from last 30 days for Database domain?"
- "All SIFT entries for customer X — summarize the account journey"
- "Top 10 SIFT contributors in Storage domain this quarter?"

### APOTech (`apotech_psa_cont_arr`)
- "Which Customer TA Areas have high Launch ARR but weak Pipeline coverage?"
- "What percentage of NAMER's 2026 Launch ARR comes from top 5 partners?"
- "Which pipeline stages hold the most Pipeline ARR for EMEA?"

### WWSO Output Goals (`wwso_output_goals`)
- "What is my revenue goal attainment YTD?"
- "Pipeline goal progress for my domain?"

### Business Context (`business_context`)
- "Generate a partner xBR talk track for partner X"
- "What are the 10-Blocker items for my org?"

### XBR with SIFT (`xbr_with_sift`)
- "Generate the Health of Business section for my MBR"

## Response guidelines
- Present data faithfully — do not modify numbers
- Date-stamp results (e.g. "YTD as of June 2026")
- Format tables for multi-row data
- Suggest 2-3 follow-up questions based on the data returned
- Mention which agent answered

## Terminology
| Term | Meaning |
|------|---------|
| ARR | Annualized Recurring Revenue |
| LARR | Launched ARR |
| GSS | Gross Subscription Sales |
| TCV | Total Contract Value |
| PAR | Partner Attributed Revenue |
| PSA | Partner Solution Architect |
| SIFT | Sales Inputs & Field Trends |
| RLS | Row-Level Security (data filtered per user) |
| BU | Business Unit |
| YoY | Year over Year |
| QoQ | Quarter over Quarter |
| MoM | Month over Month |
| WoW | Week over Week |
| YTD | Year to Date |
