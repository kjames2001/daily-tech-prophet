#!/usr/bin/env python3
"""
Reddit Daily Tech Prophet — broadsheet renderer v9, Force-Dark-proof.

Architecture (for persistent paint-time re-colouring on Android webviews):

  Telegram/WeChat in-app browsers on Android apply Force Dark at PAINT
  time — after CSS — so no color declaration or color-scheme opt-out can
  prevent it. Verified experimentally: only elements whose raster passes
  through CSS filter: invert(1) survive untouched.

  Therefore the whole page is authored as a NEGATIVE (dark paper, white
  ink) inside .world { filter: invert(1) } — the filter output is the
  final raster and the darkener cannot touch it. Real media (img/video)
  is counter-inverted (double inversion = original colors). Fixed
  overlays (flip buttons, page indicator, turn effect) sit outside the
  world and carry their own invert(1) with pre-negated colors.

  Also: fixed-height pages (uniform), client-side paginator that flows
  articles into pages until full, single-panel 3D page-turn, swipe
  gestures, shimmer on moving media, print-ink fuzz.
"""

import json
import sys
import html
from datetime import datetime

# Textures served by the artifact server /media/ route.
# Inside the inverted world the texture must be pre-negated so it
# displays as warm newsprint after the world's invert(1).
NEWSPRINT_URL = "/media/newsprint_bg_grainy_v3.jpg"


def escape(text: str) -> str:
    return html.escape(text or "")


# ─────────────────────────────────────────────────────────────
# CSS — all colors AUTHORED INVERTED (declare negative → display positive)
#   paper  #f2ecd9 → #0d1326      ink #000 → #fff
#   soft   #1a1408 → #e5ebf7      faded #3a352c → #c5cad3
#   frame  #3a3226 → #c5ddd9      rule #6a5f48 → #95a0b7
#   gold   #7a5c10 → #85a3ef      crimson #6e0f0f → #91f0f0
# ─────────────────────────────────────────────────────────────

