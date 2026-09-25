import yaml


def load(text: str) -> object:
    return yaml.load(text)
