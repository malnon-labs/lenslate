# lenslate settings UI: readability guide

Spec for making `gui.py` (settings window) and `setup.py` (first-launch wizard) easier to read: colours on buttons,
clearer hierarchy, calmer layout. It is written to be applied directly. Design rules that still hold:

- keep the UI clean; explanations live on hover (`help` property + bottom help bar), not in walls of text;
- keep the main window's page structure (Overlay, Presets, Translation, Models, Games, Names, Advanced);
- nothing switches automatically.

How this was checked: every page was rendered offscreen (`QT_QPA_PLATFORM=offscreen`, Breeze widget style,
a throw-away `XDG_CONFIG_HOME`) in the Breeze light palette and in a hand-built Breeze Dark palette (the real KDE
colour scheme was not loaded, so live KDE colours can differ slightly). The render script was a
temporary one and is not kept.
All contrast ratios below were computed with the WCAG 2.x relative-luminance formula.

---

## 1. What makes it hard to read today (seen in the screenshots)

**Everywhere**
- No page titles. Each page opens with a section label that is the same size as body text and only slightly
  bolder ("lenslate", "Preset", "Game", "general"), so nothing tells the eye where a page starts or what is most
  important. The squint test shows one flat grey mass.
- All buttons look the same. "Start overlay", "Pick area…", "Use", "Download", "Remove", "Save" and "Compare
  all…" share one style, so the main action of a page doesn't stand out, and destructive buttons ("Remove",
  "Delete selected", "Remove hook") look like harmless ones.
- Selected toggle segments and the selected sidebar item use white text on Breeze blue `#3daee9`: **2.49:1**,
  below the 4.5:1 minimum for text (WCAG 1.4.3).
- Lots of text is set to `font-size: 11px` (about 8 pt, smaller than the 10 pt system font): card details,
  the step explanations and the "good for" lines. Small *and* grey-free text is still hard to read.
- Coloured text that fails contrast: warning red `#da4453` on the window is **3.73:1** (light) and **3.71:1**
  (dark); the orange rating dots `#f67400` on white cards are **2.76:1**; the green "running" dot `#27ae60` is
  **2.52:1**; the CPU badge (white on `#7f8c8d`) is **3.48:1** at 11 px.
- `palette(mid)` used as a **text** colour (setup page 1, "You can change these later…") is **1.51:1** in dark
  mode, so it can't be read at all. `palette(mid)` is a border colour, not a text colour.
- Form labels jump around. Each `form()` call aligns its own labels, so fields start at different x
  positions on the same page (Overlay: "Placeholder cards" field at x≈290, "Reading" field at x≈405; Advanced:
  four groups, four different label columns).
- Text runs the full width of a 1120 px window: the Overlay reading tips reach ~150 characters per line, far
  past the ~85-character limit in KDE's HIG.
- The help bar has the same background as the window and only a thin top line. An error ("⚠ …") looks the same
  as a hover hint, so problems are easy to miss.

**Sidebar**: a framed white list with plain text; the selected item fails text contrast (above); no icons, and
the frame plus the page's own frames make two nested borders.

**Overlay**: the status (grey dot + "Overlay: stopped") is at the far left, and its "Start overlay" button is ~800 px away
at the far right, so the two don't read as one unit. Disabled buttons ("Translate now", "Show / hide", "Forget
area") look almost like enabled ones and nothing near them says why they are disabled (pick an area first). The
opacity slider is ~900 px wide. Seven bullet tips form a wall of text at the bottom.

**Presets**
- Two meanings for "highlighted": the blue border marks the card being *previewed* (the "Your PC" estimate), and
  a disabled "In use" button marks the *active* preset. With a Custom setup no card is "In use", but one card
  still has a blue border, so it looks active.
- Each card has six kinds of information at the same weight (title, badge, good-for line, three rating rows,
  memory, download, small text) in 8 pt type.
- "Custom: you changed settings by hand…" is plain text squeezed between the card grid and the step box.
- "Compare all…" and "Run setup again…" look as important as the cards' "Use" buttons.
- The three step rows have no space between steps. The explanation under each row is 8 pt and wraps at ~110
  characters.
- In the "Your PC" panel, the empty sparkline frames look exactly like empty text inputs (same bordered
  rectangle). The estimate is four lines of identical text; the key number (≈ 0.62 s per line) doesn't stand out.

**Translation**: in Custom state the preset row shows six equal, unselected buttons plus a bold "Custom" word and
an empty trade-off line. "Online" is a normal segment even though it sends text off the PC. Form labels in this
page are left-aligned in one group and right-aligned in the next.

**Models**: installed vs not installed is shown only by the button text ("Remove" vs "Download"), and both
buttons look identical. "(experimental)" is italic grey, easy to miss.

**Games**: four disabled buttons with no visible reason, and an empty log box (a large dark rectangle in dark
mode) that looks like an input field.

**Names / Fix translations**: "Save" (the action that matters) has the same weight as "Add row"; "Delete
selected" looks harmless; an empty table has no empty-state text.

**Advanced**: group-box titles are centred and partly lowercase ("general"); each group has its own label column;
line edits stretch to ~900 px.

**Setup wizard**: the hint on page 1 is invisible in dark mode (above). On the preset page the radio label and
summary sit side by side with no column, so summaries start at ragged x positions; the recommended preset is
marked only with "★". Warnings are red text at 3.7:1. The "Ready" page has no subtitle, so its title renders
larger than the titles of the other three pages. "Download selected" is a plain button though it's the page's
main action.

---

## 2. Principles