CSS = '''
:root { color-scheme: only light; }
:root {
  --paper: #0d1326;          /* displays as #f2ecd9 newsprint */
  --paper-hi: #101830;       /* displays slightly lighter paper */
  --ink: #ffffff;            /* displays as #000 black ink */
  --ink-soft: #e5ebf7;       /* displays as #1a1408 */
  --ink-faded: #c5cad3;      /* displays as #3a352c */
  --frame: #c5ddd9;          /* displays as #3a3226 */
  --rule: #95a0b7;           /* displays as #6a5f48 */
  --gold: #85a3ef;           /* displays as #7a5c10 */
  --crimson: #91f0f0;        /* displays as #6e0f0f */
  --shadow: rgba(235, 241, 249, 0.25);
  --page-h: 1200px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; overscroll-behavior: none; overflow-anchor: none; }

/* ═══ TYPEFACE — IM Fell English (SIL OFL 1.1, Google Fonts) ═══
   A 17th-century "Fell Types" revival whose glyphs carry the real ink
   spread and irregular edges of hand-pressed metal type — the fuzz is
   IN the letterforms, so it survives any renderer. Self-hosted woff2
   (no external CDN; WeChat webview + mainland routing make Google
   Fonts unreliable). Georgia falls back if the load fails.
   NOTE: h1-h6 default to UA-bold; Fell has no bold face, so every
   heading's weight is pinned to 400 here and real weight comes from
   the feMorphology dilate filters only. */
@font-face {
  font-family: "IM Fell English";
  src: url("/media/imfell-english-normal.woff2") format("woff2");
  font-weight: normal;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: "IM Fell English";
  src: url("/media/imfell-english-italic.woff2") format("woff2");
  font-weight: normal;
  font-style: italic;
  font-display: swap;
}

h1, h2, h3, h4, h5, h6, b, strong, th { font-weight: 400; }

body {
  font-family: "IM Fell English", Georgia, "Times New Roman", serif;
  line-height: 1.5;
  -webkit-tap-highlight-color: transparent;
  /* Only visible at overscroll bounce edges; world covers everything else */
  background-color: #f2ecd9;
}

/* ═══ THE WORLD — one global inversion turns the negative into print ═══
   MUST be opaque: the filter rasterizes only this element's own paint,
   so the un-filtered body behind would show through any transparency. */
.world {
  position: relative;
  filter: invert(1);
  background-color: var(--paper);
  background-image: url("__NEWSPRINT__");
  background-repeat: repeat;
  background-size: 480px auto;
}

.newspaper { max-width: 800px; margin: 0 auto; padding: 8px 10px 84px; }

/* ═══ MASTHEAD ═══ */
.masthead {
  text-align: center;
  padding: 8px 6px 10px;
  border-bottom: 4px double var(--frame);
  margin-bottom: 8px;
}
.mast-topline {
  font-size: 8.5px; letter-spacing: 2.5px; text-transform: uppercase;
  color: var(--ink-soft);
  border-bottom: 1px solid var(--rule);
  padding-bottom: 4px; margin-bottom: 8px;
}
.mast-title {
  font-size: 46px; /* weight via inkfuzz filter */; letter-spacing: -0.5px;
  line-height: 1.02; color: var(--ink);
  text-shadow: 1px 1px 0 rgba(255, 255, 255, 0.2);
}
.mast-the { font-size: 27px; vertical-align: 14px; margin-right: 5px; }
.mast-sub {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  border-top: 1px solid var(--rule);
  margin-top: 8px; padding-top: 5px;
  font-size: 10px; color: var(--ink-soft);
}
.mast-ear { font-variant: small-caps; letter-spacing: 1px; }
/* Emphasis span — deliberately NOT bold: Fell has no bold face, and
   synthetic bold muddies under the ink filters. Mid filter supplies
   the weight where needed. */
.b { font-style: normal; }
.mast-ear .b { font-size: 8px; text-transform: uppercase; letter-spacing: 2px; color: var(--ink-faded); display: block; }
.mast-strap { font-style: italic; font-size: 10.5px; color: var(--ink-soft); flex: 1; text-align: center; }

/* ═══ SHEETS — identical fixed heights, content paginated to fit ═══
   --type-scale is the paginator's single global "squeeze" step: when a
   page would otherwise close early and leave a gap, the sheet gets
   .tight and every measured text size on it steps down once. */
.sheet {
  --type-scale: 1;
  height: var(--page-h);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--frame);
  outline: 3px double var(--frame);
  outline-offset: 3px;
  padding: 10px 12px 10px;
  margin: 0 0 16px;
  background-color: var(--paper);
  background-image: url("__NEWSPRINT__");
  background-repeat: repeat;
  background-size: 480px auto;
  box-shadow: 0 3px 10px var(--shadow);
  overflow: hidden;
  scroll-margin-top: 12px;
}
.sheet.tight { --type-scale: 0.93; }

/* ═══ FOLIO ═══ */
.page-head {
  flex: 0 0 auto;
  display: flex; align-items: baseline; justify-content: space-between; gap: 8px;
  border-bottom: 2px solid var(--frame);
  padding-bottom: 3px; margin-bottom: 8px;
  font-size: 9.5px; text-transform: uppercase; letter-spacing: 1.5px;
  color: var(--ink-soft);
}
.page-head-mid { color: var(--ink); flex: 1; text-align: center; }
.page-head-side { flex: 0 0 auto; }

/* ═══ FRONT PAGE ═══ */
.front-body { flex: 1 1 auto; overflow: hidden; display: flex; flex-direction: column; }
.banner-block {
  text-align: center;
  padding: 2px 0 8px;
  border-bottom: 1px solid var(--rule);
  margin-bottom: 10px;
  flex: 0 0 auto;
}
.banner {
  font-size: calc(36px * var(--type-scale)); /* weight via inkfuzz filter */; line-height: 1.08;
  letter-spacing: -0.5px; margin-bottom: 7px; color: var(--ink);
}
.banner a { color: var(--ink); text-decoration: none; }
.deck {
  font-size: calc(14.5px * var(--type-scale)); font-style: italic; color: var(--ink-soft);
  line-height: 1.42; max-width: 96%; margin: 0 auto;
}
.front-grid { display: grid; grid-template-columns: 1fr; gap: 10px; }
@media (min-width: 620px) { .front-grid { grid-template-columns: 46% 1fr; } }
.front-story .byline { margin: 0 0 5px; }
.front-text { font-size: calc(14.5px * var(--type-scale)); line-height: 1.58; }
.front-text::first-letter {
  float: left; font-size: calc(58px * var(--type-scale)); /* weight via inkfuzz filter */; line-height: 0.8;
  padding: 4px 8px 0 0; color: var(--ink);
}
.relevance {
  font-size: calc(12.5px * var(--type-scale)); color: var(--ink-soft);
  margin-top: 7px; padding-top: 6px; border-top: 1px solid var(--rule);
}

/* ═══ CONTENTS — compact boxed index, newspaper-style ═══ */
.contents-body { flex: 1 1 auto; overflow: hidden; display: flex; flex-direction: column; }
.index-box {
  flex: 0 0 auto;
  padding: 10px 12px 8px;
  border: 1px solid var(--frame);
  outline: 3px double var(--frame);
  outline-offset: 2px;
  background: rgba(133, 163, 239, 0.05);
}
.index-title {
  text-align: center; font-size: calc(13.5px * var(--type-scale)); /* weight via inkfuzz filter */;
  letter-spacing: 3px; text-transform: uppercase;
  padding-bottom: 7px; margin-bottom: 5px;
  border-bottom: 3px double var(--frame);
}
.index-list { list-style: none; display: grid; gap: 2px; }
/* row 1: section · count · page   |   row 2: teaser spanning the full width */
.index-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: baseline; gap: 2px 10px;
  padding: 9px 4px;
  border-bottom: 1px solid var(--rule);
  cursor: pointer;
}
.index-row:last-child { border-bottom: none; }
.index-row:active { background: rgba(255, 255, 255, 0.06); }
.idx-sec { font-size: calc(14px * var(--type-scale)); text-transform: uppercase; letter-spacing: 1.2px; color: var(--ink); }
.idx-teaser { grid-column: 1 / -1; font-size: calc(11px * var(--type-scale)); font-style: italic; color: var(--ink-soft); line-height: 1.35; overflow: hidden; }
.idx-meta { font-size: calc(10px * var(--type-scale)); font-style: italic; color: var(--ink-faded); white-space: nowrap; }
.idx-page { font-size: calc(11px * var(--type-scale)); color: var(--ink); font-style: italic; white-space: nowrap; }
.sheet.tight .index-row { padding: 6px 4px; }
/* newspaper "filler" — small classified-style ads occupy leftover space.
   grid-auto-rows: 1fr is minmax(auto, 1fr): the ads never shrink below
   their text, but they stretch to close out the page exactly. */
.filler-grid {
  margin-top: 10px;
  flex: 1 1 auto;
  display: grid; grid-template-columns: 1fr 1fr; gap: 9px;
  grid-auto-rows: 1fr;
  align-content: stretch;
  overflow: hidden;
}
.filler-ad {
  border: 1px solid var(--rule);
  padding: 8px 10px;
  font-size: calc(10.5px * var(--type-scale)); line-height: 1.5; color: var(--ink-soft);
  display: flex; flex-direction: column;
}
.filler-ad b {
  display: block; font-variant: small-caps; letter-spacing: 1.5px;
  color: var(--ink); margin-bottom: 3px; font-size: calc(11.5px * var(--type-scale));
}
.filler-ad .ad-rule { border-bottom: 1px dotted var(--rule); margin: auto 0 0; }

/* ═══ SECTION PAGES — dense two-column newsprint, ALWAYS 2 columns ═══
   Real newspapers never collapse to one column on small paper; the
   narrow measure is what makes the page read as typeset, not stretched.
   Articles may flow across columns (newspaper behavior); only photos
   are kept whole. */
.columns {
  flex: 1 1 auto;
  min-height: 0;
  column-count: 2;
  column-gap: 13px;
  column-rule: 1px solid var(--rule);
  column-fill: auto;
  overflow: hidden;
}
@media (max-width: 560px) {
  .columns { column-count: 2; column-gap: 11px; }
  .article-text { font-size: calc(11.5px * var(--type-scale)); line-height: 1.46; }
  .headline { font-size: calc(14.5px * var(--type-scale)); }
}

.article {
  /* NO break-inside: avoid — letting text flow between columns keeps
     the page dense. Photos are individually protected. */
  padding: 0 0 6px; margin-bottom: 6px;
  border-bottom: 1px dotted var(--rule);
  overflow: hidden;
  cursor: pointer;
}
.article:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 2px; }

/* Section change inside a column: a real broadsheet marks it in the text
   rather than opening a fresh half-empty sheet. */
.section-head {
  break-inside: avoid; -webkit-column-break-inside: avoid;
  margin: 4px 0 7px; padding: 4px 0 3px;
  border-top: 3px double var(--frame);
  border-bottom: 1px solid var(--frame);
  font-size: calc(10.5px * var(--type-scale)); /* weight via inkfuzz filter */;
  text-align: center; text-transform: uppercase; letter-spacing: 2px;
  color: var(--ink);
}
.columns > .section-head:first-child { margin-top: 0; }

.headline { font-size: calc(16.5px * var(--type-scale)); /* weight via inkfuzz filter */; line-height: 1.16; margin-bottom: 2px; color: var(--ink); }
.headline a { color: var(--ink); text-decoration: none; }
.headline a:active { color: var(--crimson); }

.byline {
  font-size: calc(9px * var(--type-scale)); text-transform: uppercase; letter-spacing: 1.2px;
  color: var(--ink-faded); margin-bottom: 4px;
}
.byline::before { content: "— "; }

.article-text {
  font-size: calc(12.5px * var(--type-scale)); line-height: 1.5; color: var(--ink);
  text-align: justify; hyphens: auto; -webkit-hyphens: auto;
}

/* Standing matter — short classified notices that close out the last
   section page so it ends flush instead of half-empty. The paginator
   adds them one at a time and stops at the first that will not fit. */
.tail-ad {
  break-inside: avoid; -webkit-column-break-inside: avoid;
  border: 1px solid var(--rule);
  padding: 6px 8px; margin: 0 0 6px;
  font-size: calc(10px * var(--type-scale)); line-height: 1.45;
  color: var(--ink-soft);
}
.tail-ad b {
  display: block; font-variant: small-caps; letter-spacing: 1.4px;
  color: var(--ink); margin-bottom: 2px; font-size: calc(10.5px * var(--type-scale));
}

/* ═══ PRINT-INK EFFECT — paper-grain overlay (5th mechanism) ═══
   Four glyph-decoration attempts (shadows 0.35px + 0.6px, stroke 0.5px)
   all invisible on the device: the Android webview's paint-time Force
   Dark discards text-shadow and -webkit-text-stroke, as it discards
   color-scheme opt-outs. Glyph decoration is a dead end here.
   The effect is now a PHYSICAL TEXTURE: a tiling ink-grain layer
   composited over the whole page at 240px cells (grain ~2-3 device px
   at DPR 3). Authored white-on-black inside the inverted world, so it
   displays as dark fibers in the paper and in the ink's gaps — exactly
   how cheap newsprint reads. Cannot be rounded away or stripped: it is
   geometry, not glyph styling. */
.grain-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  background-image: url("/media/ink_grain_v4.png");
  background-repeat: repeat;
  background-size: 240px 240px;
  /* In the inverted world paper is authored DARK, so the blend must
     lighten: screen lays light fibers over authored-dark paper, which
     display as dark ink flecks on cream. Multiply would be a no-op on
     near-black paper (verified: zero delta). */
  mix-blend-mode: screen;
  opacity: 0.25;
}
.article-text, .headline, .banner, .deck, .byline, .front-text,
.idx-teaser, .idx-sec, .ponder-list li, .photo-caption, .page-head,
.mast-sub, .mast-topline, .section-head, .tail-ad, .filler-ad {
  color: var(--ink);
  filter: url(#inkfuzz);
}
/* Weight comes from the filter chain (feMorphology dilate), not
   synthetic font-weight — Fell has no bold face. */
.headline, .banner, .idx-sec, .mast-sub, .page-head-mid,
.filler-ad .b, .tail-ad .b {
  filter: url(#inkfuzz-mid);
}
.mast-title, .mast-the, .banner-headline, .dropcap {
  filter: url(#inkfuzz-head);
}

/* ═══ PHOTOS — fixed aspect boxes for correct pagination ═══
   Real media counter-inverts itself (world invert + own invert = original). */
.photo { margin: 2px 0 6px; break-inside: avoid; -webkit-column-break-inside: avoid; }
.photo.lead { width: 100%; margin: 0 0 7px; }
.photo.page { width: 100%; margin: 2px 0 7px; }

.photo-frame {
  position: relative;
  border: 1px solid var(--frame);
  outline: 3px double var(--frame);
  outline-offset: 1px;
  padding: 2px;
  background: var(--paper-hi);
  box-shadow: 2px 3px 6px var(--shadow);
}
.photo.page .photo-frame { aspect-ratio: 4 / 3; }
/* Front-page art is set square so the lead fills its sheet; the .tight
   fallback crops it back to a letterbox on short viewports. */
.photo.lead .photo-frame { aspect-ratio: 1 / 1; }
.sheet.tight .photo.lead .photo-frame { aspect-ratio: 16 / 11; }

.media-img, .media-video {
  display: block; width: 100%; height: 100%;
  object-fit: cover;
  filter: invert(1);           /* cancels the world invert — true colors */
}
.media-img { filter: invert(1) sepia(0.2) contrast(1.03) saturate(0.92); }
.media-still { animation: kenburns 16s ease-in-out infinite alternate; transform-origin: 60% 40%; }
@keyframes kenburns {
  from { transform: scale(1) translate(0, 0); }
  to   { transform: scale(1.07) translate(-2px, -2px); }
}
.media-video { background: #2b314d; }
.photo.gone { display: none; }

/* ── Shimmer on moving media: own invert keeps authored final colors ── */
.photo-shine {
  position: absolute;
  inset: 2px;
  overflow: hidden;
  pointer-events: none;
  z-index: 3;
  filter: invert(1);
}
.photo-shine::after {
  content: "";
  position: absolute;
  top: 0; bottom: 0; left: -60%; width: 45%;
  background: linear-gradient(
    105deg,
    transparent 0%,
    rgba(255, 250, 235, 0.32) 50%,
    rgba(255, 250, 235, 0.05) 80%,
    transparent 100%
  );
  transform: skewX(-12deg);
  animation: shine-sweep 5.5s ease-in-out infinite;
}
@keyframes shine-sweep {
  0%, 55% { left: -60%; }
  85%, 100% { left: 115%; }
}

.photo-caption {
  text-align: center; font-size: calc(8px * var(--type-scale)); font-style: italic;
  color: var(--ink-faded); letter-spacing: 1.5px; margin-top: 2px;
}

/* ═══ NOTICES back page ═══ */
.notices-body { flex: 1 1 auto; overflow: hidden; display: flex; flex-direction: column; }
.ponder-box {
  margin: 2px 0 0;
  padding: 14px 18px 12px;
  border: 1px solid var(--frame);
  outline: 3px double var(--frame);
  outline-offset: 2px;
  background: rgba(133, 163, 239, 0.07);
  flex: 1 1 auto;
  display: flex; flex-direction: column;
  justify-content: flex-start;
  overflow: hidden;
}
.ponder-header {
  text-align: center; font-size: calc(17px * var(--type-scale)); /* weight via inkfuzz filter */;
  font-variant: small-caps; letter-spacing: 3px; color: var(--crimson);
}
.ponder-subtitle {
  text-align: center; font-size: calc(10.5px * var(--type-scale)); font-style: italic;
  color: var(--ink-faded); margin: 2px 0 10px;
}
/* The ruled slots share whatever height is left, so the box reads as a
   full ruled notices column instead of a short list under a tall frame. */
.ponder-list { list-style: none; flex: 1 1 auto; display: flex; flex-direction: column; }
.ponder-list li {
  flex: 1 1 auto;
  display: flex; align-items: center; gap: 8px;
  font-size: calc(16px * var(--type-scale)); line-height: 1.5; color: var(--ink);
  padding: 10px 0;
  border-top: 1px dotted var(--rule);
  font-style: italic;
}
.ponder-list li:first-child { border-top: none; }
.idea-num {
  flex: 0 0 auto;
  font-style: normal; color: var(--crimson);
  font-size: calc(19px * var(--type-scale));
}

.colophon {
  margin-top: 10px;
  text-align: center; padding: 10px 12px 8px;
  border: 1px solid var(--frame);
  outline: 3px double var(--frame);
  outline-offset: 2px;
  font-size: calc(9.5px * var(--type-scale)); font-style: italic; color: var(--ink-soft);
  letter-spacing: 1px;
  flex: 0 0 auto;
}
.colophon-rule { color: var(--gold); margin-bottom: 4px; letter-spacing: 4px; }

/* Rides at the foot of the front page as a stop-press note rather than
   floating loose between the masthead and page one. */
.fetcher-notes {
  flex: 0 0 auto;
  text-align: center; font-size: calc(10.5px * var(--type-scale)); font-style: italic;
  color: var(--crimson); padding: 5px 10px; margin: 9px 0 0;
  border: 1px dashed var(--crimson);
}

/* ═══ FIXED UI — outside the world; each carries its own invert ═══ */
.flip-controls {
  position: fixed;
  right: 14px; bottom: 14px;
  z-index: 100;
  display: flex;
  gap: 8px;
  filter: invert(1);
}
.flip-btn {
  width: 52px; height: 52px;
  border-radius: 50%;
  border: 2px solid var(--frame);
  background: var(--paper);
  color: var(--ink);
  font-size: 20px;
  font-family: inherit;
  cursor: pointer;
  box-shadow: 0 3px 10px var(--shadow);
  display: flex; align-items: center; justify-content: center;
  user-select: none;
  -webkit-user-select: none;
  touch-action: manipulation;
}
.flip-btn:active { transform: scale(0.94); background: var(--paper-hi); }

.page-indicator {
  position: fixed;
  left: 14px; bottom: 24px;
  font-size: 10px; font-style: italic; color: var(--ink-soft);
  background: var(--paper);
  border: 1px solid var(--rule);
  padding: 4px 10px;
  border-radius: 12px;
  z-index: 100;
  pointer-events: none;
  filter: invert(1);
}

/* ═══ PAGE-TURN — 2D paper wipe, one moving element ═══
   Two rounds of 3D page-rotation transforms failed to render on the
   user's Android webview (3D transforms inside a filtered element are
   exactly what its compositor mishandles). A flat panel sliding across
   the screen is plain 2D compositing — it renders everywhere. The page
   jump happens UNDER the panel at mid-sweep, so the wipe IS the turn.

   Four rules keep the wipe on the boring compositing path:
   1. The layer is visibility:hidden between turns. A full-viewport
      filtered layer that is always painted is the most expensive thing
      on the page; idle it out so only the half-second turn pays for it.
   2. No will-change on the panel. A permanently promoted layer INSIDE a
      filter: invert(1) ancestor is the same path the 3D attempts died
      on — the promoted panel can be composited outside its ancestor's
      filter and paint its raw negative (near-black) instead of
      newsprint. A running transform animation gets promoted anyway.
   3. Exactly one animated property, transform, and no opacity trap in
      the base rule: the panel rests off-screen at translateX(100%), so
      it is invisible by position rather than by an opacity the
      animation's fill has to override on the very first frame.
   4. Edge shading is inset box-shadow, not a gradient ::after — one
      less surface to rasterize (and re-invert) under the filter. */
#turn-layer {
  position: fixed;
  inset: 0;
  z-index: 300;
  pointer-events: none;
  overflow: hidden;
  visibility: hidden;          /* nothing to composite between turns */
  filter: invert(1);
}
#turn-layer.turn-next, #turn-layer.turn-prev { visibility: visible; }
#turn-layer .turn-page {
  position: absolute;
  top: -2%; bottom: -2%;
  left: 0; right: 0;
  background-color: var(--paper);
  background-image: url("__NEWSPRINT__");
  background-size: 480px auto;
  /* leading/trailing edge shading — reads as a lifting page edge.
     Authored inverted: white prints dark, black prints light. */
  box-shadow:
    inset 18px 0 26px -18px rgba(255, 255, 255, 0.34),
    inset -18px 0 26px -18px rgba(0, 0, 0, 0.14),
    0 0 60px var(--shadow);
  opacity: 1;
  transform: translateX(100%);   /* rest state: parked off-screen */
}
/* Next: panel sweeps in from the right, covers, exits left —
   the page jumps while fully covered at mid-sweep. */
#turn-layer.turn-next .turn-page {
  opacity: 1;
  animation: wipe-next 0.5s cubic-bezier(0.45, 0, 0.55, 1) forwards;
}
#turn-layer.turn-prev .turn-page {
  opacity: 1;
  animation: wipe-prev 0.5s cubic-bezier(0.45, 0, 0.55, 1) forwards;
}
/* Opacity holds at 1 for the whole sweep — the panel is already fully
   off-screen at the 100% stop, so dropping the class afterwards returns
   it to an off-screen rest state and cleanup can never flash. */
@keyframes wipe-next {
  0%   { transform: translateX(100%); opacity: 1; }
  50%  { transform: translateX(0%);   opacity: 1; }
  100% { transform: translateX(-100%); opacity: 1; }
}
@keyframes wipe-prev {
  0%   { transform: translateX(-100%); opacity: 1; }
  50%  { transform: translateX(0%);    opacity: 1; }
  100% { transform: translateX(100%);  opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .media-still, .photo-shine::after, #turn-layer .turn-page { animation: none !important; }
}
'''

