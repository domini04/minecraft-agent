import os

import requests


class BodyClient:
    def __init__(self, base_url=None):
        self.base_url = base_url or os.getenv("BOT_URL", "http://127.0.0.1:3000")

    def get_status(self):
        response = requests.get(f"{self.base_url}/status", timeout=5)
        response.raise_for_status()
        return response.json()

    def execute(self, tool, params=None):
        payload = {"tool": tool, "params": params if params is not None else {}}
        response = requests.post(
            f"{self.base_url}/execute",
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        return response.json()
