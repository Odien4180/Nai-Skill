#!/usr/bin/env python3
"""Dependency-free client for NovelAI's published image API."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import secrets
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://image.novelai.net"
DEFAULT_GENERATION_MODEL = "nai-diffusion-5-full"
DEFAULT_TOKEN_ENV = "NOVELAI_API_TOKEN"
WINDOWS_CREDENTIAL_TARGET = "NovelAISkill:NOVELAI_API_TOKEN"
SKILL_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = SKILL_ROOT / "cache"
DEFAULT_CHUNK_FILE = CACHE_ROOT / "prompt-chunks.json"
DEFAULT_OUTPUT_ROOT = CACHE_ROOT / "outputs"
DEFAULT_REQUEST_ROOT = CACHE_ROOT / "requests"
PROMPT_CHUNK_PATTERN = re.compile(r"!macro:([^!\r\n]+)!")
PROMPT_TEXT_KEYS = {
    "input",
    "prompt",
    "negative_prompt",
    "base_caption",
    "char_caption",
}


class CliError(Exception):
    pass


def valid_chunk_name(name: Any) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and "!" not in name
        and "\n" not in name
        and "\r" not in name
    )


def load_json(path_text: str) -> tuple[Any, Path]:
    if path_text == "-":
        try:
            return json.load(sys.stdin), Path.cwd()
        except json.JSONDecodeError as exc:
            raise CliError(f"stdin is not valid JSON: {exc}") from exc
    path = Path(path_text).expanduser().resolve()
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle), path.parent
    except FileNotFoundError as exc:
        raise CliError(f"request file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"request file is not valid JSON: {path}: {exc}") from exc


def load_chunk_store(path_text: str) -> tuple[dict[str, str], Path]:
    path = Path(path_text).expanduser().resolve()
    try:
        decoded = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CliError(f"prompt chunk file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"prompt chunk file is not valid JSON: {path}: {exc}") from exc

    if not isinstance(decoded, dict) or decoded.get("version") != 1:
        raise CliError("prompt chunk file must be an object with version 1")
    chunks = decoded.get("chunks")
    if not isinstance(chunks, dict):
        raise CliError("prompt chunk file must contain a chunks object")
    if any(not valid_chunk_name(name) for name in chunks):
        raise CliError("prompt chunk names must be non-empty single-line strings without !")
    if any(not isinstance(content, str) for content in chunks.values()):
        raise CliError("every prompt chunk value must be a string")
    return chunks, path


def write_chunk_store(path_text: str | Path, chunks: dict[str, str]) -> Path:
    path = Path(path_text).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(
            json.dumps({"version": 1, "chunks": chunks}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def expand_prompt_text(
    text: str,
    chunks: dict[str, str],
    stack: tuple[str, ...] = (),
) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in chunks:
            raise CliError(f"prompt chunk not found: {name}")
        if name in stack:
            cycle = " -> ".join((*stack, name))
            raise CliError(f"prompt chunk cycle detected: {cycle}")
        if len(stack) >= 64:
            raise CliError("prompt chunk nesting exceeds 64 levels")
        return expand_prompt_text(chunks[name], chunks, (*stack, name))

    return PROMPT_CHUNK_PATTERN.sub(replace, text)


def expand_payload_prompt_chunks(
    value: Any,
    chunks: dict[str, str],
    key: str | None = None,
) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$file"}:
            return value
        return {
            item_key: expand_payload_prompt_chunks(item, chunks, str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [expand_payload_prompt_chunks(item, chunks, key) for item in value]
    if isinstance(value, str) and (
        key in PROMPT_TEXT_KEYS
        or (key is not None and (key.endswith("_prompt") or key.endswith("_caption")))
    ):
        return expand_prompt_text(value, chunks)
    return value


def payload_has_prompt_chunk_macro(
    value: Any,
    key: str | None = None,
) -> bool:
    if isinstance(value, dict):
        if set(value) == {"$file"}:
            return False
        return any(
            payload_has_prompt_chunk_macro(item, str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, list):
        return any(payload_has_prompt_chunk_macro(item, key) for item in value)
    if isinstance(value, str) and (
        key in PROMPT_TEXT_KEYS
        or (key is not None and (key.endswith("_prompt") or key.endswith("_caption")))
    ):
        return PROMPT_CHUNK_PATTERN.search(value) is not None
    return False


def hydrate_files(value: Any, base_dir: Path) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$file"}:
            source = Path(str(value["$file"])).expanduser()
            if not source.is_absolute():
                source = base_dir / source
            source = source.resolve()
            try:
                return base64.b64encode(source.read_bytes()).decode("ascii")
            except FileNotFoundError as exc:
                raise CliError(f"referenced file not found: {source}") from exc
        return {key: hydrate_files(item, base_dir) for key, item in value.items()}
    if isinstance(value, list):
        return [hydrate_files(item, base_dir) for item in value]
    return value


def validate_known_payload_types(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    parameters = payload.get("parameters")
    if parameters is None:
        return
    if not isinstance(parameters, dict):
        raise CliError("parameters must be a JSON object")

    integer_fields = {
        "height",
        "n_samples",
        "params_version",
        "seed",
        "tag_hint_qt",
        "tag_hint_uc_preset",
        "ucPreset",
        "width",
    }
    boolean_fields = {
        "add_original_image",
        "dynamic_thresholding",
        "legacy",
        "qualityToggle",
        "sm",
        "sm_dyn",
        "straight_alpha",
        "tag_hint_transparent_background",
    }
    number_fields = {"cfg_rescale", "scale", "steps"}

    for field in integer_fields:
        if field in parameters and (
            not isinstance(parameters[field], int)
            or isinstance(parameters[field], bool)
        ):
            raise CliError(f"parameters.{field} must be an integer")
    for field in boolean_fields:
        if field in parameters and not isinstance(parameters[field], bool):
            raise CliError(f"parameters.{field} must be a boolean")
    for field in number_fields:
        if field in parameters and (
            not isinstance(parameters[field], (int, float))
            or isinstance(parameters[field], bool)
        ):
            raise CliError(f"parameters.{field} must be a number")


def validate_generation_payload(payload: Any) -> None:
    """Validate the canonical generate-image request contract."""
    if not isinstance(payload, dict):
        raise CliError("generation request must be a JSON object")
    for field in ("action", "input", "model", "parameters"):
        if field not in payload:
            raise CliError(f"generation request is missing required field: {field}")
    for field in ("action", "input", "model"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise CliError(f"generation request.{field} must be a non-empty string")
    parameters = payload["parameters"]
    if not isinstance(parameters, dict):
        raise CliError("parameters must be a JSON object")
    required = ("prompt", "negative_prompt", "width", "height", "steps", "scale", "sampler", "n_samples")
    for field in required:
        if field not in parameters:
            raise CliError(f"generation request is missing required field: parameters.{field}")
    for field in ("prompt", "negative_prompt", "sampler"):
        if not isinstance(parameters[field], str):
            raise CliError(f"parameters.{field} must be a string")
    if payload["input"] != parameters["prompt"]:
        raise CliError("generation request input and parameters.prompt must be identical")
    for name in ("v4_prompt", "v4_negative_prompt"):
        if name not in parameters:
            continue
        structured = parameters[name]
        caption = structured.get("caption") if isinstance(structured, dict) else None
        if not isinstance(caption, dict):
            raise CliError(f"parameters.{name}.caption must be an object")
        if not isinstance(caption.get("base_caption"), str):
            raise CliError(f"parameters.{name}.caption.base_caption must be a string")
        characters = caption.get("char_captions")
        if not isinstance(characters, list):
            raise CliError(f"parameters.{name}.caption.char_captions must be an array")
        for index, character in enumerate(characters):
            prefix = f"parameters.{name}.caption.char_captions[{index}]"
            if not isinstance(character, dict) or not isinstance(character.get("char_caption"), str):
                raise CliError(f"{prefix}.char_caption must be a string")
            centers = character.get("centers", [])
            if not isinstance(centers, list):
                raise CliError(f"{prefix}.centers must be an array")
            for center_index, center in enumerate(centers):
                center_prefix = f"{prefix}.centers[{center_index}]"
                if not isinstance(center, dict) or set(center) != {"x", "y"}:
                    raise CliError(f"{center_prefix} must contain exactly x and y")
                for axis in ("x", "y"):
                    value = center[axis]
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                        raise CliError(f"{center_prefix}.{axis} must be between 0 and 1")
        for flag in ("use_coords", "use_order"):
            if not isinstance(structured.get(flag), bool):
                raise CliError(f"parameters.{name}.{flag} must be a boolean")
        if structured["use_coords"] and any(not character.get("centers") for character in characters):
            raise CliError(f"parameters.{name} requires centers for every character when use_coords is true")
    if "v4_prompt" in parameters and parameters["v4_prompt"]["caption"]["base_caption"] != parameters["prompt"]:
        raise CliError("parameters.v4_prompt.caption.base_caption and parameters.prompt must be identical")
    if "v4_negative_prompt" in parameters and parameters["v4_negative_prompt"]["caption"]["base_caption"] != parameters["negative_prompt"]:
        raise CliError("parameters.v4_negative_prompt.caption.base_caption and parameters.negative_prompt must be identical")


def apply_generation_defaults(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    payload.setdefault("model", DEFAULT_GENERATION_MODEL)
    return payload


def summarize(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {
                "image", "mask", "controlnet_condition", "reference_image",
            } and isinstance(item, str) and len(item) > 128:
                result[key] = f"<base64:{len(item)} chars>"
            elif key in {"reference_image_multiple", "director_reference_images"} and isinstance(item, list):
                result[key] = [
                    f"<base64:{len(entry)} chars>" if isinstance(entry, str) else summarize(entry)
                    for entry in item
                ]
            else:
                result[key] = summarize(item)
        return result
    if isinstance(value, list):
        return [summarize(item) for item in value]
    return value


def correlation_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def read_windows_credential(target: str = WINDOWS_CREDENTIAL_TARGET) -> str | None:
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    credential_pointer = ctypes.POINTER(Credential)()
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None

    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(credential_pointer)):
        error_code = ctypes.get_last_error()
        if error_code == 1168:
            return None
        raise CliError(f"Windows Credential Manager lookup failed with error {error_code}")

    try:
        credential = credential_pointer.contents
        size = credential.CredentialBlobSize
        if not size:
            return None
        raw = ctypes.string_at(credential.CredentialBlob, size)
        try:
            return raw.decode("utf-16-le").strip()
        except UnicodeDecodeError as exc:
            raise CliError("the stored NovelAI credential has an invalid format") from exc
    finally:
        advapi32.CredFree(credential_pointer)


def read_windows_machine_environment(name: str) -> str | None:
    if os.name != "nt":
        return None

    import winreg

    key_path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CliError(f"Windows machine environment lookup failed: {exc}") from exc

    if not isinstance(value, str):
        raise CliError(f"Windows machine environment value {name} is not text")
    return value.strip() or None


def auth_header(token_env: str) -> str:
    if token_env == DEFAULT_TOKEN_ENV:
        token = (
            os.environ.get(token_env, "").strip()
            or read_windows_machine_environment(token_env)
            or read_windows_credential()
            or ""
        )
    else:
        token = os.environ.get(token_env, "").strip()
    if not token:
        raise CliError(
            f"missing NovelAI credentials; install the Windows machine token or set {token_env}"
        )
    return token if token.lower().startswith("bearer ") else f"Bearer {token}"


def request_bytes(
    *,
    method: str,
    base_url: str,
    path: str,
    token_env: str,
    payload: Any | None = None,
    accept: str = "application/json",
    query: dict[str, str] | None = None,
    timeout: float = 300,
) -> tuple[bytes, str, str, int]:
    cid = correlation_id()
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    if query:
        url += "?" + urllib.parse.urlencode(query)
    body = None
    headers = {
        "Accept": accept,
        "Authorization": auth_header(token_env),
        "User-Agent": "novelai-image-agent-skill/1.0",
        "x-correlation-id": cid,
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return (
                response.read(),
                response.headers.get_content_type(),
                cid,
                response.status,
            )
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(response_body)
            message = parsed.get("message") or json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, AttributeError):
            message = response_body[:1000] or exc.reason
        raise CliError(f"NovelAI HTTP {exc.code}: {message} (correlation ID {cid})") from exc
    except urllib.error.URLError as exc:
        raise CliError(f"NovelAI request failed: {exc.reason} (correlation ID {cid})") from exc


def ensure_dir(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_run_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(3)}"


def resolve_output_dir(path_text: str | None, operation: str) -> Path:
    if path_text:
        return ensure_dir(path_text)
    return ensure_dir(str(DEFAULT_OUTPUT_ROOT / operation / default_run_name()))


def resolve_output_file(
    path_text: str | None,
    operation: str,
    filename: str,
) -> Path:
    if path_text:
        destination = Path(path_text).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination
    output_dir = resolve_output_dir(None, operation)
    return output_dir / filename


def image_extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def write_json_images(data: bytes, output_dir: Path, cid: str, status: int) -> list[Path]:
    try:
        decoded = json.loads(data)
    except json.JSONDecodeError as exc:
        raise CliError("NovelAI returned invalid JSON") from exc
    images = decoded.get("images", []) if isinstance(decoded, dict) else []
    written: list[Path] = []
    manifest_images: list[dict[str, Any]] = []
    for position, item in enumerate(images):
        if not isinstance(item, dict) or not isinstance(item.get("image"), str):
            continue
        try:
            raw = base64.b64decode(item["image"], validate=True)
        except ValueError as exc:
            raise CliError(f"image {position} contains invalid base64") from exc
        index = item.get("index", position)
        destination = output_dir / f"image_{index}{image_extension(raw)}"
        destination.write_bytes(raw)
        written.append(destination)
        manifest_images.append(
            {"file": destination.name, "index": index, "seed": item.get("seed")}
        )
    manifest = {
        "status": status,
        "correlation_id": cid,
        "images": manifest_images,
        "response": {key: value for key, value in decoded.items() if key != "images"}
        if isinstance(decoded, dict)
        else {},
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not written:
        (output_dir / "response.json").write_text(
            json.dumps(decoded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return written


def write_zip(data: bytes, output_dir: Path, cid: str, status: int) -> list[Path]:
    written: list[Path] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for position, member in enumerate(archive.infolist()):
                if member.is_dir():
                    continue
                raw = archive.read(member)
                original = Path(member.filename).name
                name = original or f"image_{position}{image_extension(raw)}"
                destination = output_dir / name
                if destination.exists():
                    destination = output_dir / f"{destination.stem}_{position}{destination.suffix}"
                destination.write_bytes(raw)
                written.append(destination)
    except zipfile.BadZipFile as exc:
        raise CliError("NovelAI response was not a valid ZIP archive") from exc
    manifest = {
        "status": status,
        "correlation_id": cid,
        "files": [path.name for path in written],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return written


def output_summary(paths: list[Path], cid: str) -> None:
    print(json.dumps({"files": [str(path) for path in paths], "correlation_id": cid}, indent=2))


def load_payload(args: argparse.Namespace) -> Any:
    payload, base_dir = load_json(args.request)
    chunks_file = getattr(args, "chunks_file", None)
    if not chunks_file and (DEFAULT_CHUNK_FILE.exists() or payload_has_prompt_chunk_macro(payload)):
        chunks_file = str(DEFAULT_CHUNK_FILE)
    if chunks_file:
        chunks, _path = load_chunk_store(chunks_file)
        payload = expand_payload_prompt_chunks(payload, chunks)
    payload = hydrate_files(payload, base_dir)
    validate_known_payload_types(payload)
    return payload


def maybe_dry_run(args: argparse.Namespace, payload: Any) -> bool:
    if not getattr(args, "dry_run", False):
        return False
    print(json.dumps(summarize(payload), ensure_ascii=False, indent=2))
    return True


def command_generate(args: argparse.Namespace) -> None:
    payload = load_payload(args)
    payload = apply_generation_defaults(payload)
    validate_generation_payload(payload)
    if maybe_dry_run(args, payload):
        return
    if args.stream:
        data, _content_type, cid, _status = request_bytes(
            method="POST", base_url=args.base_url, path="/ai/generate-image-stream",
            token_env=args.token_env, payload=payload, accept="text/event-stream", timeout=args.timeout,
        )
        output_dir = resolve_output_dir(args.output_dir, "generate-stream")
        destination = output_dir / "generation.sse"
        destination.write_bytes(data)
        output_summary([destination], cid)
        return
    data, content_type, cid, status = request_bytes(
        method="POST", base_url=args.base_url, path="/ai/generate-image",
        token_env=args.token_env, payload=payload, accept=args.accept, timeout=args.timeout,
    )
    output_dir = resolve_output_dir(args.output_dir, "generate")
    paths = write_zip(data, output_dir, cid, status) if "zip" in content_type else write_json_images(data, output_dir, cid, status)
    output_summary(paths, cid)


def command_encode_vibe(args: argparse.Namespace) -> None:
    payload = load_payload(args)
    if maybe_dry_run(args, payload):
        return
    data, _content_type, cid, _status = request_bytes(
        method="POST", base_url=args.base_url, path="/ai/encode-vibe",
        token_env=args.token_env, payload=payload, accept="application/binary", timeout=args.timeout,
    )
    destination = resolve_output_file(args.output, "encode-vibe", "vibe.bin")
    destination.write_bytes(data)
    output_summary([destination], cid)


def command_image_json_or_zip(
    args: argparse.Namespace,
    path: str,
    operation: str,
    force_zip: bool = False,
) -> None:
    payload = load_payload(args)
    if maybe_dry_run(args, payload):
        return
    accept = "application/zip" if force_zip else args.accept
    data, content_type, cid, status = request_bytes(
        method="POST", base_url=args.base_url, path=path, token_env=args.token_env,
        payload=payload, accept=accept, timeout=args.timeout,
    )
    output_dir = resolve_output_dir(args.output_dir, operation)
    paths = write_zip(data, output_dir, cid, status) if force_zip or "zip" in content_type else write_json_images(data, output_dir, cid, status)
    output_summary(paths, cid)


def command_suggest(args: argparse.Namespace) -> None:
    data, _content_type, cid, _status = request_bytes(
        method="GET", base_url=args.base_url, path="/ai/generate-image/suggest-tags",
        token_env=args.token_env,
        query={"model": args.model, "prompt": args.prompt, "lang": args.lang},
        timeout=args.timeout,
    )
    print(json.dumps({"correlation_id": cid, "result": json.loads(data)}, ensure_ascii=False, indent=2))


def command_models(args: argparse.Namespace) -> None:
    data, _content_type, cid, _status = request_bytes(
        method="GET", base_url=args.base_url, path="/oa/v1/models",
        token_env=args.token_env, timeout=args.timeout,
    )
    print(json.dumps({"correlation_id": cid, "result": json.loads(data)}, ensure_ascii=False, indent=2))


def command_chunks(args: argparse.Namespace) -> None:
    path = Path(args.file or DEFAULT_CHUNK_FILE).expanduser().resolve()
    if args.chunk_command == "set":
        if not valid_chunk_name(args.name):
            raise CliError("prompt chunk names must be non-empty single-line strings without !")
        if path.exists():
            chunks, _path = load_chunk_store(str(path))
        else:
            chunks = {}
        content = args.content
        if args.content_file:
            try:
                content = Path(args.content_file).expanduser().resolve().read_text(encoding="utf-8-sig")
            except FileNotFoundError as exc:
                raise CliError(f"prompt chunk content file not found: {args.content_file}") from exc
        chunks[args.name] = content
        written = write_chunk_store(path, chunks)
        print(json.dumps({"file": str(written), "saved": args.name}, ensure_ascii=False, indent=2))
        return

    chunks, loaded_path = load_chunk_store(str(path))
    if args.chunk_command == "list":
        print(json.dumps({"file": str(loaded_path), "names": sorted(chunks)}, ensure_ascii=False, indent=2))
    elif args.chunk_command == "get":
        if args.name not in chunks:
            raise CliError(f"prompt chunk not found: {args.name}")
        print(json.dumps({"name": args.name, "content": chunks[args.name]}, ensure_ascii=False, indent=2))
    elif args.chunk_command == "delete":
        if args.name not in chunks:
            raise CliError(f"prompt chunk not found: {args.name}")
        del chunks[args.name]
        written = write_chunk_store(loaded_path, chunks)
        print(json.dumps({"file": str(written), "deleted": args.name}, ensure_ascii=False, indent=2))
    elif args.chunk_command == "expand":
        print(json.dumps({"expanded": expand_prompt_text(args.text, chunks)}, ensure_ascii=False, indent=2))


def command_raw(args: argparse.Namespace) -> None:
    payload = load_payload(args) if args.request else None
    if payload is not None and maybe_dry_run(args, payload):
        return
    data, content_type, cid, _status = request_bytes(
        method=args.method, base_url=args.base_url, path=args.path,
        token_env=args.token_env, payload=payload, accept=args.accept, timeout=args.timeout,
    )
    suffix = "json" if content_type == "application/json" else "bin"
    destination = resolve_output_file(args.output, "raw", f"response.{suffix}")
    if content_type == "application/json":
        destination.write_text(json.dumps(json.loads(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        destination.write_bytes(data)
    output_summary([destination], cid)


def common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--allow-custom-host",
        action="store_true",
        help="allow a non-image.novelai.net base URL for local/mock testing",
    )
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--timeout", type=float, default=300)
    return parser


def request_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--request", required=True, help="JSON path, or - for stdin")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--chunks-file",
        help="local version-1 prompt chunk JSON; expands !macro:Name! in prompt fields",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    common = common_parser()
    request_common = request_parser()

    generate = sub.add_parser("generate", parents=[common, request_common])
    generate.add_argument("--output-dir")
    generate.add_argument("--accept", choices=["application/json", "application/zip"], default="application/json")
    generate.add_argument("--stream", action="store_true")
    generate.set_defaults(handler=command_generate)

    vibe = sub.add_parser("encode-vibe", parents=[common, request_common])
    vibe.add_argument("--output")
    vibe.set_defaults(handler=command_encode_vibe)

    augment = sub.add_parser("augment", parents=[common, request_common])
    augment.add_argument("--output-dir")
    augment.set_defaults(handler=lambda args: command_image_json_or_zip(args, "/ai/augment-image", "augment", True))

    upscale = sub.add_parser("upscale", parents=[common, request_common])
    upscale.add_argument("--output-dir")
    upscale.add_argument("--accept", choices=["application/json", "application/zip"], default="application/json")
    upscale.set_defaults(handler=lambda args: command_image_json_or_zip(args, "/ai/upscale", "upscale"))

    suggest = sub.add_parser("suggest-tags", parents=[common])
    suggest.add_argument("--model", required=True)
    suggest.add_argument("--prompt", required=True)
    suggest.add_argument("--lang", choices=["en", "jp"], default="en")
    suggest.set_defaults(handler=command_suggest)

    models = sub.add_parser("models", parents=[common])
    models.set_defaults(handler=command_models)

    chunks = sub.add_parser("chunks", help="manage a local prompt chunk JSON file")
    chunks.add_argument(
        "--file",
        help=f"override the default store at {DEFAULT_CHUNK_FILE}",
    )
    chunk_sub = chunks.add_subparsers(dest="chunk_command", required=True)
    chunk_sub.add_parser("list")
    chunk_get = chunk_sub.add_parser("get")
    chunk_get.add_argument("--name", required=True)
    chunk_set = chunk_sub.add_parser("set")
    chunk_set.add_argument("--name", required=True)
    chunk_set_content = chunk_set.add_mutually_exclusive_group(required=True)
    chunk_set_content.add_argument("--content")
    chunk_set_content.add_argument("--content-file")
    chunk_delete = chunk_sub.add_parser("delete")
    chunk_delete.add_argument("--name", required=True)
    chunk_expand = chunk_sub.add_parser("expand")
    chunk_expand.add_argument("--text", required=True)
    chunks.set_defaults(handler=command_chunks)

    raw = sub.add_parser("raw", parents=[common])
    raw.add_argument("--method", required=True)
    raw.add_argument("--path", required=True)
    raw.add_argument("--request", help="optional JSON path, or - for stdin")
    raw.add_argument("--accept", default="application/json")
    raw.add_argument("--output")
    raw.add_argument("--dry-run", action="store_true")
    raw.set_defaults(handler=command_raw)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if hasattr(args, "base_url"):
            host = urllib.parse.urlparse(args.base_url).hostname
            if host != "image.novelai.net" and not args.allow_custom_host:
                raise CliError(
                    "refusing to send credentials to a custom host; use --allow-custom-host only for local/mock testing"
                )
        args.handler(args)
        return 0
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