# ─────────────────────────────────────────────────────────────
# JS
# ─────────────────────────────────────────────────────────────

JS = '''
(function() {
"use strict";
var tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
if (tg) {
  try {
    tg.ready();
    tg.expand();
    var p = tg.themeParams || {};
    tg.setHeaderColor('#0d1326');
    tg.setBackgroundColor('#0d1326');
  } catch(e) { console.error('[TG]', e); }
}

// ── Fixed page height from viewport (uniform for every sheet) ──
// ~1.08 screens: a full page of two-column text fills naturally,
// like a real broadsheet held at reading distance.
function setPageH() {
  var h = Math.max(780, Math.min(1400, Math.round(window.innerHeight * 1.08)));
  document.documentElement.style.setProperty('--page-h', h + 'px');
}
setPageH();

var newspaper = document.querySelector('.newspaper');
var pools = Array.prototype.slice.call(document.querySelectorAll('template.pool'));
var noticesSheet = document.getElementById('sheet-notices');

// Capture each pool's articles ONCE (DocumentFragment: no :scope — use
// a plain descendant query, articles are direct children of the template
// markup so order is preserved). Each article remembers its section so a
// page that carries two sections can still label itself honestly, and
// each pool gets one in-column section head for mid-page switches.
pools.forEach(function(pool) {
  var name = pool.getAttribute('data-section') || '';
  pool._arts = Array.prototype.slice.call(pool.content.querySelectorAll('article'));
  pool._arts.forEach(function(a) { a.setAttribute('data-sec', name); });
  var head = document.createElement('div');
  head.className = 'section-head';
  head.setAttribute('data-sec', name);
  head.textContent = name;
  pool._head = head;
});

// Standing matter used to close out the final section page.
var tailTpl = document.getElementById('tail-filler');
var tailItems = tailTpl
  ? Array.prototype.slice.call(tailTpl.content.querySelectorAll('.tail-ad'))
  : [];

function overflow(el) {
  return el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2;
}

function detach(node) { if (node && node.parentNode) { node.parentNode.removeChild(node); } }

function makeSheet(name, cont) {
  var sheet = document.createElement('section');
  sheet.className = 'sheet generated';
  var mid = cont ? name + ' (cont.)' : name;
  sheet.innerHTML =
    '<div class="page-head">' +
      '<div class="page-head-side folio-left"></div>' +
      '<div class="page-head-mid">' + mid + '</div>' +
      '<div class="page-head-side folio-right"></div>' +
    '</div>' +
    '<div class="columns"></div>';
  return sheet;
}

// ── Pagination: flow articles into fixed-height pages until full ──
var sectionFirstPage = {};

// Static sheets are not paginated, so they get the same one-step squeeze
// if their content would otherwise be clipped by the fixed page height.
function fitStatic() {
  ['sheet-front', 'sheet-contents', 'sheet-notices'].forEach(function(id) {
    var s = document.getElementById(id);
    if (!s) return;
    s.classList.remove('tight');
    var body = s.querySelector('.front-body, .contents-body, .notices-body');
    if (body && overflow(body)) { s.classList.add('tight'); }
  });
}

// Name the page after the section its first article belongs to, marking
// it "(cont.)" only when that section already had a page.
function labelSheet(sheet, cols, seen) {
  var secs = [];
  Array.prototype.forEach.call(cols.querySelectorAll('.article'), function(a) {
    var s = a.getAttribute('data-sec') || '';
    if (s && secs.indexOf(s) < 0) secs.push(s);
  });
  sheet._secs = secs;
  var mid = sheet.querySelector('.page-head-mid');
  if (mid && secs.length) {
    mid.textContent = secs[0] + (seen[secs[0]] ? ' (cont.)' : '');
  }
  secs.forEach(function(s) { seen[s] = true; });
}

// Pack the leftover foot of a page with standing matter — the classifieds
// that close out real broadsheet pages. Per page: try every unused notice,
// keep the ones that fit. Skipped ones stay available for later pages.
function fillTail(cols) {
  if (!cols) return;
  for (var k = 0; k < tailItems.length; k++) {
    var ad = tailItems[k];
    if (ad._used) { continue; }
    cols.appendChild(ad);
    if (overflow(cols)) { detach(ad); continue; }
    ad._used = true;
  }
}

// Front page: the story above the fold is static, but a real front page
// also carries column matter below it. Flow as many pool articles as fit
// into #front-columns (they stay in the main stream for later pages —
// the paginator runs first and skips what the front page took).
function fillFront() {
  var fc = document.getElementById('front-columns');
  if (!fc) return;
  var stream = [];
  pools.forEach(function(pool, pi) {
    if (pi > 0 && pool._head) { stream.push(pool._head); }
    pool._arts.forEach(function(a) { stream.push(a); });
  });
  var first = stream[0];
  if (!first) return;
  var startSec = first.getAttribute('data-sec') || '';
  if (startSec) {
    var fh = document.createElement('div');
    fh.className = 'section-head';
    fh.setAttribute('data-sec', startSec);
    fh.textContent = startSec;
    fc.appendChild(fh);
  }
  for (var k = 0; k < stream.length; k++) {
    fc.appendChild(stream[k]);   // later sections continue below the fold,
    if (overflow(fc)) { detach(stream[k]); break; }  // heads and all
  }
  // never end the front page on a dangling head
  while (fc.lastElementChild && fc.lastElementChild.className.indexOf('section-head') >= 0) {
    detach(fc.lastElementChild);
  }
  fillTail(fc);   // close the front page foot with standing matter
}

function paginate() {
  // ── VIEWPORT ANCHOR: pagination rebuilds the whole DOM, which yanks
  // content out from under a scrolling finger ("jump"). Remember what
  // sits at the anchor point (1/3 down the VIEWPORT — elementsFromPoint
  // takes viewport coords, not absolute), rebuild, restore. Anchor by
  // id when the element has one, else by class+text signature so index
  // rows, notices and ads anchor too.
  var anchor = null;
  (function () {
    var els = document.elementsFromPoint(window.innerWidth / 2, window.innerHeight / 3);
    var el = null;
    for (var i = 0; i < els.length; i++) {
      var e = els[i];
      if (e.classList && (e.classList.contains('article') || e.classList.contains('tail-ad') ||
          e.classList.contains('filler-ad') || e.classList.contains('index-row') ||
          e.classList.contains('article-text') || e.tagName === 'P' || e.tagName === 'LI')) { el = e; break; }
    }
    if (!el && els.length) { el = els[els.length - 1]; }
    if (!el || el === document.documentElement || el === document.body) { return; }
    var root = el.closest ? el.closest('[id]') : null;
    anchor = {
      id: root ? root.id : null,
      cls: (el.classList && el.classList.length) ? el.classList[0] : null,
      sig: (el.textContent || '').trim().slice(0, 40),
      off: el.getBoundingClientRect().top,
      abs: el.getBoundingClientRect().top + window.scrollY
    };
  })();

  setPageH();
  sectionFirstPage = {};
  var generated = document.querySelectorAll('.sheet.generated');
  Array.prototype.forEach.call(generated, function(s) { s.remove(); });
  var fc = document.getElementById('front-columns');
  if (fc) { Array.prototype.slice.call(fc.children).forEach(detach); }
  pools.forEach(function(pool) {
    pool._arts.forEach(detach);
    detach(pool._head);
  });
  tailItems.forEach(function(ad) { detach(ad); ad._used = false; });
  tailState = 0;   // fresh edition: every classified available again
  fillFront();
  fitStatic();

  // ONE continuous stream across every section. A short section shares the
  // page with the tail of the previous one — normal newspaper flow — rather
  // than opening its own half-empty sheet; the section head marks the switch
  // inside the column and the folio still names the page's opening section.
  // Articles the front page took are already placed — skip them here.
  var frontTaken = {};
  var fc = document.getElementById('front-columns');
  if (fc) {
    Array.prototype.forEach.call(fc.querySelectorAll('.article'), function(a) {
      frontTaken[a.id] = true;
    });
  }
  var stream = [];
  pools.forEach(function(pool, pi) {
    if (pi > 0) { stream.push(pool._head); }
    pool._arts.forEach(function(a) { if (!frontTaken[a.id]) { stream.push(a); } });
  });

  var seen = {};
  var i = 0, guard = 0, lastCols = null;
  while (i < stream.length && guard < 80) {
    guard++;
    var openSec = stream[i].getAttribute('data-sec') || '';
    var sheet = makeSheet(openSec, seen[openSec] === true);
    newspaper.insertBefore(sheet, noticesSheet);
    var cols = sheet.querySelector('.columns');
    while (i < stream.length) {
      cols.appendChild(stream[i]);
      if (overflow(cols) && cols.children.length > 1) {
        // Overflowing only slightly? Take one global type step down and
        // keep the piece rather than closing the page on a gap.
        if (!sheet.classList.contains('tight')) {
          sheet.classList.add('tight');
          if (!overflow(cols)) { i++; continue; }
          sheet.classList.remove('tight');
        }
        detach(stream[i]);   // doesn't fit — close the page
        break;
      }
      i++;
    }
    // Never strand a section head at the foot of a page.
    while (cols.lastElementChild && cols.lastElementChild.className.indexOf('section-head') >= 0) {
      detach(cols.lastElementChild); i--;
    }
    // Every page must carry an article, even one taller than the page.
    while (!cols.querySelector('.article') && i < stream.length) {
      cols.appendChild(stream[i]); i++;
    }
    labelSheet(sheet, cols, seen);
    fillTail(cols);   // close out any spare page-foot with standing matter
    lastCols = cols;
  }

  rebuildSheetModel();
  updateFolios();
  attachVideos();
  updateIndicator();

  // ── restore the anchor: find the same element (by id, else class +
  // text signature) and put it back under the finger
  if (anchor) {
    var target = null;
    if (anchor.id) {
      var byId = document.getElementById(anchor.id);
      if (byId) {
        var inner = byId.querySelector('.' + anchor.cls) || byId;
        if (inner && (inner.textContent || '').trim().slice(0, 40) === anchor.sig) { target = inner; }
        else if (byId.textContent.trim().slice(0, 40) === anchor.sig) { target = byId; }
        else { target = inner || byId; }
      }
    }
    if (!target && anchor.sig) {
      // Disambiguate twin texts (contents-box entry vs in-column section
      // head share text): among same-class same-text candidates, take
      // the one whose absolute position is CLOSEST to where the
      // anchored element used to be (old layout is taller than new —
      // content sits deeper after reflow — so bias by +0..8% height).
      var cands = document.querySelectorAll('.' + (anchor.cls || 'article-text'));
      var bestD = Infinity;
      for (var ci = 0; ci < cands.length; ci++) {
        if ((cands[ci].textContent || '').trim().slice(0, 40) !== anchor.sig) { continue; }
        var cAbs = cands[ci].getBoundingClientRect().top + window.scrollY;
        var d = Math.abs(cAbs - anchor.abs);
        if (d < bestD) { bestD = d; target = cands[ci]; }
      }
    }
    if (target && target.isConnected) {
      // algebra: element's absolute position A_new after rebuild;
      // want viewport top = off  ->  newScrollY = A_new - off.
      // A_new = getBoundingClientRect().top + scrollY (post-rebuild).
      // Equivalent: scrollY + delta where delta = rect.top - off
      // (measured pre-adjustment). Sign was flipped before: 'scrollY
      // - delta' doubled the displacement instead of cancelling it.
      var delta = target.getBoundingClientRect().top - anchor.off;
      if (Math.abs(delta) > 2) { window.scrollTo(0, window.scrollY + delta); }
    }
  }
}

// ── Sheet model for flipping ──
var sheets = [];
var current = 0;
var tailState = 0;   // each standing notice used at most once per edition

function rebuildSheetModel() {
  sheets = Array.prototype.slice.call(document.querySelectorAll('.sheet'));
  current = 0;
}

function updateFolios() {
  var tpl = document.querySelector('.folio-left-template');
  var dateEar = tpl ? tpl.getAttribute('data-date') : '';
  var ed = tpl ? tpl.getAttribute('data-edition') : '';
  sheets.forEach(function(s, i) {
    var l = s.querySelector('.folio-left');
    var r = s.querySelector('.folio-right');
    if (l) { l.textContent = dateEar + ' \\u00b7 \\u2116' + ed; }
    if (r) { r.textContent = 'Page ' + (i + 1); r.setAttribute('data-n', i + 1); }
    // Generated sheets record every section they carry, so an index entry
    // still lands on the right page when a section starts mid-page.
    if (s._secs) {
      s._secs.forEach(function(name) {
        if (sectionFirstPage[name] === undefined) { sectionFirstPage[name] = i; }
      });
    } else {
      var mid = s.querySelector('.page-head-mid');
      if (mid && sectionFirstPage[mid.textContent] === undefined) {
        sectionFirstPage[mid.textContent] = i;
      }
    }
  });
  document.querySelectorAll('.index-row').forEach(function(row) {
    var sec = row.getAttribute('data-section');
    var tgt = sectionFirstPage[sec] != null ? sectionFirstPage[sec] : 1;
    row.setAttribute('data-target', tgt);
    var pg = row.querySelector('.idx-page');
    if (pg) { pg.textContent = 'Page ' + (tgt + 1); }
  });
}

// ── Turn effect ──
var layer = document.createElement('div');
layer.id = 'turn-layer';
var turnPage = document.createElement('div');
turnPage.className = 'turn-page';
layer.appendChild(turnPage);
document.body.appendChild(layer);

var TURN_MS = 500;    // must match the wipe-next/wipe-prev duration in CSS
var COVER_MS = 250;   // mid-sweep — the panel has the screen fully covered
var reducedMotion = !!(window.matchMedia &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches);
var turnTimers = [];
var pendingEnd = null;   // animationend listener of the turn in flight

function clearTurnTimers() {
  turnTimers.forEach(function(t) { clearTimeout(t); });
  turnTimers = [];
}

// Park the layer. Cleanup is driven by animationend so the classes are
// never dropped mid-sweep on a device that started the animation a few
// frames late; the timer below is only a fallback for a lost event.
function finishTurn() {
  clearTurnTimers();
  if (pendingEnd) {
    turnPage.removeEventListener('animationend', pendingEnd);
    pendingEnd = null;
  }
  layer.classList.remove('turn-next', 'turn-prev');
}

// Sweeps the paper panel across and runs atCover() while the screen is
// fully covered, so the caller's scroll jump is never visible.
function playTurn(dir, atCover) {
  var covered = false;
  function cover() {
    if (covered) return;
    covered = true;
    if (atCover) { atCover(); }
  }
  // Reduced motion kills the animation outright, so nothing ever covers
  // the screen — do the jump straight away instead of on a dead timer.
  if (reducedMotion) { cover(); return; }
  finishTurn();                 // supersede any turn still in flight
  void layer.offsetWidth;       // reflow: restart the animation cleanly
  layer.classList.add(dir === 'next' ? 'turn-next' : 'turn-prev');
  pendingEnd = function() { finishTurn(); };
  turnPage.addEventListener('animationend', pendingEnd);
  turnTimers.push(setTimeout(cover, COVER_MS));
  // Late cleanup is invisible (the panel ends off-screen); early cleanup
  // would snap it away mid-sweep. So the fallback runs well after the end.
  turnTimers.push(setTimeout(finishTurn, TURN_MS + 260));
}

function flipTo(idx) {
  idx = Math.max(0, Math.min(sheets.length - 1, idx));
  if (idx === current) return;
  var dir = idx > current ? 'next' : 'prev';
  var target = sheets[idx];
  var top = target.getBoundingClientRect().top + window.scrollY - 8;
  // Jump the page UNDER the cover so the wipe reads as the turn;
  // scrolling while covered never flashes.
  document.documentElement.style.scrollBehavior = 'auto';
  playTurn(dir, function() {
    window.scrollTo(0, top);
    document.documentElement.style.scrollBehavior = '';
  });
  current = idx;
  updateIndicator();
}

document.getElementById('flip-prev').addEventListener('click', function() { flipTo(current - 1); });
document.getElementById('flip-next').addEventListener('click', function() { flipTo(current + 1); });

document.querySelectorAll('.index-row').forEach(function(row) {
  row.addEventListener('click', function() {
    flipTo(parseInt(row.getAttribute('data-target') || '1', 10));
  });
});

function updateIndicator() {
  var el = document.getElementById('page-indicator');
  if (el && sheets[current]) {
    el.textContent = 'Page ' + (current + 1) + ' of ' + sheets.length;
  }
}

var scrollTimer = null;
window.addEventListener('scroll', function() {
  if (scrollTimer) return;
  scrollTimer = setTimeout(function() {
    scrollTimer = null;
    var mid = window.scrollY + window.innerHeight / 2;
    var best = 0;
    sheets.forEach(function(s, i) {
      var top = s.getBoundingClientRect().top + window.scrollY;
      if (top <= mid) best = i;
    });
    if (best !== current) { current = best; updateIndicator(); }
  }, 120);
}, { passive: true });

// Swipe gestures
(function() {
  var startX = 0, startY = 0, tracking = false;
  document.addEventListener('touchstart', function(e) {
    if (e.touches.length !== 1) { tracking = false; return; }
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    tracking = true;
  }, { passive: true });
  document.addEventListener('touchend', function(e) {
    if (!tracking) return;
    tracking = false;
    var dx = e.changedTouches[0].clientX - startX;
    var dy = e.changedTouches[0].clientY - startY;
    if (Math.abs(dx) > 80 && Math.abs(dx) > Math.abs(dy) * 1.6) {
      if (dx < 0) flipTo(current + 1); else flipTo(current - 1);
    }
  }, { passive: true });
})();

// Autoplay + video lifecycle
var videoObserver = new IntersectionObserver(function(entries) {
  entries.forEach(function(en) {
    if (en.isIntersecting) {
      var p = en.target.play(); if (p && p.catch) p.catch(function() {});
    } else {
      en.target.pause();
    }
  });
}, { rootMargin: '250px' });

function attachVideos() {
  document.querySelectorAll('video.media-video').forEach(function(v) {
    if (v.dataset.obs) return;
    v.dataset.obs = '1';
    videoObserver.observe(v);
  });
}

document.addEventListener('touchstart', function once() {
  document.querySelectorAll('video.media-video').forEach(function(v) {
    if (v.paused) { var p = v.play(); if (p && p.catch) p.catch(function() {}); }
  });
  document.removeEventListener('touchstart', once);
}, { passive: true });

// Article taps open the post
function bindArticleTaps() {
  document.querySelectorAll('.article, .front-story, .banner-block').forEach(function(art) {
    if (art.dataset.tap) return;
    var link = art.querySelector('a');
    if (!link) return;
    art.dataset.tap = '1';
    var url = link.href;
    art.addEventListener('click', function(e) {
      if (e.target.closest('a')) return;
      if (e.target.closest('video')) return;
      if (tg && tg.openLink) { tg.openLink(url); }
      else { window.open(url, '_blank', 'noopener'); }
    });
  });
}

// Debounced repagination — WIDTH changes only (rotation/split-screen).
// Android webviews fire 'resize' on every URL-bar show/hide and on
// keyboard open — height-only, width identical. Repaginating for those
// reflows the whole document mid-scroll: the jump. Height-only resizes
// are now ignored entirely (sheets simply extend a few px past the
// shrunken viewport, which is invisible; a reflow is not).
var rz = null;
var lastW = window.innerWidth;
window.addEventListener('resize', function() {
  if (window.innerWidth === lastW) { return; }
  lastW = window.innerWidth;
  if (rz) clearTimeout(rz);
  rz = setTimeout(paginate, 250);
});

function boot() {
  paginate();
  bindArticleTaps();
  attachVideos();
  updateIndicator();
}
if (document.readyState === 'complete') boot();
else window.addEventListener('load', boot);
setTimeout(function() { paginate(); bindArticleTaps(); attachVideos(); }, 1200);
/* Re-paginate ONCE after webfonts finish loading — font-display: swap
   lets Georgia show first, and early pagination measured the WRONG
   metrics. The old code paginated twice (timer + fonts.ready), each
   pass yanking the DOM mid-scroll; the 1200ms timer alone now covers
   the swap window, and paginate() itself preserves the viewport
   anchor. */
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(function() { setTimeout(function() { bindArticleTaps(); attachVideos(); }, 30); });
}
})();
'''


