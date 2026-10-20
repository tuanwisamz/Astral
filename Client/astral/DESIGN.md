# Design: Road paint

The design plan for Smart Analysis Road (spec §9.3, T3.8). Read this before building or changing a screen, and add to the notes at the bottom when you try something.

## Brief

- **Subject:** deciding which road in Peninsular Malaysia to repair first, and which agency owns it.
- **Audiences:**
  - JKR officers and stakeholders at a desk, scanning dense information every day.
  - Members of the public on a phone, outdoors, reporting a hazard in under a minute.
- **Primary job:** make the next road to fix, and who is responsible for it, obvious within 30 seconds.

## Tokens

| Name | Hex | Role |
|---|---|---|
| Asphalt | `#2E3236` | Text, nav rail, route plates, the account-page panel |
| Road grey | `#5A6168` | Secondary text only (5.4:1 on concrete). Never a fill, so it can't read as the pothole grey |
| Concrete | `#EDEFEE` | Page background |
| Kerb white | `#FFFFFF` | Working surfaces: tables, drawer, forms |
| Marking yellow | `#F5C400` | The one accent: primary buttons (asphalt text), focus ring, current nav item, the #1 road. Never text on a light background |
| Overdue red | `#C62828` | Overdue SLAs and errors only |

The hazard colours are fixed by the spec and live in `src/lib/hazards.ts`: pothole `#6B7280`, fallen tree `#16A34A`, sinkhole `#8B4513`. Nothing in the palette above sits near them.

Hairlines are `#D6DADB`, the concrete darkened, and are used only where they separate rows of data.

## Type

- **Barlow** (400, 500, 600) for interface text. It's a grotesk based on public road signage.
- **Barlow Condensed** (500, 600) for road names, scores, counts and route plates.
- **Scale**, from the traditional scale: 12 / 14 / 16 / 18 / 21 / 24 / 36 px.
  - Body is 16 px with line height 1.5; dense tables are 14 px.
  - Page titles are 24 px Barlow 600; the account-page statement is 36 px Barlow Condensed.
- **Figures:** tabular for scores and counts.
- **Line length:** prose stays under 75 characters.
- **Case:** sentence case throughout. The only all-caps text is the spec's DEMO DATA badge.

## Signature element: route plates

A road appears with its route number on a plate, and the plate's shape shows the road class. Colour is never the only cue.

```text
federal FT1      state A15        expressway E2    municipal
+-------+        +-------+        +=======+
|##FT1##|        |  A15  |        |# E2  #|        (no plate; the council name is shown)
+-------+        +-------+        +=======+
solid asphalt    white, asphalt   asphalt with a
white text       outline          white inner rule
```

The plates are the one place the design is bold. Everything around them stays quiet: no gradients, no decorative icons, no shadows except on the drawer, which floats above the map.

## Layout

```text
Shell, desktop
+--------+--------------------------------------------+
| Smart  | Perak > Kinta            [Report a hazard] |
| Analysis+-------------------------------------------+
| Road   | Fix first                                  |
|        |  1 [FT1] Jalan Gopeng           91.3 ##### |
|| Dash  |  2 [A15] Jalan Sultan Azlan Shah 64.2 ###  |
|  Map   |  3       Jalan Tambun            53.0 ##   |
|  Rank  |                                            |
|  Zones | 51 open  |  7 overdue  |  2 warnings | 18 |
+--------+--------------------------------------------+
The nav rail is asphalt; the current item gets a yellow lane-marking bar.

Account pages, desktop                     Phone
+----------------------+--------------+    +-------------------+
| Smart Analysis Road  |  asphalt     |    | asphalt strip,    |
|                      |      |       |    | dashed yellow line|
| Sign in              |      |       |    +-------------------+
| [Continue with Google]     |  dashed|    | Sign in           |
| Email    [         ] |      | yellow|    | [Google]          |
| Password [         ] |      | centre|    | Email / Password  |
| Forgot password?     |      | line  |    | [Sign in]         |
| [Sign in]            | Every road   |    +-------------------+
| New here? Create...  | has an owner |
+----------------------+--------------+
```

- Content is left-aligned. Forms are a single column, no wider than 24 rem.
- The ranking is a ledger, one row per road segment, separated by hairlines. It is not a grid of cards.
- The four dashboard KPIs sit in one strip, with no card per number. The "fix first" list gets the space.

## Principles

1. **The road is the unit.** Every list, drawer and map row starts with the road: its plate, its name, its owner.
2. **Owner next to the problem.** Wherever a hazard or a score appears, the responsible agency is one glance away.
3. **Yellow means act here.** If something is yellow, it's the next thing to do or the thing you're on.
4. **Quiet surfaces, loud facts.** Structure comes from alignment and hairlines, not boxes and shadows.
5. **Phone users are outside.** Report flows use large targets and high contrast, and need no reading of fine print.