1. **One primary action per view; everything else steps down in weight** (filled → outlined → text-only).
   [NN/g: Button states communicate interaction](https://www.nngroup.com/articles/button-states-communicate-interaction/),
   [NN/g: Visual hierarchy](https://www.nngroup.com/articles/visual-hierarchy-ux-definition/)
2. **Use colour sparingly and on purpose: blue = selected/primary, orange = warning or non-default, red =
   error/danger.** [KDE HIG: Communicating status changes](https://develop.kde.org/hig/status_changes/)
3. **Never use colour alone; pair it with text, an icon or a shape (✓, ⚠, a chip label).**
   [KDE HIG: status changes](https://develop.kde.org/hig/status_changes/),
   [WCAG 2.2 SC 1.4.1 Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)
4. **Body and hint text ≥ 4.5:1 against its background.**
   [WCAG 2.2 SC 1.4.3 Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
5. **States and focus rings ≥ 3:1 against neighbouring colours; disabled controls are exempt.**
   [WCAG 2.2 SC 1.4.11 Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)
6. **Group by spacing: less space inside a group, more space between groups; only things that belong together
   may look grouped.** [KDE HIG: Layout and navigation](https://develop.kde.org/hig/layout_and_nav/),
   [NN/g: Proximity principle](https://www.nngroup.com/articles/gestalt-proximity/)
7. **Keep multi-sentence text at ≤ 85 characters a line (about 450 px); in wide windows move long text to
   help rather than stretching it.** [KDE HIG: Text and labels](https://develop.kde.org/hig/text_and_labels/)
8. **Don't overuse bold; sentence case for labels, hints and tooltips, title case for buttons.**
   [KDE HIG: Text and labels](https://develop.kde.org/hig/text_and_labels/)
9. **Checkable buttons must make the checked state obvious; otherwise use a radio/checkbox.**
   [KDE HIG: Getting input](https://develop.kde.org/hig/getting_input/)
10. **Cards are for comparing a few rich options; a card's border and background group its content, so keep one
    clear visual state per meaning.** [NN/g: Cards component](https://www.nngroup.com/articles/cards-component/)
11. **Respect the user's light/dark scheme: derive surfaces from the palette and switch token sets when the
    palette changes.** [Qt: QStyleHints::colorScheme](https://doc.qt.io/qt-6/qstylehints.html),
    [Qt blog: dark mode with Qt 6.5](https://www.qt.io/blog/dark-mode-on-windows-11-with-qt-6.5),
    [NN/g: Dark mode issues](https://www.nngroup.com/articles/dark-mode-users-issues/)
12. **Style only what needs a role (QSS property selectors); leave the rest to Breeze so the app still looks
    native.** [Qt Style Sheets syntax: property selectors](https://doc.qt.io/qt-6/stylesheet-syntax.html)

---

## 3. Design tokens

Surfaces come from the palette at runtime (so a user's own KDE colour scheme still works); the values listed
are Breeze defaults and are what the contrast numbers were computed against. Semantic colours are fixed per
scheme because Breeze's own blue (`#3daee9`) is too light for white text.

### 3.1 Colours

| Token | Light | Dark | Use |
|---|---|---|---|
| `surface_window` | palette Window (`#eff0f1`) | palette Window (`#202326`) | page background |
| `surface_card` | palette Base (`#ffffff`) | `#2a2e32` | cards, model rows, panels, group boxes |
| `surface_sunken` | `#e3e5e7` | `#1a1d20` | sidebar, help bar, log boxes, "Your PC" panel |
| `text` | palette WindowText (`#232629`) | palette WindowText (`#fcfcfc`) | body |
| `text_muted` | `#5b6168` | `#a9b1b9` | hints, metadata, idle help bar |
| `text_disabled` | `#9aa1a8` | `#6e757c` | disabled (exempt from contrast) |
| `border_subtle` | `#c3c7cb` | `#454a50` | card/panel outlines (decorative) |
| `border_strong` | `#757c84` | `#7d848c` | button and segment outlines |
| `accent` (text/border) | `#1b6dac` | `#5cbcf0` | links, selected borders, focus ring |
| `accent_tint` | `#dbeaf6` | `#1d3448` | selected sidebar item, current card, chips |
| `accent_text` (on tint) | `#0f4a78` | `#bfe3f8` | text on `accent_tint` |
| `primary` (fill) | `#1b6dac` | `#1f78b8` | primary buttons, checked segments |
| `primary_hover` | `#185d8f` | `#1f78b8` + `accent` 1px border | |
| `primary_pressed` | `#124b73` | `#185d8f` | |
| `on_primary` | `#ffffff` | `#ffffff` | text on primary/success/danger fills |
| `hover_tint` | `#e3eef8` | `#2f3a45` | hover background of secondary/quiet buttons, nav items |
| `pressed_tint` | `#cfe2f3` | `#1d3448` | |
| `success` (fill) | `#1d7a3a` | `#1d7a3a` | download buttons |
| `success_hover` / `_pressed` | `#186a32` / `#145a2a` | `#186a32` / `#145a2a` | |
| `success_text` | `#1d7a3a` | `#5fcf80` | "✓ installed", running dot |
| `success_tint` | `#dff3e5` | `#1f3327` | success chip background |
| `warning_text` | `#9c4f00` | `#f5a742` | warnings, rating dots, "experimental" |
| `warning_tint` | `#fdf0dc` | `#3a2f1c` | warning messages, Custom notice |
| `danger` (fill/border) | `#b8322a` | `#b8322a` | destructive buttons |
| `danger_text` | `#b8322a` | `#f2777a` | errors |
| `danger_tint` | `#fbe7e5` | `#3a2224` | error help bar, danger-button hover |
| `badge_cpu` / `badge_gpu` / `badge_allgpu` | `#5b6168` / `#1b6dac` / `#7b3fa0` | same | preset badges (white text) |
| spark colours | CPU `accent`, GPU `success_text`, VRAM `warning_text` | same tokens | sparklines |

### 3.2 Contrast check (computed)

Text (needs ≥ 4.5:1):

| Pair | Light | Dark |
|---|---|---|
| `text` on window / card | 13.33 / 15.21 | 15.39 / 13.33 |
| `text_muted` on window / card | 5.49 / 6.26 | 7.28 / 6.30 |
| `text_muted` on `surface_sunken` | 4.96 | 7.80 |
| `on_primary` on `primary` | 5.48 | 4.73 |
| `on_primary` on `primary_hover` / `_pressed` | 7.26 / 9.21 | 4.73 / 7.00 |
| `on_primary` on `success` / hover / pressed | 5.39 / 6.67 / 8.31 | same |
| `on_primary` on `danger` | 5.95 | 5.95 |
| `accent` text on window / card | 4.81 / 5.48 | 7.45 / 6.45 |
| `accent_text` on `accent_tint` | 7.53 | 9.50 |
| `success_text` on window / card | 4.72 / 5.39 | 8.06 / 6.98 |
| `warning_text` on window / card | 5.21 / 5.95 | 7.89 / 6.83 |
| `warning_text` on `warning_tint` | 5.29 | 6.54 |
| `danger_text` on window / card | 5.22 / 5.95 | 5.79 / 5.01 |
| `danger_text` on `danger_tint` | 7.00 (use `#8f2a22` on tint in light) | 5.37 |
| `text` on `hover_tint` | 12.93 | 11.30 |
| white on badges cpu / gpu / allgpu | 6.26 / 5.48 / 6.86 | same |

Non-text (needs ≥ 3:1):

| Pair | Light | Dark |
|---|---|---|
| `border_strong` on window / card | 3.70 / 4.22 | 4.17 / 3.62 |
| focus ring (`accent`) on window | 4.81 | 7.45 |
| checked segment (`primary`) vs window | 5.0+ | 3.34 |
| rating dots (`warning_text`) on card | 5.95 | 6.83 |
| `accent` border on `accent_tint` | 4.47 | 6.05 |

Notes: `border_subtle` (1.70 / 1.53) is decorative only: cards are identified by their content, and WCAG 1.4.11
does not require a boundary when text identifies the component. Success/danger fills against the dark window
(2.93 / 2.65) are fine for the same reason (the label identifies the button).

### 3.3 Spacing (4 px grid)

| Token | px | Use |
|---|---|---|
| `xs` | 4 | label ↔ its control, badge padding, title ↔ subtitle |
| `s` | 8 | inside a group (rows, buttons in a row), card grid gap is `m` |
| `m` | 12 | card inner padding, card grid gap |
| `l` | 16 | page side margins, between related groups |
| `xl` | 24 | between sections (before every section header) |
| `xxl` | 32 | top of page title area |

### 3.4 Type scale (relative to the system font, Breeze default Noto Sans 10 pt)

| Role | Size | Weight | Colour |
|---|---|---|---|
| Page title | body × 1.6 (16 pt) | 600 | `text` |
| Page subtitle | body | 400 | `text_muted` |
| Section header | body × 1.2 (12 pt) | 600 | `text` |
| Card title | body × 1.3 (13 pt) | 700 | `text` |
| Body | system (10 pt) | 400 | `text` |
| Hint / metadata | body − 1 pt, never under 9 pt | 400 | `text_muted` |
| Badge / chip | body − 1 pt | 600 | per chip |

Never use `px` font sizes in labels (they ignore the user's font-size setting); compute pt from
`QApplication.font().pointSizeF()`. Replace every `font-size: 11px` and `font-size:15px`.

### 3.5 Corner radius

`4` badges and chips, `6` buttons, segments, inputs, nav items, inline messages, `8` cards, panels, group boxes.

---

## 4. Button system

All sizes: min-height 32 px (Breeze-like), horizontal padding 14 px, label in title case, one action verb.
Every role has a **2 px focus ring in `accent`** (on filled buttons the ring colour is `on_primary`, which
contrasts with the fill). Disabled: `text_disabled` on `surface_window` with `border_subtle`; whenever a button
is disabled, its `help` text must say why (for example "Pick an area first.").

| Role (`role` property) | Normal | Hover | Pressed | Use for |
|---|---|---|---|---|
| `primary` | `primary` fill, white 600 text | `primary_hover` | `primary_pressed` | the one main action of a view |
| `secondary` | `surface_card` fill, `border_strong` 1 px, `text` | `hover_tint` + `accent` border | `pressed_tint` | ordinary actions |
| `quiet` (tertiary) | transparent, no border, `accent` text | `hover_tint` | `pressed_tint` | side links: "Compare all…", "Open config.toml" |
| `download` | `success` fill, white 600 text, "↓" or `download` icon | `success_hover` | `success_pressed` | anything that downloads |
| `danger` (outline) | transparent, `danger` 1 px border, `danger_text` | `danger_tint` | `danger_tint` + 2 px border | Remove / Delete; still confirm with a dialog |
| `segment` unchecked | as `secondary`, square inner corners | `hover_tint` | `pressed_tint` | step/option choosers |
| `segment` checked | `primary` fill, white 600 text, label prefixed "✓ " | `primary_hover` | `primary_pressed` | the chosen option |
| `icon` | 28×28, transparent, icon only, tooltip + help required | `hover_tint` | `pressed_tint` | future small buttons (none today) |

The "✓ " prefix on checked segments makes the choice readable without colour (principle 3) and answers KDE's
"checkability isn't obvious" concern.

### 4.1 Which existing button gets which role

**gui.py, Overlay** (`page_overlay`)
- `self.run_btn`: "Start overlay" → `primary`; "Stop overlay" → `secondary`; "Restart overlay" → `primary`
  (set in `refresh_status`, re-polish when it changes).
- `b_select` "Pick area…" → `primary` when no area is picked, `secondary` once an area exists (only one primary
  per view). If that is too dynamic, keep it `primary` and make `run_btn` "Start" `secondary`.
- `self.b_now` "Translate now", `self.b_toggle` "Show / hide" → `secondary`.
- `self.b_reset` "Forget area" → `secondary` (reversible, no confirmation needed; not `danger`).

**Presets** (`page_presets`, `_card`, `_steps_box`)
- `b_cmp` "Compare all…", `b_setup` "Run setup again…" → `quiet`.
- Card `btn`: "Use" → `secondary`; "Download X GB" → `download`; "In use" → no button: show a
  `chip success` label "✓ In use" in its place.
- Step segments (`_steps_box`, `b` in the loop) → `segment` (+ `pos` property, see QSS).
- `b_measure` "Measure again" → `secondary`.

**Translation** (`page_translation`): preset row buttons and `kind_group` buttons → `segment`.

**Models** (`_model_row` / `_update_model_row`): "Download" → `download`; "Remove" → `danger`.

**Games** (`page_games`): `browse` "Choose folder…" → `secondary`; `self.b_install` "Install hook" → `primary`;
`self.b_remove` "Remove hook" → `danger`; `self.b_pre` "Translate all text now" → `secondary`;
`self.b_names` "Find character names" → `secondary`.

**Names** (`section_names`): `b_add` "Add row", `b_ok` "Use all suggestions" → `secondary`; `b_save` "Save" →
`primary`, moved to the right end of the row (after the stretch).
**Fix translations** (`section_fixes`): `b_del` "Delete selected" → `danger`; `b_save` "Save" → `primary`, right end.

**Advanced** (`page_advanced`): `cfg` "Open config.toml" → `quiet`, placed at the top-right of the page rather
than after the last group.

**Dialogs**: `preset_fits` box: "Use X anyway" → `secondary`, "Use Y instead" → `primary`, "Cancel" stays native.
`_model_action` remove confirmation: set the Yes button to `danger` and rename it "Remove". `Compare` dialog: no
buttons to change.

**setup.py**
- QWizard Next / Finish → `primary` (`wiz.button(QWizard.NextButton)`, `QWizard.FinishButton`); Back, Cancel →
  leave native.
- `PresetPage.use_rec` "Use X instead" → `secondary` (shown inside a warning message, see 5.7).
- `DownloadsPage.go` "Download selected" → `download`; `DownloadsPage.stop_btn` "Cancel downloads" → `danger`.

---

## 5. Layout changes per page

### 5.0 Shared page frame (all pages)
- Every page starts with a **page title** (the sidebar name) and a one-line **subtitle** in `text_muted` (reuse
  the `about` strings in `page_specs`; they are already short). Title ↔ subtitle `xs`, subtitle → content `xl`.
- Content column: left-aligned, side margins `l`, **max width 880 px** for Overlay, Translation, Models, Games
  and Advanced (put the page's inner widget in an HBox with a stretch on the right, or `setMaximumWidth`).
  Presets and Names keep the full width (cards, tables).
- Explanatory labels (`note()`, step explanations, model `about`): `setMaximumWidth(640)` so lines stay ≤ ~85
  characters.
- Section headers: `role="section"`, `xl` space above, `s` below. Replace the `margin-top: 6px` hack in
  `section_label`.
- Forms: one label column per page. Use a shared helper that sets `QFormLayout` label alignment right and
  `setLabelMinimumWidth`-style alignment by putting all of a page's rows in **one** `QFormLayout` (insert section
  headers with `addRow(section_label(...))` spanning both columns), so all fields start at the same x.
  Controls that take free text (line edits, URLs, paths) get `setMaximumWidth(480)`; spin boxes and short
  combos stay at their natural width.

### 5.1 Sidebar (`self.nav`)
- `objectName("nav")`, no frame, `surface_sunken` background, a 1 px `border_subtle` line on its right, width
  180, items 32 px high with 10 px padding and radius 6.
- Selection: `accent_tint` background, `accent_text`, 3 px `accent` bar on the left (shape + colour, not colour
  alone). Hover: `hover_tint`.
- Theme icons (via `QIcon.fromTheme`, no new files): Overlay `view-preview`, Presets `configure`, Translation
  `preferences-desktop-locale`, Models `download`, Games `input-gaming`, Names `user-identity`, Advanced
  `preferences-other`. Missing icons simply show none.
- A spacing gap (`m`) before Advanced to separate it from everyday pages. No renaming, no reordering.

### 5.2 Overlay
- **Status card** (`role="card"`) at the top, one row: dot (`success_text` when running, `text_muted` when
  stopped, 14 pt) + status text + stretch + `run_btn` directly at the card's right edge (inside the card, so it
  reads as one unit). When the running version is stale: card gets `state="warning"` (warning tint) and the text
  starts with "⚠".
- **Actions** under a "Translate what is on screen" header: one row `Pick area…` (primary), `Translate now`,
  `Show / hide`, `Forget area`, then the auto checkbox on its own line. When no area is picked, show a single
  muted hint under the row, "Pick an area to use the other buttons." (one line, not a paragraph).
- **Card opacity**: slider capped at 320 px with its % label right next to it; put it and "Placeholder cards"
  in the shared form.
- **When to look again**: same shared form.
- **Reading tips**: put them in a `card` titled "Clearer text, faster reading", as a two-column grid: bold title
  in the left column, a ≤ 1-line short version in the right column (`text_muted`), and the full current text as
  the row's `help` (hover). This removes the wall of text and follows the hover-help rule. Suggested short
  versions: "Raise the text box's opacity", "Larger text or UI scale", "The game's standard font",
  "No outlines, glow or shadows", "Text speed: instant", "Pick just the dialogue box", "4K: Big text = half".

### 5.3 Presets page
- Page title "Presets"; the old "Pick how lenslate works" header becomes the subtitle. `Compare all…` and
  `Run setup again…` (quiet) sit right-aligned on the title row.
- **Custom notice**: when `current == "custom"`, show an inline message (`role="message"`, `kind="warning"`) *above*
  the cards: "⚠ Custom: you changed settings by hand. Pick a preset to go back to one." Hide it otherwise (no
  empty label taking space).
- **Cards** (3 × 2 grid, gap `m`, padding `m`, `surface_card`, radius 8):
  - Header row: card title (card-title style) + badge (`role="badge"`, `kind="cpu|gpu|allgpu"`).
  - Good-for line: body size, `text` (not muted, not 11 px), max 2 lines.
  - Ratings: label column `text_muted`, dots in `warning_text` at body size (shape ●/○ already carries the
    value; add the value to the row's help, e.g. "Dialogue 4 of 5").
  - Metadata ("1.7 GB GPU · download 3.1 GB", "small text: found / may be missed") as hint style; "may be
    missed" in `warning_text`.
  - Footer: the action button (full card width) or the "✓ In use" chip.
  - **Two distinct states**: `state="current"` (the preset in use) = `accent_tint` background + "✓ In use"
    chip; `state="selected"` (previewed in Your PC) = 2 px `accent` border. Both can apply
    (`state="current selected"` → use the combined selector in the QSS). With Custom, no card is current.
  - Spacing inside a card: `xs` between rating rows, `s` between blocks.
- **Step chooser** (`_steps_box`): a `card` titled "What it does, step by step".
  - Grid: column 0 = step label in a fixed 150 px column ("1  Reading", number in `accent` 600 weight);
    column 1 = segment row.
  - Explanation under the segment in hint style, `text_muted`, max width 640.
  - `l` space between steps, `xs` between a segment row and its explanation.
  - Disabled "Graphics card" segment keeps its help text ("Needs an NVIDIA graphics card…").
- **Your PC panel** (`pcpanel`): `role="panel"` (`surface_sunken`), width 260-300.
  - Hardware lines in hint style.
  - Each meter: one row with the name on the left and the live value right-aligned in 600 weight
    ("Processor ··· 23%"), then the sparkline. The sparkline frame gets the `surface_card` fill and no
    input-like border (draw the outline in `border_subtle` in `Spark.paintEvent`, and use the spark colour
    tokens), so it no longer looks like an empty text field.
  - "With the selected preset": preset name as section header; the time estimate as a big line (section-header
    size, 600) "≈ 0.62 s per line"; the rest in hint style. GPU-memory problems become a small inline warning
    message (⚠ + `warning_tint`), not red text. The ✓ line uses `success_text`.
  - "Measure again" (`secondary`) at the bottom, full panel width.

### 5.4 Translation page
- Preset row: `segment` buttons; when Custom, add a muted chip "Custom" after the row instead of bold text, and
  hide the empty trade-off line.
- Trade-off line: hint style, max width 640.
- "Who translates": `segment` row; the "Online" segment's label stays "Online", and its help keeps the privacy
  warning. Under the row, when Online is checked, show a one-line inline warning: "⚠ Text is sent to the
  online service." (not colour alone).
- One shared form for Languages / Online translators / LLM rows.

### 5.5 Models page
- Page subtitle shows the runner line ("Built-in model runner: llama.cpp …") in hint style.
- Each model row is a `card`: title (600) + chips + stretch + button in the header row.
  - Chips: "✓ Installed" (`success`) or none; "Experimental" (`warning`) instead of the italic suffix.
  - Metadata line hint style; about text body, max width 640.
  - Button: `download` ("↓ Download 3.1 GB" — include the size) or `danger` "Remove".
- `s` between rows, `xl` before each group header.

### 5.6 Games page
- Path row: line edit + `Choose folder…` (secondary).
- Game status as chips under the path: engine chip (neutral), "✓ Hook installed" (success) or "No hook"
  (neutral), "No hook for this engine yet" (warning). Keep the longer extra text as a muted line.
- Action row: `Install hook` (primary), `Translate all text now`, `Find character names` (secondary), stretch,
  `Remove hook` (danger) at the right end, away from Install.
- When no game is chosen, one muted line: "Choose a game folder to enable these actions."
- Log: `surface_sunken`, monospace (`QFontDatabase.systemFont(QFontDatabase.FixedFont)`), hidden until the first
  action writes to it.

### 5.7 Names / Fix translations
- Button rows: left `Add row`, `Use all suggestions` (or `Delete selected` as `danger`), stretch, right `Save`
  (primary).
- Tables: `setAlternatingRowColors(True)`; State column text colour: used = `success_text`, suggestion =
  `warning_text`, rejected = `text_muted` (text already says the state, so colour is redundant support).
- Empty table: a muted placeholder label over the table, "No names for this game yet. Add one, or use Find
  character names on the Games page."

### 5.8 Advanced
- Group titles left-aligned, sentence case, 600 ("General", "Translator", "Screen reading (OCR)", "Hook mode",
  "Files and folders", "Troubleshooting": add `"general": "General"` to the mapping).
- One label width for all groups: compute the widest label once and give every group's form
  `setLabelAlignment(Qt.AlignRight)` plus a fixed first-column width (or one QFormLayout with section rows).
- Line edits max width 480. `Open config.toml` (quiet) at the top right.

### 5.9 Help bar
- `role="helpbar"`, `surface_sunken`, 1 px `border_subtle` top, padding 8 × 12, fixed height for two lines (no
  layout jumps), max text width 880.
- Three states through a `state` property: `idle` (the default text, `text_muted`, with an ⓘ prefix or the
  `help-about` icon), `help` (hover text, `text`), `error` (`danger_tint` background, `danger_text`, 2 px
  `danger` top border, "⚠" prefix). Replace `self.error` and the "⚠" writes with a `set_help(text, state)` helper
  that re-polishes.
- Errors stay visible until the next hover/click (don't let a mouse-leave wipe an error immediately): in
  `HelpFilter`, on Leave restore the last error if one is pending instead of `DEFAULT_HELP`.

### 5.10 Setup wizard
- Use the same QSS (it is set on the application, see 6).
- Every page gets a subtitle (DonePage: "lenslate is set up. Here is how to use it.") so all titles render the
  same size.
- Page 1: replace `style="color: palette(mid);"` with `role="muted"`. Put the two combos in one form, max width
  480.
- Page 2 (preset): "Your PC" box → `role="panel"`. Preset list as a grid: column 0 the radio with the preset name
  (fixed 140 px), column 1 the summary in `text_muted`; rows `s` apart. Recommended preset: an accent chip
  "★ Recommended" in a third column instead of the bare star. Trade-off text in a card under the list. Problems
  → an inline warning message (`kind="warning"`, ⚠ lines) containing the `use_rec` button.
- Page 3 (downloads): grid columns name / size+licence / status; "installed ✓" in `success_text`; "failed: …" in
  `danger_text`; total line in 600 weight, the disk warning as an inline warning message instead of red text.
- Page 4: hotkeys as a two-column grid, key combo rendered as key caps (rich text with a `surface_sunken`
  background is not supported per-span reliably in QLabel; use one QLabel per combo with `role="kbd"`).

---

## 6. Ready-to-use QSS and helper

Put this in a new small module `theme.py` (imported by `gui.py` and `setup.py`), or at the top of `gui.py`.
It uses `string.Template` (`$name`) because QSS braces clash with `str.format`.

```python
# theme.py - lenslate colour tokens + application stylesheet (light/dark aware)
from string import Template

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "light": dict(
        surface_card="#ffffff", surface_sunken="#e3e5e7", text_muted="#5b6168", text_disabled="#9aa1a8",
        border_subtle="#c3c7cb", border_strong="#757c84",
        accent="#1b6dac", accent_tint="#dbeaf6", accent_text="#0f4a78",
        primary="#1b6dac", primary_hover="#185d8f", primary_hover_border="#185d8f", primary_pressed="#124b73",
        on_primary="#ffffff", hover_tint="#e3eef8", pressed_tint="#cfe2f3",
        success="#1d7a3a", success_hover="#186a32", success_pressed="#145a2a",
        success_text="#1d7a3a", success_tint="#dff3e5",
        warning_text="#9c4f00", warning_tint="#fdf0dc",
        danger="#b8322a", danger_text="#b8322a", danger_text_on_tint="#8f2a22", danger_tint="#fbe7e5",
        badge_cpu="#5b6168", badge_gpu="#1b6dac", badge_allgpu="#7b3fa0"),
    "dark": dict(
        surface_card="#2a2e32", surface_sunken="#1a1d20", text_muted="#a9b1b9", text_disabled="#6e757c",
        border_subtle="#454a50", border_strong="#7d848c",
        accent="#5cbcf0", accent_tint="#1d3448", accent_text="#bfe3f8",
        primary="#1f78b8", primary_hover="#1f78b8", primary_hover_border="#5cbcf0", primary_pressed="#185d8f",
        on_primary="#ffffff", hover_tint="#2f3a45", pressed_tint="#1d3448",
        success="#1d7a3a", success_hover="#186a32", success_pressed="#145a2a",
        success_text="#5fcf80", success_tint="#1f3327",
        warning_text="#f5a742", warning_tint="#3a2f1c",
        danger="#b8322a", danger_text="#f2777a", danger_text_on_tint="#f2777a", danger_tint="#3a2224",
        badge_cpu="#5b6168", badge_gpu="#1b6dac", badge_allgpu="#7b3fa0"),
}

QSS = Template("""
/* ---------- sidebar ---------- */
QListWidget#nav { background: $surface_sunken; border: none; border-right: 1px solid $border_subtle;
                  padding: 6px; outline: 0; }
QListWidget#nav::item { min-height: 32px; padding: 0 10px; margin: 1px 0; border-radius: 6px; color: $text; }
QListWidget#nav::item:hover { background: $hover_tint; }
QListWidget#nav::item:selected { background: $accent_tint; color: $accent_text; border-left: 3px solid $accent; }

/* ---------- surfaces ---------- */
QFrame[role="card"]  { background: $surface_card; border: 1px solid $border_subtle; border-radius: 8px; }
QFrame[role="card"][state="current"]          { background: $accent_tint; border: 1px solid $accent; }
QFrame[role="card"][state="selected"]         { border: 2px solid $accent; }
QFrame[role="card"][state="current selected"] { background: $accent_tint; border: 2px solid $accent; }
QFrame[role="card"][state="warning"]          { background: $warning_tint; border: 1px solid $warning_text; }
QFrame[role="panel"] { background: $surface_sunken; border: 1px solid $border_subtle; border-radius: 8px; }
QGroupBox { background: $surface_card; border: 1px solid $border_subtle; border-radius: 8px;
            margin-top: 14px; padding: 12px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 4px; }
QPlainTextEdit[role="log"] { background: $surface_sunken; border: 1px solid $border_subtle; border-radius: 6px; }

/* ---------- text ---------- */
QLabel[role="title"]   { font-size: ${fs_title}pt; font-weight: 600; }
QLabel[role="section"] { font-size: ${fs_section}pt; font-weight: 600; }
QLabel[role="cardtitle"] { font-size: ${fs_card}pt; font-weight: 700; }
QLabel[role="muted"]   { color: $text_muted; }
QLabel[role="hint"]    { color: $text_muted; font-size: ${fs_hint}pt; }
QLabel[role="rating"]  { color: $warning_text; letter-spacing: 1px; }
QLabel[role="kbd"]     { background: $surface_sunken; border: 1px solid $border_strong; border-radius: 4px;
                         padding: 1px 6px; font-weight: 600; }
QLabel[role="badge"]   { color: #ffffff; border-radius: 4px; padding: 1px 6px;
                         font-size: ${fs_hint}pt; font-weight: 600; }
QLabel[role="badge"][kind="cpu"]    { background: $badge_cpu; }
QLabel[role="badge"][kind="gpu"]    { background: $badge_gpu; }
QLabel[role="badge"][kind="allgpu"] { background: $badge_allgpu; }
QLabel[role="chip"] { border-radius: 4px; padding: 1px 6px; font-size: ${fs_hint}pt; font-weight: 600;
                      background: $surface_sunken; color: $text_muted; }
QLabel[role="chip"][kind="success"] { background: $success_tint; color: $success_text; }
QLabel[role="chip"][kind="warning"] { background: $warning_tint; color: $warning_text; }
QLabel[role="chip"][kind="accent"]  { background: $accent_tint;  color: $accent_text; }
QLabel[role="message"] { border-radius: 6px; padding: 8px 12px; background: $accent_tint; color: $accent_text;
                         border-left: 4px solid $accent; }
QLabel[role="message"][kind="warning"] { background: $warning_tint; color: $text; border-left-color: $warning_text; }
QLabel[role="message"][kind="error"]   { background: $danger_tint; color: $danger_text_on_tint;
                                         border-left-color: $danger; }

/* ---------- help bar ---------- */
QLabel[role="helpbar"] { background: $surface_sunken; border: none; border-top: 1px solid $border_subtle;
                         padding: 8px 12px; color: $text; }
QLabel[role="helpbar"][state="idle"]  { color: $text_muted; }
QLabel[role="helpbar"][state="error"] { background: $danger_tint; color: $danger_text_on_tint;
                                        border-top: 2px solid $danger; }

/* ---------- buttons (only widgets with a role; the rest stay native Breeze) ---------- */
QPushButton[role] { min-height: 30px; padding: 3px 14px; border-radius: 6px;
                    border: 1px solid $border_strong; background: $surface_card; color: $text; }
QPushButton[role]:hover   { background: $hover_tint; border-color: $accent; }
QPushButton[role]:pressed { background: $pressed_tint; }

QPushButton[role="primary"]         { background: $primary; border-color: $primary; color: $on_primary; font-weight: 600; }
QPushButton[role="primary"]:hover   { background: $primary_hover; border-color: $primary_hover_border; }
QPushButton[role="primary"]:pressed { background: $primary_pressed; border-color: $primary_pressed; }

QPushButton[role="download"]         { background: $success; border-color: $success; color: $on_primary; font-weight: 600; }
QPushButton[role="download"]:hover   { background: $success_hover; border-color: $success_hover; }
QPushButton[role="download"]:pressed { background: $success_pressed; border-color: $success_pressed; }

QPushButton[role="danger"]         { background: transparent; border-color: $danger; color: $danger_text; }
QPushButton[role="danger"]:hover   { background: $danger_tint; color: $danger_text_on_tint; }
QPushButton[role="danger"]:pressed { background: $danger_tint; border-width: 2px; padding: 2px 13px; }

QPushButton[role="quiet"]         { background: transparent; border-color: transparent; color: $accent; }
QPushButton[role="quiet"]:hover   { background: $hover_tint; border-color: transparent; }
QPushButton[role="quiet"]:pressed { background: $pressed_tint; }

/* segmented choosers: pos = first | mid | last | only */
QPushButton[role="segment"]               { border-radius: 0; padding: 3px 14px; }
QPushButton[role="segment"][pos="first"]  { border-top-left-radius: 6px; border-bottom-left-radius: 6px; }
QPushButton[role="segment"][pos="last"]   { border-top-right-radius: 6px; border-bottom-right-radius: 6px;
                                            border-left: 0; }
QPushButton[role="segment"][pos="mid"]    { border-left: 0; }
QPushButton[role="segment"][pos="only"]   { border-radius: 6px; }
QPushButton[role="segment"]:checked       { background: $primary; border-color: $primary; color: $on_primary;
                                            font-weight: 600; }
QPushButton[role="segment"]:checked:hover { background: $primary_hover; border-color: $primary_hover_border; }

/* focus: after hover so it wins; filled buttons get a ring in the text colour (contrasts with the fill) */
QPushButton[role]:focus                    { border: 2px solid $accent; padding: 2px 13px; }
QPushButton[role="primary"]:focus,
QPushButton[role="download"]:focus,
QPushButton[role="segment"]:checked:focus  { border: 2px solid $on_primary; }

/* disabled last so it always wins */
QPushButton[role]:disabled { background: $surface_window; border: 1px solid $border_subtle;
                             color: $text_disabled; font-weight: 400; }
""")


def is_dark(pal=None):
    pal = pal or QApplication.palette()
    return pal.color(QPalette.Window).lightness() < 128   # works on every Qt 6; colorScheme() can be Unknown


def tokens():
    """The token set for the current palette; surfaces/text from the palette, semantic colours fixed."""
    pal = QApplication.palette()
    t = dict(TOKENS["dark" if is_dark(pal) else "light"])
    t["surface_window"] = pal.color(QPalette.Window).name()
    t["text"] = pal.color(QPalette.WindowText).name()
    if not is_dark(pal):
        t["surface_card"] = pal.color(QPalette.Base).name()
    base = QApplication.font().pointSizeF() if QApplication.font().pointSizeF() > 0 else 10.0
    t.update(fs_title="%.1f" % (base * 1.6), fs_section="%.1f" % (base * 1.2),
             fs_card="%.1f" % (base * 1.3), fs_hint="%.1f" % max(9.0, base - 1))
    return t


def color(name):
    """A token for inline rich text, e.g. "<span style='color:%s'>" % theme.color("danger_text")."""
    return tokens()[name]


def apply(app=None):
    app = app or QApplication.instance()
    app.setStyleSheet(QSS.substitute(tokens()))


def set_role(w, role=None, **props):
    """Give a widget a style role (and e.g. kind=, state=, pos=); re-polish so the QSS applies at once."""
    if role is not None:
        w.setProperty("role", role)
    for k, v in props.items():
        w.setProperty(k, v)
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()
    return w


def segment_row(buttons):
    """Mark buttons of one segmented chooser: role=segment and pos=first/mid/last/only; ✓ on the checked one."""
    n = len(buttons)
    for i, b in enumerate(buttons):
        pos = "only" if n == 1 else "first" if i == 0 else "last" if i == n - 1 else "mid"
        label = b.text().removeprefix("✓ ")
        b.setText(("✓ " + label) if b.isChecked() else label)
        b.toggled.connect(lambda on, b=b, label=label: b.setText(("✓ " + label) if on else label))
        set_role(b, "segment", pos=pos)
        # the checked state is bold and has "✓ ": reserve that width so the label never gets clipped
        f = b.font()
        f.setWeight(QFont.DemiBold)
        b.setMinimumWidth(max(b.minimumWidth(), QFontMetrics(f).horizontalAdvance("✓ " + label) + 34))
    return buttons


class _Follow(QObject):
    """Re-apply the stylesheet when the user switches light/dark (KDE changes the palette live)."""

    def eventFilter(self, obj, ev):
        if obj is QApplication.instance() and ev.type() == QEvent.ApplicationPaletteChange:
            apply()
        return False


def install(app):
    apply(app)
    app._theme_follow = _Follow(app)
    app.installEventFilter(app._theme_follow)
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):          # Qt >= 6.5
        hints.colorSchemeChanged.connect(lambda _s: apply(app))
```

### 6.1 Wiring it into gui.py (sketch)

```python
import theme

def main(args=()):
    ...
    app = QApplication.instance() or QApplication(sys.argv[:1])
    theme.install(app)                    # before MainWindow() is built
    ...

# helpers that replace inline styles
def section_label(text):
    return theme.set_role(QLabel(text), "section")

def note(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setMaximumWidth(640)
    return theme.set_role(lab, "muted")

def page_title(title, subtitle):
    box = QVBoxLayout()
    box.setSpacing(4)
    box.addWidget(theme.set_role(QLabel(title), "title"))
    box.addWidget(note(subtitle))
    box.addSpacing(16)
    return box

# Window.__init__
self.nav.setObjectName("nav")
self.nav.setFrameShape(QFrame.NoFrame)
self.nav.setFixedWidth(180)
self.helpbar.setStyleSheet("")            # drop the inline style
theme.set_role(self.helpbar, "helpbar", state="idle")

def set_help(self, text, state="help"):  # state: idle | help | error
    self.helpbar.setText(("⚠ " + text) if state == "error" else text)
    theme.set_role(self.helpbar, state=state)

def error(self, text):
    self.set_help(text, "error")

# buttons
theme.set_role(self.b_install, "primary")
theme.set_role(self.b_remove, "danger")
theme.segment_row(step_buttons)          # replaces every b.setStyleSheet(self._seg_style(i, n))

# cards (_style_card): no setStyleSheet, just state
def _style_card(self, name):
    states = []
    if name == cfgmod.current_preset():
        states.append("current")
    if name == self.sel_preset:
        states.append("selected")
    theme.set_role(self.cards[name], "card", state=" ".join(states))

# inline HTML colours: "<span style='color:%s'>…</span>" % theme.color("danger_text")
# Spark colours: Spark(theme.color("accent")), Spark(theme.color("success_text")), Spark(theme.color("warning_text"))
```

`HelpFilter` must then call `set_help(text, "help")` on Enter and `set_help(DEFAULT_HELP, "idle")` on Leave
(unless an error is pending). `PageHelp` in `setup.py` does the same for the wizard bars. `setup.run()` works
without changes when started from the window (the app stylesheet already applies); if `setup.py` is ever run
on its own, call `theme.install(app)` there too.

### 6.2 Removals (they would fight the QSS)
- `Window._seg_style` and every `setStyleSheet(self._seg_style(...))`.
- Inline styles: `helpbar`, `steps`, `pcpanel`, `card`, `modelrow`, `badge`, dots (`#f67400`), `font-size: 11px`,
  `font-size:15px`, `run_dot` colours (`#27ae60` / `#7f8c8d` → `success_text` / `text_muted`), `#da4453`
  (gui.py and `WARN` in setup.py → `danger_text`/`warning_text` tokens), `color: palette(mid)` in setup.py,
  `font-weight: 600` on setup radios (use the grid layout instead).

### 6.3 Gotchas
- A QSS rule with `background`/`border` makes Qt draw that widget with the stylesheet style instead of Breeze;
  that's why only widgets with a `role` are styled. Inputs, combos, checkboxes and tables stay native.
- After changing `role`/`state`/`kind`/`pos` at runtime, always go through `set_role` (unpolish/polish);
  otherwise the old style stays.
- QSS has no outline offset; the focus ring is the 2 px border. Every role keeps total border+padding constant
  (1 px + 3 px → 2 px + 2 px), so focus doesn't shift the label.
- `font-weight` in `QListWidget::item` is not reliably applied; the nav selection relies on tint + left bar.
- Badges and chips are QLabels: add them to a layout with `Qt.AlignLeft` (or inside an HBox with a stretch),
  otherwise a VBox stretches them across the whole card.
- Checked segments get bold text and a "✓ " prefix; `segment_row` reserves that width (a test render without it
  clipped "✓ Language model").
- The QSS and helper above were test-rendered offscreen in light and dark (primary, secondary, quiet,
  download, danger, disabled, segments, a current+selected card, badge, chip, warning message, error help
  bar); they parse and look as described.
- Verify in both schemes with the offscreen render (`shots.py` approach) and in a real Plasma session after
  switching Breeze ↔ Breeze Dark while the window is open (palette-change path).
