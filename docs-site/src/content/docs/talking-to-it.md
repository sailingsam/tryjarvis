---
title: Talking to Mantrin
description: Voice, push-to-talk, dictation, and swapping providers.
---

There is no button and no time limit by default: Mantrin works out that you
stopped talking by listening. Interrupt it mid-sentence and it stops, like a
person would. After it answers it keeps listening for a few seconds, so a
back-and-forth doesn't need the wake word every time.

```bash
mantrin      # say "hey jarvis"
```

## Push-to-talk

```bash
mantrin set-key    # press the key you want; hold it to talk
```

Hold your chosen key (any key — a Lenovo star key, F10, whatever your
keyboard has) and Mantrin listens; release it and the answer comes. The
release is the endpoint — no wake word, no waiting out your pauses, and a
press always interrupts a reply.

Three trigger modes (pick during `set-key`, or from the tray): wake word,
talk key, or both. In key-only mode the microphone device simply does not
exist between presses.

:::caution
Reading the keyboard needs your user in the `input` group (`set-key` offers
to add you; one logout applies it). That permission can see every key, so
`jarvis/hotkey.py` stays one short, verifiable file that matches a single
keycode and ignores the rest.
:::

## Type instead

```bash
mantrin --text        # keyboard in, text out
mantrin --dictate     # dictate with your own app, spoken reply
```

`--dictate` is for Wispr Flow's app, superwhisper, Willow and the rest. They
own the microphone and type into whatever has focus, so there is nothing to
integrate with — Mantrin reads the line and answers out loud.

## Swap providers

```bash
mantrin --stt grok --tts openai
mantrin --timings     # where each turn's time actually went
```

Settings live in `~/.config/mantrin/config.json` (mode `0600`, it holds
keys). Anything in the environment wins over what is saved there.

## Next

- [Connecting your accounts](/integrations/)
- [Commands](/reference/commands/)
