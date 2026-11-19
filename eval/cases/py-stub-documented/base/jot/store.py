import json
import os

PATH = os.path.expanduser("~/.jot.json")


class Store:
    def __init__(self, path=PATH):
        self.path = path
        self.notes = json.load(open(path)) if os.path.exists(path) else {}

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.notes, f, indent=2)

    def add(self, date, text):
        self.notes[date] = text
        self.save()

    def get(self, date):
        return self.notes.get(date)

    def remove(self, date):
        if self.notes.pop(date, None) is not None:
            self.save()
            return True
        return False
