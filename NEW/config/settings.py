import json
import os

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

class Settings:
    def __init__(self):
        self._load()

    def _load(self):
        with open(SETTINGS_PATH, "r") as f:
            self.data = json.load(f)

    def save(self):
        with open(SETTINGS_PATH, "w") as f:
            json.dump(self.data, f, indent=4)

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value
        self.save()

settings = Settings()
