# NovelAI Image API reference

This reference reflects NovelAI's official Swagger schema checked on 2026-09-16. The API is versioned in place, so preserve unfamiliar fields and re-check the live schema when exact current limits or model identifiers matter.

## Client commands

```text
python scripts/novelai_image.py generate --request cache/requests/request.json
python scripts/novelai_image.py generate --request cache/requests/request.json --stream
python scripts/novelai_image.py encode-vibe --request cache/requests/vibe.json
python scripts/novelai_image.py augment --request cache/requests/director.json
python scripts/novelai_image.py upscale --request cache/requests/upscale.json
python scripts/novelai_image.py suggest-tags --model MODEL --prompt "blue hai" --lang en
python scripts/novelai_image.py models
python scripts/novelai_image.py raw --method POST --path /ai/new-endpoint --request cache/requests/body.json
python scripts/novelai_image.py chunks list
```

All commands accept `--base-url`, but a non-official host additionally requires `--allow-custom-host` and is intended only for local/mock tests. Never send a real token to a custom host. On Windows, authenticated commands first read the generic credential `NovelAISkill:NOVELAI_API_TOKEN` from Windows Credential Manager. The environment variable named by `--token-env` (default `NOVELAI_API_TOKEN`) is a fallback; specifying a custom `--token-env` bypasses Credential Manager. `generate`, `encode-vibe`, `augment`, `upscale`, and `raw` accept recursive `{"$file":"path"}` values. Use `--dry-run` to expand and summarize a request without sending it.

## Published endpoints

| Command | Method and path | Response |
|---|---|---|
| `generate` | `POST /ai/generate-image` | JSON base64 images by default |
| `generate --stream` | `POST /ai/generate-image-stream` | Server-sent events |
| `encode-vibe` | `POST /ai/encode-vibe` | Binary Vibe encoding |
| `augment` | `POST /ai/augment-image` | ZIP of output images |
| `upscale` | `POST /ai/upscale` | JSON base64 images by default |
| `suggest-tags` | `GET /ai/generate-image/suggest-tags` | JSON tags |
| `models` | `GET /oa/v1/models` | JSON model list exposed by the service |

Authorization is `Authorization: Bearer <persistent API token>`. The client adds `Bearer` if absent and sends a six-character `x-correlation-id`.

When no explicit output path is supplied, artifacts are written to a unique directory under the installed skill's `cache/outputs/<operation>/`. Request JSON belongs under `cache/requests/`. Explicit `--output-dir` and `--output` still override these defaults when the user asks for another destination.

Before either a dry run or live request, the client validates known parameter types from the published schema. In particular, `tag_hint_qt`, `tag_hint_uc_preset`, and `ucPreset` are integers, while `tag_hint_transparent_background` and `straight_alpha` are booleans. JSON booleans are not accepted for integer hint fields. `qualityToggle` remains a separate boolean field.

## Local Prompt Chunks

The client uses a per-installation local store at `cache/prompt-chunks.json` because NovelAI's account-side client settings do not accept Persistent API Tokens. `--file PATH` overrides the store for a `chunks` command. The file format is:

```json
{
  "version": 1,
  "chunks": {
    "CharacterA": "1girl, red hair, green eyes,",
    "CafeScene": "!macro:CharacterA!, sitting in a cafe,"
  }
}
```

Use `chunks list|get|set|delete|expand` to manage it. Generation automatically loads the installed skill's store when it exists or when a prompt contains a macro. Use `--chunks-file PATH` only to override the default. Case-sensitive `!macro:Name!` references expand in `input`, prompt, negative-prompt, and structured caption fields. Expansion rejects missing chunks, malformed stores, cycles, and nesting deeper than 64 levels. It never expands image data or `$file` paths.

## Generation envelope

Generation requests use the canonical JSON Schema in
[`generate-request.schema.json`](generate-request.schema.json). It mirrors the
field types published by the live Swagger and adds the V4+ invariants needed by
the current model families. The client requires
`input`, `parameters.prompt`, and the V4/V5 positive `base_caption` to be
identical. Negative prompt copies must also match. Character-only details
belong in `char_captions`; when `use_coords` is true, every character needs a
normalized `{x, y}` center. A dry run rejects drift before a paid request.
When `model` is omitted, the client inserts the default
`nai-diffusion-5-full`; an explicitly supplied model is never overwritten.
V4, V4.5, and V5 canonical requests use `params_version: 4` plus both
`v4_prompt` and `v4_negative_prompt`.

