import sys
from pathlib import Path

_MARKER_FILES = (".env", "main.py", "pyproject.toml", ".git", "cli.py", "app.py")

def find_project_root() -> Path:
    current = Path(__file__).resolve().parent
    for candidate in [current] + list(current.parents):
        if any((candidate / m).exists() for m in _MARKER_FILES):
            return candidate
    return current.parent

PROJECT_ROOT: Path = find_project_root().resolve()
USER_HOME: Path = Path.home().resolve()

# Forbidden critical system directories where no project or file operations may target
FORBIDDEN_SYSTEM_DIRS: set[Path] = {
    Path("/bin").resolve(),
    Path("/sbin").resolve(),
    Path("/usr").resolve(),
    Path("/lib").resolve(),
    Path("/lib64").resolve(),
    Path("/boot").resolve(),
    Path("/dev").resolve(),
    Path("/proc").resolve(),
    Path("/sys").resolve(),
    Path("/run").resolve(),
    Path("/var").resolve(),
    Path("/etc").resolve(),
    Path("/root").resolve(),
}

FORBIDDEN_SYSTEM_ROOTS: set[Path] = FORBIDDEN_SYSTEM_DIRS | {Path("/").resolve()}

# Forbidden user files and credential directories inside USER_HOME
FORBIDDEN_USER_NAMES: set[str] = {
    ".ssh",
    ".gnupg",
    ".gpg",
    ".bashrc",
    ".bash_profile",
    ".profile",
    ".zshrc",
    ".zprofile",
    ".bash_history",
    ".zsh_history",
    ".gitconfig",
    ".netrc",
    ".aws",
}

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def is_path_sandboxed(
    path: str | Path,
    base_root: Path | None = None,
) -> tuple[bool, str]:
    """
    Validate whether a target path is safe and adheres to sandboxing constraints.

    Rules:
      1. Path must not be empty.
      2. If base_root is provided:
         - The resolved path must be within base_root (cannot traverse above base_root via '..').
      3. If base_root is None:
         - The resolved path cannot be the root filesystem ('/').
         - The resolved path cannot be the root of '/tmp'.
         - The resolved path cannot be the user home directory root itself ('USER_HOME').
         - The resolved path cannot be inside or equal to any FORBIDDEN_SYSTEM_DIRS
           (/etc, /bin, /sbin, /usr, /lib, /boot, /dev, /proc, /sys, /run, /var, /root).
         - The resolved path cannot target sensitive user files or folders in USER_HOME
           (~/.ssh, ~/.gnupg, ~/.bashrc, ~/.bash_profile, ~/.zshrc, ~/.aws, etc.).

    Returns:
      (True, "") if safe, or (False, error_message) if violated.
    """
    if not path:
        return False, "Path cannot be empty"

    raw_str = str(path).strip()
    if not raw_str:
        return False, "Path cannot be empty or whitespace"

    try:
        p = Path(raw_str).expanduser()
        if base_root is not None:
            resolved_base = base_root.resolve()
            resolved = (resolved_base / p).resolve() if not p.is_absolute() else p.resolve()
            if resolved != resolved_base and resolved_base not in resolved.parents:
                return False, f"Access denied: path '{raw_str}' escapes sandbox base '{resolved_base}'"
            # Check user security inside sandbox if it targets sensitive names
            for forbidden_name in FORBIDDEN_USER_NAMES:
                forbidden_path = USER_HOME / forbidden_name
                if resolved == forbidden_path or forbidden_path in resolved.parents:
                    return False, f"Access denied: path '{raw_str}' targets sensitive user configuration: {forbidden_name}"
            return True, ""

        # General path validation (when base_root is None)
        resolved = p.resolve()

        # Check root filesystem
        if resolved == Path("/").resolve():
            return False, "Security violation: Root filesystem '/' cannot be used as project path"

        # Check /tmp root
        if resolved == Path("/tmp").resolve():
            return False, "Security violation: System directory '/tmp' root cannot be used directly as project path"

        # Check USER_HOME root
        if resolved == USER_HOME:
            return False, "Security violation: User home directory cannot be used directly as project path"

        # Check system forbidden directories
        for forbidden_dir in FORBIDDEN_SYSTEM_DIRS:
            if resolved == forbidden_dir or forbidden_dir in resolved.parents:
                return False, f"Security violation: Path is in forbidden system directory: {forbidden_dir}"

        # Check sensitive user files and directories
        for forbidden_name in FORBIDDEN_USER_NAMES:
            forbidden_path = USER_HOME / forbidden_name
            if resolved == forbidden_path or forbidden_path in resolved.parents:
                return False, f"Security violation: Path targets sensitive user configuration: {forbidden_name}"

        return True, ""
    except Exception as exc:
        return False, f"Invalid path '{raw_str}': {exc}"


def assert_path_sandboxed(
    path: str | Path,
    base_root: Path | None = None,
) -> Path:
    """
    Assert that path is safe according to sandboxing rules.
    Returns the resolved Path if safe, or raises ValueError if violated.
    """
    safe, reason = is_path_sandboxed(path, base_root=base_root)
    if not safe:
        raise ValueError(reason)

    p = Path(path).expanduser()
    if base_root is not None:
        resolved_base = base_root.resolve()
        return (resolved_base / p).resolve() if not p.is_absolute() else p.resolve()
    return p.resolve()