from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    WAITING_FOR_PHONE = State()
    WAITING_FOR_OTP   = State()
    WAITING_FOR_2FA   = State()


class SearchWizardStates(StatesGroup):
    """Multi-step search wizard."""
    SELECTING_ACCOUNTS   = State()
    SELECTING_PLATFORM   = State()
    SELECTING_LINK_TYPE  = State()
    SELECTING_DEPTH      = State()
    SELECTING_TIME_RANGE = State()
    CUSTOM_DATE_FROM     = State()   # text input – date "from"
    CUSTOM_DATE_TO       = State()   # text input – date "to"
    SELECTING_MAX_RESULTS = State()
    CONFIRMING           = State()
    RUNNING              = State()


# Keep old names for backward compatibility with any existing references
class SearchStates(StatesGroup):
    SELECTING_ACCOUNTS = State()
    SELECTING_TYPE     = State()
    WAITING_FOR_QUERY  = State()


class PublishStates(StatesGroup):
    SELECTING_CONTENT  = State()
    SELECTING_TARGETS  = State()
    WAITING_FOR_SCHEDULE = State()