```json
{
  "action": "generate",
  "input": "1girl, red hair, cinematic lighting",
  "model": "nai-diffusion-5-full",
  "parameters": {
    "params_version": 4,
    "prompt": "1girl, red hair, cinematic lighting",
    "negative_prompt": "lowres, blurry",
    "width": 832,
    "height": 1216,
    "steps": 28,
    "scale": 5.5,
    "sampler": "k_euler_ancestral",
    "noise_schedule": "karras",
    "seed": 123456789,
    "n_samples": 1,
    "qualityToggle": true,
    "ucPreset": 0,
    "cfg_rescale": 0,
    "image_format": "png",
    "v4_prompt": {
      "caption": {
        "base_caption": "1girl, red hair, cinematic lighting",
        "char_captions": []
      },
      "use_coords": false,
      "use_order": true
    },
    "v4_negative_prompt": {
      "caption": {
        "base_caption": "lowres, blurry",
        "char_captions": []
      },
      "use_coords": false,
      "use_order": true,
      "legacy_uc": false
    }
  }
}
```

Do not treat this as a fixed preset. `model`, defaults, valid resolutions, samplers, schedules, and limits may change. `input` and `parameters.prompt` are both used by current clients; keep them synchronized unless reproducing a known payload.

The official `parameters` schema currently publishes:

`add_original_image`, `cfg_rescale`, `color_correct`, `controlnet_condition`, `controlnet_model`, `controlnet_strength`, `deliberate_euler_ancestral_bug`, `director_reference_descriptions`, `director_reference_images`, `director_reference_information_extracted`, `director_reference_secondary_strength_values`, `director_reference_strength_values`, `dynamic_thresholding`, `extra_noise_seed`, `height`, `image`, `image_format`, `img2img`, `legacy`, `legacy_v3_extend`, `mask`, `n_samples`, `negative_prompt`, `noise`, `noise_schedule`, `params_version`, `prefer_brownian`, `prompt`, `qualityToggle`, `reference_image`, `reference_image_multiple`, `reference_information_extracted`, `reference_information_extracted_multiple`, `reference_strength`, `reference_strength_multiple`, `sampler`, `scale`, `seed`, `skip_cfg_above_sigma`, `sm`, `sm_dyn`, `steps`, `straight_alpha`, `stream`, `strength`, `tag_hint_qt`, `tag_hint_transparent_background`, `tag_hint_uc_preset`, `ucPreset`, `upscale`, `upscaled_enhance`, `v4_negative_prompt`, `v4_prompt`, and `width`.

## Alpha Transparency

Official image documentation limits true alpha transparency to V5. The UI's
Transparent BG toggle adds `transparent background` to the prompt. Swagger
describes `tag_hint_transparent_background` as a pass-through hint that the
server does not interpret, so the hint is not a replacement for that tag.

A canonical transparent request therefore requires all of the following:

- A V5 model such as `nai-diffusion-5-full`.
- `transparent background`, `has alpha`, or `alpha transparency` in `input`,
  `parameters.prompt`, and `v4_prompt.caption.base_caption`.
- `tag_hint_transparent_background: true` and `straight_alpha: true`.
- `image_format: "png"`.
- `params_version: 4` and synchronized V4+ structured prompts.

Do not carry these alpha fields into a V4/V4.5 comparison request. Those model
families do not support true alpha output.

## Input-image modes

For img2img, add base64 `parameters.image`, plus `strength`, `noise`, and optionally `extra_noise_seed` and `color_correct`.

For inpaint/outpaint, provide `parameters.image` and `parameters.mask` as lossless files of identical pixel dimensions. A practical file-backed request uses:

```json
{
  "action": "infill",
  "input": "replace the masked area with a red scarf",
  "model": "VERIFIED_MODEL_API_NAME",
  "parameters": {
    "image": {"$file": "source.png"},
    "mask": {"$file": "mask.png"},
    "width": 832,
    "height": 1216,
    "prompt": "replace the masked area with a red scarf",
    "negative_prompt": "blurry, malformed",
    "img2img": {
      "strength": 1,
      "noise": 0,
      "color_correct": true
    }
  }
}
```

