import asyncio
import os
import json
import tempfile
from pathlib import Path

class GHuntRunner:
    def __init__(self, ghunt_cmd="ghunt"):
        self.ghunt_cmd = ghunt_cmd

    async def run_email_scan(self, email):
        # Create a temporary file for JSON output
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            output_path = tmp_file.name

        try:
            cmd = [
                self.ghunt_cmd,
                "email",
                email,
                "--json",
                output_path
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return {"error": stderr.decode().strip()}

            # Load the JSON file result
            with open(output_path, "r") as f:
                data = json.load(f)

            return {"data": data}

        except Exception as e:
            return {"error": str(e)}

        finally:
            if os.path.exists(output_path):
                os.remove(output_path)