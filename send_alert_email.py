"""Send an explicitly enabled alert using project-local configuration."""

import argparse
import logging
import smtplib
from email.message import EmailMessage

from lyo_config import ConfigError, configure_logging, load_settings

LOG = logging.getLogger(__name__)


def send_alert(alert_type, settings):
    if not settings.alerts_enabled:
        return False
    try:
        message = EmailMessage()
        message["Subject"] = f"{settings.instrument_name} Alert: {alert_type}"
        message["From"] = settings.gmail_user
        message["To"] = settings.alert_recipient
        message.set_content(f"Alert triggered: {alert_type}\n"
                            f"Please check {settings.instrument_name}.\n")
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.login(settings.gmail_user, settings.gmail_app_password)
            server.send_message(message)
        LOG.info("Alert email delivered (%s)", alert_type)
        return True
    except (OSError, smtplib.SMTPException, ValueError) as error:
        # SMTP exception text can contain credentials returned by a server.
        LOG.error("Email delivery failed (%s)", type(error).__name__)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send an enabled instrument alert")
    parser.add_argument("alert_type", nargs="?", default="Unknown")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(operation="mail")
        configure_logging(settings)
        if not settings.alerts_enabled:
            LOG.info("Alerts disabled; no email sent")
            return 0
        return 0 if send_alert(args.alert_type, settings) else 1
    except ConfigError as error:
        LOG.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
