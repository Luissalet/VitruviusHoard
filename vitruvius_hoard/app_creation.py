"""Expected input errors when creating a project from a starter."""


class ProjectCreationError(ValueError):
    def __init__(self, en: str, es: str):
        super().__init__(en)
        self.es = es
