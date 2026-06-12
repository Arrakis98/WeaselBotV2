# Chaos Mode

Chaos Mode, also called Mad DJ mode, is a future opt-in personality and playback feature for Weasel Bot V2.

The goal is to make the bot feel playful without compromising reliable music playback.

## Concept

Chaos Mode may eventually allow the bot to:

- occasionally reshuffle part of the queue
- suggest surprising tracks
- react dramatically to skips or repeats
- add playful commentary to music sessions
- trigger themed listening events
- create temporary challenge queues

## Safety Boundaries

Chaos Mode must be disabled by default. It should require explicit guild configuration and appropriate permissions.

Expected controls:

- admin-only enablement
- cooldowns
- clear audit messages
- per-guild settings
- limits on queue changes
- easy disable command

Chaos Mode should never delete playlists, corrupt history, modify local music files, or require AI.

## Relationship to AI

Chaos Mode can exist without AI. Optional AI or Ollama integrations may enhance future behavior, but they must not be required.
