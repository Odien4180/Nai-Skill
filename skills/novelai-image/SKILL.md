---
name: novelai-image
description: Generate, transform, inpaint, reference, enhance, stream, and upscale images with NovelAI's official Image Generation API. Use for NovelAI text-to-image, img2img, masks, Vibe Transfer, Precise Reference, multi-character prompts, Director Tools, tag suggestions, and raw image API requests; not for the NovelAI web UI or text generation.
---

# NovelAI Image

Use the bundled standard-library client at `scripts/novelai_image.py`. It covers every image endpoint currently published by NovelAI and accepts complete raw request payloads so new parameters remain usable without changing the skill.

## Before a request

- Require `NOVELAI_API_TOKEN`. On Windows, the installer stores it in the machine environment so sandboxed agent accounts can read it directly even when the process did not inherit it. The previous `NovelAISkill:NOVELAI_API_TOKEN` Windows Credential Manager entry remains a legacy fallback for non-sandboxed runs. Never ask the user to paste a token into chat, put it in a command, print it, or save it in the workspace.
- Keep the base URL at `https://image.novelai.net`. Never send a real token to a custom host; the client blocks custom hosts unless `--allow-custom-host` is explicitly supplied for local/mock testing.
- Treat the user's prompt as the required human initiation. Never create unattended generation loops, scheduled generation, or load-amplifying retries; NovelAI's API documentation prohibits automated excessive generation.
- A generation may spend Anlas. Resolve material ambiguities before a paid call and state the final model, prompt summary, resolution, steps, guidance, and sample count. One explicit request authorizes one call, including its requested batch.
- Do not claim an exact charge unless it is returned by NovelAI. Do not perform a paid live call merely to test configuration.

## Resolve the generation brief

Preserve every explicit choice. Ask only about missing values that could materially change the image, compatibility, or cost; do not turn advanced settings into a questionnaire. When the host offers a choice UI, use it with the recommended option first and no more than three questions at once. Otherwise ask one compact question with clear alternatives.

Before generation, make sure these decisions are resolved:

- Operation and required inputs: text-to-image, img2img, inpaint/outpaint, Enhance, reference mode, Director Tool, or upscale. Inpaint requires both a source image and a mask.
- Model: default to NAI Diffusion 5 Full (`nai-diffusion-5-full`) when the user omits the model. Preserve any model the user explicitly selects. Verify the official identifier only when the user requests another model or the API rejects the default as unavailable.
- Prompt: obtain the subject and intended result. If the user gives only a broad idea, offer a faithful drafted prompt and let them choose whether to use or revise it.
- Composition: resolve aspect ratio or exact image size. Offer portrait, landscape, and square when the request does not imply one; validate the exact dimensions against the selected model before calling.
- Cost/behavior controls: resolve `n_samples`, `steps`, and guidance/`scale`. Recommend one image unless a batch was requested. Use current model guidance rather than treating one numeric preset as universal.
- Undesired Content: distinguish a current model/UI preset from custom negative text. If exclusions matter but are unspecified, offer the model-appropriate default/no custom exclusions or a concise custom option.
- Characters: when named or distinct characters matter, resolve count, appearance, role/action, and approximate placement. For V4+ structured prompts, keep scene-wide text in `base_caption` and character details in `char_captions`; ask whether coordinates/order should be enforced when placement matters.

Seed, sampler, schedule, quality toggles, and other advanced controls are optional. Ask about them only when reproducibility, comparison, or the user's stated visual goal makes them material. If the user explicitly says to choose for them, use conservative current defaults, disclose them, and proceed.

## Choose the operation

- Text-to-image, img2img, inpaint/outpaint, Enhance, multi-character prompting, Vibe Transfer, Precise Reference, ControlNet-compatible fields, and advanced sampling all use `generate` with a full request JSON file.
- Progressive generation uses `generate --stream`; preserve the SSE transcript.
- V4+ Vibe encoding uses `encode-vibe` before placing the returned encoding in a generation payload.
- Remove background, line art, sketch, colorize, emotion, and declutter use `augment`.
- Standalone enlargement uses `upscale`.
- Prompt autocomplete uses `suggest-tags`.
- Use `raw` for a newly published endpoint or response mode not yet given a convenience command.

For payload fields and examples, read [references/api.md](references/api.md). For prompting and model-selection behavior, read [references/prompting.md](references/prompting.md) only when the user wants prompt help or a model recommendation.

For inpaint/outpaint, read the inpaint section in [references/api.md](references/api.md) before building the request. Explain that this client sends the source image and mask to NovelAI; it does not paint a mask, perform Focused Inpainting crops, or composite the result locally.

## Local Prompt Chunks

NovelAI account Prompt Chunks cannot be read with a Persistent API Token. Each installed copy of this skill keeps its own local store at `cache/prompt-chunks.json` inside that skill directory. Use that default unless the user explicitly selects another file. The installer preserves an existing cache when updating the same installation. Do not create or modify the store until the user requests that mutation.

Manage the store with:

```text
python scripts/novelai_image.py chunks list
python scripts/novelai_image.py chunks get --name CharacterA
python scripts/novelai_image.py chunks set --name CharacterA --content-file chunk.txt
python scripts/novelai_image.py chunks delete --name CharacterA
python scripts/novelai_image.py chunks expand --text "!macro:CharacterA!, outdoors"
```

Names are case-sensitive. Chunks may contain nested `!macro:Name!` references. Missing names, invalid stores, and cycles are errors. Generation automatically uses the installed skill's default store; pass `--chunks-file PATH` only to override it. The client expands macros only in prompt/caption fields before file hydration and before a dry run. Always inspect the expanded dry-run payload for a complex or nested prompt.

## Build payloads safely

Keep generated artifacts inside the installed skill. Create request JSON under `cache/requests/`; relative `$file` paths resolve from that request file's directory, so prefer absolute source-image paths when the inputs live elsewhere. Any value written as `{"$file":"relative/or/absolute/path"}` is replaced recursively with that file's base64, which works for input images, masks, Vibe encodings, and reference-image arrays.

Unless the user explicitly requests another destination, omit output path arguments. The client creates a unique run directory under `cache/outputs/<operation>/` for generated images, manifests, streams, Vibe encodings, augmentations, upscales, and raw responses. The installer preserves the entire cache during updates.

Prefer the user's explicit model and parameters. When unspecified, consult the current official docs instead of assuming that the names or limits in the reference are still current. Keep unknown official fields intact; do not narrow a request to only familiar options.

Run a local validation before every generation call. This expands Prompt Chunks and rejects known schema type errors before a request can spend Anlas:

```text
python scripts/novelai_image.py generate --request cache/requests/request.json --dry-run
```

Then make exactly one live call after resolving validation errors. On 401, explain how to rerun the installer as administrator to update the machine token without displaying it. On 402, report insufficient Anlas. On 429 or 5xx, report the correlation ID and ask before retrying a request that may be billable.

## Deliver results

Save every returned image plus `manifest.json` in the automatic per-run cache directory unless the user explicitly requested another destination. Preserve seed/index metadata. For streaming, return the saved `.sse` transcript and any final artifact the response exposes. Show the resulting images with absolute paths when the host supports inline images, and summarize the model, seed, dimensions, and major settings used.

Official sources: [Image guide](https://docs.novelai.net/en/image/), [Image API schema](https://image.novelai.net/docs/index.html), and [Terms](https://novelai.net/terms).
