# UI Design

## Weasel Galaxy

Phase 5.3B introduces the Weasel Galaxy player interface for the authoritative
Discord Now Playing panel.

- Name: Weasel Galaxy.
- Language: English.
- Accent: vivid magenta/violet, `#C026D3`.
- Tone: premium, compact, playful, cosmic, and readable.
- Controls: emoji-only public player buttons with stable `custom_id` values.

The main player panel should not look like a diagnostic dashboard. It avoids raw
local file paths, Lavalink status, host filesystem details, and implementation
debug text. Technical status remains available through `/bot_status` and
`/audio_status`.

## Information Hierarchy

The Components V2 player panel shows:

- `WEASEL GALAXY`
- `Now Playing`
- current track title
- artist and optional category
- playback state, volume, and queue size
- next track preview
- rating totals: heart, diamond, thumbs-down, skull
- subtle loop state when loop is enabled

If the artist is unknown, the panel displays `Divers`. If the category is
unknown, the category line is omitted rather than showing an empty separator.

## Controls

Public player controls are arranged as:

- Row 1: previous, pause/resume, next, stop, loop
- Row 2: volume down, volume up, queue, shuffle, more actions
- Row 3: like, superlike, dislike, superdislike

Temporary Unicode emoji are used for now. Custom application emoji IDs are a
future extension point once a galaxy emoji pack exists.

## Artwork Extension Point

The player service has an optional artwork hook for a future thumbnail URL or
Discord attachment reference. No mascot GIF, spritesheet, or external hosted
asset is integrated in Phase 5.3B. Animated mascot support will be tested
separately later, and the panel remains balanced when no artwork is configured.

## Fallback

Components V2 is the primary renderer when the installed `discord.py` exposes
the required APIs. The legacy embed renderer remains available as a fallback. If
Components V2 message creation or editing fails, the panel service logs safe
diagnostics and tries the legacy embed without interrupting playback.
