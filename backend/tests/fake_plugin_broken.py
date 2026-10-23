"""Extension factice qui échoue à l'enregistrement."""


def register() -> None:
    raise RuntimeError("boîte déjà enregistrée")
