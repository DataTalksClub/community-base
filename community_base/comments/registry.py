import re
from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete

TARGET_KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_targets = {}


def public_read(_target, _user):
    return True


def authenticated_write(_target, user):
    return bool(getattr(user, "is_authenticated", False))


@dataclass(frozen=True, slots=True)
class CommentTarget:
    key: str
    model: type
    content_id_field: str
    can_read: object
    can_write: object
    cascade_delete: bool

    def resolve(self, content_id):
        return self.model.objects.filter(**{self.content_id_field: content_id}).first()


@dataclass(frozen=True, slots=True)
class ResolvedCommentTarget:
    registration: CommentTarget
    target: object

    @property
    def content_type(self):
        return ContentType.objects.get_for_model(self.target, for_concrete_model=False)


def register_comment_target(
    key,
    model,
    *,
    content_id_field="content_id",
    can_read=public_read,
    can_write=authenticated_write,
    cascade_delete=False,
):
    if not isinstance(key, str) or not TARGET_KEY.fullmatch(key):
        raise ValueError("invalid comment target key")
    model._meta.get_field(content_id_field)
    registration = CommentTarget(
        key=key,
        model=model,
        content_id_field=content_id_field,
        can_read=can_read,
        can_write=can_write,
        cascade_delete=bool(cascade_delete),
    )
    existing = _targets.get(key)
    if existing is not None:
        if existing != registration:
            raise ValueError(f"comment target is already registered: {key}")
        return existing
    _targets[key] = registration
    if registration.cascade_delete:

        def delete_comments(sender, instance, **kwargs):
            from community_base.comments.services import delete_thread

            delete_thread(getattr(instance, content_id_field))

        post_delete.connect(
            delete_comments,
            sender=model,
            weak=False,
            dispatch_uid=f"community_base.comments.delete.{model._meta.label_lower}.{key}",
        )
    return registration


def resolve_comment_target(content_id):
    for key in sorted(_targets):
        registration = _targets[key]
        target = registration.resolve(content_id)
        if target is not None:
            return ResolvedCommentTarget(registration, target)
    return None


def registered_comment_targets():
    return tuple(_targets[key] for key in sorted(_targets))


def _clear():
    for registration in _targets.values():
        post_delete.disconnect(
            sender=registration.model,
            dispatch_uid=(
                f"community_base.comments.delete."
                f"{registration.model._meta.label_lower}.{registration.key}"
            ),
        )
    _targets.clear()
