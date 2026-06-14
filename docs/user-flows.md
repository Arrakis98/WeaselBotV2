# User Flows

## Now Playing Panel

Playback commands such as `/play_local`, `/play_all`, `/skip`, `/back`,
`/pause`, `/resume`, `/stop`, `/leave`, `/volume`, queue changes, ratings, and
natural track advance refresh one authoritative Now Playing panel per guild.
`/now_playing` refreshes or recreates that panel rather than creating a permanent
duplicate.

## Queue Button

The queue button opens a concise private ephemeral queue view. It shows the
current track, a limited number of upcoming tracks, and the remaining hidden
count when the queue is long. It does not create another public panel and does
not replace the existing `/queue` command.

## Shuffle Button

The shuffle button randomizes only the existing upcoming queue. It does not
interrupt the current track, rescan the filesystem, rebuild `/play_all`, or add
new tracks. Empty and one-track queues return a private explanation.

## More Actions

The more actions button opens a private ephemeral select menu.

Currently functional:

- Show queue
- Track information

Reserved for future phases and clearly marked as unavailable:

- Same artist
- Same category
- Add to playlist
- Start similar radio

These future options do not implement playlist, recommendation, radio, web
playback, Chaos Mode, or AI behavior in Phase 5.3B.

## Known Limits

Loop remains experimental, and the known long-pause and loop playback
instability issues are not addressed in this phase. Components V2 panel
persistence across full bot restarts is not guaranteed because persistent view
registration is not implemented.
