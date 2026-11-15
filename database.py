from peewee import *
from elements import get_db


db = SqliteDatabase(get_db(), timeout=20, pragmas={'journal_mode': 'wal', 'synchronous': 'normal'})


class Mods(Model):
    modId = CharField(max_length=20+4)
    tokenKey = BlobField()
    tokenHash = FixedCharField(primary_key=True, max_length=38)
    createdAt = DateTimeField()
    expiresAt = DateTimeField()
    seenAt = DateTimeField()
    enabled = BooleanField(default=True)

    class Meta:
        database = db


class Authentication(Model):
    state = FixedCharField(primary_key=True, max_length=22)
    verifier = FixedCharField(max_length=43)
    expiresAt = DateTimeField()

    class Meta:
        database = db


class Messages(Model):
    id = AutoField()
    time = DateTimeField(index=True)
    delay = IntegerField(null=True)
    username = CharField(max_length=20+4)
    text = CharField()
    removed = BooleanField(default=False)
    disabled = BooleanField(default=False)
    timeout = BooleanField(default=False)
    tournament = CharField(index=True)

    class Meta:
        database = db


class Chats(Model):
    id = CharField(primary_key=True)
    type = IntegerField()
    name = CharField(null=True)
    url = CharField(null=True)
    startsAt = DateTimeField(null=True)
    checkedAt = DateTimeField(index=True)

    class Meta:
        database = db


Messages.add_index(SQL('CREATE INDEX IF NOT EXISTS "messages_username_nocase" ON "messages" ("username" COLLATE NOCASE)'))

db.connect()
db.create_tables([Mods, Authentication, Messages, Chats], safe=True)
