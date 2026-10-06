# Public website — master plan

Status: **draft for review**. Client request: a detailed, customer-facing public website for the CBAM product, modelled on cbamreturn.co.uk and cbamcheck.co.uk.
This is a marketing and education site. It is not part of R1/R2/R3 scope and must not delay Phase 3 onward. It needs a requirement ID before build (CLAUDE.md §7): proposed **R1-061 Public website** in `docs/PRD.md` §6.

## 0. How this was researched, and what is unverified

| Source | What we had | Confidence |
|---|---|---|
| cbamcheck.co.uk | Full browser walkthrough recorded in `docs/research/CBAMCHECK_SITE_ANALYSIS.md` on branch `worktree-agent-ab4c1b6aa14bb10f3` (7 pages, layout, design tokens, tools, gaps). Not re-checked today. | High for structure; forms were never submitted |
| cbamreturn.co.uk | **Direct access is blocked from this environment.** Only search-engine summaries of 3 pages: home, `/guides/uk-cbam-guide`, `/guides/uk-vs-eu-cbam`. Nav, pricing page, footer, visuals and any other pages are **not seen**. | Low. Treat every cbamreturn detail below as "reported" |
| Law and dates | Copied from those sites' copy. Not verified against gov.uk or legislation.gov.uk (also blocked here) | Unverified — domain owner must confirm every legal statement before publishing |

**Action for the team:** someone with normal internet access should open both sites and fill the "to confirm" boxes in section 3 (nav, footer, pricing, extra pages, mobile). About 1 hour. Send screenshots to the repo or the next session.

## 1. What each competitor does

### cbamreturn.co.uk (platform vendor, "software for importers")
- Positioning: "UK CBAM software for importers of iron & steel, aluminium, cement, fertiliser and hydrogen." Track the £50,000 threshold, collect supplier emissions data, see liability build, get an HMRC-ready return for the 31 May 2028 deadline.
- Honest framing: "HMRC won't send a bill — you self-assess"; "nothing is filed during 2027, but the return by 31 May 2028 is built from what you collect in 2027".
- Product pillars reported: import ledger upload (maps commodity codes, flags CBAM lines, month-by-month threshold position); supplier data collection by link or template, accepting the files suppliers actually send, showing what is missing; records vault (invoices, declarations, supplier data, verification reports filed against the supplier line); audit trail (sign-in, save, upload, download, role change, export); default-versus-actual liability visibility; HMRC-ready return.
- Offer: free founding account, free through 2026, saved ledgers, monthly threshold statement.
- Content: guides section (`/guides/uk-cbam-guide` "complete guide for importers (2027)", `/guides/uk-vs-eu-cbam`). SEO-led education. Page titles end "· CBAMReturn".

### cbamcheck.co.uk (free lead-gen exposure checker by Oportax)
- 7 pages: home, estimate chooser, quick estimate, upload check, CBAM explained, book a call, privacy, terms.
- Home flow: hero, "does this apply to me" two-test box, 3-step how-it-works, five-sector cards, regulation summary with stat tiles, sample report card, platform upsell, FAQ (9), final CTA.
- Single primary CTA ("Get free estimate"), single accent colour, serif headings, calm advisory tone, "indicative" on every number.
- Weaknesses to avoid (from the research note): two different import-band lists; 20-min vs 30-min call copy; fields collected that change nothing; consent bundled with the estimate; analytics scripts before consent; a generic deadline rule contradicting its own dates; says indirect emissions are in scope (our spec: direct only initially).

### What we take, what we do better
| Take | Do better |
|---|---|
| Plain-English, calm, caveated tone | Every legal date, threshold and sector list is read from reference data with a source and "last reviewed" (law is data) |
| Two-test "does this apply to me" box | Make it interactive without email: enter 30-day and 12-month import values, get a "likely must register" pointer, no account |
| Sector cards, timeline, EU vs UK table, FAQ, glossary | Each fact links to its source; version shown on page |
| Sample report preview | Our real differentiator: HMRC "Get customs data" import, coverage tracker, tax-point-first logic |
| Free founding offer (cbamreturn) | Decide offer with the client (section 8) |
| Lead capture | Separate consent for marketing; estimate never gated behind email |

