"""Run the fw-ai cookbook "Muse Glimmer First Fine-Tune" recipe (Serverless Training, local chat JSONL, no dataset
upload) on IMAGE examples.

The recipe as shipped builds its renderer without an image processor, so image content parts fail with
"Muse Glimmer image content requires an image processor". The renderer itself supports images; this wrapper only
injects ``MuseGlimmerImageTokenCounter`` (the cookbook's own processor-config-backed counter) into
``get_renderer`` and then runs the unmodified recipe with the same command-line arguments.

Runs in the Fireworks training venv (requirements-fireworks-training.txt) from the cookbook's ``training/`` folder:

    cd <cookbook>/training
    PYTHONPATH=<cookbook> G:\walkdown-data\venv-fwtrain\Scripts\python.exe <repo>/benchmark/fw_glimmer_sft.py prepare --file data.jsonl
"""

from __future__ import annotations

import sys


def main() -> int:
    import training.renderer as renderer_pkg
    from training.renderer.muse_glimmer import MuseGlimmerImageTokenCounter

    from examples.sft import muse_glimmer_starter as starter

    original = renderer_pkg.get_renderer
    counter = MuseGlimmerImageTokenCounter.from_pretrained(starter.TOKENIZER_MODEL)

    def get_renderer(name, tokenizer, image_processor=None, model_name=None):
        return original(name, tokenizer, image_processor=image_processor or counter, model_name=model_name)

    renderer_pkg.get_renderer = get_renderer
    return starter.main()


if __name__ == "__main__":
    sys.exit(main())
