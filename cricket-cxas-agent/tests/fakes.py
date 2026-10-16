"""Smallest in-memory stand-in for the Firestore client calls the code uses."""


class FakeSnap:
    def __init__(self, id, data):
        self.id, self._d, self.exists = id, data, data is not None

    def to_dict(self):
        return dict(self._d) if self._d is not None else None


class FakeDoc:
    def __init__(self, data, coll, id):
        self.data, self.coll, self.id = data, coll, id

    def get(self):
        return FakeSnap(self.id, self.data.get(self.coll, {}).get(self.id))

    def set(self, value, merge=False):
        cur = self.data.setdefault(self.coll, {}).get(self.id, {}) if merge else {}
        self.data.setdefault(self.coll, {})[self.id] = {**cur, **value}

    def delete(self):
        self.data.get(self.coll, {}).pop(self.id, None)


class FakeColl:
    def __init__(self, data, name):
        self.data, self.name = data, name

    def document(self, id):
        return FakeDoc(self.data, self.name, id)

    def stream(self):
        return [FakeSnap(i, d) for i, d in self.data.get(self.name, {}).items()]


class FakeDB:
    def __init__(self, data=None):
        self.data = data if data is not None else {}

    def collection(self, name):
        return FakeColl(self.data, name)