Verify the current site/API payload for the selected model before using the example's `action` or defaults; the published schema leaves `action` open-ended. The current schema exposes this nested inpaint-specific object:

```json
"img2img": {
  "strength": 0.7,
  "noise": 0,
  "extra_noise_seed": 123,
  "color_correct": true
}
```

The mask selects the area NovelAI may regenerate; unmasked pixels are intended to remain unchanged. Prompt for what should appear inside the selected region. V4+ supports adjustable Inpainting Strength: lower values preserve more of the source beneath the mask, while `1` lets the prompt dictate the replacement more strongly. The API performs the diffusion edit and returns the result. This client only validates/expands the payload and base64-encodes files; it does not draw masks, crop/upscale a Focused Inpainting region, synthesize context borders, or composite patches locally. Focused Inpainting therefore requires the caller to prepare the crop/context workflow or reproduce the current site payload explicitly.

For outpainting, first extend the source canvas, mask the newly empty region, and keep the source and mask dimensions aligned. When mask polarity or alpha interpretation is uncertain, validate it against a small non-billable local inspection or the current official guide rather than guessing from black/white appearance alone.

Enhance is a generation request built around an input image; preserve the originating metadata where possible and use `upscaled_enhance`, `upscale.declared_blur_sigma`, and/or the current site payload appropriate to the chosen model. Standalone `upscale` is a separate endpoint and has no generation prompt.

## Vibe Transfer

Encode request:

```json
{
  "image": {"$file": "reference.png"},
  "model": "MODEL_API_NAME",
  "information_extracted": 1,
  "mask": {"$file": "optional-mask.png"},
  "crop_to_mask": false,
  "info_extract_seed": 123,
  "focus_seed": 456
}
```

Only `image`, `model`, and the intended extraction value are normally needed. Omit either seed to let the service choose its recommended deterministic seed. Put the returned encoding in `reference_image` or `reference_image_multiple`; align the strength and information arrays by index. The official UI supports up to 16 Vibes, but current costs and model compatibility must be checked before a paid call.

## V4+ structured and multi-character prompts

`v4_prompt` and `v4_negative_prompt` use:

```json
{
  "caption": {
    "base_caption": "two characters in a cafe",
    "char_captions": [
      {"char_caption": "1girl, red hair", "centers": [{"x": 0.3, "y": 0.5}]},
      {"char_caption": "1boy, black hair", "centers": [{"x": 0.7, "y": 0.5}]}
    ]
  },
  "use_coords": true,
  "use_order": true,
  "legacy_uc": false
}
```

Coordinates are normalized numbers. Use the same outer shape for negative structured prompts, with only the captions that are actually unwanted.

## Precise Reference

Use aligned arrays:

- `director_reference_images`: base64 images.
- `director_reference_descriptions`: V4 condition objects; `caption.base_caption` is `character`, `style`, or `character&style` as supported by the current model. The official schema explicitly documents `character` and `character&style`.
- `director_reference_strength_values`: reference strength.
- `director_reference_secondary_strength_values`: Fidelity.
- `director_reference_information_extracted`: extraction values where applicable.

The official guide says Precise Reference works with inpainting and is currently incompatible with Vibe Transfer. Do not combine them unless current documentation says that limitation has changed.

## Director Tools

```json
{
  "req_type": "lineart",
  "image": {"$file": "input.png"},
  "width": 1024,
  "height": 1024,
  "prompt": "optional tool-specific prompt",
  "defry": 0
}
```

Known request types are `bg-removal`, `lineart`, `sketch`, `colorize`, `emotion`, and `declutter`. `prompt` and `defry` are tool-specific (notably colorize and emotion). Width and height must describe the source image. The API schema intentionally leaves `req_type` open, so pass a newly documented value unchanged.

## Upscale and suggestions

Upscale request:

```json
{
  "image": {"$file": "input.png"},
  "model": "MODEL_API_NAME",
  "declared_blur_sigma": 0.3
}
```

The schema documents blur sigma values `0.0`, `0.30`, `0.35`, `0.40`, `0.45`, and `0.50`. Tag suggestions require `model` and the incomplete `prompt`; `lang` is `en` or `jp`.
