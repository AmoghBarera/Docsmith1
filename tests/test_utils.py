"""Unit tests for utilities."""

from docksmith.utils import parse_memory_string, sanitize_base_name, strip_digest_ref

def test_parse_memory_string() -> None:
    assert parse_memory_string("512") == 512
    assert parse_memory_string("512k") == 512 * 1024
    assert parse_memory_string("512K") == 512 * 1024
    assert parse_memory_string("512m") == 512 * 1024 * 1024
    assert parse_memory_string("1g") == 1024 * 1024 * 1024

def test_sanitize_base_name() -> None:
    assert sanitize_base_name("ubuntu:latest") == "ubuntu_latest"
    assert sanitize_base_name("my-image_1.0") == "my-image_1.0"
    assert sanitize_base_name("some/path/image") == "some_path_image"

def test_strip_digest_ref() -> None:
    assert strip_digest_ref("sha256:abcdef") == "abcdef"
    assert strip_digest_ref("abcdef") == "abcdef"
