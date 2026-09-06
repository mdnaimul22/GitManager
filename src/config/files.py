import os
import json
import shutil
from pathlib import Path
from typing import Any

from .paths import (
    PROJECT_ROOT,
    assert_path_sandboxed,
    is_path_sandboxed,
)


def _abs(relative_path: str) -> Path:
    p = Path(relative_path).expanduser()
    if p.is_absolute():
        return assert_path_sandboxed(p)
    return assert_path_sandboxed(relative_path, base_root=PROJECT_ROOT)


def read_text(relative_path: str, encoding: str = "utf-8") -> str:
    return _abs(relative_path).read_text(encoding=encoding)


def write_text(relative_path: str, content: str, encoding: str = "utf-8") -> None:
    path = _abs(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)


def read_json(relative_path: str) -> Any:
    return json.loads(read_text(relative_path))


def write_json(relative_path: str, data: Any, indent: int = 2) -> None:
    write_text(relative_path, json.dumps(data, indent=indent, ensure_ascii=False))


def exists(relative_path: str) -> bool:
    return _abs(relative_path).exists()


def is_file(relative_path: str) -> bool:
    return _abs(relative_path).is_file()


def is_dir(relative_path: str) -> bool:
    return _abs(relative_path).is_dir()


def ensure_dir(relative_path: str) -> Path:
    path = _abs(relative_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def delete(relative_path: str) -> None:
    path = _abs(relative_path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def list_files(relative_path: str, pattern: str = "*") -> list[Path]:
    return list(_abs(relative_path).glob(pattern))


def get_size(relative_path: str) -> int:
    return os.path.getsize(_abs(relative_path))


def get_mtime(relative_path: str) -> float:
    return os.path.getmtime(_abs(relative_path))


def read_from_pos(relative_path: str, pos: int, encoding: str = "utf-8") -> str:
    with open(_abs(relative_path), "r", encoding=encoding, errors="ignore") as f:
        f.seek(pos)
        return f.read()


def get_abs_path(*parts: str) -> str:
    if not parts:
        return str(PROJECT_ROOT)
    first = Path(parts[0]).expanduser()
    if first.is_absolute():
        p = Path(*parts).expanduser()
        return str(assert_path_sandboxed(p))
    target = PROJECT_ROOT.joinpath(*parts)
    return str(assert_path_sandboxed(target, base_root=PROJECT_ROOT))