# ─────────────────────────────────────────────────────────────
# Standing matter — the paginator packs as many of these as fit into the
# foot of the last section page so it ends flush, the way a real back
# section is closed out with classifieds. Order matters: shortest last.
# ─────────────────────────────────────────────────────────────

TAIL_NOTICES = [
    ("Owlery Hours",
     "The Owlery closes at dusk. Dispatches handed in after the bell travel with the morning post."),
    ("Wanted",
     "One competent Automaton to sort the dawn feeds. Must tolerate rate limits. Enquire at the Notices desk."),
    ("For Sale",
     "Assorted enchanted quills, lightly used. They will not correct your spelling, only your posture."),
    ("Weather",
     "Fair over the Highlands; light static in the wireless after midnight."),
    ("Corrections",
     "An earlier edition misprinted the tally of subreddits. The Prophet regrets the error."),
    ("Next Edition",
     "By owl, at first light."),
    ("Broom Racing",
     "Saturday twilight trials over the south pitch. Spectators welcome; umbrellas advised."),
    ("Potions Register",
     "Names are being taken for the autumn brewing circle. Beginners seated at the back."),
    ("Lost & Found",
     "A single maroon sock was left on the Express. Claim at the counter with a description."),
    ("House Points",
     "The hourglass counts this edition's bylines. Idle reading earns nothing, as ever."),
    ("Owl Treats",
     "Fresh mice and toasted crumbs now stocked at the counter. Owls queue on the left."),
    ("Apparition Test",
     "The next examination falls on the new moon. Side-along splinching insurance available."),
    ("Quidditch Fixtures",
     "Season opening match postponed; the referee's broom is undergoing an unauthorised refit. Watch this column."),
    ("Puzzle Corner",
     "What walks the castle at midnight with four legs at dawn and none by dusk? Answers to the caretaker, not in writing."),
    ("Second-Hand Cauldrons",
     "Three pewter cauldrons, one with a hairline charm-crack, priced for quick sale. Thorough cleaning guaranteed."),
    ("Musical Notices",
     "The Frog Choir rehearses at seven sharp. Newts are provided; earplugs are not."),
    ("Greenhouse Survey",
     "Professor Sprout requests volunteers for repotting. Those who squeaked last time need not apply."),
    ("Ravenclaw Notice",
     "The door-knocker has taken to asking riddles before breakfast. Arrive early or arrive clever."),
    ("Kitchen Hours",
     "House-elves serve supper at six. Late diners may collect a basket at the fruit-bowl portrait."),
    ("Wanted", "One marbled quill, last seen Tuesday."),
    ("Found", "A very smug brown owl. Counter."),
    ("Exchange", "Two galleons for one honest map."),
    ("Notice", "Do not feed the books after midnight."),
    ("Sweets", "Chocolate frogs restocked this morning."),
    ("Reminder", "Owls queue on the left. Always left."),
]

