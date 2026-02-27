from aiogram.fsm.state import State, StatesGroup


class AddPackage(StatesGroup):
    name = State()
    traffic = State()
    duration = State()
    price = State()
    description = State()


class CreateConfig(StatesGroup):
    email = State()
    traffic = State()
    duration = State()
    server = State()


class BulkConfig(StatesGroup):
    prefix = State()
    count = State()
    traffic = State()
    duration = State()
    server = State()


class EditConfig(StatesGroup):
    traffic = State()
    expire = State()


class BuyService(StatesGroup):
    waiting_receipt = State()


class Broadcast(StatesGroup):
    target = State()
    text = State()
    confirm = State()


class MigrateServer(StatesGroup):
    pick_server = State()


class WholesaleBuy(StatesGroup):
    count = State()
    traffic = State()
    duration = State()
    naming_prefix = State()
    naming_start = State()


class LegacySync(StatesGroup):
    waiting_link = State()


class PrivateMessage(StatesGroup):
    user_id = State()
    text = State()


class WalletTopup(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()
