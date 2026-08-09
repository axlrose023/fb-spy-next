class RunError(Exception):
    pass


class RunNotFound(RunError):
    pass


class RunNotActive(RunError):
    pass


class RunArtifactsNotFound(RunError):
    pass