TAIL_FILLER = ('<template id="tail-filler">\n' + "\n".join(
    f'<div class="tail-ad"><span class="b">{escape(t)}</span>{escape(body)}</div>'
    for t, body in TAIL_NOTICES
) + '\n</template>')


# ─────────────────────────────────────────────────────────────
# HTML pieces
# ─────────────────────────────────────────────────────────────

def render_media(media: dict, article_id, size: str = "page") -> str:
    if not media:
        return ""
    mtype = media.get("type", "")
    url = escape(media.get("url", ""))
    if not url or not mtype:
        return ""

    # NOTE: colors are authored inverted (the .world flips them back).
    # Real media counter-inverts itself via CSS filter.
    if mtype == "gif":
        inner = (f'<img class="media-img" src="{url}" alt="animated photograph" '
                 f'loading="lazy" referrerpolicy="no-referrer" '
                 f'onerror="this.closest(\'.photo\').classList.add(\'gone\')">')
    elif mtype == "image":
        inner = (f'<img class="media-img media-still" src="{url}" alt="photograph" '
                 f'loading="lazy" referrerpolicy="no-referrer" '
                 f'onerror="this.closest(\'.photo\').classList.add(\'gone\')">')
    elif mtype == "video":
        inner = (f'<video class="media-video" src="{url}" autoplay loop muted '
                 f'playsinline preload="metadata" '
                 f'onerror="this.closest(\'.photo\').classList.add(\'gone\')">'
                 f'</video>')
    else:
        return ""

    shine = '<div class="photo-shine"></div>' if mtype in ("gif", "video") else ""
    cap = {"gif": "Animated Photograph", "video": "Moving Picture",
           "image": "Photograph"}.get(mtype, "Photograph")

    return f'''<figure class="photo {size}" id="fig_{article_id}">
  <div class="photo-frame">{inner}{shine}</div>
  <figcaption class="photo-caption">✦ {cap} ✦</figcaption>
</figure>'''


