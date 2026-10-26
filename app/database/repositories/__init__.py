from .broadcasts import BroadcastRepo
from .content import ButtonRepo, CommandRepo, MediaRepo, ResponseRepo, ScriptRepo, WelcomeRepo
from .core import BotRepo, BotUserRepo, PlatformRepo, UserRepo


class Repos:
    def __init__(self, db):
        self.users = UserRepo(db)
        self.bots = BotRepo(db)
        self.botusers = BotUserRepo(db)
        self.platform = PlatformRepo(db)
        self.commands = CommandRepo(db)
        self.responses = ResponseRepo(db)
        self.buttons = ButtonRepo(db)
        self.welcome = WelcomeRepo(db)
        self.media = MediaRepo(db)
        self.scripts = ScriptRepo(db)
        self.broadcasts = BroadcastRepo(db)
