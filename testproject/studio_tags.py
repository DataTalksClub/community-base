_tags = {}


class TestUserTagsAccessor:
    def get(self, user):
        return _tags.get(user.pk, [])

    def set(self, user, tags):
        _tags[user.pk] = list(tags)


def clear():
    _tags.clear()
