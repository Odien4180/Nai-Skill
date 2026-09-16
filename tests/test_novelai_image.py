import base64
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "skills" / "novelai-image" / "scripts" / "novelai_image.py"
SPEC = importlib.util.spec_from_file_location("novelai_image", SCRIPT)
CLIENT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CLIENT)


class ClientTests(unittest.TestCase):
    def test_default_auth_prefers_process_environment(self):
        with mock.patch.dict(os.environ, {"NOVELAI_API_TOKEN": "environment-secret"}, clear=True), mock.patch.object(
            CLIENT, "read_windows_machine_environment", return_value="machine-secret"
        ), mock.patch.object(CLIENT, "read_windows_credential", return_value="vault-secret"):
            self.assertEqual(CLIENT.auth_header("NOVELAI_API_TOKEN"), "Bearer environment-secret")

    def test_default_auth_reads_machine_environment_without_inheritance(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            CLIENT, "read_windows_machine_environment", return_value="machine-secret"
        ), mock.patch.object(CLIENT, "read_windows_credential", return_value="vault-secret"):
            self.assertEqual(CLIENT.auth_header("NOVELAI_API_TOKEN"), "Bearer machine-secret")

    def test_default_auth_keeps_credential_manager_as_legacy_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            CLIENT, "read_windows_machine_environment", return_value=None
        ), mock.patch.object(CLIENT, "read_windows_credential", return_value="vault-secret"):
            self.assertEqual(CLIENT.auth_header("NOVELAI_API_TOKEN"), "Bearer vault-secret")

    def test_file_placeholder_is_recursive_and_relative(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "image.bin").write_bytes(b"image bytes")
            hydrated = CLIENT.hydrate_files(
                {"items": [{"$file": "image.bin"}]}, root
            )
            self.assertEqual(
                hydrated["items"][0],
                base64.b64encode(b"image bytes").decode("ascii"),
            )

    def test_known_generation_parameter_types_are_validated(self):
        CLIENT.validate_known_payload_types(
            {
                "parameters": {
                    "tag_hint_qt": 0,
                    "tag_hint_uc_preset": 0,
                    "tag_hint_transparent_background": True,
                    "straight_alpha": True,
                }
            }
        )
        with self.assertRaisesRegex(
            CLIENT.CliError,
            "parameters.tag_hint_qt must be an integer",
        ):
            CLIENT.validate_known_payload_types(
                {"parameters": {"tag_hint_qt": False}}
            )

    def test_boolean_and_numeric_generation_fields_do_not_cross_types(self):
        with self.assertRaisesRegex(
            CLIENT.CliError,
            "parameters.straight_alpha must be a boolean",
        ):
            CLIENT.validate_known_payload_types(
                {"parameters": {"straight_alpha": 1}}
            )
        with self.assertRaisesRegex(
            CLIENT.CliError,
            "parameters.scale must be a number",
        ):
            CLIENT.validate_known_payload_types(
                {"parameters": {"scale": True}}
            )

    def test_prompt_chunks_expand_nested_prompt_fields(self):
        chunks = {
            "Hero": "1girl, !macro:Hair!",
            "Hair": "red hair",
            "Avoid": "blurry, lowres",
        }
        payload = {
            "input": "!macro:Hero!, in a cafe",
            "parameters": {
                "prompt": "!macro:Hero!, in a cafe",
                "negative_prompt": "!macro:Avoid!",
                "image": "!macro:Hero!",
                "v4_prompt": {
                    "caption": {
                        "base_caption": "!macro:Hero!",
                        "char_captions": [{"char_caption": "!macro:Hair!"}],
                    }
                },
            },
        }
        expanded = CLIENT.expand_payload_prompt_chunks(payload, chunks)
        self.assertEqual(expanded["input"], "1girl, red hair, in a cafe")
        self.assertEqual(expanded["parameters"]["negative_prompt"], "blurry, lowres")
        self.assertEqual(expanded["parameters"]["image"], "!macro:Hero!")
        self.assertEqual(
            expanded["parameters"]["v4_prompt"]["caption"]["char_captions"][0]["char_caption"],
            "red hair",
        )

    def test_prompt_chunk_cycle_is_rejected(self):
        with self.assertRaisesRegex(CLIENT.CliError, "cycle detected"):
            CLIENT.expand_prompt_text(
                "!macro:A!",
                {"A": "!macro:B!", "B": "!macro:A!"},
            )

    def test_prompt_chunk_macro_detection_only_checks_prompt_fields(self):
        self.assertTrue(
            CLIENT.payload_has_prompt_chunk_macro(
                {"parameters": {"prompt": "!macro:Style!"}}
            )
        )
        self.assertFalse(
            CLIENT.payload_has_prompt_chunk_macro(
                {"parameters": {"image": "!macro:Style!"}}
            )
        )

    def test_prompt_chunk_store_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chunks.json"
            CLIENT.write_chunk_store(path, {"Lighting": "soft light"})
            chunks, loaded_path = CLIENT.load_chunk_store(str(path))
            self.assertEqual(chunks, {"Lighting": "soft light"})
            self.assertEqual(loaded_path, path.resolve())

    def test_chunks_command_does_not_require_network_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chunks.json"
            args = CLIENT.build_parser().parse_args(
                [
                    "chunks",
                    "--file",
                    str(path),
                    "set",
                    "--name",
                    "Lighting",
                    "--content",
                    "soft light",
                ]
            )
            args.handler(args)
            chunks, _loaded_path = CLIENT.load_chunk_store(str(path))
            self.assertEqual(chunks, {"Lighting": "soft light"})

    def test_chunks_parser_allows_the_installed_default_store(self):
        args = CLIENT.build_parser().parse_args(["chunks", "list"])
        self.assertIsNone(args.file)

    def test_output_arguments_are_optional_and_default_to_skill_cache(self):
        generate_args = CLIENT.build_parser().parse_args(
            ["generate", "--request", "request.json"]
        )
        vibe_args = CLIENT.build_parser().parse_args(
            ["encode-vibe", "--request", "vibe.json"]
        )
        raw_args = CLIENT.build_parser().parse_args(
            ["raw", "--method", "GET", "--path", "/test"]
        )
        self.assertIsNone(generate_args.output_dir)
        self.assertIsNone(vibe_args.output)
        self.assertIsNone(raw_args.output)

    def test_default_output_directory_is_unique_and_inside_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "outputs"
            with mock.patch.object(CLIENT, "DEFAULT_OUTPUT_ROOT", root):
                first = CLIENT.resolve_output_dir(None, "generate")
                second = CLIENT.resolve_output_dir(None, "generate")
            self.assertEqual(first.parent, root / "generate")
            self.assertEqual(second.parent, root / "generate")
            self.assertNotEqual(first, second)

    def test_json_images_and_manifest_are_written(self):
        png = b"\x89PNG\r\n\x1a\nmock"
        response = json.dumps(
            {"images": [{"image": base64.b64encode(png).decode(), "index": 2, "seed": 7}]}
        ).encode()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            paths = CLIENT.write_json_images(response, output, "abc123", 201)
            self.assertEqual(paths[0].name, "image_2.png")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["images"][0]["seed"], 7)
            self.assertNotIn(base64.b64encode(png).decode(), json.dumps(manifest))

    def test_zip_member_cannot_escape_output_directory(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../../result.png", b"\x89PNG\r\n\x1a\nmock")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            paths = CLIENT.write_zip(buffer.getvalue(), output, "abc123", 201)
            self.assertEqual(paths, [output / "result.png"])
            self.assertTrue((output / "result.png").exists())

    def test_request_adds_bearer_and_correlation_headers(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured["authorization"] = self.headers["Authorization"]
                captured["correlation"] = self.headers["x-correlation-id"]
                length = int(self.headers["Content-Length"])
                captured["body"] = json.loads(self.rfile.read(length))
                response = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        previous = os.environ.get("NOVELAI_TEST_TOKEN")
        os.environ["NOVELAI_TEST_TOKEN"] = "secret"
        try:
            data, content_type, correlation, status = CLIENT.request_bytes(
                method="POST",
                base_url=f"http://127.0.0.1:{server.server_port}",
                path="/test",
                token_env="NOVELAI_TEST_TOKEN",
                payload={"hello": "world"},
            )
        finally:
            server.shutdown()
            server.server_close()
            if previous is None:
                os.environ.pop("NOVELAI_TEST_TOKEN", None)
            else:
                os.environ["NOVELAI_TEST_TOKEN"] = previous
        self.assertEqual(json.loads(data), {"ok": True})
        self.assertEqual(content_type, "application/json")
        self.assertEqual(status, 200)
        self.assertEqual(captured["authorization"], "Bearer secret")
        self.assertEqual(captured["correlation"], correlation)
        self.assertEqual(len(correlation), 6)
        self.assertEqual(captured["body"], {"hello": "world"})


if __name__ == "__main__":
    unittest.main()
