# Prompting and model routing

Use this only when prompt construction or model choice is part of the request. Check the live [model guide](https://docs.novelai.net/en/image/models/) for current availability and API identifiers.

## Current families documented on 2026-09-16

- V5 Full: broadest V5 dataset, multilingual prompting, transparency, improved positioning and text, and up to 22 distinct characters. The official guide reports about 1471 effective base-prompt tokens and about 750 text-rendering tokens.
- V5 Curated: cleaner/focused and safer general-purpose V5 dataset, with shorter prompt limits (about 703 effective and 374 text-rendering tokens).
- V4.5 Full / Curated and V4 Full / Curated: older original NovelAI families with structured multi-character prompting and strong natural-language behavior.
- Anime V3 and Furry V3: older SDXL-derived tag-oriented models. Furry uses a different tag vocabulary.

Do not infer an API model identifier solely from the display name. Use an identifier supplied by the user or verified from current NovelAI API/site data.

## Prompt construction

- Preserve the user's wording and intended content. Add composition, subject, environment, lighting, camera, medium/style, and quality details only where they resolve ambiguity.
- Tags and natural language can be mixed. Use tag suggestions for model vocabulary rather than inventing obscure tags.
- Put important concepts early for V3; current V4/V5 models also support natural-language descriptions.
- Use `{...}` / `[...]` or numeric prompt mixing only when the user wants weighting and the selected model supports the syntax. Do not silently exaggerate weights.
- Put exclusions in Undesired Content / `negative_prompt`, not as negated prose in the positive prompt.
- Keep V4/V5 character-specific details in `char_captions`; keep scene-wide relationships, background, composition, and style in `base_caption`.
- For exact rendered text, follow the current Text Rendering guide and quote/spell the desired text precisely. Expect iteration rather than promising perfect typography.

## Prompt decision points

When the user has not fixed them and the difference matters, present concise choices for model family, prompt draft, aspect ratio/size, steps, guidance, Undesired Content, and character structure. Ask at most three related choices in one round. Do not ask for settings already implied by the request, and do not ask about expert-only controls without a concrete reason.

For characters, separate persistent identity traits from the current scene/action. Local Prompt Chunks are useful for reusable identity, outfit, style, and negative-prompt fragments; expand them before constructing V4+ `base_caption` and `char_captions`.

## Settings

- Start with one image unless a batch was requested.
- The official guide recommends guidance around 5–6 for V3 or newer as a starting region, not a universal optimum.
- Use a fixed seed to reproduce or compare parameter changes. Use a fresh/random seed for exploration.
- Increase steps only when it adds value; the guide warns that excessive steps may not improve a result.
- For img2img, higher strength permits more change; noise can add detail but may introduce artifacts.
- For multiple Vibes, the official guide recommends total reference strength around 1.0 or less as a useful starting point and notes that more than four Vibes can add cost on V4+.

Official references: [Basics](https://docs.novelai.net/en/image/basics/), [Steps and Guidance](https://docs.novelai.net/en/image/stepsguidance/), [Vibe Transfer](https://docs.novelai.net/en/image/vibetransfer/), and [Precise Reference](https://docs.novelai.net/en/image/precisereference/).
