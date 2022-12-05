from peewee import *
from elements import get_db


db = SqliteDatabase(get_db())


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
    time = DateTimeField()
    delay = IntegerField(null=True)
    username = CharField(max_length=20+4)
    text = CharField()
    removed = BooleanField(default=False)
    disabled = BooleanField(default=False)
    timeout = BooleanField(default=False)
    tournament = CharField()

    class Meta:
        database = db


db.connect()
db.create_tables([Mods, Authentication, Messages], safe=True)
