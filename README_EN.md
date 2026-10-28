# dafeiyu-wechat-group

English | [中文](README.md)

Run a DeepSeek-powered AI character ("Da Fei Yu", a community-created persona based on the DeepSeek whale logo, unofficial) inside a WeChat group. The project uses a brain–hand split architecture: all inference and decision-making live on a Linux server you own, while a Windows endpoint sends and receives messages through UI automation of the official WeChat PC client. No process injection, no unofficial protocols, no client modification.

> **Project status**: This is a learning artifact and an engineering field report, not a production-ready solution. The authors consider the approach operationally demanding and of limited long-term viability. Please read "Positioning and Limitations" below in full before use.

## Contents

- [Architecture](#architecture)
- [Positioning and Limitations](#positioning-and-limitations)
- [Features](#features)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Risks and Acceptable Use](#risks-and-acceptable-use)
- [Attribution and License](#attribution-and-license)

## Architecture

```
┌─────────────────────────────┐         ┌──────────────────────────┐
│  Linux server (brain)       │         │  Windows machine (hand)  │
│  brain/  FastAPI + DeepSeek │ ◄HTTPS► │  hand/  wxauto poller    │
│  · persona + slang lexicon  │   key   │  · official WeChat PC    │
│  · active-period decision   │         │  · no injection/protocol │
│  · memory + chat logs       │         │  · UI automation only    │
│  · scheduled messages       │         │                          │
└─────────────────────────────┘         └──────────────────────────┘
```

Rationale: automating a personal WeChat account offers only three technical routes—protocol emulation, client injection, and UI automation. The first two face ongoing platform enforcement and legal pressure, with multiple public precedents of takedowns and bans. UI automation never touches client internals and is the lowest-risk option, at the cost of requiring a live Windows desktop session. The project therefore concentrates all computation and state on the server, reducing the Windows endpoint to a stateless dumb terminal and lowering the cost of recovery from any single-point failure.

## Positioning and Limitations

This section states the boundaries of what the project is, and forms an integral part of its documentation.

**Demanding deployment requirements.** A full setup requires:

1. A continuously running Windows machine (physical or cloud desktop) dedicated to the WeChat client;
2. A secondary WeChat account whose mobile session must remain permanently signed in (spare device or OS-level app cloning); switching accounts on the phone invalidates every other session;
3. A WeChat client version pinned to the range supported by the automation library, with auto-update disabled.

**Limited outlook.** Personal-account WeChat automation is a steadily shrinking space: the official API currently covers only private chats; multiple third-party protocol implementations have been discontinued under platform pressure; and UI automation depends on the client's interface structure, which any WeChat update may break. This project makes no guarantee of long-term viability.

**The reply logic is a basic implementation.** Specifically:

- Utterance decisions use a single-pass LLM judgment, without a cheap pre-filter and generation two-stage structure;
- No retrieval augmentation, no tool use, no image understanding (images and stickers are represented as placeholder text);
- Long-term memory is a periodic rolling summary, not retriever-based memory;
- All probabilities and thresholds (wake probability 0.05, 25-second interjection interval, etc.) are heuristic values, not systematically tuned;
- Personality is driven entirely by prompt engineering, with no model fine-tuning.

**Value.** A runnable, fully annotated reference implementation that documents its own defects honestly. It suits developers who want to understand the engineering difficulty of group-chat AI, users running a small private group for fun, and anyone who wants to build on top of it.

## Features

| Feature | Description |
|---|---|
| Persona system | Community-authored character card with an internet slang lexicon; replaceable as files |
| Group triggers | Replies when named; quoting the bot's past message counts as a follow-up (no @ needed); responds to being called by name alone |
| Memory | Periodic per-group summaries of "recent topics + member impressions", injected into subsequent dialogue |
| Proactive speech | Active-period model: after being woken, an LLM judges each incoming message; consecutive "skip" verdicts exit the active state |
| Self-awareness | The model sees its own past utterances (avoiding repetition) and honestly declares media it cannot parse |
| Output shaping | Double-parenthesized text is treated as a draft and stripped; meta-narrative sentences removed; overlong replies auto-compressed |
| Scheduled messages | Fixed daily messages (morning greeting, bedtime reminder) |
| Chat logs | Persistent per-chat, per-date records (JSONL) with a query API |
| Safeguards | Daily utterance cap, minimum proactive-speech interval, shared-key API authentication |

## Quick Start

Prerequisites: one Linux server (Docker), one Windows machine, one secondary WeChat account, one DeepSeek API key.

```bash
# Server (brain)
cd brain
FISH_KEY=$(openssl rand -hex 24) DEEPSEEK_API_KEY=sk-xxx docker compose up -d
# Expose via HTTPS reverse proxy; see docs/deploy-server.md

# Windows (hand)
pip install -r hand/requirements.txt
cp hand/config.example.json hand/config.json   # fill in brain_url / fish_key / group names
python hand/fish_hand.py
```

## Documentation

Deployment and configuration guides are currently maintained in Chinese:

- [Server-side deployment](docs/deploy-server.md)
- [Windows-side deployment](docs/deploy-windows.md)
- [Configuration reference](docs/config.md)
- [Troubleshooting](docs/troubleshooting.md)

## Risks and Acceptable Use

- WeChat's terms of service do not permit unauthorized automation. UI automation is the least intrusive of the available routes, but the risk is not zero. Use a secondary account and keep utterance frequency moderate.
- Use only with accounts, conversations, and data you are authorized to access. Do not use for marketing, bulk messaging, harassment, or unauthorized data collection.
- Group content is sent to a third-party model provider. Inform group members that an AI participant is present.
- The free tier of the wxauto dependency currently supports WeChat PC ≤ 4.1.8.107. Disable the client's auto-update immediately after installation.

## Attribution and License

- Code: [MIT](LICENSE)
- The persona card and slang lexicon are adapted works; see [NOTICE](NOTICE) for provenance
- This project is not affiliated with, endorsed by, or authorized by DeepSeek or Tencent
