class AccountingError(Exception):
    pass


class InsufficientCredit(AccountingError):
    pass


class InvalidConsumption(AccountingError):
    pass


class RequestClosed(AccountingError):
    pass


class InvalidPledge(AccountingError):
    pass
