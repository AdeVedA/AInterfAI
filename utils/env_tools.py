import os
from pathlib import Path


def ensure_qdrant_path(dotenv_path: Path) -> str:
    """
    Check if QDRANT_ENGINE_PATH is defined and points to a valid file.
    Otherwise, ask the user to provide the path interactively via stdin.
    Update the .env file if a valid path is given.
    Works on Windows, Linux, and macOS.
    Returns the final path (empty string if canceled/invalid).
    """
    qdrant_path = os.getenv("QDRANT_ENGINE_PATH", "").strip()
    if qdrant_path and Path(qdrant_path).is_file():
        return qdrant_path

    print("\n⚠️ Qdrant executable not configured.")
    print(
        "\n=== Please enter the full path to Qdrant executable ===\n"
        r"c:\path\QDrant\qdrant.exe on Windows, c:/path/QDrant/qdrant on Linux/macOS"
    )
    exe_path = input("Path (leave empty to skip, but no RAG functionality without Qdrant): \n").strip()

    if not exe_path:
        print("❌ No Qdrant path provided. RAG functionality will be disabled.")
        return ""

    exe_path = str(Path(exe_path).expanduser().resolve())
    if not Path(exe_path).is_file():
        print(f"❌ The provided path is invalid: {exe_path}")
        return ""

    # Write/update .env
    dotenv_path = Path(dotenv_path)
    lines = []
    if dotenv_path.exists():
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()

    updated = False
    for i, line in enumerate(lines):
        if line.startswith("QDRANT_ENGINE_PATH="):
            lines[i] = f"QDRANT_ENGINE_PATH={exe_path}"
            updated = True
            break

    if not updated:
        lines.append(f"QDRANT_ENGINE_PATH={exe_path}")

    dotenv_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Qdrant path saved in {dotenv_path}")

    return exe_path