## 2. Principles for our site
1. **No invented law (CLAUDE.md §3.15).** No £ liability figure, no assumed carbon rate, no default intensities on the site until the domain owner approves (R1 has no tax calculation). The checker shows scope, value and threshold position only.
2. **Law is data.** Dates, thresholds, sectors, codes come from the same reference tables as the app via a read-only public endpoint, never typed into components. Marketing copy that quotes a date is a content block with a source ID and review date.
3. **Draft law never drives claims.** Content states source status (in force / commenced / laid / draft). Draft items are labelled "proposed".
4. **Humans approve; system never files.** Copy must say we prepare the return and a named person approves and files. Never "we file for you automatically".
5. **Tax agent is not the liable person.** Never imply an agent registers or becomes liable.
6. **Privacy by default (UK GDPR).** No analytics or session replay before consent; no replay ever on pages showing uploaded customs data; no real customer data in screenshots; log IDs not names or emails.
7. **Independent of HMRC** statement in footer. Not legal or tax advice disclaimer on every guide and result.
8. **Accessibility:** WCAG 2.2 AA, axe-core in CI, keyboard-first, visible focus, skip link, no colour-only meaning.

## 3. Information architecture (the master file of pages)

Legend: P0 launch, P1 shortly after, P2 later. "Source" = where content comes from.

### 3.1 Global elements
| Element | Contents | Notes |
|---|---|---|
| Header (sticky) | Logo; **Product**, **Guides**, **Check my exposure**, **Pricing** (if used), **Book a demo**, **Log in**, **Start free** button | Mobile: hamburger with same items; to confirm vs both sites |
| Announcement bar (optional) | "UK CBAM starts 1 January 2027" and days to go | Date from calendar dataset |
| Footer | Product links; Guides; Company (About, Contact, Security); Legal (Privacy, Terms, Cookies, Accessibility statement); "Independent of HMRC. Not legal or tax advice."; company name, number, registered address; contact email | Registered details from client |
| Cookie banner | Accept / Reject / Settings, equal prominence | Gates analytics |
| Sticky CTA (mobile) | "Check my exposure" | |
| Disclaimer block | Reusable component | on guides and results |