def render_inner_article(article: dict, idx: int) -> str:
    title = escape(article.get("title", ""))
    summary = escape(article.get("summary", ""))
    link = escape(article.get("link", ""))
    author = escape(article.get("author", ""))
    subreddit = escape(article.get("subreddit", ""))
    media = article.get("media")

    byline = " · ".join(x for x in [author, subreddit] if x)
    photo = render_media(media, idx, size="page")
    relevance = escape(article.get("relevance", ""))
    note = f'<p class="relevance">→ <em>{relevance}</em></p>' if relevance else ""

    return f'''<article class="article" id="art_{idx}">
  <h3 class="headline"><a href="{link}" target="_blank" rel="noopener">{title}</a></h3>
  <div class="byline">{byline}</div>
  {photo}
  <p class="article-text">{summary}</p>
  {note}
</article>'''


def render_newspaper(data: dict) -> str:
    date = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    total_posts = data.get("total_posts", 0)
    total_subs = data.get("total_subs", 0)
    sections = [s for s in data.get("sections", []) if s.get("articles")]
    ideas = data.get("integration_ideas", [])
    fetcher_notes = data.get("fetcher_notes", "")

    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        date_display = dt.strftime("%A, %B %d, %Y")
        date_ear = dt.strftime("%b %d")
        edition = (dt - datetime(1970, 1, 1)).days
    except ValueError:
        date_display = date
        date_ear = date
        edition = "?"

    if not sections:
        return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>The Daily Tech Prophet</title></head>'
                '<body style="font-family:Georgia,serif;text-align:center;padding:60px 20px;'
                'background:#f2ecd9;color:#000;filter:invert(0)">'
                '<div style="background:#0d1326;color:#fff;filter:invert(1)">'
                '<h1>The Daily Tech Prophet</h1>'
                '<p>No news arrived by owl post today.</p></div></body></html>')

    lead = sections[0]["articles"][0]
    lead_title = escape(lead.get("title", ""))
    lead_link = escape(lead.get("link", ""))
    lead_byline = " · ".join(x for x in [lead.get("author", ""), lead.get("subreddit", "")] if x)
    deck = lead.get("relevance") or lead.get("summary", "")

    notes_html = f'<div class="fetcher-notes">⚠ {escape(fetcher_notes)}</div>' if fetcher_notes else ""

    # Everything the front page does not print gets paginated, including the
    # rest of the lead section — those articles used to be dropped silently.
    pool_sections = []
    lead_rest = sections[0].get("articles", [])[1:]
    if lead_rest:
        pool_sections.append({"name": sections[0].get("name", ""), "articles": lead_rest})
    pool_sections.extend(sections[1:])

    front_sheet = f'''<section class="sheet" id="sheet-front">
  <div class="page-head">
    <div class="page-head-side folio-left-template" data-date="{date_ear}" data-edition="{edition}"></div>
    <div class="page-head-mid">FRONT PAGE</div>
    <div class="page-head-side folio-right"></div>
  </div>
  <div class="front-body">
    <div class="banner-block">
      <h2 class="banner"><a href="{lead_link}" target="_blank" rel="noopener">{lead_title}</a></h2>
      <div class="deck">{escape(deck)}</div>
    </div>
    <div class="front-grid">
      {render_media(lead.get("media"), "lead", size="lead")}
      <div class="front-story">
        <div class="byline">{escape(lead_byline)}</div>
        <p class="article-text front-text">{escape(lead.get("summary", ""))}</p>
        {f'<p class="relevance">→ <em>{escape(lead.get("relevance",""))}</em></p>' if lead.get("relevance") else ''}
      </div>
    </div>
    {notes_html}
    <div class="columns" id="front-columns"></div>
  </div>
</section>'''

    rows = []
    for sec in pool_sections:
        name = escape(sec.get("name", ""))
        n = len(sec.get("articles", []))
        teaser = escape(sec.get("articles", [{}])[0].get("title", "")[:70])
        rows.append(
            f'<li class="index-row" data-section="{name}">'
            f'<span class="idx-sec">{name}</span>'
            f'<span class="idx-meta">{n} article{"s" if n != 1 else ""}</span>'
            f'<span class="idx-page">Page —</span>'
            f'<div class="idx-teaser">{teaser}</div>'
            f'</li>'
        )
    contents_sheet = f'''<section class="sheet" id="sheet-contents">
  <div class="page-head">
    <div class="page-head-side folio-left"></div>
    <div class="page-head-mid">CONTENTS</div>
    <div class="page-head-side folio-right"></div>
  </div>
  <div class="contents-body">
    <div class="index-box">
      <div class="index-title">✦ Inside This Edition ✦</div>
      <ul class="index-list">{''.join(rows)}</ul>
    </div>
    <div class="filler-grid">
      <div class="filler-ad"><span class="b">Owl Post Speed</span>Delivery in under a minute, rain or shine. No howlers accepted.<div class="ad-rule"></div></div>
      <div class="filler-ad"><span class="b">Weasely's Web Feeds</span>Seventeen subreddits scoured hourly so you needn't stir from your armchair.<div class="ad-rule"></div></div>
      <div class="filler-ad"><span class="b">Moving Photographs</span>Bring your snapshots to life — ask the Hermes Automata.<div class="ad-rule"></div></div>
      <div class="filler-ad"><span class="b">Classifieds</span>Lost: one sock, House-elf blame unclear. Reward: two galleons.<div class="ad-rule"></div></div>
      <div class="filler-ad"><span class="b">Ponder Submissions</span>Send integration notions by owl to the Notices desk.<div class="ad-rule"></div></div>
      <div class="filler-ad"><span class="b">Print Quality Oath</span>All ink enchanted against smudges and dark-mode curses.<div class="ad-rule"></div></div>
    </div>
  </div>
</section>'''

    pools = []
    art_counter = 0
    for sec in pool_sections:
        name = escape(sec.get("name", ""))
        arts = []
        for a in sec.get("articles", []):
            arts.append(render_inner_article(a, art_counter))
            art_counter += 1
        pools.append(f'<template class="pool" data-section="{name}">\n' + "\n".join(arts) + '\n</template>')
    pools_html = "\n".join(pools)

    items = "\n".join(
        f'<li><span class="idea-num">{i}.</span> {escape(idea)}</li>'
        for i, idea in enumerate(ideas, 1)
    )
    notices_sheet = f'''<section class="sheet" id="sheet-notices">
  <div class="page-head">
    <div class="page-head-side folio-left"></div>
    <div class="page-head-mid">NOTICES</div>
    <div class="page-head-side folio-right"></div>
  </div>
  <div class="notices-body">
    <aside class="ponder-box">
      <div class="ponder-header">✦ Ponder This ✦</div>
      <div class="ponder-subtitle">Notices for the Worthy Wizard</div>
      <ol class="ponder-list">
        {items}
      </ol>
    </aside>
    <div class="colophon">
      <div class="colophon-rule">✦ ❦ ✦</div>
      <div>Printed by Magical Press · Delivered by Hermes Agent</div>
      <div style="margin-top:2px">{total_posts} posts · {total_subs} subreddits · {date_display}</div>
    </div>
  </div>
</section>'''

    css = CSS.replace("__NEWSPRINT__", NEWSPRINT_URL)
    js = JS

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="only light">
<meta name="theme-color" content="#0d1326">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>The Daily Tech Prophet — {date}</title>
<style>{css}</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <!-- ═══ INK-SOFTEN FILTER (letterpress fuzz) ═══
         Technique per Andy Jakubowski's ink-bleed recipe: feGaussianBlur
         softens glyph edges, feComponentTransfer thresholds them back
         crisp with a fattened toe — the print reads as slightly wet,
         spread ink rather than blurred text. Rides in the CSS filter
         channel, the only channel proven to survive this webview's
         paint-time Force Dark (the inverted world itself depends on it;
         text-shadow/-webkit-text-stroke do NOT). -->
    <filter id="inkfuzz" x="-5%" y="-5%" width="110%" height="110%"
            color-interpolation-filters="sRGB">
      <feGaussianBlur in="SourceGraphic" stdDeviation="0.28" result="soft"/>
      <feComponentTransfer in="soft" result="fuzz">
        <feFuncA type="table" tableValues="0 0.35 0.72 1"/>
      </feComponentTransfer>
      <feMerge>
        <feMergeNode in="fuzz"/>
      </feMerge>
    </filter>
    <!-- mid weight: genuine ink gain via feMorphology (real weight —
         Fell has NO bold face, and browser-synthesized bold under the
         threshold filter reads as mud). Replaces font-weight 700.
         Config C: measured lowest line-to-line boldness variance
         (CV 0.069 vs 0.080 for the harder-threshold set) in an A/B/C/D
         sweep under forced-dark DPR3; fuzz edge band 0.19 (visible). -->
    <filter id="inkfuzz-mid" x="-8%" y="-8%" width="116%" height="116%"
            color-interpolation-filters="sRGB">
      <feMorphology in="SourceGraphic" operator="dilate" radius="0.15" result="fat"/>
      <feGaussianBlur in="fat" stdDeviation="0.28" result="soft"/>
      <feComponentTransfer in="soft" result="fuzz">
        <feFuncA type="table" tableValues="0 0.33 0.68 1"/>
      </feComponentTransfer>
      <feMerge>
        <feMergeNode in="fuzz"/>
      </feMerge>
    </filter>
    <!-- display weight: heavier dilate for masthead / big headline /
         dropcap. Replaces font-weight 900. Gentle slope preserves
         counters (the blob problem came from tableValues 0 x 1 1
         re-solidifying the halo). -->
    <filter id="inkfuzz-head" x="-8%" y="-8%" width="116%" height="116%"
            color-interpolation-filters="sRGB">
      <feMorphology in="SourceGraphic" operator="dilate" radius="0.28" result="fat"/>
      <feGaussianBlur in="fat" stdDeviation="0.38" result="soft"/>
      <feComponentTransfer in="soft" result="fuzz">
        <feFuncA type="table" tableValues="0 0.30 0.62 1"/>
      </feComponentTransfer>
      <feMerge>
        <feMergeNode in="fuzz"/>
      </feMerge>
    </filter>
  </defs>
