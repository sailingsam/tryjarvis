# Training a custom wake word ("Mantrin", "Jarvis", or anything else)

Mantrin's wake gate runs [openWakeWord](https://github.com/dscripka/openWakeWord)
models locally. It ships pretrained phrases (`hey_jarvis` is the default), and
it will happily run models you train yourself — say, plain **"Mantrin"** and
**"Jarvis"**.

Training doesn't need your voice or a dataset: openWakeWord generates
thousands of synthetic voices saying your phrase and trains on those. It needs
a GPU for about an hour, which Google Colab provides for free.

## Train (once per phrase, ~1 hour, free)

1. Open the official training notebook in Colab:
   [notebooks/automatic_model_training.ipynb](https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb)
   (Runtime → Change runtime type → **GPU**.)
2. In the config cell, set the phrase — one word is fine:
   `target_phrase: "mantrin"` (train a second model with `"jarvis"` if you
   want both names to work).
3. Run all cells. It synthesizes samples, augments them with noise, trains,
   and hands you a small model file: `mantrin.onnx` (or `.tflite`).
4. Download the file.

## Install

Drop the file where Mantrin looks for custom models:

```bash
mkdir -p ~/.config/mantrin/wake
mv ~/Downloads/mantrin.onnx ~/.config/mantrin/wake/
```

The filename is the phrase — `mantrin.onnx` becomes the wake phrase
`mantrin`. Then pick it:

```bash
mantrin setup        # the wake-word menu now lists "mantrin"
```

To answer to **several** names at once, type them comma-separated at the
wake-word prompt — `mantrin, jarvis` — or set it directly:

```bash
export MANTRIN_WAKE_WORD="mantrin,jarvis"    # or via mantrin setup
mantrin restart
```

All phrases run in a single model pass, so two names cost the same CPU as
one.

## Tuning

- **Misses your voice?** Retrain with more samples (`n_samples` in the
  notebook config), or lower the gate's threshold — it defaults to `0.5` in
  `jarvis/wake.py`.
- **Fires on TV/similar words?** Raise the threshold, or retrain with the
  similar-sounding words added as adversarial negatives (the notebook has a
  field for this).
- A custom model with the same name as a pretrained one (e.g. your own
  `hey_jarvis.onnx`) wins — training a better version of a stock phrase is a
  drop-in upgrade.