### 3.2 Page list
| # | Path | Page | Purpose | Key content | Source | Pri |
|---|---|---|---|---|---|---|
| 1 | `/` | Home | Explain and convert | See 4.1 | CMS + refdata | P0 |
| 2 | `/does-cbam-apply` | Does UK CBAM apply to me? | Answer the first question | Two tests explained; interactive threshold check; sector and code lookup; "what does not count" (pre-2027 imports) | refdata (threshold, scope) | P0 |
| 3 | `/check` | Exposure check (chooser) | Route to upload or quick | Two cards | — | P0 |
| 4 | `/check/upload` | Upload exposure check | Core lead magnet | Upload HMRC customs report, preview, row errors, result | R1-054 parser, scope data | P1 |
| 5 | `/check/quick` | Quick questionnaire | Fast directional result | 4 closed questions; directional band; no £ | product config | P2 |
| 6 | `/product` | Product overview | Show the platform | Pillars with screenshots (see 4.3) | CMS | P0 |
| 7 | `/product/import-and-scope` | Customs import and scope | Feature page | HMRC reports, commodity match, coverage tracker | CMS | P1 |
| 8 | `/product/threshold-and-registration` | Threshold and registration | Feature page | Forward and backward tests, tax point first, readiness checklist | CMS | P1 |
| 9 | `/product/suppliers` | Supplier data collection | Feature page | Magic-link portal, Day 0/7/14/21/28 chase as workflow (not law), accepts supplier files | CMS | P1 |
| 10 | `/product/evidence-vault` | Evidence and audit trail | Feature page | Six-year records, audit log, legal hold | CMS | P1 |
| 11 | `/product/returns` | Returns and approval | Feature page (R3) | Mark as "coming" until R3 ships; human approval | CMS | P2 |
| 12 | `/who-its-for` | Who it's for | Segments | Importers, freight forwarders and agents (separate liable person), finance, customs | CMS | P1 |
| 13 | `/guides` | Guides index | SEO hub | Cards by topic, "last reviewed" | CMS | P0 |
| 14 | `/guides/uk-cbam-guide` | Complete guide | Pillar | Key facts, scope, liability basis, dates, to-do steps, import data, FAQ, glossary, sources | refdata + CMS | P0 |
| 15 | `/guides/uk-vs-eu-cbam` | UK vs EU CBAM | Comparison | Table: tax vs certificate, threshold, deadlines, sectors, defaults | CMS (reviewed) | P0 |
| 16 | `/guides/threshold-explained` | The £50,000 threshold | Guide | Forward 30-day, backward 12-month on the 1st | refdata | P1 |
| 17 | `/guides/tax-point` | Tax point explained | Guide | Why not the declaration date | domain owner | P1 |
| 18 | `/guides/supplier-emissions-data` | Getting supplier data | Guide | Actual vs default (rules-driven), verification, what suppliers send | domain owner | P1 |
| 19 | `/guides/carbon-price-relief` | Carbon Price Relief | Guide | Conditions and evidence | domain owner | P2 |
| 20 | `/guides/get-your-customs-data` | How to export your customs data | Guide | HMRC "Get customs data" steps | R1-054 docs | P1 |
| 21 | `/guides/freight-forwarders-and-agents` | Forwarders and agents | Guide | Not liable; who registers | LEGAL-DEC-019 pending | P2 (blocked on decision) |
| 22 | `/key-dates` | Key dates | Timeline | Registration, return and payment dates, with sources | `ref_compliance_calendar` | P0 |
| 23 | `/glossary` | Glossary | SEO, clarity | Tax point, CPR, precursor, liable person, default value | `docs/GLOSSARY.md` | P1 |
| 24 | `/faq` | FAQ | Objections | 15-20 questions grouped | CMS | P0 |
| 25 | `/pricing` | Pricing | Convert | Plans or founding offer | client decision | P1 |
| 26 | `/security` | Security and data | Trust | UK/EU hosting, RLS tenant isolation, encryption, MFA, audit log, retention, processors list | `docs/SECURITY.md` (public version) | P0 |
| 27 | `/about` | About | Trust | Team, mission, independence | client | P1 |
| 28 | `/contact` | Contact and book a demo | Convert | Form, email, calendar | client | P0 |
| 29 | `/demo` | Product tour | Convert | Screenshots or short video, no real data | CMS | P2 |
| 30 | `/legal/privacy` `/legal/terms` `/legal/cookies` `/legal/accessibility` | Legal | Compliance | Named processors, retention, lawful bases, cap on liability | client + lawyer | P0 |
| 31 | `/status` | Status (external) | Trust | link only | devops | P2 |
| 32 | `/sitemap.xml` `/robots.txt` | SEO | | | build | P0 |

To confirm on both competitor sites (not seen): full nav labels, pricing structure, "log in" placement, extra pages (blog, changelog, partners), 404 and mobile behaviour, any trust logos or testimonials.

## 4. Page designs

### 4.1 Home (section order)
1. Header
2. **Hero:** H1 "Be ready for UK CBAM before 1 January 2027." Sub: threshold tracking, supplier data, an HMRC-ready return you approve. Primary "Check my exposure". Secondary "Book a demo". Micro-line: "Independent of HMRC. Built for UK importers."
3. **Countdown and key facts strip:** days to start, £50,000 threshold, five sectors, first return due date (all from datasets)
4. **Does this apply to me?** Two tests + mini interactive checker
5. **The problem in plain English:** "HMRC will not send a bill. You self-assess from data held overseas." (cbamreturn framing)
6. **How it works (4 steps):** Import customs data → See what's in scope and your threshold → Collect supplier evidence → Review and approve your return
7. **Product pillars (6 cards):** Import and scope, Threshold watch, Supplier outreach, Evidence vault, Audit trail, Return preparation
8. **Product screenshots/tour** (synthetic data only)
9. **Who it's for:** importers, forwarders and agents, finance teams
10. **Sectors in scope** (5 cards, from refdata)
11. **Timeline** (from calendar dataset)
12. **Trust and security strip:** UK/EU hosting, tenant isolation, MFA, audit trail, six-year retention, independence from HMRC
13. **Pricing or founding offer teaser**
14. **FAQ (top 8)**
15. **Final CTA**
16. Footer

