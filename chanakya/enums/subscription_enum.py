from enum import Enum


class SubsEnum(Enum):
    GOOGLE = "google"
    APPLE = "apple"
    STRIPE = "stripe"
    FREE = "free"
    PLAY_STORE = "PLAY_STORE"

    @classmethod
    def choices(cls):
        return [(role.value, role.name.capitalize()) for role in cls]
