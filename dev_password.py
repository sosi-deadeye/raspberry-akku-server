import os
from hashlib import pbkdf2_hmac
from pathlib import Path
from secrets import compare_digest

SALT_FILE = Path("/media/data/salt.bin")
PASS_FILE = Path("/media/data/pass.bin")


def gen_salt() -> bytes:
    salt = os.urandom(256)
    SALT_FILE.write_bytes(salt)
    return salt


def gen_password(password: str) -> bytes:
    digest = pbkdf2_hmac("sha256", password.encode(), SALT, 3000)
    PASS_FILE.write_bytes(digest)
    return digest


def check_password(password: str) -> bool:
    return compare_digest(
        PASSWORD,
        pbkdf2_hmac("sha256", password.encode(), SALT, 3000),
    )


def get_set_salt() -> bytes:
    if SALT_FILE.exists():
        return SALT_FILE.read_bytes()
    else:
        return gen_salt()


def get_set_password(password: str) -> bytes:
    if PASS_FILE.exists():
        return PASS_FILE.read_bytes()
    else:
        return gen_password(password)


def get_args():
    parser = ArgumentParser()
    parser.add_argument("--password", help="Check given password")
    parser.add_argument("--gen-salt", action="store_true", help="Generate salt")
    parser.add_argument("--set-password", help="Set a new password")
    parser.add_argument(
        "--clear-all", action="store_true", help="Remove salt and password"
    )
    return parser.parse_args()


SALT = get_set_salt()
PASSWORD = get_set_password("default")


if __name__ == "__main__":
    import sys
    from argparse import ArgumentParser

    args = get_args()
    if args.clear_all:
        SALT_FILE.unlink()
        PASS_FILE.unlink()
        sys.exit(0)
    if args.gen_salt:
        SALT_FILE.unlink()
        SALT = get_set_salt()
    if args.set_password:
        PASS_FILE.unlink()
        PASSWORD = get_set_password(args.set_password)
    if args.password:
        result = check_password(args.password)
        print(result, file=sys.stderr)
        if result:
            sys.exit(0)
        else:
            sys.exit(1)