### 4.2 Exposure check
- Chooser: "Upload customs report (most accurate)" vs "Quick questions (about 60 seconds, directional)". One band list only.
- Upload: no email before the result. Show: lines in scope by sector, import value, threshold position and first trigger date, top suppliers to contact, data-coverage warnings, dataset versions, "indicative" label. Email only to receive a PDF copy, with optional separate marketing checkbox (unticked).
- No £ liability. Pending domain-owner decision (open decision to add).
- Upload safety: size cap, magic-byte allow-list, malware scan, sandbox tenant, auto-purge after a short period, no names stored beyond what is needed.

### 4.3 Product pages
Each: problem, what we do, 3-5 screenshots (synthetic), how a human stays in control, requirement mapping (internal), related guides, CTA. Wording must match built features; unbuilt features marked "coming in <release>" (R2/R3 not built yet).

### 4.4 Guides template
Eyebrow, H1, key-facts box, "last reviewed" and source list, table of contents, body, "what to do next" steps, related guides, FAQ block, disclaimer, CTA. FAQ and Article JSON-LD for SEO.

## 5. Content plan
- Voice: plain English, short sentences, specific numbers, no hype, no exclamation marks, caveats where law is unsettled.
- Every legal statement: source ID, status, "last reviewed". Domain owner (GOV-DEC-009) signs off each guide before publish. Claude drafts, never signs off law.
- Content blocks stored as data: `ref_content_blocks` (FAQ, glossary, key facts) with source IDs. Dates and thresholds are references to datasets, not text.
- Launch set (P0): home, does-it-apply, key dates, complete guide, UK vs EU, FAQ, security, contact, legal. Target about 12 pages.
- Search topics: "UK CBAM", "UK CBAM threshold £50,000", "UK CBAM vs EU CBAM", "UK CBAM registration deadline", "how to get customs data for CBAM", "CBAM supplier emissions data", "CBAM tax point".

## 6. Design system
Start from the cbamcheck tokens as a reference, adapt to the client brand:
- Colours: ink `#0A0A0A`, muted `#525252`, border `#E5E5E5`, surface `#FAFAFA`, navy accent `#0E2A47` (all to be replaced by client brand; keep contrast ≥ 4.5:1). Add status colours (success, warning, danger) for the checker.
- Type: serif display for H1/H2, neutral sans for UI; self-hosted fonts.
- Layout: 1200 px max, 80 px section rhythm, alternating bands, 8 px cards, 6 px buttons, sticky 65 px header.
- Components: Header, Footer, Hero, SectionHeader, TwoTestCallout, ThresholdMiniChecker, StepList, SectorGrid, StatTile, Timeline, KeyFactsTable, DataTable, FaqAccordion (aria-expanded), PricingTable, ChooserCard, FileDropzone, ValidationSummary, ExposureReportCard, ThresholdStatusBadge, DatasetVersionFooter, ConsentBanner, DisclaimerNote, SourceList.
- Imagery: line illustration for hero; real UI screenshots from a synthetic demo tenant. No stock photos of people required.

