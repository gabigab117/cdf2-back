"""What the application's emails share."""

# A message that could not go: SMTPException is an OSError, and so are a
# refused connection and a timeout. The SMTP backend raises a ValueError for an
# address it cannot send with, such as a sender left empty in the configuration.
MAIL_FAILURES = (OSError, ValueError)
