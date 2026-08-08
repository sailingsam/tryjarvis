# Mantrin

## Vision

> *"Everyone deserves a chief of staff — your personal Jarvis."*

(Mantrin is the company and the product. Jarvis is the persona — the name it
answers to. The dual naming is deliberate; these docs use both.)

---

## Why this exists

Computers have become incredibly powerful.

AI models have become incredibly intelligent.

Yet interacting with software still feels fragmented.

We unlock our phones.

Open an app.

Type a prompt.

Explain the same context again.

Wait for an answer.

Repeat.

Today's AI is intelligent, but it isn't truly personal.

Every conversation starts from scratch.

Every application knows only a tiny part of our lives.

Your calendar doesn't know your goals.

Your notes don't know your projects.

Your email doesn't know your priorities.

Your phone doesn't know what you're trying to achieve.

And every AI assistant behaves like you've just met.

We believe this is the wrong direction.

---

## The Dream

When we were kids, many of us watched Iron Man and imagined what it would be like to have Jarvis.

Not because Jarvis could answer questions.

But because Jarvis understood Tony.

It remembered.

It observed.

It anticipated.

It took action.

Tony never explained everything from the beginning.

Jarvis already knew.

That vision has stayed with us for years.

Today, for the first time, advances in AI make building something close to that vision technically possible.

---

## Our Belief

The future is not another chatbot.

The future is a personal intelligence.

One that understands who you are.

What you're working on.

Who matters to you.

What your goals are.

What you're trying to accomplish.

And how it can help with less effort and less repetition.

---

## What We Are Building

We are building a Personal AI Operating System.

Not an app.

Not another assistant.

Not another AI wrapper.

A system that continuously learns, remembers, understands, and acts.

It should feel less like software and more like a trusted companion.

---

## The Big Idea

> *Don't connect the apps. Connect the devices.*

Plenty of platforms already connect apps.

Automation tools chain them.

Agent frameworks wrap their APIs.

That race is crowded, and it misses the point.

Your life doesn't happen in apps.

It happens across devices.

Laptop at work.

Phone in your pocket.

Car on the commute.

A watch, a speaker, a home.

Each one currently has its own assistant, its own context, its own amnesia.

Mantrin's bet is a **continuous intelligence layer across the devices
themselves** — one brain that follows you, so the context you built on one
screen is simply *there* on the next.

Apps are plumbing. Devices are where you live.

---

## Our Principles

### Context over conversations

The most valuable thing an AI can have isn't a larger model.

It's a deeper understanding of the person using it.

Context compounds.

Every interaction should make the system more useful.

---

### Intelligence is replaceable

Better language models will continue to appear.

Better speech models will appear.

Better vision models will appear.

We won't compete by building foundational models.

We'll compete by building the best experience on top of them.

Models evolve.

Your digital identity shouldn't.

---

### One brain, many interfaces

Your phone.

Your laptop.

Your watch.

Your home.

Your car.

These shouldn't each have a different assistant.

They should all share one intelligence.

One memory.

One understanding of you.

The interface changes.

The brain stays the same.

---

### Proactive, not reactive

Today's assistants wait for instructions.

We want an assistant that understands when it should help.

Not by interrupting constantly.

But by acting when context makes it valuable.

The goal isn't more notifications.

The goal is fewer things to remember.

---

### Human-first technology

People shouldn't adapt to software.

Software should adapt to people.

Technology should disappear into the background.

The experience should feel natural.

Voice should feel like talking.

Memory should feel effortless.

Automation should feel invisible.

---

## Why Laptop First

We originally assumed mobile first. Building taught us otherwise.

A cross-device brain has to exist somewhere first — and the laptop is the
only device that lets an always-on assistant actually be *always on*:

* the microphone can stay open, with a local wake word guarding it
* the OS lets a daemon live forever (systemd) — phones kill background apps
* connections (WhatsApp, calendar, tools) can stay warm around the clock
* the people who try software at this stage live in a terminal anyway
* everything can run locally, which is where trust starts

So the laptop is the beachhead: prove the brain, the memory and the trust
model on the most permissive device.

The phone comes next — and that is the moment the real product appears,
because the second device is where **continuity** becomes visible: what you
said at the desk is simply known in your pocket.

Laptop is the first interface.

Not the final one.

---

## Long-Term Vision

Eventually, this won't feel like an application.

It will feel like a presence.

Something that is always available.

Always learning.

Always improving.

Always working in your best interest.

Not because it is told to.

But because it understands enough to know when it should help.

---

## Success

We'll know we've succeeded when people stop thinking:

> "I need to ask my AI."

And instead think:

> "My AI already knows."

That is the future we're building.

One where software finally understands the person using it.

One where everyone has their own Jarvis.

---

## What We Are Not Building

Mantrin is not:

- A ChatGPT competitor
- An app-integration platform
- An MCP wrapper
- An AI coding assistant
- A smart home platform
- A search engine
- A productivity app
- A voice clone

These may become capabilities.

They are not the product.

The product is one intelligence that follows you across your devices,
understands your context, and acts before you have to ask.

---

## Where We Are

Honesty is part of the design, so the docs say it plainly.

**Built and running today** (Linux, `pip install mantrin`): the always-on
voice daemon, wake word and endpointing, cross-session memory with
supersession, real actions (WhatsApp and any MCP tool) behind a consent
gate, swappable ears/voice/brain, the tray with an OS-verifiable mute.

**Next**: proactivity — the scheduler, reminders, the morning brief; the
assistant that speaks first. Then the phone, where continuity begins.

**Vision**: car, wearables, home — the same one brain, everywhere.