## 7. Technical plan
- **Where it lives:** `frontend/src/public/` alongside `ops`, `portal`, `shared` (CLAUDE.md §5), React + TypeScript + Vite + Tailwind + shadcn. **SEO risk:** a plain SPA indexes poorly. Options: (a) pre-render static pages at build with a Vite SSG plugin (recommended, keeps stack); (b) separate Next.js marketing site (competitor's choice, adds a framework, needs an ADR). Decide with the client; (a) needs no new framework.
- **Data:** public pages read from read-only, cacheable, unauthenticated endpoints; no tenant data. Proposed (add to `docs/API_SPEC.md` when approved): `GET /api/v1/public/reference/scope-summary`, `GET /api/v1/public/reference/calendar`, `GET /api/v1/public/content/{slug}`; check flow: `POST /api/v1/public/exposure-checks`, `POST .../{id}/files`, `GET .../{id}`, `GET .../{id}/report`; `POST /api/v1/public/leads`; `POST /api/v1/public/contact`.
- **Security for public endpoints:** rate limits and CAPTCHA/Turnstile on write routes, strict schemas, no stack traces, sandbox tenant with RLS, upload limits, signed report URLs with expiry, purge job, CORS to the public origin only. Never expose the Supabase service key or the auto-generated API (rule §3.18).
- **Hosting:** separate origin (e.g. www.<domain>) from the app (app.<domain>); CDN for static assets; security headers (CSP, HSTS, X-Content-Type-Options, Referrer-Policy).
- **Email:** Resend adapter for report delivery and contact form; SPF/DKIM/DMARC.
- **Analytics:** privacy-friendly or consent-gated tool; no session replay on upload pages.
- **SEO:** per-page title and meta, canonical, Open Graph, sitemap, robots, structured data (Organization, FAQPage, Article), `lastmod` real not build-time.
- **Performance:** Lighthouse ≥ 90, LCP < 2.5 s, images optimised, fonts preloaded.
- **Quality gates:** axe-core, Playwright journeys (home → check → result; contact), broken-link check, spelling, Lighthouse CI, security headers test.

## 8. Decisions needed from the client or user
| # | Question | Recommendation |
|---|---|---|
| 1 | Brand name, logo, colours, domain | Client supplies; use placeholders until then |
| 2 | Pricing: published plans, "contact us", or free founding offer | Founding offer plus "contact us" until pricing is known (do not invent prices) |
| 3 | Show a £ liability range in the checker? | No. R1 forbids tax calculation. Raise as an open decision with the domain owner |
| 4 | SPA with pre-rendering vs separate Next.js site | Pre-rendered Vite (no new framework) |
| 5 | Who writes and approves legal copy | Claude drafts, domain owner signs off, lawyer reviews privacy and terms |
| 6 | Real customer logos and testimonials | None until real, permitted ones exist |
| 7 | Gate results behind email? | No: result first, email optional for PDF |
| 8 | Free tool before login, or only for registered users | Public sandbox check (R1-059) |
| 9 | Registered company details, contact email, calendar tool | Client supplies |

New open decisions to record in `docs/OPEN_DECISIONS.md`: £ figure on public checker; processor list for public site (hosting, email, analytics, calendar); content sign-off owner and review cadence.

## 9. Delivery plan (does not block Phases 3 to 5)
| Stage | Output | Needs |
|---|---|---|
| W0 Confirm | Fill section 3 "to confirm" boxes from live sites; client answers section 8; add R1-061 to PRD §6 | 1-2 days, client |
| W1 Foundation | `frontend/src/public` skeleton, design tokens, header/footer, consent banner, SSG setup, CI gates | 1 week |
| W2 Core pages | Home, does-it-apply, key dates, FAQ, security, contact, legal | 1-2 weeks; needs refdata calendar and threshold endpoints |
| W3 Guides | Complete guide, UK vs EU, glossary; domain-owner review | 1-2 weeks |
| W4 Product pages | Pillars with synthetic screenshots; wording matches built features | 1 week; after Phase 7+ UI exists |
| W5 Exposure check | Upload checker on sandbox tenant (R1-059) | after Phase 3 PR 5 and Phase 4 threshold; 2-3 weeks |
| W6 Launch | Accessibility audit, security review, Lighthouse, redirects, analytics | 1 week |

Release order is fixed: this site is marketing, so build W0-W3 in parallel only if capacity allows; the exposure check (W5) waits for the data pipeline.

## 10. Acceptance checklist before launch
- [ ] Every date, threshold, sector and code on the site comes from reference data or a signed-off content block with source and review date
- [ ] No £ liability, rate or default value unless approved
- [ ] Domain owner signed off all legal copy; lawyer reviewed privacy and terms
- [ ] No analytics or replay before consent; processors listed in the privacy page
- [ ] No real client or supplier data in any screenshot or fixture
- [ ] axe-core clean; keyboard and screen-reader pass; mobile checked in a browser
- [ ] Security review of every public endpoint (rate limit, upload checks, purge)
- [ ] "Independent of HMRC" and "not legal or tax advice" present
- [ ] Copy matches built features; unbuilt ones marked