## Review against the brief

I checked the first draft against what a generic dashboard would get, and changed four things:

- **Dark theme.** The first idea was asphalt-dark everywhere, but a near-black UI with one bright accent is a common generated-page default. Now asphalt appears only on the nav rail and the account panel, and the work happens on concrete and white.
- **KPI cards.** Four identical big-number cards are the default dashboard opening. The KPIs are now one strip, and the ranked list leads.
- **Account-page image.** A split screen with a decorative photo is the default auth layout. The panel now says what the product is about, in its own material: asphalt, one dashed centre line, and the three route plates.
- **Yellow.** Yellow and black together read as "under construction" when overused. Yellow is now limited to action and focus, never fills large areas, and never appears as text.

## Copy rules

- Active voice, sentence case. Buttons say what happens: "Sign in", "Create account", "Send reset code", "Set new password".
- An action keeps its name: a "Mark verified" button produces a "Marked verified" toast.
- Errors say what happened and what to do. They don't apologise.
- No middle-dot meta strings and no arrows on links.

## Notes

- 19 Oct: first pass. The plates use Barlow Condensed 600 at 12 px with a 3 px radius; at 375 px wide, the ranking turns into stacked rows.
- 20 Oct, after screenshot review at 1400 and 375 px:
  - **Account panel:** the centre line ran into the statement text; moved it to 82% of the panel width.
  - **Removed accessory:** the tinted background on the current nav item. The yellow bar alone marks it.
  - **Header on phones:** the scope breadcrumb now wraps to its own row, and the dev-mode label is hidden below 640 px.
  - **Map legend on phones:** the hazard key stays visible; the outline key folds into "What the outlines mean", so the legend no longer covers a third of the map.
  - **Score breakdown colours:** cool-only (navy to lilac, plus magenta for overdue repairs), so they can't be mistaken for hazards, overdue red, or the yellow action colour. Segments are separated by 1 px gaps.
  - **Road layer:** asphalt tones whose line weight shows the road class; it highlights in marking yellow on hover. Hazards stay the loudest thing on the map.
- **Contrast** (checked numerically): every text pair passes WCAG AA. The lowest is overdue red on concrete at 4.87:1; road grey on concrete is 5.44:1.
- **Screenshot tooling:** headless Edge on Windows won't render narrower than about 500 px, so phone views are captured through a 375 px iframe served from localhost.
- **Not tried yet:** dark mode, which the spec doesn't ask for.
- 20 Oct, landing page (`/welcome`, where signed-out visitors opening `/` are sent): modelled on the HUDA entry screen. The asphalt panel carries the name, the account-page statement, the plates and the hazard key; the concrete side is a ledger of three ways in (report, live map, staff sign-in) with one yellow button. On phones, the hazard key is hidden so the ways in sit near the top.
- 20 Oct, M6 polish, reviewed from screenshots at 1400 and 375 px in both languages:
  - **Bahasa Melayu:** the nav rail holds every BM label on one line. One fix: "Kedudukan" ran into "Jalan" in the ranking header, so the rank column is now 4.75rem wide.
  - **Language toggle:** a quiet text button in the header that names the language you switch to, in that language ("BM" / "EN").
  - **Onboarding tour:** a native `<dialog>` with a yellow top rule, three steps, Skip on the left and one yellow action on the right. Shown once to staff.
  - **Jargon tooltips** (`components/ui/Term.tsx`): dotted underline; opens on hover, focus or tap, and closes with Escape. Used for ADT and SLA.
  - **Scores** always show one decimal ("98.0", not "98"), so a column of scores lines up.
  - **Empty values:** a road with no recommended action shows nothing rather than a dash, and an unnamed road says "Unnamed road".
  - **Special zones** on the Zones page use the same ledger rows as the districts, with the zone type on the right.
  - **Google button:** carries the standard four-colour "G" (18 px, left of the label), as Google's sign-in branding guidelines require. It is the one place where colour outside the palette is allowed.
- 20 Oct, Settings (`/settings`):
  - **Layout:** each block is a two-column row, heading and one-line explanation on the left, controls on the right. On phones they stack.
  - **Danger section:** Delete account sits last, marked by a red left rule. Its button is outlined in overdue red, never yellow: yellow means "act here", and deleting is the one action we don't want to invite. It's confirmed by typing DELETE, and the result is said on the landing page ("Your account is deleted.").
  - **Language:** two large radio cards, each language named in itself. It's the same setting as the header toggle, saved to the account.
- 20 Oct, tab icon: the Road paint tile at a new URL (`/icon.svg`), plus `favicon.ico` and a 180 px `apple-touch-icon.png`. The new URL forces browsers to drop the cached Vite icon.
