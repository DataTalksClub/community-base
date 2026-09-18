"""A synthetic non-default authentication backend, standing in for a site's own.

DataTalks.Club's `AUTHENTICATION_BACKENDS` is `["accounts.backends.DurableAccountBackend"]` and
nothing else -- no `ModelBackend` anywhere in the list. This class exists so a test can configure
exactly that shape and prove impersonation resolves the site's own backend rather than the
package's former hardcoded `ModelBackend` path. Its behaviour is `ModelBackend`'s; only its dotted
path differs, which is the only thing this issue's fix reads.
"""

from django.contrib.auth.backends import ModelBackend


class DurableAccountBackend(ModelBackend):
    pass
