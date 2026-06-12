# Architecture Decisions

This file records architecture decisions for Weasel Bot V2. Add new decisions when implementation choices affect project structure, dependencies, deployment, persistence, or long-term maintenance.

## ADR-0001: Public Repository With No Secrets

- Status: Accepted
- Date: 2026-06-12

Weasel Bot V2 will be developed as a public-repository-safe project. Secrets, private runtime data, local infrastructure files, old V1 save files, cookies, tokens, and private Arcadia deployment details must not be committed.

## ADR-0002: Docker-First

- Status: Accepted
- Date: 2026-06-12

The project will be designed around Docker deployment from the start. Docker Compose examples may be provided, but local real compose files must stay ignored.

## ADR-0003: Lavalink-First

- Status: Accepted
- Date: 2026-06-12

Audio playback will be built around Lavalink as a separate service. The bot communicates with Lavalink through an internal Docker network.

## ADR-0004: SQLite-First

- Status: Accepted
- Date: 2026-06-12

SQLite will be the first persistent database. It keeps the bot self-hosted and simple without requiring a separate database service.

## ADR-0005: AI Is Optional

- Status: Accepted
- Date: 2026-06-12

AI and Ollama features may be added later, but they must remain optional. Core bot features must not require a paid API, external AI service, or local LLM.

## ADR-0006: Lavalink Python Client Not Selected Yet

- Status: Pending
- Date: 2026-06-12

The Python Lavalink client must not be blindly chosen. Before implementation, the project must verify the current best maintained Python Lavalink client.

Candidate families include:

- Wavelink
- Mafic
- Pomice
- lavalink.py

Selection criteria should include maintenance activity, Lavalink v4 compatibility, Discord library compatibility, documentation quality, async behavior, release cadence, and migration risk.