</svg>

<div class="world">
<div class="grain-overlay"></div>
<div class="newspaper">

  <header class="masthead">
    <div class="mast-topline">✦ Trusted by Wizards Since 1743 ✦ · ✦ Powered by Hermes Automata ✦</div>
    <h1 class="mast-title"><span class="mast-the">The</span>Daily Tech Prophet</h1>
    <div class="mast-sub">
      <span class="mast-ear"><span class="b">Edition</span> №{edition}</span>
      <span class="mast-strap">“All the News That's Fit to Enchant”</span>
      <span class="mast-ear"><span class="b">Owl Post</span> {date_ear}</span>
    </div>
  </header>

  {notes_html}

  {front_sheet}

  {contents_sheet}

  {pools_html}

  {TAIL_FILLER}

  {notices_sheet}

</div>
</div>

<div class="flip-controls">
  <button class="flip-btn" id="flip-prev" aria-label="Previous page">‹</button>
  <button class="flip-btn" id="flip-next" aria-label="Next page">›</button>
</div>
<div class="page-indicator" id="page-indicator">Page 1</div>

<script>{js}</script>

</body>
</html>'''


def main():
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        with open(sys.argv[1]) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    html_output = render_newspaper(data)

    output_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/reddit_newspaper.html"
    with open(output_path, "w") as f:
        f.write(html_output)

    print(f"Newspaper rendered: {output_path} ({len(html_output)} bytes)")


if __name__ == "__main__":
    main()