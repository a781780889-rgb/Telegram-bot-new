from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    WAITING_FOR_PHONE = State()
    WAITING_FOR_OTP   = State()
    WAITING_FOR_2FA   = State()


class SearchWizardStates(StatesGroup):
    """
    Multi-step search wizard.
    State data keys (all stored in FSM context):
      selected_accounts  : list[int]         — account IDs
      platform           : str               — "tg" | "wa" | "bo"
      link_types         : dict[str, bool]   — per-type toggle flags
      depth              : str               — "fa" | "no" | "de"
      period             : str               — "dy"|"wk"|"mn"|"yr"|"cu"
      date_from          : str | None        — ISO date string (custom period)
      date_to            : str | None        — ISO date string (custom period)
    """

    SELECTING_ACCOUNTS = State()   # Step 1
    SELECTING_PLATFORM = State()   # Step 2
    SELECTING_TYPES    = State()   # Step 3
    SELECTING_DEPTH    = State()   # Step 4
    SELECTING_PERIOD   = State()   # Step 5
    CUSTOM_DATE_FROM   = State()   # Step 5b (text input)
    CUSTOM_DATE_TO     = State()   # Step 5c (text input)
    CONFIRMING         = State()   # Step 6
    RUNNING            = State()   # Job is live


# ── legacy (kept for compatibility with any existing imports) ─────────────

class SearchStates(StatesGroup):
    SELECTING_ACCOUNTS = State()
    SELECTING_TYPE     = State()
    WAITING_FOR_QUERY  = State()


class PublishStates(StatesGroup):
    SELECTING_CONTENT = State()
    SELECTING_TARGETS = State()
    WAITING_FOR_SCHEDULE = State()
