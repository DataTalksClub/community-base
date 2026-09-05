from community_base.config.registry import declare

declare(
    key="AWS_SES_REGION",
    group="mail",
    label="AWS SES region",
    description="AWS region containing the verified SES sending identity.",
    value_type="str",
    default="us-east-1",
)

declare(
    key="AWS_ACCESS_KEY_ID",
    group="mail",
    label="AWS access key id",
    description="IAM access key allowed to send mail through SES.",
    value_type="str",
    default="",
    secret=True,
)

declare(
    key="AWS_SECRET_ACCESS_KEY",
    group="mail",
    label="AWS secret access key",
    description="Secret paired with the IAM access key used by SES.",
    value_type="str",
    default="",
    secret=True,
)

declare(
    key="SES_FROM_EMAIL",
    group="mail",
    label="SES from email",
    description="Default From address when a delivery does not name a sender.",
    value_type="str",
    default="",
    optional=True,
    is_email=True,
)
