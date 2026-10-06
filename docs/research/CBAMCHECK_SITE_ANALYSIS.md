# CBAMcheck (cbamcheck.co.uk) - Design and Product Analysis

Observed: 6 Oct 2026, Chrome (Claude-in-Chrome), desktop viewport ~1024 px wide, plus WebFetch for legal pages and sitemap.
Purpose: give the team enough detail to build a comparable "exposure check" feature inside our UK CBAM platform.
Status: research note, not a requirement. Nothing here overrides `docs/spec/CBAM_Spec_v1.4.md` or `docs/PRD.md`.

## Contents

1. [Scope, method and what could not be accessed](#1-scope-method-and-what-could-not-be-accessed)
2. [Product summary](#2-product-summary)
3. [Site map, information architecture, journeys](#3-site-map-information-architecture-journeys)
4. [Page-by-page layout](#4-page-by-page-layout)
5. [Visual design system](#5-visual-design-system)
6. [Functionality: tools and inferred logic](#6-functionality-tools-and-inferred-logic)
7. [Technical observations](#7-technical-observations)
8. [Compliance accuracy and gaps vs our docs](#8-compliance-accuracy-and-gaps-vs-our-docs)
9. [Implementation recommendations](#9-implementation-recommendations)
10. [Prioritised backlog](#10-prioritised-backlog)

---

## 1. Scope, method and what could not be accessed

**Reached and read:** `/` (home), `/estimate`, `/quick-estimate` (form only, not submitted), `/check` (step 1 only, not submitted), `/cbam-explained` (full, including expanded FAQ), `/book` (Calendly embed), `/privacy` and `/terms` (via WebFetch summaries), `/sitemap.xml` (7 URLs).

**Not accessed, and why (be careful treating these as facts):**

| Item | Reason |
|---|---|
| Quick-estimate result screen and the PDF "readiness report" | Both are behind a form that requires name, company, work email and consent. We were told never to submit lead forms. Output shape is taken from the home-page sample report only. |
| `/check` step 2 (the actual CSV upload step) | Step 1 is a lead form (company, role, work email, import band); step 2 is only reachable by submitting it. Not submitted. |
| CSV template file contents | Not downloaded (no permission to download files). Required columns are taken from the on-page list. |
| API calls / payload shapes | The browser tool's JS sandbox blocked reads of cookie/query-string data, and network capture only starts after first call, so none of the static-page loads were captured. Submission calls were never triggered. **No endpoints or payloads are known.** Only third-party script hosts and form attributes were observed. |
| Mobile viewport rendering | `resize_window` was not loaded; responsiveness is inferred from CSS (max-width containers, stacked cards) and not verified visually. |
| Validation and error messages | Not triggered (would require submitting). Only HTML attributes were inspected (inputs are not marked `required` in the DOM; validation, if any, is in JS). |
| Calendly booking UI | Embedded third-party widget; a cookie banner (Decline / "I understand" / Cookie settings) appeared on `/book`. Not interacted with. |

Browser tools worked throughout; WebFetch was used only for legal pages, the sitemap and two long FAQ answers that the DOM read truncated. Tabs: a new tab was used (a first one was lost mid-session when the tab group was reset; a second new tab was created).

---

## 2. Product summary

CBAMcheck is a free, lead-generation "exposure checker" run by **Oportax Ltd** (England and Wales), which sells a paid UK CBAM compliance platform (import monitoring, supplier outreach for verified emissions, HMRC-ready return and audit pack). The site is deliberately small: one landing page, one education page, two estimate routes, a booking page and legal pages.

Core promise: "Find out what UK CBAM will cost your business in 2027" - a **liability range in GBP** plus a supplier-readiness report, delivered as a PDF by email in about 60 seconds.

Positioning notes worth copying:
- Honest labelling: estimates use *proxy* factors (EU Commission defaults / sector global averages) "until the UK Treasury notice is published", and an *assumed* CBAM rate of £35-£55/tCO2e. The word "indicative" appears on every page that shows a number.
- Funnel: free estimate -> "Prepare the return with Oportax" -> Book a 20-minute call (Calendly).
- Authority content: regulation timeline citing SI numbers, key-facts table, glossary, EU vs UK comparison.

---

## 3. Site map, information architecture, journeys

### 3.1 Site map

| Path | Title (tab) | Purpose | In sitemap.xml | Priority |
|---|---|---|---|---|
| `/` | UK CBAM exposure checker, Free tool by Oportax | Landing, explain, convert | yes | 1.0 |
| `/estimate` | Estimate your UK CBAM levy | Choose route: upload vs quick | yes | - |
| `/quick-estimate` | Quick CBAM estimate | 5-question wizard (single page form) | yes | - |
| `/check` | Check your UK CBAM exposure | 2-step flow: details then upload | yes | - |
| `/cbam-explained` | UK CBAM explained | Long-form regulatory guide, FAQ, glossary | yes | - |
| `/book` | Book a call | Calendly embed (30 min meeting; copy says 20 min - inconsistent) | no | - |
| `/privacy` | Privacy policy | Legal (last updated 5 Jun 2026) | yes | 0.2 |
| `/terms` | Terms of service | Legal | yes | 0.2 |
| `oportax.com/book`, `mailto:hello@oportax.com` | external | Parent-brand CTA | - | - |

All seven sitemap pages show `lastmod` 2026-10-06 (generated at build time, so it carries no signal).

### 3.2 Navigation

- **Header (all pages, static, 65 px, 1 px bottom border):** wordmark "CBAMcheck" (left); right: `CBAM explained` (text link), `Book a call` (text link with a left divider), `Check my exposure` (primary navy button).
- **Footer (4 columns on desktop):** brand + "Built for UK importers. Independent of HMRC."; Product (Check exposure, CBAM explained, Book a call); Legal (Privacy policy, Terms of service, hello@oportax.com); "Oportax" link.
- No search, no login, no pricing page, no blog/resources index, no multi-level menu. Mobile menu behaviour was not observed.

### 3.3 Primary journeys

```
Home --"Get free estimate"--> /estimate --+--> Upload CSV --> /check (step 1: lead details -> step 2: upload) --> report by email (PDF)
                                          \--> Quick estimate --> /quick-estimate (5 Q + name/company/email/consent) --> estimate + report
Home --"Check my exposure" (header/CTA)--> /check
Home --"Read full breakdown"--> /cbam-explained --"Check my exposure"/"Book a call"-->
Any page --"Book a call"--> /book (Calendly)
/check banner: "Don't have a CSV? Try our quick estimate instead" --> /quick-estimate
```

CTA inventory on home: header x2, hero "Get free estimate", "Read full breakdown", Oportax block "Book a call", final-CTA "Get free estimate", plus "Check exposure" in footer. Every CTA is either "get the estimate" (navy, filled) or "book a call" (text/outline). Single colour, single primary action.

---

## 4. Page-by-page layout

Tone: plain-English, calm, advisory, no emoji, no exclamation marks; short declarative sentences; numbers given as specific figures ("£50,000", "2 min", "60 sec"). Heavy use of caveat language ("indicative", "labelled proxy").

### 4.1 Home `/`

Sections in order (backgrounds alternate white / #FAFAFA):

| # | Section | Content (summary) |
|---|---|---|
| 0 | Header | wordmark, 2 links, primary CTA |
| 1 | Hero (padding-top 128 px) | H1 "Find out what UK CBAM will cost your business in 2027." sub "free liability estimate and supplier readiness report"; primary button "Get free estimate" with arrow; micro-copy "Built specifically for UK importers." Right side: line-art illustration of cargo ship, port, factories, train, rising bar silhouette in navy/grey (decorative, descriptive alt text). |
| 2 | "Does this apply to me?" (eyebrow) | H2 "You must register for UK CBAM if either test is true"; two numbered tests (30-day forward £50k, 12-month backward £50k checked on the 1st). Side card: five sectors list + note that only imports from 1 Jan 2027 count. |
| 3 | "Three steps" (grey bg) | How it works: 1 Upload customs data (2 min), 2 Get liability estimate (60 sec), 3 Receive readiness report (instant). Each step has a numeral circle, time chip, short copy. |
| 4 | "Scope" | H2 "Who needs to care about UK CBAM?" five sector cards: Aluminium, Cement, Fertiliser, Hydrogen, Iron and steel, each with one-line product list. |
| 5 | "The regulation" (grey bg) | H2 "What the regulation actually says"; 3 paragraphs (Budget 2024, regs made 13/14 Jul and 8 Sep 2026); link "Read full breakdown"; 4 stat tiles: 1 Jan start, £50k threshold, 5 sectors, £35-£55 assumed rate. |
| 6 | "Your report" | Three feature blurbs (Liability estimate, Supplier exposure, Action checklist) + a mock PDF card "UK CBAM Readiness Report - Example" (company, month, estimated liability range, sector bar breakdown, top-3 suppliers with country code chips). |
| 7 | Oportax upsell (grey bg) | H2 "Prepare the return with Oportax"; 3 bullets (continuous import monitoring; automated supplier outreach; HMRC-ready returns prepared for you to file); "Book a call". |
| 8 | FAQ | 9 accordion questions (What is UK CBAM, start date, goods in scope, de minimis, how liability is calculated, data needed, accuracy, registration, UK vs EU). |
| 9 | Final CTA | "Find out where you stand before 2027." + "in under 5 minutes" + button. |
| 10 | Footer | as 3.2 |

Note the sample report content (Acme Manufacturing Ltd; £62,000 - £94,200; Steel £28,500, Aluminium £19,800, Cement £11,200, Fertiliser £2,500; suppliers in CN, NL, AE) is illustrative and labelled "Example".

```
+------------------------------------------------------------------------------------------+
| CBAMcheck                                   CBAM explained | Book a call | [Check my exposure]|
+------------------------------------------------------------------------------------------+
|  Find out what UK                                   .  ,-/|   (line-art ship, port,       |
|  CBAM will cost your                              ,-'  | |   chimneys, rising bars)       |
|  business in 2027.            (Fraunces 56px)                                              |
|  Free liability estimate and supplier readiness report.                                    |
|  [ Get free estimate -> ]    Built specifically for UK importers.                          |
+------------------------------------------------------------------------------------------+
|  DOES THIS APPLY TO ME?                       +------------------------------------+       |
|  You must register if either is true         | CBAM goods: five sectors           |       |
|  (1) >= GBP50k expected in next 30 days       | Alu - Cement - Fert - H2 - Iron/St |       |
|  (2) >= GBP50k in previous 12 months,         | Only imports from 1 Jan 2027 count |       |
|      checked on the 1st of each month         +------------------------------------+       |
+------------------------------------------------------------------------------------------+
|                         THREE STEPS  /  How it works             (grey band)               |
|   (1) 2 min Upload data     (2) 60 sec Estimate        (3) Instant Readiness report        |
+------------------------------------------------------------------------------------------+
|  Scope: [Aluminium] [Cement] [Fertiliser] [Hydrogen] [Iron and steel]   (5 cards)          |
+------------------------------------------------------------------------------------------+
|  Regulation text (3 paras) | Read full breakdown ->     [1 Jan][GBP50k][5][GBP35-55]     |
+------------------------------------------------------------------------------------------+
|  Your report: Liability estimate / Supplier exposure / Action checklist | [mock PDF card]  |
+------------------------------------------------------------------------------------------+
|  Prepare the return with Oportax  - 3 bullets - [Book a call]           (grey band)        |
+------------------------------------------------------------------------------------------+
|  FAQ accordion (9)                                                                         |
+------------------------------------------------------------------------------------------+
|  Find out where you stand before 2027.   [ Get free estimate ]                             |
+------------------------------------------------------------------------------------------+
|  Footer: brand | Product | Legal | Oportax                                                 |
+------------------------------------------------------------------------------------------+
```

### 4.2 `/estimate` (route chooser)

H1 "Get your CBAM estimate"; sub "Both options are free". Two equal cards side by side (stack on narrow screens):

- **Upload your import data** (badge "Most accurate"): copy about matching each line against CBAM commodity codes and "liability per shipment"; checklist "Your file should include": commodity codes (8 or 10 digit), country of origin, net weight (kg), invoice value (GBP); link "Download CSV template"; primary button "Upload CSV" (navy, filled).
- **Quick estimate** (lightning icon): "Answer five questions"; "Best if you" checklist (no customs data to hand / want a ballpark / need a number for a board discussion); note "about 60 seconds, less precise"; secondary outline button "Start quick estimate".

```
Get your CBAM estimate
Choose how you want to estimate your UK CBAM liability. Both options are free.
+-------------------------------------+   +-------------------------------------+
| [Most accurate]                     |   | (bolt icon)                          |
| (file icon)                         |   | Quick estimate                       |
| Upload your import data             |   | Answer five questions ... proxy      |
| text ...                            |   | Best if you:                         |
| Your file should include:           |   |  o no customs data to hand           |
|  o Commodity codes (8 or 10 digit)  |   |  o want a ballpark                   |
|  o Country of origin                |   |  o need a number for the board       |
|  o Net weight (kg)                  |   | ~60 seconds. Less precise ...        |
|  o Invoice value (GBP)              |   | [ Start quick estimate -> ] (outline)|
|  Download CSV template              |   +-------------------------------------+
| [        Upload CSV ->            ] |
+-------------------------------------+
```

### 4.3 `/quick-estimate`

Single long form, ~640 px column, eyebrow "Free estimate", H1 "Estimate your UK CBAM exposure in 60 seconds". All questions on one page (not a stepper):

1. Annual import value from outside the UK (radio, `name=importBand`): Under £100k; £100k-£500k; £500k-£2m; £2m-£10m; £10m-£50m; Over £50m.
2. CBAM sectors imported (checkboxes): Iron & steel; Aluminium; Cement; Fertiliser; Hydrogen; Not sure.
3. Main countries of origin (checkboxes, 11): Turkey; India; China; South Korea; Russia; Egypt; UAE; Ukraine; Norway; Brazil; Other.
4. Number of overseas suppliers (radio, `name=supplierCount`): 1-3; 4-10; 11-25; 26-50; 50+.
5. "Your details (for the report)": Name, Company name, Work email (type=email), consent checkbox linking to privacy policy; submit "Get my estimate".

Observations: the form element has `method=get` with a submit button (progressive-enhancement default; a JS handler almost certainly intercepts it - not confirmed). No input has the `required` attribute. Radio/checkbox inputs are native, small and left-aligned. Note: the import bands here (6 bands, top "Over £50m") differ from `/check` step 1 bands (Under £50k ... £20m+) - two different band sets for the same concept.

### 4.4 `/check` (upload route)

A tinted info banner on top: "Don't have a CSV? Try our quick estimate instead in 60 seconds, no upload needed." H1 "Check your exposure"; sub "Upload your import data and get a free CBAM liability estimate in under 5 minutes." A 2-step progress indicator (circles 1, 2). Step 1 fields: Company name (placeholder "Acme Manufacturing Ltd"), Your role (select: Finance Director, Head of Procurement, Customs Manager, CFO, Sustainability Lead, Other), Work email (placeholder you@company.co.uk), Approximate annual import value (select: Under £50k; £50k-£250k; £250k-£1m; £1m-£5m; £5m-£20m; £20m+), "Continue". Step 2 (not seen) is presumably the file upload. The form column is narrow (~280 px at this viewport) and left-aligned, leaving the right half empty - looks unfinished on desktop.

### 4.5 `/cbam-explained` (long-form guide)

Eyebrow "Regulatory guide", H1 "UK CBAM explained", intro, disclaimer line ("Based on... Emissions and Verification Regulations made 8 September 2026... not legal or tax advice"). Blocks in order:

1. **Key facts** definition table (start date, sectors, threshold, liability basis, CBAM rate, filing frequency, record keeping, assumed rate in estimates).
2. What is UK CBAM (carbon leakage rationale; "not a tariff").
3. Who is in scope (liable person is importer named on declaration; broker/forwarder/agent not liable; tax representative can file but cannot register the importer); **sector table** (Sector / Key commodity codes / Scope).
4. How is the liability calculated: formula `Liability = Embedded emissions (tCO2e) x CBAM rate (£/t) - Carbon Price Relief (£)`; embedded emissions = tonnes x intensity; verified vs default; CPR conditions; **default-basis table** (product, estimate, source: worldsteel 1.92; IAI 15.1; GCCA 0.8; IEA 2.4; IEA 11).
5. **Key dates** timeline (13-16 Jul 2026; 8 Sep 2026; autumn 2026; 1 Jan 2027; 31 Jan 2028; 31 May 2028; 2028 quarterly; Q1 due 31 Jul 2028).
6. What importers need to do (4 numbered steps: assess, register, engage suppliers, set up reporting).
7. How to get import data (CDS export, agents, 8/10-digit codes).
8. **UK vs EU CBAM comparison table** (start, sectors, carbon price link, payment, frequency, defaults, de minimis).
9. Common questions (5-item accordion, one-open-at-a-time; buttons with "+" glyph).
10. Glossary (6 terms) and a Sources line citing SI 2026/802, /809, /830, /995, GOV.UK guidance, HMRC Systems Boundaries Reference Document; "Last reviewed August 2026".
11. Closing CTA block (Check my exposure / Book a call).

### 4.6 `/book`

H1 "Book a call"; copy: free 20-minute call, "no sales pitch"; "We're the team behind Oportax, the UK CBAM compliance platform"; Calendly inline widget ("30 Minute Meeting", host named). Inconsistency: copy says 20 minutes, widget says 30.

### 4.7 `/privacy`, `/terms`

Privacy (summary): controller Oportax Ltd; collects name/company/email/role, import data (codes, origins, values, weights, supplier names) and anonymised usage analytics; processors named: PostHog (EU), Resend (email), Vercel (hosting), Supabase (EU database/storage), Calendly; retention 24 months from upload with deletion on request; lawful basis legitimate interest for the service and consent for marketing; non-essential analytics cookies are opt-in via banner (note: PostHog scripts were present in the page before any consent action - consent behaviour not verified); last updated 5 Jun 2026.
Terms (summary): estimates "indicative only"; no guarantee of accuracy; users keep ownership of uploads, grant a limited processing licence, told not to upload personal data beyond the listed categories; England and Wales law; liability capped at £100; service independent of HMRC, not tax/legal advice.

---

## 5. Visual design system

Values read from computed styles on the live site (desktop). Tailwind v4-style utilities appear to be in use (oklab colour values, 12/14/16/18/30/56 px scale, 4 px spacing grid).

### 5.1 Colour palette

| Role | Hex | Source / usage |
|---|---|---|
| Ink (text, headings) | `#0A0A0A` (rgb 10,10,10) | body and heading colour |
| Muted text | `#525252` (82,82,82) | paragraphs, captions |
| Primary / brand navy | `#0E2A47` (14,42,71) | primary buttons, eyebrow text, wordmark accents, numeral circles |
| Navy tint 10% | navy @ 10% alpha (oklab 0.280 -0.020 -0.060 / 0.1) | icon chips, soft fills |
| Navy tint 15% | navy @ 15% alpha | card borders (12 px radius cards) |
| Navy 70% | navy @ 70% alpha | secondary fills |
| Border / divider | `#E5E5E5` (229,229,229) | header bottom border, card borders (8 px radius), table rules |
| Surface alt | `#FAFAFA` (250,250,250) | alternate section bands, sample-report card |
| Surface alt 50% | near-white @ 50% alpha | translucent cards |
| Page background | `#FFFFFF` | body |
| On-primary | `#FFFFFF` | text on navy buttons |

No red/amber/green status colours were observed (nothing on the pages needed them). The look is monochrome plus one navy accent.

### 5.2 Typography

| Element | Family | Size / line-height | Weight | Letter-spacing | Colour |
|---|---|---|---|---|---|
| H1 | Fraunces (serif; Georgia fallback) | 56 / 61.6 px | 400 | -1.4 px (-0.025 em) | #0A0A0A |
| H2 | Fraunces | 30 / 36 px | 400 | -0.75 px | #0A0A0A |
| H3 | Inter | 16 / 24 px | 500 | normal | #0A0A0A |
| Lead paragraph | Inter | 18 / 28 px | 400 | normal | #525252 |
| Body | Inter | 16 / 25.6 px (1.6) | 400 | normal | #0A0A0A |
| Eyebrow | Inter | 12 px | 500 | 1.2 px, uppercase | #0E2A47 |
| Button | Inter | 14 px | 500 | normal | #FFFFFF on navy |

Fonts are self-hosted variable fonts (Inter 100-900, Fraunces 100-900) with generated size-adjusted fallbacks ("Inter Fallback", "Fraunces Fallback") - this is the signature of Next.js `next/font`. Serif display + neutral sans is the main brand differentiator (editorial, trustworthy).

### 5.3 Spacing, layout and shape

| Token | Value |
|---|---|
| Max content width | 1200 px; text blocks 560 / 640 / 720 px |
| Section vertical padding | 80 px (py-20); hero top 128 px (py-32); one thin band 56 px |
| Section rhythm | white / #FAFAFA alternating bands, no dividers |
| Header | 65 px tall, static (not sticky), 1 px #E5E5E5 bottom border, transparent bg |
| Button (primary) | bg #0E2A47, white 14/500, padding 12 x 24, radius 6 px, no border, no shadow |
| Card | 1 px border (#E5E5E5 or navy 15%), radius 8-12 px, no shadow |
| Eyebrow + H2 + lead | standard section header pattern |

### 5.4 Components observed

- Primary button with trailing arrow icon; outline/secondary button; text nav links with a vertical divider before "Book a call".
- Card with badge ("Most accurate"), icon chip, title, body, check-list, CTA.
- Numbered step circles (1, 2, 3) with time chips ("2 min", "60 sec", "Instant").
- Stat tiles (value + caption); sector cards; definition table (key facts); data tables with light row rules (sector codes, default factors, UK vs EU) and a header row; vertical timeline for key dates.
- Accordion: button row with "+"/"x" glyph, one open at a time, animated reveal. Implemented as button (not `<details>`), `aria-expanded` found on 5 elements.
- Mock PDF document card (report preview) with a horizontal bar breakdown and ranked supplier rows with country-code chips.
- Form controls: native radios/checkboxes, text/email inputs with placeholder examples, native selects (chevron styling), 2-step progress circles, info banner.
- Cookie consent banner (Calendly-hosted on `/book`): Decline / I understand / Cookie settings.
- Decorative hero illustration (monochrome line art with navy fill) with a long descriptive alt text.

### 5.5 Responsive and accessibility observations

- Layout is container-based with stacked cards; the screenshot at ~1024 px shows the hero illustration cropped on the right and a single-column flow. Mobile behaviour: **not verified**.
- Positives: semantic headings (one H1 per page, H2 per section), accessible names on accordion buttons, descriptive alt text, high text contrast (#0A0A0A / #525252 on white; #FFFFFF on #0E2A47 is roughly 14:1), generous line-height, no colour-only meaning.
- Concerns: `#525252` at 12-13 px captions is acceptable (about 7.8:1) but small; small native radio/checkbox targets and no custom focus ring was visible in screenshots; the sector list on `/quick-estimate` lists 11 countries without a search, so "Other" hides a long tail; `/check` form is narrow with large unused space; no skip link observed; the `method=get` form relies on JS (progressive enhancement unclear).

---

## 6. Functionality: tools and inferred logic

### 6.1 Tool inventory

| Tool | Inputs | Output (as advertised) | Gate |
|---|---|---|---|
| Upload checker (`/check`) | Company, role, work email, import band; then file (CSV or Excel) with commodity code (8/10 digit), country of origin, net weight kg, invoice value GBP | Liability range, breakdown by sector and by supplier ("liability per shipment"), action checklist; PDF emailed in ~60 s | Lead form first |
| Quick estimate (`/quick-estimate`) | 4 closed questions + name, company, email, consent | Liability range (low-high) using sector global averages | Lead form on same page |
| CSV template | download link | template file | none |
| Readiness report | n/a | PDF: estimated 2027 liability range, assumed rate £35-£55/t, sector breakdown, top exposed suppliers, checklist | emailed |

There is no on-page threshold calculator, no commodity-code lookup, and no scope checker as a standalone tool, even though the home page states the two registration tests.

### 6.2 Inferred calculation logic

All inferred from page copy; the code and results were not observed.

1. **Scope match:** each CSV line's commodity code is matched against an in-scope code list. Copy says "8 or 10 digit", "partial code matches may not be in scope", and the sector table gives only 4-digit headings (e.g. 7601, 7603-7616, 7618; 2523, 6810, 6811; 2814, 2834, 3102, 3105; 2804.10; 7201-7207, 7218; 7208-7217, 7219-7229, 7304-7306), so the real match is presumably against a fuller 8-digit list held server-side.
2. **Threshold:** "Only imports from 1 January 2027 count"; below £50,000 "no CBAM obligations". The estimator itself does not appear to compute a registration date.
3. **Embedded emissions per line:** `net weight (t) x intensity factor (tCO2e/t)`. Factor = EU Commission product-level default (proxy) where available, else a sector global average. Table shown on the guide: steel 1.92 (crude steel), primary aluminium 15.1, cement clinker 0.8, ammonia 2.4, hydrogen 11 (tCO2/tCO2e per tonne). "Country of origin does not change the default basis."
4. **Liability range:** `emissions x rate` for rate in [£35, £55] per tCO2e (low/high), "after free allocation"; no CPR assumed. Sample report: £62,000 - £94,200 (ratio 1.52, slightly below 55/35 = 1.57, so the high/low are not an exact linear scale or the sample is hand-written).
5. **Quick estimate:** import band midpoint x sector share x average intensity per £ of goods x rate range (inferred; the country and supplier-count answers are collected but the guide says country does not change defaults, so they probably only feed the lead score and supplier-exposure narrative).
6. **Supplier ranking:** sum of estimated liability per supplier, shown with country code chips.

### 6.3 Edge cases visible or implied

- Non-GBP values: template column is "Invoice value (GBP)" - the user must convert; no FX handling. (Our R1-035 requires source currency and customs-rate conversion.)
- 8 vs 10 digit codes both accepted; unknown/invalid code handling and error messages **not observed**.
- Pre-2027 imports: copy says they do not count towards the threshold, but a CSV of 2025-26 data is the obvious input; how the checker treats those lines (annualise? exclude?) is not stated.
- Special procedures, returned goods, re-exports, exemptions, tax point vs declaration date: not mentioned anywhere.
- Quick estimate answer "Not sure" for sectors: handling not documented.

### 6.4 Validation and errors

Not observed (see section 1). The DOM shows no `required` attributes, so behaviour is entirely script-driven. Treat the rest as unknown rather than assuming.

---

## 7. Technical observations

| Area | Observation | Confidence |
|---|---|---|
| Framework | React app built with Next.js App Router and Turbopack (chunk names `turbopack-*.js`, `?dpl=dpl_...` deployment-id query on chunks) | high |
| Hosting | Vercel (deployment ids; privacy policy names Vercel) | high |
| Styling | Tailwind CSS v4 style utilities (oklab colours, 4 px scale) | medium |
| Fonts | `next/font`: Inter + Fraunces, self-hosted with fallbacks | high |
| Analytics | PostHog, EU region (`eu-assets.i.posthog.com`): config.js, surveys.js, dead-clicks-autocapture.js, **posthog-recorder.js (session replay)**, web-vitals.js | high |
| Scheduling | Calendly inline widget (`assets.calendly.com/assets/external/widget.js`, iframe to a 30-minute event) | high |
| Email | Resend (privacy policy) | policy only |
| Database/storage | Supabase, EU region (privacy policy) | policy only |
| Forms backend | Unknown; form is `method=get` with JS expected; no endpoint observed | unknown |
| SEO | Per-page `<title>` ("... \| CBAMcheck"), sitemap.xml with 7 URLs; no robots/OG checks done | partial |
| Consent | Cookie banner appears on `/book` (Calendly); PostHog recorder script was present when the page loaded; whether it respects consent was not tested | unverified |
| API/network | No requests captured; no payload shapes known | none |

Observation only; no probing of endpoints was attempted.

---

## 8. Compliance accuracy and gaps vs our docs

Compared with `docs/spec/CBAM_Spec_v1.4.md`, `docs/PRD.md` (incl. section 6.1 clarifications). Our docs are the build contract; items below are discrepancies or risks, not legal advice. "Domain owner" should confirm anything marked (verify).

| # | CBAMcheck says | Our docs say | Assessment |
|---|---|---|---|
| 1 | Return and payment deadlines: Q1 2028 due 31 Jul 2028, Q2 29 Sep 2028; then "last working day of the second month after the quarter ends" | PRD 6.1: Q1 31 Jul, Q2 29 Sep, Q3 30 Nov, Q4 28 Feb 2029; pattern irregular, dates only from `ref_compliance_calendar`, never computed | Site's dates match ours, but its stated generic rule contradicts its own dates (second month after Q1 would be end of May/June, not 31 Jul). Do not copy the rule; source dates from reference data. |
| 2 | Registration "by 31 Jan 2028 if you met the threshold during 2027"; "You do not need to be registered before importing in 2027" | Spec/PRD: 31 Jan 2028 transition deadline; registration service opens by 1 Jan 2028; pre-registration record-keeping required from 1 Jan 2027 | Consistent on the date. Site omits the 2027 record-keeping obligation. |
| 3 | Threshold tests: 30-day forward and 12-month backward on the 1st | Spec: forward test any day; backward on first day of each month; forecast register needed (R1-037); customs data lags 2-5 days | Consistent. Site has no tool for the forward test (needs forecasts) or data-coverage warnings (our R1-054). |
| 4 | Emission scope "both direct process emissions and indirect energy-related emissions" | Spec: initial UK scope is direct emissions incl. relevant precursors; indirect effective-dated for future rules | Likely wrong or at least out of line with spec. (verify) |
| 5 | Default values: one value per product set by Treasury notice (FA 2026 Sch 17 para 11(1)); EU defaults used as labelled proxy | Spec R2: defaults are reference data under the HMRC/Treasury rules; "law is data" | Good practice to label proxy. Our version must show dataset id/version and a "not HMRC value" flag. |
| 6 | "Do I need verified supplier data? No ... you will be able to use HMRC defaults" | PRD: actual/default selection under strict legal rules; Day-28 chase does not make defaults legal | Over-simplified. Our flow must not imply defaults are always available; selection is rule-driven (R2). |
| 7 | CPR: independently verified on HMRC Carbon Pricing Verification Form, capped at liability; "no blanket exemption for EU goods" | Spec R2-009/R2-023, R3-004/005; linked-ETS exemption list stays empty (PRD 6.1) | Consistent. |
| 8 | Liability shown as £ range from an assumed £35-£55/t rate | PRD: no tax calculation in R1; R1-059 exposure check "no liability figure" | **Direct conflict with our non-goal** for R1. Our exposure check should show scope, value, threshold date and supplier priority only. A £ figure would need to be R3-gated or a clearly separate, domain-owner-approved "illustrative" mode. |
| 9 | Record keeping "6 years" | PRD 6.1: 6 years after end of the accounting period, anchor to confirm | Site omits the anchor. |
| 10 | Liable person = importer on declaration; agent/broker not liable; tax representative may file but not register | Spec: importer, declarant and agent kept separate; tax agent may submit once authorised but not register | Consistent. Good plain-English wording to reuse (after review). |
| 11 | Scope table by 4-digit headings (e.g. "Iron 7201-7207, 7218", "Steel 7208-7217 ...") | Scope from versioned 8-digit reference data (R1-007) | Summary-level only; fine for education, never for decisions. (verify headings against our `ref_` dataset) |
| 12 | "Embedded emissions: tonnes x intensity" with single default per product; "country of origin does not change the default" | Spec: precursor emissions, functional units, rounding to 5 dp, route/boundary data | Simplified. Fine for an estimate, not for the return. |
| 13 | Default intensity numbers from worldsteel, IAI, GCCA, IEA (global averages) | Spec: only regulation-published defaults are legal values | Good: they separate "estimate" from "HMRC value" explicitly. |
| 14 | `/book` says 20-minute call; Calendly shows 30 minutes; quick-estimate and check use different import bands; home says liability due for "all in-scope imports" from 1 Jan 2027 in the guide's timeline | - | Inconsistencies in the site itself; avoid duplicating. |
| 15 | Currency: GBP column only | R1-035: store source currency, customs monthly FX; R3-005 CPR uses prior-quarter rate | Site ignores FX; we must not. |
| 16 | No mention of tax point, special procedures (free zones, inward processing), Returned Goods Relief, NI/XI geography | R1-008, R1-009, R1-011, R1-027 | Large coverage gap vs us; the site cannot be used as a scope engine reference. |
| 17 | Quick estimate asks origin countries but copy says origin does not alter defaults | - | The input has no analytical effect on the number (or it is undisclosed). Avoid collecting fields that do not change output, or say why. |

Positive patterns (compliance-adjacent): disclaimers on every estimate surface, sources and "last reviewed" date on the guide, explicit mention of what is not yet published (rate, defaults), liability cap in terms, consent checkbox and named processors.

---

## 9. Implementation recommendations

### 9.1 Principles

- Keep the "free exposure check" as **R1-059** (backlog P2) in a sandbox tenant, but design it as the front of our existing import pipeline, not a parallel calculator. It must reuse `ref_` scope data (R1-007), the HMRC "Get customs data" parser (R1-054), and the threshold engine (R1-012).
- Output = scope, value, threshold status/date, priority installations (matches R1-059). If the business wants a £ range, record it as an open decision (new `OPEN_DECISIONS.md` entry) because it contradicts the R1 non-goal "no tax calculation".
- No hard-coded law: assumed rate, default intensities, bands and sector lists all come from versioned datasets with source and `status` (R1-050).
- Everything labelled "indicative" and showing dataset versions.

### 9.2 Pages and flows to build (public/prospect area, plus in-app mapping)

| Page / flow | Notes | Plan phase / req |
|---|---|---|
| Landing + "Does this apply to me?" block | Static React page or marketing site; reuse hero/section pattern, two-test callout, five-sector scope cards | Phase 8/10 (Live cut), copy tied to R1-012 |
| Estimate chooser (upload vs quick) | Two-card selector | Backlog R1-059 |
| Upload route (HMRC "Get customs data" CSVs, not a bespoke template) | Accept the four HMRC reports (R1-054); show row-level validation and preview before commit; sandbox tenant | Phase 3 (R1-003/005/025/054), R1-059 |
| Quick estimate form | Optional; collects band, sectors, supplier count; no £ tax figure; links to upload | R1-059 (P2) |
| Result / exposure report | In-scope lines by sector, value, threshold position, first trigger date, top installations to contact; PDF/CSV export with dataset versions and generated-at | R1-059, R1-024, R1-012 |
| CBAM explained (education) | Key-facts table, sector table, timeline, EU vs UK table, FAQ, glossary - content driven from reference data (dates from `ref_compliance_calendar`, sectors from scope data) | Phase 10; R1-050 |
| Book-a-call / contact | Internal link or Calendly; low priority | - |
| Legal pages | Privacy (processors named, retention), Terms (indicative-only, cap) | Phase 9 (hardening); R2-030 style processor register |
| Cookie / consent | Respect consent before analytics/session replay | Phase 9 |
| Sandbox purge | Delete prospect data after configured period | R1-059 |
| Monthly digest | Re-use their "report in the inbox" idea for existing clients | R1-060 |

### 9.3 API endpoints (proposed, to be added to `docs/API_SPEC.md` when approved)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/public/exposure-checks` | Create a sandbox check (company, role, email, consent, import band). Rate-limited, no auth. Returns check id + upload token. |
| POST | `/api/v1/public/exposure-checks/{id}/files` | Upload HMRC CSV(s); magic-byte allow-list, 25 MB (R1-048). |
| GET | `/api/v1/public/exposure-checks/{id}` | Status + result summary (in-scope lines, value by sector, threshold position). |
| GET | `/api/v1/public/exposure-checks/{id}/report` | Signed URL for PDF/CSV report. |
| POST | `/api/v1/public/quick-estimates` | Questionnaire answers -> directional band result (no £ liability unless approved). |
| GET | `/api/v1/reference/scope/summary` | Read-only, versioned sector/code summary for the education pages. |
| GET | `/api/v1/reference/calendar` | Key dates from `ref_compliance_calendar` (never computed in the UI). |
| POST | `/api/v1/public/leads` | Optional marketing opt-in, separate from the check; consent recorded. |

Reuse existing import, scope and threshold services via a sandbox tenant, not new logic.

### 9.4 Reference data needed (datasets, not code)

| Dataset | Content | Status |
|---|---|---|
| `ref_cbam_commodity_scope` | 8-digit codes, sector, effective dates, exclusions | R1-007 (exists in plan) |
| `ref_compliance_calendar` | registration, return, payment dates | R1-050, R3-009/012 |
| `ref_threshold_rules` | £50k, 30-day forward / 12-month backward cadence | R1-012 |
| `ref_exposure_bands` | bands used by the quick form | new, product config |
| `ref_indicative_intensity` *(only if £ view approved)* | per-product proxy factors + source + "not HMRC value" flag | needs domain owner approval |
| `ref_indicative_rate_range` *(same)* | low/high assumed rate | same |
| `ref_hmrc_customs_report_layouts` | CSV layouts | R1-054 |
| `ref_content_blocks` | FAQ, glossary, key facts with source IDs and "last reviewed" | new, domain-owner approved |

### 9.5 React / shadcn component list

Existing: `frontend/src/{ops,portal,shared}`, shadcn configured (`components.json`).

| Component | Based on | Notes |
|---|---|---|
| `SiteHeader`, `SiteFooter` | custom + shadcn `button`, `navigation-menu` | 65 px header, 1 px border |
| `Hero` with illustration slot | custom | serif H1, single CTA |
| `SectionHeader` (eyebrow + H2 + lead) | custom | reusable pattern |
| `TwoTestCallout` | custom | the two registration tests, data-driven |
| `StepList` (numbered, time chip) | custom | |
| `SectorCard` / `SectorGrid` | shadcn `card` | five sectors from refdata |
| `StatTile` | custom | |
| `KeyFactsTable`, `DataTable` | shadcn `table` | refdata-driven |
| `Timeline` (key dates) | custom | calendar API |
| `FaqAccordion` | shadcn `accordion` | use proper accordion semantics (`aria-expanded`) |
| `ChooserCard` (badge, check-list, CTA) | shadcn `card`, `badge`, `button` | `/estimate` |
| `QuickEstimateForm` | shadcn `form`, `radio-group`, `checkbox`, `input`, react-hook-form + zod | grouped fieldsets, consent checkbox |
| `UploadStepper` | shadcn `progress`, `input`, custom dropzone | 2-step, preview + row errors (R1-051 style) |
| `FileDropzone` + `ValidationSummary` | custom | per-row errors, accepted/rejected counts |
| `ExposureReportCard` | shadcn `card` + chart (bar) | sector breakdown, top installations; mirrors their mock PDF |
| `ThresholdStatusBadge` | shadcn `badge` | below / forward trigger / backward trigger |
| `DatasetVersionFooter` | custom | shows dataset versions and "indicative" label on every result |
| `ConsentBanner` | custom | gate analytics and replay |
| `DisclaimerNote` | custom | consistent legal caveat |

Design tokens to consider (aligned to the observed system, adapt to our brand): ink `#0A0A0A`, muted `#525252`, border `#E5E5E5`, surface `#FAFAFA`, primary navy `#0E2A47`; Fraunces for H1/H2 and Inter for UI; 8 px card radius, 6 px buttons; 80 px section rhythm. For the in-app UI keep denser, workflow-style layout; use the public-site look only for the prospect area.

### 9.6 Things to deliberately do differently

1. Do not gate results behind an email address without a recorded lawful basis and separate marketing consent (they bundle estimate and "related communications" into one consent).
2. Do not ask questions whose answers do not change the output.
3. Use the HMRC "Get customs data" CSV layout and a coverage tracker rather than a bespoke template with GBP-only values.
4. One band set; one source for any "call length" copy.
5. Dates, scope and factors from reference data with versions; show the version on screen.
6. Session replay only after consent, and never on pages showing uploaded customs data.

---

## 10. Prioritised backlog

| Pri | Item | Maps to | Phase / release | Effort |
|---|---|---|---|---|
| P0 | Reference datasets for scope, threshold rules, compliance calendar (domain-owner approved) | R1-007, R1-012, R1-050 | Phase 2/4/5 (already planned) | existing |
| P0 | Education content blocks driven by refdata (key facts, timeline, glossary, FAQ) | R1-050, R1-024 | Phase 10 | S |
| P1 | Sandbox tenant + public upload endpoint with magic-byte checks | R1-059, R1-048, R1-058 | Backlog -> Live cut if capacity | M |
| P1 | Exposure report (scope + value + threshold + priority installations) as PDF/CSV with dataset versions | R1-059, R1-024 | Backlog | M |
| P1 | Landing/chooser/explainer pages using the pattern above | R1-059 | Backlog | M |
| P1 | Consent banner and analytics/replay gating; privacy and terms pages | R1-048, security | Phase 9 | S |
| P2 | Quick questionnaire (directional bands, no £ liability) | R1-059 | Backlog | S |
| P2 | Monthly digest email | R1-060 | Backlog | S |
| P2 | Open decision: show an illustrative £ range? (conflicts with R1 non-goal) | new `OPEN_DECISIONS.md` entry | before any build | decision |
| P2 | Supplier-exposure ranking view for prospects | R1-059 | Backlog | S |
| P3 | Calendly/booking link or in-app "request a call" task | - | any | XS |

Open questions for the domain owner before building anything user-facing:
1. May the prospect report show a monetary figure at all, and if so under what labelling (their "assumed £35-£55" model)?
2. Does indirect-emission treatment in the site's guide match the effective UK rule, and when does it change (spec says direct only initially)?
3. Source of truth for the "last working day of second month" claim: the site's rule conflicts with the dates it lists; confirm against the calendar dataset.

---

*End of document.*
