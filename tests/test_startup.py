import startup


class FakeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    class Key:
        def __init__(self, owner):
            self.owner = owner

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def CreateKeyEx(self, *_args):
        return self.Key(self)

    def OpenKey(self, *_args):
        return self.Key(self)

    def SetValueEx(self, _key, name, _reserved, _kind, value):
        self.values[name] = value

    def QueryValueEx(self, _key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def DeleteValue(self, _key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def test_startup_uses_current_user_registry_and_windows_quoting():
    registry = FakeRegistry()
    command = [r"C:\Program Files\AI Usage\tracker.exe", "--quiet mode"]

    startup.set_startup(True, command, registry=registry)

    assert registry.values[startup.VALUE_NAME] == (
        '"C:\\Program Files\\AI Usage\\tracker.exe" "--quiet mode"'
    )
    assert startup.is_startup_enabled(registry=registry)


def test_disabling_startup_is_idempotent_and_removes_only_our_value():
    registry = FakeRegistry()
    registry.values.update({startup.VALUE_NAME: "ours", "AnotherApp": "keep"})

    startup.set_startup(False, [], registry=registry)
    startup.set_startup(False, [], registry=registry)

    assert startup.VALUE_NAME not in registry.values
    assert registry.values["AnotherApp"] == "keep"

