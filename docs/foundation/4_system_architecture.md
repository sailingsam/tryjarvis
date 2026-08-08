# Mantrin

# System Architecture

> This document is in two parts on purpose.
>
> **Part One** is the architecture that exists — shipped, running,
> `pip install mantrin`.
>
> **Part Two** is where it goes as devices are added.
>
> Mixing the two is how docs start lying.

------------------------------------------------------------------------

# Core Principle

**One Brain. Many Runtimes.**

Devices are interfaces. Intelligence is singular.

Adding a device must never mean adding an assistant.

------------------------------------------------------------------------

# Part One — The Architecture Today

One device (a Linux laptop), one process that never sleeps, and a desktop
that can always see what the ears are doing.

                          "hey jarvis"
                               │
        ┌── desktop session ───────────────────────────┐
        │   tray icon (own process, GTK)               │
        │   reads state.json · drops the mute flag     │
        └──────────────────────────────────────────────┘
                               │  files, not protocol
        ┌── the daemon (systemd user service) ─────────┐
        │                                              │
        │   VOICE PIPELINE                             │
        │   mic → echo cancel → endpointing → wake gate│
        │       → STT ─┐            ┌─ TTS → speaker   │
        │              ▼            │                  │
        │   BRAIN ── reply pass ────┘                  │
        │        └─ extract pass (background)          │
        │                                              │
        │   MEMORY (SQLite)     TOOLS                  │
        │   facts · directives  WhatsApp · web · X     │
        │   commitments         any MCP server         │
        │   exchanges           consent gate           │
        └──────────────────────────────────────────────┘

------------------------------------------------------------------------

## The daemon

Everything lives in one always-on process, installed as a systemd user
service: starts at login, restarts on a crash, survives reboots.

Why one process:

-   Connections must stay warm. WhatsApp captures messages around the
    clock; two processes would mean two clients on one set of
    credentials, which kills the session for both.
-   The microphone needs exactly one owner.
-   Everything else — the CLI, text mode — is a thin client on a Unix
    socket, talking to the same brain.

------------------------------------------------------------------------

## The voice pipeline

The pipeline exists to answer one question honestly: **when is audio
allowed to become text?**

-   The wake word runs locally. Until it fires, frames are dropped —
    nothing is transcribed, stored, or sent.
-   Endpointing (VAD) decides when you finished talking. No button, no
    time limit. A dangling "his name was ummm…" is waited out, not cut.
-   Barge-in: speak over Mantrin and it stops, like a person.
-   Echo cancellation (WebRTC AEC via PipeWire) lives exactly as long as
    the mic does. Mute from the tray and the recorder process dies — the
    OS mic light goes out because nothing is capturing. Trust is
    OS-verifiable, not claimed.
-   The gate is also the cost boundary: a `transcribed_seconds` counter
    shows exactly how much audio ever reached the recogniser.

------------------------------------------------------------------------

## The brain

Two passes per turn, deliberately separate:

**Reply pass** — answer naturally, using tools when they help. It sees a
window of recent exchanges, the most relevant remembered facts, every
standing directive, and anything from the archive that looks related.

**Extract pass** — a background call that decides what was worth
keeping: new facts, new directives, commitments opened or closed, old
entries now contradicted.

The user never waits on bookkeeping, and the conversation never ships
its whole life story: the working window stays small forever, and older
exchanges come back by meaning when referred to.

The system prompt is split static/dynamic so the unchanging part is
cached by the provider. Simple turns run in under two seconds.

------------------------------------------------------------------------

## Memory

SQLite, on the user's disk. The one thing never rented.

Four kinds of knowledge, each stamped with where it came from:

