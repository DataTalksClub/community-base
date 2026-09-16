"""A module-level callable for COURSEWORK_CERTIFICATE_GENERATOR dotted-path resolution tests.

Kept separate from the test module itself because Hook/_callback resolution (community_base.kernel
.hooks.resolve, used by community_base.coursework.integrations) needs a real importable dotted
path, which a function defined inside a test function does not have.
"""


def fake_generator(enrollment, certificate=None):
    del enrollment, certificate
    return "https://certs.example.com/dotted-path.pdf"
