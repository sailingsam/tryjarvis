# Project Jarvis

# System Architecture

> This document defines the high-level architecture of Jarvis. It
> focuses on responsibilities and information flow, not implementation
> details.

------------------------------------------------------------------------

# Core Principle

Jarvis is **not** an Android application.

Jarvis is **not** a desktop application.

Jarvis is a **Personal Intelligence System**.

Applications are simply different interfaces into the same intelligence.

------------------------------------------------------------------------

# Architecture Overview

                     User
                       │
              Voice / Text / UI
                       │
                  Client Runtime
                       │
                Context Capture
                       │
                  Event Filter
                       │
                 Event Gateway
                       │
                ┌─────────────┐
                │ Jarvis Core │
                └─────────────┘
                       │
         ┌────────┬────────┬────────┐
         │        │        │        │
      Memory   Context   Planner  Learning
         │        │        │
         └────────┴────────┘
                       │
                 Model Router
                       │
             Tools / AI Providers
                       │
                  Runtime → User

------------------------------------------------------------------------

# Three Layers

## 1. Runtime Layer

A Runtime adapts Jarvis to a specific platform.

Examples

-   Android Runtime
-   Desktop Runtime
-   Wear Runtime
-   Car Runtime

A Runtime knows everything about its operating system.

Jarvis Core knows nothing about operating systems.

Responsibilities

-   Capture user input
-   Expose device capabilities
-   Receive platform events
-   Handle permissions
-   Deliver responses

------------------------------------------------------------------------

## 2. Jarvis Core

The Core is platform independent.

It should run unchanged regardless of whether the client is Android,
Desktop or a future device.

The Core has four responsibilities.

### Memory

Stores long-term knowledge.

People.

Projects.

Preferences.

Goals.

Relationships.

Habits.

------------------------------------------------------------------------

### Context

Represents what matters **right now**.

Current task.

Current device.

Current application.

Current conversation.

Current location (if available).

Context is temporary.

------------------------------------------------------------------------

### Planner

Transforms understanding into decisions.

Possible outcomes

-   Reply
-   Ask a question
-   Execute a tool
-   Wait
-   Ignore

The Planner always prefers deterministic execution before AI reasoning.

------------------------------------------------------------------------

### Learning

Updates memory after every completed interaction.

Learning compounds over time.

------------------------------------------------------------------------

## 3. Execution Layer

The execution layer connects Jarvis to external intelligence and
external systems.

### Model Router

Chooses the best provider based on

-   Quality
-   Cost
-   Latency
-   Availability

Providers are replaceable.

Jarvis is not.

------------------------------------------------------------------------

### Tool Layer

Tools expose capabilities.

Examples

-   Call Person
-   Send Message
-   Calendar
-   Browser
-   Files
-   Navigation
-   Music

The Planner thinks in capabilities.

Each Runtime implements those capabilities differently.

------------------------------------------------------------------------

# Information Lifecycle

Every interaction follows the same lifecycle.

    User

    ↓

    Runtime

    ↓

    Context Capture

    ↓

    Event Filter

    ↓

    Event Gateway

    ↓

    Memory

    ↓

    Context

    ↓

    Planner

    ↓

    Need AI?

    ├── No
    │     ↓
    │  Execute Tool
    │
    └── Yes
          ↓
     Model Router
          ↓
     Execute Tool (if needed)

    ↓

    Update Memory

    ↓

    Return Response

------------------------------------------------------------------------

# Context Capture

Context is collected only from sources the user explicitly provides.

Examples

-   Voice
-   Text
-   Calendar
-   Contacts
-   Notifications
-   Location
-   Current application

Jarvis does not collect data simply because it can.

It captures only the context required to help.

------------------------------------------------------------------------

# Event Filter

Every operating system produces thousands of events.

Most are irrelevant.

The Event Filter removes noise before information reaches Jarvis Core.

Examples to ignore

-   Battery changed from 98% to 97%
-   Random app notifications
-   Background system broadcasts

Examples to keep

-   User interaction
-   Calendar changes
-   Reminder completed
-   Important notifications
-   Explicit commands

Filtering keeps the system fast, cheap and privacy-friendly.

------------------------------------------------------------------------

# Design Principles

-   One responsibility per component.
-   One brain across every device.
-   Context over raw data.
-   AI is the last step.
-   Tools execute; they do not think.
-   Models are replaceable.
-   Trust is non-negotiable.
-   Business logic never belongs inside a Runtime.

------------------------------------------------------------------------

# Scaling

Adding a new platform should only require a new Runtime.

The Core should remain unchanged.

                  Jarvis Core

            Memory
            Context
            Planner
            Learning

          /      |       \

     Android   Desktop   Wear
     Runtime   Runtime   Runtime

------------------------------------------------------------------------

# Success

If a future device is added, the architecture should not change.

Only a new Runtime should be written.

Everything else should already exist.

That is the definition of

**One Brain. Many Runtimes.**