-   **Facts** — stable truths ("User is vegetarian")
-   **Directives** — standing orders to the assistant ("keep replies
    short"), injected into every turn
-   **Commitments** — open loops that still need to happen
-   **Exchanges** — the conversation itself, archived out of the window,
    searchable by meaning

Recall fuses keyword search (FTS5) with local embeddings.

Memory does not merely grow: a contradicted fact is **superseded** —
out of recall, kept on disk with its provenance. An append-only memory
eventually argues with its own user.

------------------------------------------------------------------------

## Tools and consent

Real actions — WhatsApp, web search, X, and any MCP server the user
plugs in — share one registry.

Anything irreversible sits behind a consent gate:

-   the model phrases the confirmation in human terms (names, quoted
    content — never a 14-digit id),
-   a small model judges the answer by **intent**, not keywords —
    "no, I said yes" sends; "yes, but change it first" does not,
-   when unsure, it re-asks. A wrong send cannot be unsent; a re-ask
    costs two seconds.

------------------------------------------------------------------------

## Providers

Ears, voice, brain, embeddings — all rented, all behind one-method
interfaces, all swappable in setup: local Whisper or hosted ears, local
Piper or hosted voices.

Adding a provider is one class and one registry line.

Dependencies follow choices: nobody downloads a local model runtime for
a hosted provider they picked instead.

------------------------------------------------------------------------

## The tray

A separate process, on the system's own GTK — because the daemon may
outlive any desktop session, and the desktop may kill its ornaments
freely.

They meet at two files: `state.json` (daemon writes, tray reads) and the
mute flag (tray writes, voice loop reads). Files, not a protocol:
readable after either side dies, debuggable with `cat`, atomic by
rename.

Green means listening. Blue means mid-conversation. Grey means muted or
stopped — and muted means the device is *released*, witnessed by the
OS's own indicator.

------------------------------------------------------------------------

## Deliberately not here yet

-   **The event system and scheduler** — proactivity is the next build:
    reminders, the morning brief, the assistant that speaks first.
-   **A model router** — one model family serves today. A router earns
    its place when there is something real to route between.
-   **The Runtime split** — today the desktop runtime and the core are
    one process, because there is one device. The seam is drawn (the
    brain never touches the OS; io/, audio, tray are the only parts that
    do), and it splits when the second device arrives.

------------------------------------------------------------------------

# Part Two — Where It Goes

The laptop proves the brain. Then the brain leaves the laptop.

------------------------------------------------------------------------

## Runtimes

A Runtime adapts Mantrin to a platform. It knows everything about its
operating system; the Core knows nothing about operating systems.

    Android Runtime · Desktop Runtime · Wear Runtime · Car Runtime

Responsibilities:

-   Capture input (voice, text, notifications)
-   Expose the device's capabilities
-   Receive platform events
-   Handle permissions
-   Deliver responses

Business logic never belongs inside a Runtime.

------------------------------------------------------------------------

## One brain across devices

When the second device arrives, the Core becomes a service the Runtimes
share — the same memory, the same commitments, the same understanding,
reachable from every screen.

                      Mantrin Core

                Memory · Context · Planner · Learning

              /            |             \

        Android         Desktop          Wear
        Runtime         Runtime          Runtime

Continuity is the product: what you said at the desk is simply known in
your pocket.

------------------------------------------------------------------------

## Events

Proactivity thinks in events, not APIs:

    User spoke · Calendar updated · Reminder due · Flight delayed

An Event Filter removes noise before anything reaches the Core — a
battery percentage change is not a thought. Most events never require
AI. Filtering keeps the system fast, cheap, and privacy-friendly.

------------------------------------------------------------------------

## Model Router

When multiple model families genuinely serve, a router chooses by
quality, cost, latency, and availability.

Providers are replaceable.

Mantrin is not.

------------------------------------------------------------------------

## Capabilities

The Planner thinks in capabilities, not platforms:

    Call Person

Android: an intent. Desktop: a VoIP app. A future device: whatever is
native there. The capability stays the same.

------------------------------------------------------------------------

# Design Principles

-   One responsibility per component.
-   One brain across every device.
-   Context over raw data.
-   AI is the last step.
-   Tools execute; they do not think.
-   Models are replaceable.
-   Trust is non-negotiable — and OS-verifiable where possible.
-   Business logic never belongs inside a Runtime.

------------------------------------------------------------------------

# Success

If a future device is added, the architecture should not change.

Only a new Runtime should be written.

Everything else should already exist.

That is the definition of

**One Brain. Many Runtimes.**
