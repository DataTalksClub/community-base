"""Durable mail API."""


def send(*args, **kwargs):
    from community_base.mail.service import send as send_mail

    return send_mail(*args, **kwargs)


__all__ = ["send"]
