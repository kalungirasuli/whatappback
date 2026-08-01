import re

COMMAND_PREFIX = "@"
COMMANDS = {"register", "post", "edit", "stock", "price", "delete", "help", "plans", "subscribe", "code"}

COMMAND_REGEX = re.compile(rf"^@({'|'.join(sorted(COMMANDS, key=len, reverse=True))})(\s.*)?$", re.IGNORECASE)
COMMAND_PARSE_REGEX = re.compile(rf"^@(\w+)(?:\s+(.*))?$", re.IGNORECASE)


def is_merchant_command(text: str) -> bool:
    return bool(COMMAND_REGEX.match(text.strip()))


def parse_command(text: str) -> tuple[str, str] | None:
    m = COMMAND_PARSE_REGEX.match(text.strip())
    if not m:
        return None
    cmd = m.group(1).lower()
    args = (m.group(2) or "").strip()
    return cmd, args
