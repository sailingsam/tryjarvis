# Mantrin

# Mental Model

> Written before the first line of code, to answer one question — and kept
> because the answer survived contact with the code.

**What exactly is Jarvis?**

This document defines how we think about Jarvis. Every engineering
decision should align with this mental model.

------------------------------------------------------------------------

# Jarvis is NOT

Jarvis is **not**:

-   A chatbot
-   A voice assistant
-   A language model
-   An automation platform
-   A mobile application
-   A collection of AI APIs

Those are implementation details.

------------------------------------------------------------------------

# Jarvis IS

Jarvis is a **Personal Intelligence System**.

Its purpose is to understand a person's digital life, maintain the right
amount of context, and help them accomplish their goals with the least
amount of effort.

The product is **understanding**, not conversation.

------------------------------------------------------------------------

# Core Mental Model

Jarvis is a continuous intelligence loop.

    Capture Context
            ↓
    Remember
            ↓
    Understand
            ↓
    Reason
            ↓
    Plan
            ↓
    Act
            ↓
    Learn
            ↓
    Repeat

The loop never stops.

However, **AI models are not involved in every step.**

(Status: the loop runs today for user-initiated turns — voice in, memory,
tools, learning. What's not yet built is the loop *starting itself*:
events and the scheduler, i.e. proactivity. That is the next build.)

------------------------------------------------------------------------

# Step 1 --- Capture Context

Everything begins with context.

Not observation.

Jarvis is **not** constantly watching the user.

Instead, it maintains only the context necessary to help.

Context comes from three sources.

## 1. User initiated

The primary source.

Examples:

-   Voice
-   Text
-   Questions
-   Commands
-   Conversations

The user is always the strongest signal.

------------------------------------------------------------------------

## 2. Connected systems

Only systems the user explicitly connects.

Examples

-   Calendar
-   Contacts
-   Notifications
-   Location
-   Photos
-   Files

Jarvis should never assume access.

Permissions must be explicit.

------------------------------------------------------------------------

## 3. Current environment

The current task matters.

Examples

-   Current application
-   Current screen
-   Current conversation
-   Current device

Context is temporary.

It should expire naturally.

------------------------------------------------------------------------

## Principle

Jarvis should never collect information simply because it can.

It should only maintain context that makes future interactions easier.

------------------------------------------------------------------------

# Step 2 --- Remember

Not every event deserves memory.

Memory is selective.

Jarvis should remember:

-   People
-   Projects
-   Preferences
-   Goals
-   Relationships
-   Important conversations
-   Long-term facts

Memory is **not** chat history.

Memory is structured understanding.

------------------------------------------------------------------------

# Step 3 --- Understand

Facts alone are not useful.

Understanding comes from connecting facts.

Example

    Tanay

    ↓

    CEO

    ↓

    Worked together

    ↓

    Frequently contacted

    ↓

    Important relationship

Understanding is what makes Jarvis personal.

------------------------------------------------------------------------

# Step 4 --- Reason

Reasoning answers

"What does this mean?"

Reasoning should only happen when necessary.

Simple requests should not invoke expensive AI.

------------------------------------------------------------------------

# Step 5 --- Plan

Planning converts understanding into actions.

Possible outcomes:

-   Respond
-   Execute a tool
-   Ask a follow-up
-   Wait
-   Ignore

Planning should always choose the simplest solution.

------------------------------------------------------------------------

# Step 6 --- Act

Tools execute.

Examples

-   Call
-   Message
-   Calendar
-   Navigation
-   Browser
-   Files

Tools do **not** make Jarvis intelligent.

They allow intelligence to act.

------------------------------------------------------------------------

# Step 7 --- Learn

Every interaction improves future interactions.

Feedback updates:

-   Memory
-   Preferences
-   Relationships
-   Confidence

Learning should compound slowly.

------------------------------------------------------------------------

# AI is NOT the System

LLMs are components.

Speech models are components.

Vision models are components.

Voice models are components.

Jarvis remains the same even if every provider changes.

------------------------------------------------------------------------

# Context vs Memory

Context answers:

"What matters right now?"

Memory answers:

"What should never be forgotten?"

Context changes frequently.

Memory changes slowly.

------------------------------------------------------------------------

# Events

Jarvis thinks in events.

Not APIs.

Examples

-   User spoke
-   Calendar updated
-   Call ended
-   Reminder completed
-   Flight delayed

Events are filtered before entering the system.

Most events never require AI.

------------------------------------------------------------------------

# One Brain

Jarvis should have one brain.

Devices are merely interfaces.

            One Brain

          /    |     \

     Android Desktop Watch

The user should never feel like different devices have different
assistants.

------------------------------------------------------------------------

# Capabilities

Jarvis thinks in capabilities.

Not platforms.

Example:

    Call Person

Android:

Intent.

Desktop:

VoIP application.

Future device:

Native implementation.

The capability remains the same.

------------------------------------------------------------------------

# Trust

Trust comes before intelligence.

Jarvis should never surprise users with hidden knowledge.

The user should always understand why Jarvis knows something.

------------------------------------------------------------------------

# Success

The goal is not to answer more questions.

The goal is to reduce the number of questions the user needs to ask.

When the user feels

> "Jarvis already understands."

the system is succeeding.
