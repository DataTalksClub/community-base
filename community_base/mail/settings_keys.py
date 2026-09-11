from community_base.config.registry import declare_if_absent

# The AWS credentials are commonly declared by the site first (with its own
# operator-facing group and docs); the first declaration wins. The same holds
# for the fallback sender, so every key this module contributes keeps docs
# metadata even when the site declares nothing itself.
declare_if_absent(
    key="AWS_SES_REGION",
    group="mail",
    label="AWS SES region",
    description="AWS region containing the verified SES sending identity.",
    value_type="str",
    default="us-east-1",
    docs_url="community_base/mail/README.md#runtime-settings",
)

declare_if_absent(
    key="AWS_ACCESS_KEY_ID",
    group="mail",
    label="AWS access key id",
    description="IAM access key allowed to send mail through SES.",
    value_type="str",
    default="",
    secret=True,
    docs_url="community_base/mail/README.md#runtime-settings",
)

declare_if_absent(
    key="AWS_SECRET_ACCESS_KEY",
    group="mail",
    label="AWS secret access key",
    description="Secret paired with the IAM access key used by SES.",
    value_type="str",
    default="",
    secret=True,
    docs_url="community_base/mail/README.md#runtime-settings",
)

declare_if_absent(
    key="SES_FROM_EMAIL",
    group="mail",
    label="SES from email",
    description="Default From address when a delivery does not name a sender.",
    value_type="str",
    default="",
    optional=True,
    is_email=True,
    docs_url="community_base/mail/README.md#runtime-settings",
)
