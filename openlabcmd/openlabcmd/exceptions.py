class OpenLabCmdError(Exception):
    pass


class ClientError(OpenLabCmdError):
    pass


class ValidationError(OpenLabCmdError):
    pass
