from community_base.kernel.hooks import resolve

_resolvers = {}


def register_context_resolver(purpose_prefix, resolver):
    if not isinstance(purpose_prefix, str) or not purpose_prefix.endswith("."):
        raise ValueError("Mail context purpose prefix must end with a dot.")
    existing = _resolvers.get(purpose_prefix)
    if existing is not None and existing != resolver:
        raise ValueError(f"Mail context resolver already registered: {purpose_prefix}")
    _resolvers[purpose_prefix] = resolver


def resolve_delivery_context(*, delivery, context):
    result = dict(context)
    for prefix in sorted(_resolvers, key=len, reverse=True):
        if delivery.purpose.startswith(prefix):
            callback = _resolvers[prefix]
            callback = resolve(callback) if isinstance(callback, str) else callback
            return callback(delivery=delivery, context=result)
    return result
