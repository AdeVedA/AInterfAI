import socket
import threading
import time
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Optional

import httpx


def is_qdrant_running(host: str, port: int) -> bool:
    """
    Try to connect to host:port through TCP.
    Returns True if qdrant answers.
    """
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


class QdrantLauncher:
    """
    Life cycle manager for Qdrant (binary).
    - launch() starts Qdrant (Non-blocking thread) if necessary, passing
      explicitly --http-port and --grpc-port to avoid any default port.
    - stop() properly stops the process if it has been launched here.
    """

    def __init__(self, exe_path: str, host: str, grpc_port: int, config_yaml: str):
        self.exe_path = Path(exe_path)
        self.host = host
        self.grpc_port = grpc_port  # convention : gRPC = HTTP + 1
        self.http_port = grpc_port - 1
        self.config_yaml = Path(config_yaml)
        self._process: Optional[Popen] = None
        self._launched_here = False

    def launch(self) -> None:
        """Launches Qdrant if not already active on host:grpc_port."""

        if not self.exe_path.exists() or not Path(self.exe_path).is_file():
            print("QDRANT EXE not found, RAG disabled.\nplease install Qdrant and put its path in .env file")
            return
        if not self.config_yaml.exists():
            print(f"config.yaml not found : {self.config_yaml}")
            return

        if is_qdrant_running(self.host, self.grpc_port):
            print(f"✅ Qdrant active on {self.host}:{self.grpc_port}")
            return

        def _runner():
            # Construire la commande complète
            cmd = [str(self.exe_path), "--config-path", str(self.config_yaml)]
            print("Qdrant starting with :", " ".join(cmd))
            # Ne plus masquer stdout/stderr pour voir immédiatement les erreurs
            self._process = Popen(
                cmd,
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                bufsize=1,
            )
            self._launched_here = True

            # en cas de besoins de debugging, uncomment :
            # threading.Thread(target=self._stream_logs, args=(self._process.stdout, "OUT"), daemon=True).start()
            # threading.Thread(target=self._stream_logs, args=(self._process.stderr, "ERR"), daemon=True).start()

            # Attendre jusqu'à ce que l'API HTTP réponde
            url = f"http://{self.host}:{self.http_port}/collections"
            for i in range(20):
                try:
                    resp = httpx.get(url, timeout=1.0)
                    if resp.status_code == 200:
                        print(f"✅ Qdrant HTTP ready ({url}) after {i*0.5:.1f}s")
                        return
                except Exception:
                    pass
                # Sinon, on vérifie juste que le port TCP est ouvert
                if is_qdrant_running(self.host, self.grpc_port):
                    print(f"✅ Qdrant replied TCP on {self.host}:{self.grpc_port} after {i*0.5:.1f}s")
                    return
                time.sleep(0.5)

            # Si on arrive là, Qdrant ne répond pas
            print("Qdrant did not respond after 10s. Logs :")
            try:
                out, err = self._process.communicate(timeout=1)
                print("--- stdout ---\n", out.decode(errors="ignore"))
                print("--- stderr ---\n", err.decode(errors="ignore"))
            except Exception as e:
                print(f"Impossible to recover the logs : {e}")

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()

    def _stream_logs(self, stream, prefix):
        for line in iter(stream.readline, ""):
            print(f"[QDRANT {prefix}] {line.strip()}")

    def stop(self) -> None:
        """Stops Qdrant properly if it was launched by this launcher."""
        if self._process and self._launched_here and self._process.poll() is None:
            print("Qdrant stopping...")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except Exception:
                print("Couldn't terminate, killing Qdrant...")
                self._process.kill()
            print("Qdrant stopped.")
        else:
            print("No qdrants to stop (already running elsewhere or already stopped).")
